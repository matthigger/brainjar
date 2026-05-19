"""Tests for ``brain_pipe.oasis3.pipeline.fourdfp``.

Two layers of validation:

1. **Synthetic round-trip** (always runs): write a known float32 array
   and a hand-crafted ``.ifh`` to a temp dir, load via our reader,
   compare data + affine against the inputs. Catches parser bugs that
   are independent of WashU's tool.

2. **WashU reference** (skipped unless ``nifti_4dfp`` on PATH and
   real PUP test data is on disk): convert the same ``.4dfp.img`` via
   WashU's ``nifti_4dfp`` (the gold standard) and via our reader,
   compare both. Catches affine-convention bugs that the synthetic
   test can't.

If ``nifti_4dfp`` is missing, the WashU-ref test is skipped with a
warning that points to how to install it
(<https://4dfp.readthedocs.io/>). The synthetic test still runs.
"""

import os
import shutil
import subprocess
import warnings
from pathlib import Path

import numpy as np
import pytest

import nibabel as nib

from brain_pipe.oasis3.pipeline.fourdfp import (
    affine_from_ifh,
    load,
    parse_ifh,
)


# ---- synthetic round-trip -----------------------------------------------

# Tiny known volume + minimal .ifh content for round-trip testing.
_IFH_TEMPLATE = """\
INTERFILE\t:=
version of keys\t:= 3.3
number format\t\t:= float
number of bytes per pixel\t:= 4
imagedata byte order\t:= littleendian
orientation\t\t:= 2
number of dimensions\t:= {ndim}
matrix size [1]\t:= {n1}
matrix size [2]\t:= {n2}
matrix size [3]\t:= {n3}
matrix size [4]\t:= {n4}
scaling factor (mm/pixel) [1]\t:= {sx}
scaling factor (mm/pixel) [2]\t:= {sy}
scaling factor (mm/pixel) [3]\t:= {sz}
mmppix\t:=   {mx} {my} {mz}
center\t:=   {cx} {cy} {cz}
"""


def _write_synthetic_4dfp(stem, data, mmppix, center):
    """Write a minimal valid 4dfp triplet (.img + .ifh, plus an empty
    .hdr placeholder) to ``stem``. ``data`` is the array; mmppix and
    center are the .ifh fields.

    Returns the path to the .4dfp.img file.
    """
    stem = Path(stem)
    n1, n2, n3 = data.shape[:3]
    n4 = data.shape[3] if data.ndim == 4 else 1
    ndim = 4 if data.ndim == 4 else 3

    img_path = stem.with_suffix(".4dfp.img")
    ifh_path = stem.with_suffix(".4dfp.ifh")
    hdr_path = stem.with_suffix(".4dfp.hdr")

    # On-disk order: transpose to (n4, n3, n2, n1) row-major.
    if ndim == 3:
        raw = data[..., np.newaxis].transpose(3, 2, 1, 0).astype("<f4")
    else:
        raw = data.transpose(3, 2, 1, 0).astype("<f4")
    raw.tofile(img_path)

    ifh_path.write_text(_IFH_TEMPLATE.format(
        ndim=ndim, n1=n1, n2=n2, n3=n3, n4=n4,
        sx=abs(mmppix[0]), sy=abs(mmppix[1]), sz=abs(mmppix[2]),
        mx=mmppix[0], my=mmppix[1], mz=mmppix[2],
        cx=center[0], cy=center[1], cz=center[2],
    ))
    hdr_path.write_bytes(b"\x00" * 348)  # placeholder Analyze 7.5 hdr
    return img_path


def test_parse_ifh_extracts_known_fields(tmp_path):
    img = _write_synthetic_4dfp(
        tmp_path / "tiny",
        data=np.zeros((4, 5, 6), dtype=np.float32),
        mmppix=(1.0, -1.0, -1.0),
        center=(2.5, -3.0, -3.5),
    )
    md = parse_ifh(img.with_suffix(".ifh"))
    assert md["matrix size [1]"] == 4
    assert md["matrix size [2]"] == 5
    assert md["matrix size [3]"] == 6
    assert md["mmppix"] == [1.0, -1.0, -1.0]
    assert md["center"] == [2.5, -3.0, -3.5]
    assert md["imagedata byte order"] == "littleendian"
    assert md["number format"] == "float"


def test_affine_centers_image_center_voxel_at_ifh_center(tmp_path):
    """For a (5, 5, 5) image with center=(10, -10, 0), the affine should
    map voxel (2, 2, 2) — the image center in 0-indexed terms — exactly
    to (10, -10, 0) in world space."""
    img = _write_synthetic_4dfp(
        tmp_path / "tiny",
        data=np.zeros((5, 5, 5), dtype=np.float32),
        mmppix=(1.0, -1.0, -1.0),
        center=(10.0, -10.0, 0.0),
    )
    md = parse_ifh(img.with_suffix(".ifh"))
    A = affine_from_ifh(md)

    center_voxel = np.array([2, 2, 2, 1])
    world = A @ center_voxel
    np.testing.assert_allclose(world[:3], [10.0, -10.0, 0.0], atol=1e-9)


def test_load_recovers_synthetic_data_and_shape(tmp_path):
    """End-to-end: write a known float32 array, load it back, ensure
    data + shape + affine are preserved within float tolerance."""
    rng = np.random.default_rng(seed=42)
    data = rng.uniform(0, 5, size=(8, 9, 10)).astype(np.float32)
    img = _write_synthetic_4dfp(
        tmp_path / "tiny",
        data=data,
        mmppix=(2.0, -2.0, -2.0),
        center=(7.0, -8.0, -9.0),
    )

    nii = load(img)

    assert nii.shape == (8, 9, 10)
    np.testing.assert_array_equal(nii.get_fdata(dtype=np.float32), data)

    # affine: voxel (3.5, 4.0, 4.5) -- the image-center voxel for a
    # (8, 9, 10) image -- should map to (7, -8, -9)
    A = nii.affine
    image_center_voxel = np.array([(8 - 1) / 2, (9 - 1) / 2, (10 - 1) / 2, 1])
    world = A @ image_center_voxel
    np.testing.assert_allclose(world[:3], [7.0, -8.0, -9.0], atol=1e-6)


# ---- WashU nifti_4dfp reference comparison ------------------------------

def _which_nifti_4dfp():
    return shutil.which("nifti_4dfp")


def _real_pup_image():
    """Locate a real OASIS-3 PUP .4dfp.img if available locally. Returns
    ``None`` when test data isn't on disk."""
    cache = Path.home() / ".local/share/brain_pipe/oasis3/raw/pup"
    if not cache.exists():
        return None
    hits = list(cache.glob("*/*_msum_SUVR.4dfp.img"))
    return hits[0] if hits else None


@pytest.mark.skipif(
    _which_nifti_4dfp() is None,
    reason=(
        "nifti_4dfp not on PATH — cannot validate against WashU's "
        "gold-standard 4dfp→NIfTI conversion. Install the WashU 4dfp "
        "toolkit (see https://4dfp.readthedocs.io/) to run this test. "
        "The synthetic round-trip tests still cover parser + affine "
        "self-consistency."
    ),
)
def test_load_matches_washu_nifti_4dfp(tmp_path):
    src = _real_pup_image()
    if src is None:
        pytest.skip(
            "no PUP .4dfp.img on disk to compare against. Run "
            "`brain_pipe.oasis3.fetch()` first, then re-run this test."
        )

    # WashU reference conversion. ``nifti_4dfp -n in out_stem`` writes
    # out_stem.nii (the toolkit picks the extension).
    out_stem = tmp_path / "washu"
    subprocess.run(
        ["nifti_4dfp", "-n", str(src), str(out_stem)],
        check=True, capture_output=True,
    )
    # nifti_4dfp may write .nii or .nii.gz; resolve.
    nii_path = next(
        (p for p in [out_stem.with_suffix(".nii"),
                     out_stem.with_suffix(".nii.gz")] if p.exists()),
        None,
    )
    assert nii_path is not None, (
        f"nifti_4dfp produced no .nii output for {src}; tmp_path "
        f"contents: {list(tmp_path.iterdir())}"
    )

    ours = load(src)
    washu = nib.load(str(nii_path))

    assert ours.shape == washu.shape, (
        f"shape mismatch: ours {ours.shape} vs washu {washu.shape}"
    )
    # Affines should match within float tolerance.
    np.testing.assert_allclose(
        ours.affine, washu.affine, atol=1e-4,
        err_msg="our affine differs from WashU nifti_4dfp's affine",
    )
    # Data should match within float tolerance. (nifti_4dfp may
    # rescale int16 -> float; for already-float SUVR images they
    # should match bit-for-bit modulo storage type.)
    np.testing.assert_allclose(
        ours.get_fdata(dtype=np.float32),
        washu.get_fdata(dtype=np.float32),
        atol=1e-5,
        err_msg="our data differs from WashU nifti_4dfp's data",
    )
