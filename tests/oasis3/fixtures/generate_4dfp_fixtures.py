"""Generate synthetic 4dfp fixtures + WashU-converted reference NIfTIs.

Run on a machine where WashU's ``nifti_4dfp`` is on PATH; commit the
resulting ``inputs/`` and ``expected/`` directories. End users running
``pytest`` then validate our Python reader against the frozen WashU
outputs without needing to install WashU themselves.

Coverage matrix (24 base cases + 2 extras):

  * orientation ∈ {2, 3, 4}                  — 3 axis-permutation cases
  * sign(mmppix) ∈ {+, -}³                   — 8 axis-flip combinations
  * extras: 4D (n_dim=4, n4=2) and center=(0, 0, 0)

Per case we write ``<stem>.4dfp.{img,ifh,hdr}`` to ``inputs/`` and
``<stem>.nii`` to ``expected/``. The data is a coordinate-gradient
(``data[i,j,k] = 100*i + j + 0.001*k``) so any axis swap / flip is
detectable in the voxel values, not just the affine.

Re-running this script overwrites both directories.
"""

from __future__ import annotations

import itertools
import shutil
import subprocess
from pathlib import Path

import numpy as np


HERE = Path(__file__).parent
INPUTS = HERE / "inputs"
EXPECTED = HERE / "expected"

# Non-cubic shape so each axis is identifiable in the data array.
SHAPE = (4, 5, 6)
# Distinct per-axis voxel sizes so any axis swap is visible in mmppix.
SCALING = (2.0, 3.0, 4.0)
# Off-origin center so the translation half of the affine is non-trivial.
CENTER_DEFAULT = (10.0, -20.0, 30.0)


_IFH_TEMPLATE = """\
INTERFILE\t:=
version of keys\t:= 3.3
number format\t\t:= float
number of bytes per pixel\t:= 4
imagedata byte order\t:= littleendian
orientation\t\t:= {orientation}
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


def gradient_data(shape, n4=1):
    """Coordinate-gradient float32 array. data[i,j,k(,t)] = 100*i + j + 0.001*k + t."""
    n1, n2, n3 = shape
    i = np.arange(n1).reshape(n1, 1, 1)
    j = np.arange(n2).reshape(1, n2, 1)
    k = np.arange(n3).reshape(1, 1, n3)
    base = (100.0 * i + j + 0.001 * k).astype(np.float32)
    if n4 == 1:
        return base
    return np.stack([base + t for t in range(n4)], axis=-1)


def write_fixture(stem, data, mmppix, center, orientation):
    n1, n2, n3 = data.shape[:3]
    n4 = data.shape[3] if data.ndim == 4 else 1
    ndim = 4 if data.ndim == 4 else 3

    img_path = stem.with_suffix(".4dfp.img")
    ifh_path = stem.with_suffix(".4dfp.ifh")
    hdr_path = stem.with_suffix(".4dfp.hdr")

    if ndim == 3:
        raw = data[..., np.newaxis].transpose(3, 2, 1, 0).astype("<f4")
    else:
        raw = data.transpose(3, 2, 1, 0).astype("<f4")
    raw.tofile(img_path)

    ifh_path.write_text(_IFH_TEMPLATE.format(
        orientation=orientation,
        ndim=ndim, n1=n1, n2=n2, n3=n3, n4=n4,
        sx=abs(mmppix[0]), sy=abs(mmppix[1]), sz=abs(mmppix[2]),
        mx=mmppix[0], my=mmppix[1], mz=mmppix[2],
        cx=center[0], cy=center[1], cz=center[2],
    ))
    hdr_path.write_bytes(b"\x00" * 348)
    return img_path


def run_nifti_4dfp(img_path, out_path):
    """Run WashU's nifti_4dfp -n on ``img_path``, saving to ``out_path``."""
    out_stem = out_path.with_suffix("")
    subprocess.run(
        ["nifti_4dfp", "-n", str(img_path), str(out_stem)],
        check=True, capture_output=True,
    )
    # nifti_4dfp may emit .nii or .nii.gz; normalize.
    candidates = [out_stem.with_suffix(".nii"), out_stem.with_suffix(".nii.gz")]
    written = next((p for p in candidates if p.exists()), None)
    if written is None:
        raise RuntimeError(
            f"nifti_4dfp produced no output for {img_path}; "
            f"expected one of {candidates}"
        )
    if written != out_path:
        shutil.move(str(written), str(out_path))


def case_name(orientation, sign_x, sign_y, sign_z, suffix=""):
    s = lambda v: "p" if v > 0 else "n"  # noqa: E731
    return f"ori{orientation}_{s(sign_x)}{s(sign_y)}{s(sign_z)}{suffix}"


def generate():
    if shutil.which("nifti_4dfp") is None:
        raise SystemExit(
            "nifti_4dfp not on PATH. Install via "
            "tests/oasis3/install_nifti_4dfp.sh first."
        )

    for d in (INPUTS, EXPECTED):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    cases = []

    # Core 24: orientation × sign combinations on a 3D gradient.
    data_3d = gradient_data(SHAPE)
    for orientation in (2, 3, 4):
        for sx, sy, sz in itertools.product((+1, -1), repeat=3):
            mmppix = (sx * SCALING[0], sy * SCALING[1], sz * SCALING[2])
            name = case_name(orientation, sx, sy, sz)
            img = write_fixture(
                INPUTS / name, data_3d, mmppix, CENTER_DEFAULT, orientation,
            )
            run_nifti_4dfp(img, EXPECTED / f"{name}.nii")
            cases.append(name)

    # Extra 1: 4D volume (n4=2). Picks orientation=2, all-positive signs.
    data_4d = gradient_data(SHAPE, n4=2)
    name = "ori2_ppp_4d"
    img = write_fixture(
        INPUTS / name, data_4d, SCALING, CENTER_DEFAULT, orientation=2,
    )
    run_nifti_4dfp(img, EXPECTED / f"{name}.nii")
    cases.append(name)

    # Extra 2: center at origin. Picks orientation=2, all-positive signs.
    name = "ori2_ppp_origin"
    img = write_fixture(
        INPUTS / name, data_3d, SCALING, (0.0, 0.0, 0.0), orientation=2,
    )
    run_nifti_4dfp(img, EXPECTED / f"{name}.nii")
    cases.append(name)

    print(f"wrote {len(cases)} fixtures to {INPUTS}/ and {EXPECTED}/")
    for c in cases:
        print(f"  {c}")


if __name__ == "__main__":
    generate()
