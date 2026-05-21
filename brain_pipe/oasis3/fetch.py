"""Build the OASIS-3 processed derivative under the local cache.

Unlike ``brain_pipe.hcp_ya_open``, there is no Zenodo download path —
OASIS-3 raw and derived data is restricted by the OASIS DUA and cannot
be redistributed. ``process(raw_dir=...)`` requires the caller to point
at their own NITRC-IR-authenticated copy (the bundled `0AS_data_files`
metadata CSVs, at minimum; downstream stages fetch the actual scan
files via the vendored oasis-scripts).
"""

import os
from pathlib import Path

import yaml

from brain_pipe.hcp_ya_open.fetch import resolve_dest

_PKG_DIR = Path(__file__).resolve().parent
_MANIFEST = _PKG_DIR / "manifest.yaml"


def _resolve_dest(dest=None):
    return resolve_dest("oasis3", dest)


def prepare(bundle=None, dest=None, nitrc_user=None, nitrc_password=None):
    """Extract the OASIS-3 metadata bundle and build the cohort + xfeat
    table.

    First of three stages (prepare -> fetch -> process):

    - ``prepare`` (here): downloads (or accepts) the metadata bundle,
      extracts the CSVs, builds ``cohort_sessions.csv`` and
      ``covariates.csv``.
    - ``fetch``: downloads T1w+DWI imaging for the cohort subjects.
    - ``process``: DTI fit + MNI152 registration + final covariates.

    By default, downloads ``OASIS3_data_files.zip`` (~67 MB) from
    NITRC-IR via the same XNAT REST API ``fetch()`` uses, so this is
    a one-call entry point. Pass ``bundle=<path>`` to skip the download
    (for offline use or a pre-downloaded zip).

    The downloaded bundle is cached at
    ``<dest>/raw/OASIS3_data_files.zip``. Re-running ``prepare()`` with
    that file present prints a reuse message and skips the network call;
    delete the file to force a re-download.

    Args:
        bundle: optional path to a pre-downloaded
            ``OASIS3_data_files.zip``. If omitted, the bundle is fetched
            from NITRC-IR (prompts for credentials).
        dest: cache location; defaults to ``$BRAIN_PIPE_OASIS3_PATH`` or
            ``platformdirs.user_data_dir('brain_pipe')/oasis3``.
        nitrc_user: NITRC-IR username for the bundle download. Ignored
            when ``bundle`` is provided. Prompted if omitted.
        nitrc_password: NITRC-IR password for the bundle download.
            Prompted via getpass if omitted. Provided primarily so the
            CLI's ``all`` subcommand can prompt once and pass through
            to both ``prepare`` and ``fetch``.

    Returns:
        ``Path`` to ``dest``. The two output CSVs live at
        ``dest/cohort_sessions.csv`` and ``dest/covariates.csv``.
    """
    from brain_pipe.oasis3.pipeline import bundle as bundle_stage
    from brain_pipe.oasis3.pipeline import cohort as cohort_stage

    dest = _resolve_dest(dest)
    dest.mkdir(parents=True, exist_ok=True)
    raw_dir = dest / "raw"

    if bundle is None:
        bundle = _fetch_bundle(raw_dir, nitrc_user, nitrc_password)

    print("[1/2] extracting bundle CSVs")
    bundle_paths = bundle_stage.extract(bundle, raw_dir)

    print("[2/2] building cohort + covariates")
    cohort_stage.build(bundle_paths, dest)

    print()
    print(f"Done. Review covariates.csv at {dest / 'covariates.csv'}")
    print(f"Next: fetch imaging (prompts NITRC-IR creds)")
    return dest


def _fetch_bundle(raw_dir, nitrc_user, nitrc_password=None):
    """Download OASIS3_data_files.zip to ``raw_dir`` via NITRC-IR's
    XNAT REST API. Idempotent (reuses an existing file with a message).
    """
    out_path = raw_dir / "OASIS3_data_files.zip"
    if out_path.exists():
        print(f"bundle already downloaded at {out_path} — reusing")
        return out_path

    from brain_pipe.oasis3.pipeline.xnat import NitrcXnat

    nitrc_user, nitrc_password = _prompt_creds(nitrc_user, nitrc_password)

    print(f"[downloading bundle from NITRC-IR -> {out_path}]")
    with NitrcXnat(nitrc_user, nitrc_password) as xnat:
        xnat.download_data_files_bundle(out_path)
    return out_path


def _prompt_creds(nitrc_user, nitrc_password):
    """Prompt for missing NITRC-IR username/password. Lifted out so the
    CLI's ``all`` mode can prompt once and pass to both prepare+fetch.
    """
    import getpass

    if nitrc_user is None:
        nitrc_user = input("NITRC-IR username: ").strip()
        while not nitrc_user:
            nitrc_user = input("NITRC-IR username (required): ").strip()
    if nitrc_password is None:
        nitrc_password = getpass.getpass(f"NITRC-IR password for {nitrc_user}: ")
    return nitrc_user, nitrc_password


def fetch(dest=None, nitrc_user=None, nitrc_password=None):
    """Download cohort imaging from NITRC-IR via the XNAT REST API.

    Second of three stages. ``prepare(bundle=...)`` must have run
    first — this reads ``dest/cohort_sessions.csv`` to know which
    sessions to fetch.

    Prompts for the NITRC-IR password at every call (never saved
    to disk). Username can be passed explicitly via ``nitrc_user=``
    or will also be prompted.

    For each cohort subject, fetches T1w + DWI scans from the chosen
    MR session.

    The downloader is fully Python (uses ``requests``, no bash
    subprocess) so it works on Linux / Mac / Windows. Per-file
    progress is shown via ``tqdm``. Idempotent: subjects already on
    disk are skipped, so an interrupted fetch resumes cleanly.

    Args:
        dest: cache location; defaults to
            ``platformdirs.user_data_dir('brain_pipe')/oasis3``.
        nitrc_user: NITRC-IR username. Prompted if omitted.
        nitrc_password: NITRC-IR password. Prompted via getpass if
            omitted. Provided primarily so the CLI's ``all`` subcommand
            can prompt once and pass through to both ``prepare`` and
            ``fetch``.

    Returns:
        ``Path`` to ``dest/raw/`` (where the ``scans/`` subdir lives).
    """
    dest = _resolve_dest(dest)
    cohort_csv = dest / "cohort_sessions.csv"
    if not cohort_csv.exists():
        raise FileNotFoundError(
            f"cohort_sessions.csv not found at {cohort_csv}. Run "
            f"`prepare(bundle=...)` first."
        )
    raw_dir = dest / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    nitrc_user, nitrc_password = _prompt_creds(nitrc_user, nitrc_password)

    from brain_pipe.oasis3.pipeline import fetch_imaging
    from brain_pipe.oasis3.pipeline.xnat import NitrcXnat

    print(f"[authenticating against NITRC-IR]")
    with NitrcXnat(nitrc_user, nitrc_password) as xnat:
        fetch_imaging.fetch_cohort(cohort_csv, raw_dir, xnat)

    print()
    print(f"Done. Raw data at {raw_dir}")
    print(f"Next: process()  (DTI + MNI registration)")
    return raw_dir


def process(dest=None, n_jobs=1, n_jobs_dti=None):
    """Run the compute stages: DTI fit + MNI152 registration.

    Third of three stages. ``prepare()`` + ``fetch()`` must have run
    first — this reads ``dest/cohort_sessions.csv`` for the subject
    list and ``dest/raw/`` for the downloaded imaging.

    ``covariates.csv`` is written during ``prepare()`` (from the
    metadata bundle) and is not regenerated here.

    Args:
        dest: cache location. Defaults to ``$BRAIN_PIPE_OASIS3_PATH``
            if set, else ``platformdirs.user_data_dir('brain_pipe')/oasis3``.
        n_jobs: parallel workers for SyN registration.
        n_jobs_dti: parallel workers for DTI fitting; defaults to
            ``min(n_jobs, 4)`` since each holds the DWI volume in RAM.

    Returns:
        ``pathlib.Path`` to a directory of
        ``<sbj>_{t1,fa,md}.nii.gz`` (all in MNI152),
        plus ``mni_template.nii.gz``, ``group_mask.nii.gz``,
        ``cohort_sessions.csv``, and ``covariates.csv``.
    """
    dest = _resolve_dest(dest)
    sentinel = dest / ".complete"
    if sentinel.exists():
        return dest

    cohort_csv = dest / "cohort_sessions.csv"
    if not cohort_csv.exists():
        raise FileNotFoundError(
            f"cohort_sessions.csv not found at {cohort_csv}. Run "
            f"`prepare(...)` first."
        )
    raw_dir = dest / "raw"
    if not raw_dir.exists():
        raise FileNotFoundError(
            f"raw imaging not found at {raw_dir}. Run `fetch(...)` first."
        )

    manifest = yaml.safe_load(_MANIFEST.read_text())

    if n_jobs_dti is None:
        n_jobs_dti = min(n_jobs, 4)
    os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = "1"

    # Imports are lazy so a loader-only install can still do
    # `from brain_pipe.oasis3 import process` without antspyx / dipy.
    try:
        import dipy  # noqa: F401
        import ants  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "Reprocessing requires the pipeline extra; install with:\n"
            "    pip install 'brain_pipe[oasis3-pipeline]'\n"
            "into a fresh venv."
        ) from e

    from brain_pipe.oasis3.pipeline import dti, reg

    print(f"[1/2] DTI fitting (FA + MD) — n_jobs_dti={n_jobs_dti}")
    dti.process_cohort(cohort_csv, raw_dir, n_jobs=n_jobs_dti)

    print(f"[2/2] registration to MNI152 — n_jobs={n_jobs}")
    reg.register_cohort(cohort_csv, raw_dir, dest, manifest=manifest,
                        n_jobs=n_jobs)

    sentinel.touch()
    return dest
