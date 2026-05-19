"""Read WashU 4dfp images into nibabel ``Nifti1Image``.

The OASIS-3 PUP outputs ship in WashU's legacy 4dfp format
(``.4dfp.{img,hdr,ifh}`` triplets), not NIfTI. ``nibabel.load`` reads
``.4dfp.img`` as ``Spm2AnalyzeImage`` (the ``.hdr`` happens to be
Analyze-7.5-compatible) but silently drops the orientation info that
lives in the ``.ifh`` text sidecar, leaving us with a generic
Analyze-default affine. For our T1→MNI registration that affine
mismatch is fatal.

This module parses the ``.ifh``, derives a proper NIfTI affine, reads
the raw float32 data, and returns a ``Nifti1Image`` we can hand to
ANTs.

Format reference: <https://4dfp.readthedocs.io/>. Key ``.ifh`` fields:

  matrix size [1..4]      per-axis dimensions (4 is time)
  scaling factor (mm/pixel) [1..3]   per-axis voxel size, unsigned
  mmppix                  signed voxel sizes (sign = axis flip)
  center                  world coord (mm) of voxel ((N+1)/2 in
                          1-indexed convention) i.e. image center
  imagedata byte order    'littleendian' or 'bigendian'
  number format           expected 'float'

The pipeline validates this implementation against WashU's
``nifti_4dfp`` reference tool in ``tests/oasis3/test_fourdfp.py``.
"""

from pathlib import Path

import nibabel as nib
import numpy as np


def parse_ifh(ifh_path):
    """Parse a 4dfp ``.ifh`` (INTERFILE-style ``key := value``) into a
    dict, coercing known numeric fields to their proper types.

    Returns a dict with at minimum:

        'matrix size [1..4]'  -> int
        'scaling factor (mm/pixel) [1..3]' -> float
        'mmppix'              -> [float, float, float]
        'center'              -> [float, float, float]
        'imagedata byte order' -> 'littleendian' / 'bigendian'
        'number format'       -> 'float'
        'orientation'         -> int (2=transverse, 3=coronal, 4=sagittal)
    """
    out = {}
    for raw in Path(ifh_path).read_text().splitlines():
        if ":=" not in raw:
            continue
        key, _, value = raw.partition(":=")
        key, value = key.strip(), value.strip()
        if key in ("mmppix", "center"):
            out[key] = [float(x) for x in value.split()]
        elif key.startswith("matrix size") or key in (
            "number of dimensions", "number of bytes per pixel", "orientation",
        ):
            out[key] = int(value)
        elif key.startswith("scaling factor"):
            out[key] = float(value)
        else:
            out[key] = value
    return out


def affine_from_ifh(metadata):
    """Construct a NIfTI 4×4 affine from parsed ``.ifh`` metadata.

    The 4dfp convention: ``center`` is the world coordinate (mm) of
    the **image-center voxel**, i.e. voxel index ``((N1+1)/2, ...)``
    in 4dfp's 1-indexed convention. ``mmppix`` is the signed per-axis
    voxel size.

    For NIfTI's 0-indexed voxel ``(i, j, k)``, the image-center voxel
    is at index ``(N-1)/2``. The affine maps voxel → world via::

        world = diag(mmppix) @ voxel + offset
        offset = center − diag(mmppix) @ (N − 1)/2

    so that voxel ``(N-1)/2`` lands exactly at ``center``.
    """
    N = np.array(
        [metadata[f"matrix size [{i}]"] for i in (1, 2, 3)], dtype=float,
    )
    mmppix = np.array(metadata["mmppix"], dtype=float)
    center = np.array(metadata["center"], dtype=float)

    affine = np.eye(4)
    affine[np.arange(3), np.arange(3)] = mmppix
    affine[:3, 3] = center - mmppix * (N - 1) / 2
    return affine


def load(img_path):
    """Load a 4dfp image as a ``nibabel.Nifti1Image``.

    Args:
        img_path: path to the ``.4dfp.img`` binary data file. The
            sibling ``.4dfp.ifh`` is read for shape and affine.

    Returns:
        ``nibabel.Nifti1Image`` with the data array and a proper
        affine derived from the ``.ifh``.
    """
    img_path = Path(img_path)
    if not img_path.name.endswith(".4dfp.img"):
        raise ValueError(
            f"expected a *.4dfp.img file, got {img_path}",
        )
    ifh_path = img_path.with_suffix(".ifh")
    if not ifh_path.exists():
        raise FileNotFoundError(f"sibling .ifh missing: {ifh_path}")

    md = parse_ifh(ifh_path)

    if md.get("number format") != "float":
        raise NotImplementedError(
            f"only 'number format := float' is supported; "
            f"{img_path} declares {md.get('number format')!r}",
        )
    if md.get("number of bytes per pixel", 4) != 4:
        raise NotImplementedError(
            f"only 4-byte (float32) pixels supported; got "
            f"{md.get('number of bytes per pixel')}",
        )

    n_dim = md.get("number of dimensions", 3)
    shape = tuple(md[f"matrix size [{i}]"] for i in range(1, n_dim + 1))
    while len(shape) < 4:
        shape = shape + (1,)
    n1, n2, n3, n4 = shape

    byte_order = md.get("imagedata byte order", "littleendian")
    dtype = np.dtype("<f4") if byte_order == "littleendian" else np.dtype(">f4")

    expected_bytes = n1 * n2 * n3 * n4 * 4
    actual_bytes = img_path.stat().st_size
    if actual_bytes != expected_bytes:
        raise ValueError(
            f".4dfp.img size {actual_bytes} bytes != expected "
            f"{expected_bytes} from matrix size {shape}",
        )

    # 4dfp on-disk order: frame-major, then slice (axis 3), then row
    # (axis 2), then column (axis 1) varies fastest. C-order reshape
    # to (N4, N3, N2, N1) then transpose to (N1, N2, N3, N4) gives the
    # usual (x, y, z, t) view.
    raw = np.fromfile(img_path, dtype=dtype).reshape(n4, n3, n2, n1)
    data = raw.transpose(3, 2, 1, 0)
    if n_dim == 3 or n4 == 1:
        data = data[..., 0]

    return nib.Nifti1Image(data, affine_from_ifh(md))
