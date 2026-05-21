"""Bit-equality regression tests for ``brain_pipe.oasis3``.

This file is excluded from default pytest discovery (see
``tests/conftest.py``). Invoke explicitly::

    pytest tests/oasis3/test_repro.py -v                                    # all
    pytest tests/oasis3/test_repro.py::test_dti_single_subject_deterministic
    pytest tests/oasis3/test_repro.py::test_process_bit_identical_to_reference

Requirements:
- Raw OASIS-3 data + cohort/covariates CSVs at the default cache
  ``~/.local/share/brain_pipe/oasis3/`` (re-used so the raw isn't
  re-staged).
- Pipeline extra installed: ``pip install brain_pipe[oasis3-pipeline]``.
- Approx wall time: ~30 s DTI, ~2 h full process (n_jobs=8 on a
  32-core box).

There is no Zenodo-download counterpart (OASIS-3 is DUA-restricted and
not redistributable).
"""

import hashlib
import os
import re
import shutil
from pathlib import Path

import pytest

REFERENCE_MD5 = Path(__file__).parent.parent / "reference" / "oasis3_v1_md5.txt"
OUTPUT_PATTERN = re.compile(
    r"^(?:OAS\d{5}_(?:fa|md|t1)\.nii\.gz|"
    r"mni_template\.nii\.gz|group_mask\.nii\.gz)$"
)


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _md5_set(dest):
    return {
        f.name: _md5(f)
        for f in sorted(Path(dest).iterdir())
        if OUTPUT_PATTERN.match(f.name)
    }


def _read_reference():
    out = {}
    for line in REFERENCE_MD5.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        md5_hex, path = line.split(None, 1)
        out[Path(path.lstrip("./")).name] = md5_hex
    return out


def _default_dest():
    from brain_pipe.oasis3.fetch import _resolve_dest
    return _resolve_dest()


def _pick_subject_with_dti(raw_dir):
    """Smallest subject id whose first dwi run has data + cached fa/md."""
    from brain_pipe.oasis3.pipeline.dti import _find_subject_dwi

    scans_dir = raw_dir / "scans"
    if not scans_dir.exists():
        return None, None
    for mr_dir in sorted(scans_dir.glob("OAS*_MR_*")):
        mr_id = mr_dir.name
        found = _find_subject_dwi(scans_dir, mr_id)
        if found is None:
            continue
        dwi_nii, _, _ = found
        if (dwi_nii.parent / "fa.nii.gz").exists() and (dwi_nii.parent / "md.nii.gz").exists():
            return mr_id, dwi_nii.parent
    return None, None


def test_dti_single_subject_deterministic(tmp_path):
    """Re-run DIPY DTI on one subject; md5 must match the cached fa/md.

    Cheap (~30 s) sanity check that the tensor fit is deterministic on
    this platform. Inputs are symlinked from the cached raw into
    ``tmp_path`` so the per-subject outputs land in ``tmp_path``, not
    overwriting the cached fa/md.
    """
    pytest.importorskip("dipy")
    pytest.importorskip("nibabel")

    raw = _default_dest() / "raw"
    if not raw.exists():
        pytest.skip(f"Raw OASIS-3 data not at {raw}")

    mr_id, src_dir = _pick_subject_with_dti(raw)
    if mr_id is None:
        pytest.skip(f"No subject under {raw} has both DWI + cached fa/md")

    # DWI nifti + bvals/bvecs symlinks (the dipy fit looks for these
    # exact filenames next to the .nii.gz).
    dwi_nii = next(src_dir.glob("sub-*_dwi.nii.gz"))
    bids_files = src_dir.parent.parent / "BIDS" / "files"
    bval = next(bids_files.glob("*.bval"))
    bvec = next(bids_files.glob("*.bvec"))
    os.symlink(dwi_nii, tmp_path / dwi_nii.name)
    os.symlink(bval, tmp_path / "bvals")
    os.symlink(bvec, tmp_path / "bvecs")

    from brain_pipe._dwi_pipeline.dti import process_dti
    from dipy.reconst.dti import fractional_anisotropy, mean_diffusivity

    process_dti(
        tmp_path / dwi_nii.name,
        {"fa": fractional_anisotropy, "md": mean_diffusivity},
    )

    for label in ("fa", "md"):
        produced = _md5(tmp_path / f"{label}.nii.gz")
        cached = _md5(src_dir / f"{label}.nii.gz")
        assert produced == cached, (
            f"DTI {label} for {mr_id} differs from cached "
            f"({produced} vs {cached})"
        )


def test_process_bit_identical_to_reference(tmp_path):
    """Full seeded process() into tmp_path; all 270 output md5s must match.

    Symlinks the cached ``raw/`` and copies ``cohort_sessions.csv`` +
    ``covariates.csv`` into ``tmp_path`` so process() runs the DTI fit
    (short-circuits on cached fa/md) + reg.register_cohort end-to-end
    without re-fetching imaging. Wall time scales with ``n_jobs``:
    ~2 h on 32 cores.
    """
    pytest.importorskip("dipy")
    pytest.importorskip("ants")
    pytest.importorskip("templateflow")
    from brain_pipe.oasis3 import process

    cached_dest = _default_dest()
    raw = cached_dest / "raw"
    cohort_csv = cached_dest / "cohort_sessions.csv"
    covariates_csv = cached_dest / "covariates.csv"
    if not (raw.exists() and cohort_csv.exists()):
        pytest.skip(f"Cached OASIS-3 deliverable not at {cached_dest}")
    if not REFERENCE_MD5.exists():
        pytest.skip(f"Reference md5 list missing at {REFERENCE_MD5}")

    # Stage tmp_path: raw is large so symlink it; CSVs are small +
    # process() may pass them around so copy them.
    os.symlink(raw, tmp_path / "raw")
    shutil.copy(cohort_csv, tmp_path / "cohort_sessions.csv")
    shutil.copy(covariates_csv, tmp_path / "covariates.csv")

    n_jobs = os.cpu_count() or 1
    process(dest=tmp_path, n_jobs=n_jobs)

    current = _md5_set(tmp_path)
    reference = _read_reference()

    missing_in_current = set(reference) - set(current)
    extra_in_current = set(current) - set(reference)
    content_diffs = [
        name
        for name in set(current) & set(reference)
        if current[name] != reference[name]
    ]
    assert not missing_in_current and not extra_in_current and not content_diffs, (
        f"md5 mismatch: missing={sorted(missing_in_current)[:5]}, "
        f"extra={sorted(extra_in_current)[:5]}, "
        f"content_diffs={sorted(content_diffs)[:5]}, "
        f"total_content_diffs={len(content_diffs)}/{len(reference)}"
    )
