"""Bit-equality regression tests for ``brainjar.hcp_ya_open``.

This file is excluded from default pytest discovery (see
``tests/conftest.py``). Invoke explicitly:

    pytest tests/hcp_ya_open/test_repro.py -v                       # all
    pytest tests/hcp_ya_open/test_repro.py::test_dti_single_subject_deterministic
    pytest tests/hcp_ya_open/test_repro.py::test_syn_bit_identical_to_reference
    pytest tests/hcp_ya_open/test_repro.py::test_zenodo_download_md5_matches_reference

Requirements:
- Raw HCP data at ``~/.local/share/brainjar/hcp_ya_open/raw/`` (the
  package's default cache; reused so the 266 GB doesn't need to be
  re-staged into a temp dir).
- Pipeline extra installed: ``pip install brainjar[hcp_ya_open-pipeline]``.
- Internet for the Zenodo test.
- Approx wall time: ~3 min DTI, ~14 min SyN, ~3 min Zenodo download.
"""

import hashlib
import os
import re
from pathlib import Path

import pytest

REFERENCE_MD5 = Path(__file__).parent.parent / "reference" / "hcp_ya_open_v2_md5.txt"
OUTPUT_PATTERN = re.compile(
    r"^(?:\d{6}_(?:fa|md)\.nii\.gz|fa_template\.nii\.gz|"
    r"group_mask\.nii\.gz|covariates\.csv)$"
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


def _default_raw():
    from brainjar.hcp_ya_open.fetch import _resolve_dest
    return _resolve_dest() / "raw"


def _find_subject_with_dti(raw_dir):
    """First subject (smallest id) whose Diffusion folder has data + cached fa/md."""
    for d in sorted(raw_dir.glob("*_Diffusion3TRecommended/*/T1w/Diffusion")):
        files = {f.name for f in d.iterdir()}
        if {"data.nii.gz", "bvals", "bvecs", "fa.nii.gz", "md.nii.gz"} <= files:
            sbj_match = re.search(r"\d{6}", str(d))
            if sbj_match:
                return sbj_match.group(), d
    return None, None


def test_dti_single_subject_deterministic(tmp_path):
    """Re-run DIPY DTI on one subject; md5 must match the cached fa/md.

    Cheap (~1–2 min) sanity check that the tensor fit is deterministic on
    this platform. Inputs are symlinked from the cached raw into tmp_path
    so the per-subject fa/md outputs land in tmp_path, not in raw/.
    """
    pytest.importorskip("dipy")
    pytest.importorskip("nibabel")

    raw = _default_raw()
    if not raw.exists():
        pytest.skip(f"Raw HCP data not at {raw}")

    sbj, src_dir = _find_subject_with_dti(raw)
    if sbj is None:
        pytest.skip(f"No subject under {raw} has data.nii.gz + cached fa/md")

    for name in ("data.nii.gz", "bvals", "bvecs"):
        os.symlink(src_dir / name, tmp_path / name)

    from brainjar._dwi_pipeline.dti import process_dti
    from dipy.reconst.dti import fractional_anisotropy, mean_diffusivity

    process_dti(
        tmp_path / "data.nii.gz",
        {"fa": fractional_anisotropy, "md": mean_diffusivity},
    )

    for label in ("fa", "md"):
        produced = _md5(tmp_path / f"{label}.nii.gz")
        cached = _md5(src_dir / f"{label}.nii.gz")
        assert produced == cached, (
            f"DTI {label} for subject {sbj} differs from cached "
            f"({produced} vs {cached})"
        )


def test_syn_bit_identical_to_reference(tmp_path):
    """Full seeded SyN re-run into tmp_path; all 203 output md5s must match.

    Uses the raw HCP data + cached DTI at the default location, so stage 2
    (DTI) short-circuits and only stage 3 (SyN) + stage 4 (covariates)
    actually run. Wall time scales with ``os.cpu_count()``: roughly 14 min
    on 32 cores, ~2 h on 4 cores.
    """
    pytest.importorskip("dipy")
    pytest.importorskip("ants")
    from brainjar.hcp_ya_open import process

    raw = _default_raw()
    if not raw.exists():
        pytest.skip(f"Raw HCP data not at {raw}")
    if not REFERENCE_MD5.exists():
        pytest.skip(f"Reference md5 list missing at {REFERENCE_MD5}")

    n_jobs = os.cpu_count() or 1
    # n_jobs_dti not specified: process() caps it at min(n_jobs, 4),
    # which keeps DTI memory bounded on small machines even though it
    # short-circuits here.
    process(
        download=False,
        raw_dir=raw,
        dest=tmp_path,
        n_jobs=n_jobs,
    )

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


def test_zenodo_download_md5_matches_reference():
    """Verify the deposit at the default cache md5-matches the reference.

    Calls ``process(download=True)`` which:
    - returns instantly if the default cache is already populated (the
      ``.complete`` sentinel exists), OR
    - prompts the user to type the HCP DUA agreement and downloads the
      Zenodo archive to the default cache.

    If the user declines the DUA, ``process`` raises ``SystemExit`` and
    this test errors out — that is the intended "throw an error"
    behavior when the download isn't available.

    To force a true round-trip test of the Zenodo download path, clear
    the default cache first::

        rm -rf ~/.local/share/brainjar/hcp_ya_open/{,*.nii.gz,covariates.csv,.complete}
        # (or override with BRAINJAR_HCP_YA_OPEN_PATH)
    """
    if not REFERENCE_MD5.exists():
        pytest.skip(f"Reference md5 list missing at {REFERENCE_MD5}")

    from brainjar.hcp_ya_open import process
    from brainjar.hcp_ya_open.fetch import _resolve_dest

    dest = process(download=True)
    assert dest == _resolve_dest(), "process() returned an unexpected path"

    current = _md5_set(dest)
    reference = _read_reference()

    missing_in_current = set(reference) - set(current)
    extra_in_current = set(current) - set(reference)
    content_diffs = [
        name
        for name in set(current) & set(reference)
        if current[name] != reference[name]
    ]
    assert not missing_in_current and not extra_in_current and not content_diffs, (
        f"Zenodo deposit differs from seeded reference. "
        f"missing={sorted(missing_in_current)[:5]}, "
        f"extra={sorted(extra_in_current)[:5]}, "
        f"content_diffs={sorted(content_diffs)[:5]}, "
        f"total_content_diffs={len(content_diffs)}/{len(reference)}."
    )
