"""Pure-Python NITRC-IR / XNAT REST client for OASIS-3 downloads.

Replaces the bash-script subprocess approach (``download_oasis_scans.sh``
+ ``download_oasis_pup_files_by_partial_filename_match.sh``) with a
cross-platform Python client that:

- authenticates once per process (HTTP Basic against ``/data/JSESSION``,
  keeps the JSESSIONID cookie for subsequent requests),
- streams downloads with ``tqdm`` progress so users see what's
  happening,
- never puts the password in ``argv`` (avoids the ``ps``-visible
  exposure of the old ``curl -u user:pass`` invocations),
- supports per-scan-type filtering for MR sessions (``T1w,dwi``) and
  per-filename-substring filtering for PUP outputs (``SUVR``) so we
  fetch ~30 MB SUVR files instead of ~2.7 GB full-PUP dirs.

URL patterns mirror what oasis-scripts uses; see that repo for the
canonical reference (https://github.com/NrgXnat/oasis-scripts).
"""

import csv
import io
import re
import zipfile
from pathlib import Path

import requests
from tqdm.auto import tqdm

BASE = "https://www.nitrc.org/ir"

# The OASIS-3 metadata bundle — same payload as the web UI's
# "0AS_data_files -> OASIS3_data_files -> Bulk Action -> Download"
# (~67 MB zip containing UDS forms, per-scan JSON metadata CSVs,
# centiloid, demographics, and dictionaries).
BUNDLE_URL = (
    f"{BASE}/data/archive/projects/OASIS3/subjects/0AS_data_files"
    f"/experiments/OASIS3_data_files/scans/ALL/files?format=zip"
)


# --- URL routing helpers -----------------------------------------------

def _project_for_experiment(experiment_id, tau_project="OASIS3_AV1451"):
    """Pick the XNAT project given an experiment ID. Mirrors the
    routing logic from download_oasis_scans.sh / download_oasis_pup.sh.
    """
    if experiment_id.startswith("OAS4"):
        return "OASIS4"
    if "_AV1451" in experiment_id:
        return tau_project
    return "OASIS3"


def _subject_from_id(experiment_id):
    """Pull the leading ``OASNNNNN`` subject ID out of an experiment
    or PUP ID like ``OAS30003_MR_d3731`` or
    ``OAS30003_AV45_PUPTIMECOURSE_d3731``.
    """
    return experiment_id.split("_", 1)[0]


def _experiment_label_from_pup(pup_id):
    """PUP IDs encode the originating PET experiment label by adding
    ``_PUPTIMECOURSE`` before the day suffix. E.g.::

        OAS30003_AV45_PUPTIMECOURSE_d3731 -> OAS30003_AV45_d3731
    """
    return pup_id.replace("_PUPTIMECOURSE", "")


# --- client -----------------------------------------------------------

class NitrcXnat:
    """Authenticated session against NITRC-IR's XNAT instance.

    Use as a context manager so the session is logged out cleanly::

        with NitrcXnat(user, password) as xnat:
            xnat.download_mr_scans('OAS30003_MR_d3731', 'T1w,dwi', '/dest/scans')
    """

    def __init__(self, username, password):
        self.session = requests.Session()
        r = self.session.get(
            f"{BASE}/data/JSESSION",
            auth=(username, password),
        )
        if r.status_code == 401:
            raise PermissionError(
                "NITRC-IR rejected credentials (401). Check username/password "
                "and that your account has OASIS3 / OASIS3_AV1451 access."
            )
        r.raise_for_status()
        self._open = True

    def close(self):
        """Best-effort logout."""
        if self._open:
            try:
                self.session.delete(f"{BASE}/data/JSESSION", timeout=10)
            except requests.RequestException:
                pass
            self._open = False
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- downloads ----------------------------------------------------

    def download_mr_scans(self, experiment_id, scan_types, dest, project=None):
        """Download specified scan types from an MR experiment as a zip,
        extract into ``dest/<experiment_id>/``. Idempotent — skips if the
        target dir already has content.

        Args:
            experiment_id: e.g. ``'OAS30003_MR_d3731'``.
            scan_types: comma-separated list, e.g. ``'T1w,dwi'``.
            dest: parent dir; output lands at ``dest/<experiment_id>/``.
            project: XNAT project id. Auto-routed when ``None``.

        Returns:
            ``Path`` to the per-experiment dir.
        """
        out_dir = Path(dest) / experiment_id
        if out_dir.exists() and any(out_dir.iterdir()):
            return out_dir
        subject = _subject_from_id(experiment_id)
        project = project or _project_for_experiment(experiment_id)
        url = (
            f"{BASE}/data/archive/projects/{project}/subjects/{subject}"
            f"/experiments/{experiment_id}/scans/{scan_types}/files?format=zip"
        )
        self._stream_zip(url, out_dir, label=f"{experiment_id} [{scan_types}]")
        return out_dir

    def download_pup_filtered(self, pup_id, filename_pattern, dest, project=None):
        """List files in a PUP assessor, filter filenames by
        case-sensitive regex search, download each into
        ``dest/<pup_id>/``. Skips if target dir already has content.

        PUP assessors ship hundreds of files per session — full 4D
        dynamic PET, motion-corrected frames, gaussian-smoothed
        variants, per-ROI scalar tables (``.suvr`` and ``.txt``
        extensions), QC plots, logs. The pipeline only reads the
        single volumetric SUVR image triplet. The default pattern
        ``_SUVR\\.4dfp\\.`` matches exactly that: the three files
        ``*_msum_SUVR.4dfp.{img,hdr,ifh}``, while excluding the
        Gaussian-smoothed ``_g8`` variant (we apply our own SyN warp
        which has built-in smoothing) and the per-ROI scalar tables.

        Per-PUP file count dropped this way: ~700 files (no filter)
        → ~12 files (substring "SUVR") → 3 files (this regex).

        Args:
            pup_id: e.g. ``'OAS30003_AV45_PUPTIMECOURSE_d3731'``.
            filename_pattern: regex string OR compiled ``re.Pattern``.
                Matched against the filename via ``re.search``, so
                anchors are explicit. Case-sensitive by default.
            dest: parent dir; output lands at ``dest/<pup_id>/``.
            project: XNAT project id. Auto-routed when ``None``.

        Returns:
            ``Path`` to the per-PUP dir.
        """
        out_dir = Path(dest) / pup_id
        if out_dir.exists() and any(out_dir.iterdir()):
            return out_dir
        subject = _subject_from_id(pup_id)
        project = project or _project_for_experiment(pup_id)
        experiment_label = _experiment_label_from_pup(pup_id)

        if isinstance(filename_pattern, str):
            filename_pattern = re.compile(filename_pattern)

        list_url = (
            f"{BASE}/data/archive/projects/{project}/subjects/{subject}"
            f"/experiments/{experiment_label}/assessors/{pup_id}"
            f"/files?format=csv"
        )
        r = self.session.get(list_url)
        r.raise_for_status()
        reader = csv.DictReader(io.StringIO(r.text))
        matches = [row for row in reader if filename_pattern.search(row["Name"])]
        if not matches:
            print(f"  [WARN] no files matching {filename_pattern.pattern!r} "
                  f"in {pup_id}")
            return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)
        for row in matches:
            self._stream_file(
                f"{BASE}{row['URI']}",
                out_dir / row["Name"],
                label=f"{pup_id}/{row['Name']}",
            )
        return out_dir

    def download_data_files_bundle(self, out_path):
        """Download the OASIS-3 metadata bundle zip (~67 MB) to
        ``out_path``. Idempotent: if the file already exists, prints a
        reuse message and returns without touching the network.

        Args:
            out_path: target file (typically
                ``<dest>/raw/OASIS3_data_files.zip``).

        Returns:
            ``Path(out_path)``.
        """
        out_path = Path(out_path)
        if out_path.exists():
            print(f"  bundle already downloaded at {out_path} — reusing")
            return out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._stream_file(BUNDLE_URL, out_path, label=out_path.name)
        return out_path

    # --- internals ----------------------------------------------------

    def _stream_zip(self, url, out_dir, label):
        """Stream a zip URL to a temp file, extract to out_dir, delete
        the zip. XNAT returns an empty/invalid zip when the experiment
        doesn't have the requested scan type — log + continue rather
        than crash the cohort fetch."""
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp = out_dir / "_dl.zip"
        with self.session.get(url, stream=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with open(tmp, "wb") as f, tqdm(
                total=total, unit="B", unit_scale=True,
                desc=label, leave=False,
            ) as bar:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
                    bar.update(len(chunk))
        try:
            with zipfile.ZipFile(tmp) as zf:
                zf.extractall(out_dir)
        except zipfile.BadZipFile:
            print(f"  [WARN] {label} returned a non-zip "
                  f"(scan type missing? auth error?)")
        tmp.unlink(missing_ok=True)

    def _stream_file(self, url, out_path, label):
        """Stream a single file URL to ``out_path``."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with self.session.get(url, stream=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with open(out_path, "wb") as f, tqdm(
                total=total, unit="B", unit_scale=True,
                desc=label, leave=False,
            ) as bar:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
                    bar.update(len(chunk))
