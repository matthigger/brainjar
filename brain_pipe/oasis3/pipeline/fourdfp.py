"""Read WashU 4dfp images into nibabel ``Nifti1Image``.

The OASIS-3 PUP outputs ship in WashU's legacy 4dfp format
(``.4dfp.{img,hdr,ifh}`` triplets), not NIfTI. ``nibabel.load`` reads
``.4dfp.img`` as ``Spm2AnalyzeImage`` (the ``.hdr`` happens to be
Analyze-7.5-compatible) but silently drops the orientation info that
lives in the ``.ifh`` text sidecar, leaving us with a generic
Analyze-default affine. For our T1→MNI registration that affine
mismatch is fatal.

This module parses the ``.ifh``, derives a NIfTI affine via the same
two-step algorithm WashU's ``nifti_4dfp`` uses, permutes the voxel
data accordingly, and returns a ``Nifti1Image`` we can hand to ANTs.

Format reference: <https://4dfp.readthedocs.io/>. Key ``.ifh`` fields:

  matrix size [1..4]      per-axis dimensions (4 is time)
  scaling factor (mm/pixel) [1..3]   per-axis voxel size, unsigned
  mmppix                  signed voxel sizes (sign = axis flip)
  center                  world coord (mm) of voxel ((N+1)/2 in
                          1-indexed convention) i.e. image center
  imagedata byte order    'littleendian' or 'bigendian'
  number format           expected 'float'
  orientation             2=transverse, 3=coronal, 4=sagittal

The implementation mirrors the C source at
``~/src/4dfp_tools/nifti_4dfp/{4dfp-format.c,transform.c}``:
``parse_4dfp`` builds an initial sform from orientation-permuted
``mmppix``/``center``; ``to_lpi`` finds dominant world axes; and
``auto_orient_header`` negates flipped columns and permutes axes to
land in NIfTI's (x, y, z) ordering. Validated against frozen WashU
outputs in ``tests/oasis3/fixtures/expected/``.
"""

from pathlib import Path

import nibabel as nib
import numpy as np


def parse_ifh(ifh_path):
    """Parse a 4dfp ``.ifh`` (INTERFILE-style ``key := value``) into a
    dict, coercing known numeric fields to their proper types.
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


def _initial_order(orientation):
    """4dfp orientation field → initial axis order on the input lattice.

    Mirrors the switch with fall-through in ``parse_4dfp`` (4dfp-format.c
    lines 179-196): start with [0,1,2], then for ori=4 swap order[0]↔[1],
    for ori∈{3,4} swap order[1]↔[2]. Time axis stays at index 3.
    """
    order = [0, 1, 2, 3]
    if orientation == 4:
        order[0], order[1] = order[1], order[0]
    if orientation in (3, 4):
        order[1], order[2] = order[2], order[1]
    elif orientation != 2:
        raise ValueError(f"unrecognized 4dfp orientation: {orientation}")
    return order


def _parse_4dfp_initial_sform(metadata):
    """Replicates the no-t4 branch of WashU's ``parse_4dfp``.

    Returns (sform_3x4, length_4, dims, n4) where sform is the initial
    affine *before* ``to_lpi`` / ``auto_orient_header`` are applied.
    """
    orientation = metadata["orientation"]
    order = _initial_order(orientation)

    length = [metadata[f"matrix size [{i}]"] for i in (1, 2, 3, 4)]

    # sform initialized to the permutation matrix: sform[order[i]][i] = 1.
    sform = np.zeros((3, 4), dtype=float)
    for i in range(3):
        sform[order[i], i] = 1.0

    spacing = list(metadata["mmppix"])
    center = list(metadata["center"])

    # Orientation-specific sign-flip + index shift on (spacing, center).
    # Switch with fall-through in the C: case 4 falls into case 3's block
    # (both x and z manipulated), case 3 alone only touches x.
    if orientation in (2, 4):
        center[2] = -center[2]
        spacing[2] = -spacing[2]
        center[2] = spacing[2] * (length[2] + 1) - center[2]
    if orientation in (2, 3, 4):
        center[0] = -center[0]
        spacing[0] = -spacing[0]
        center[0] = spacing[0] * (length[0] + 1) - center[0]

    # Fortran 1-indexing adjustment, then negate to express center as
    # the world coord of voxel (0,0,0) under NIfTI 0-indexed convention.
    center = [spacing[i] - center[i] for i in range(3)]

    # Compose: new_sform[:, :3] = sform[:, :3] @ diag(spacing);
    #          new_sform[:, 3] = sform[:, :3] @ center  (was 0 before).
    t4 = sform.copy()
    for i in range(3):
        for j in range(3):
            sform[i, j] = t4[i, j] * spacing[j]
        sform[i, 3] = sum(center[j] * t4[i, j] for j in range(3))

    return sform, length, metadata["number of dimensions"]


def _to_lpi(sform):
    """Find dominant-axis permutation + flip mask for an arbitrary sform.

    Returns (order, orient_bits). ``order[k]`` is the output axis that
    input axis k maps to; ``orient_bits`` is a 3-bit mask where bit k
    means input axis k needs flipping (because the dominant component
    of column k of sform is negative).

    Mirrors ``to_lpi`` in transform.c (lines 170-212).
    """
    order = [-1, -1, -1, 3]
    used = 0
    for i in range(2):  # only resolves columns 0 and 1; column 2 = the leftover
        best, best_j = -1.0, -1
        for j in range(3):
            if not (used & (1 << j)) and abs(sform[j, i]) > best:
                best, best_j = abs(sform[j, i]), j
        used |= (1 << best_j)
        order[i] = best_j
    # leftover axis gets column 2
    order[2] = {3: 2, 5: 1, 6: 0}[used]

    orient_bits = 0
    for i in range(3):
        if sform[order[i], i] < 0.0:
            orient_bits |= (1 << i)
    return order, orient_bits


def _auto_orient_header(sform, length, order, orient_bits):
    """Apply column flips and axis permutation to land in NIfTI orientation.

    Mirrors ``auto_orient_header`` in transform.c (lines 214-245).
    """
    sform = sform.copy()
    # For each input axis i whose flip bit is set: subtract the column
    # from the offset (with length-1 weighting) and negate the column.
    # NOTE: the C code reads `length[i]` here — pre-permutation lengths.
    for i in range(3):
        if orient_bits & (1 << i):
            for j in range(3):
                sform[j, 3] += (length[i] - 1) * sform[j, i]
                sform[j, i] = -sform[j, i]

    # Permute columns: new[i][order[j]] = old[i][j]. I.e. the column
    # that came from input axis j now sits at output column order[j].
    new = sform.copy()
    for j in range(3):
        new[:, order[j]] = sform[:, j]
    return new


def affine_from_ifh(metadata):
    """Construct the NIfTI 4×4 affine that ``nifti_4dfp -n`` would emit.

    The full algorithm is documented in ``parse_4dfp`` and the
    ``to_lpi``/``auto_orient_header`` helpers in WashU's source. This
    function ties those three stages together and pads the resulting
    3×4 to a 4×4 homogeneous matrix.
    """
    sform_3x4, length, _ = _parse_4dfp_initial_sform(metadata)
    order, orient_bits = _to_lpi(sform_3x4)
    final_3x4 = _auto_orient_header(sform_3x4, length, order, orient_bits)
    affine = np.eye(4)
    affine[:3, :] = final_3x4
    return affine


def _orient_data(data, order, orient_bits):
    """Permute and flip the voxel array to match WashU's NIfTI layout.

    Mirrors ``auto_orient`` in transform.c (lines 247-309): for each
    input voxel ``in_val``, the corresponding output voxel index is
    ``out_val[order[k]] = (length[k] - 1 - in_val[k])`` if flip bit k
    is set, else ``in_val[k]``. In numpy terms: transpose by
    ``revorder`` (the inverse of ``order``), then flip each output
    axis ``order[k]`` whose flip bit is set.

    ``data`` has shape ``(L0, L1, L2, L3)`` where axis k corresponds to
    input axis k.
    """
    revorder = [0] * 4
    for k, o in enumerate(order):
        revorder[o] = k
    permuted = np.ascontiguousarray(data.transpose(revorder))
    for k in range(3):
        if orient_bits & (1 << k):
            permuted = np.flip(permuted, axis=order[k])
    return np.ascontiguousarray(permuted)


def load(img_path):
    """Load a 4dfp image as a ``nibabel.Nifti1Image``.

    Args:
        img_path: path to the ``.4dfp.img`` binary data file. The
            sibling ``.4dfp.ifh`` is read for shape and affine.

    Returns:
        ``nibabel.Nifti1Image`` whose data array and affine match
        what WashU's ``nifti_4dfp -n`` would produce on the same input.
    """
    img_path = Path(img_path)
    if not img_path.name.endswith(".4dfp.img"):
        raise ValueError(f"expected a *.4dfp.img file, got {img_path}")
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
    length = [md[f"matrix size [{i}]"] for i in (1, 2, 3, 4)]
    n1, n2, n3, n4 = length

    byte_order = md.get("imagedata byte order", "littleendian")
    dtype = np.dtype("<f4") if byte_order == "littleendian" else np.dtype(">f4")

    expected_bytes = n1 * n2 * n3 * n4 * 4
    actual_bytes = img_path.stat().st_size
    if actual_bytes != expected_bytes:
        raise ValueError(
            f".4dfp.img size {actual_bytes} bytes != expected "
            f"{expected_bytes} from matrix size {length}",
        )

    # 4dfp on-disk order is column-major with axis 0 fastest. Reading
    # via numpy as (n4, n3, n2, n1) C-order and transposing to
    # (n1, n2, n3, n4) puts axis k at numpy axis k.
    raw = np.fromfile(img_path, dtype=dtype).reshape(n4, n3, n2, n1)
    data = raw.transpose(3, 2, 1, 0)  # (L0, L1, L2, L3)

    sform_3x4, length_4, _ = _parse_4dfp_initial_sform(md)
    order, orient_bits = _to_lpi(sform_3x4)
    final_3x4 = _auto_orient_header(sform_3x4, length_4, order, orient_bits)

    data = _orient_data(data, order, orient_bits)
    if n_dim == 3:
        data = data[..., 0]

    affine = np.eye(4)
    affine[:3, :] = final_3x4
    return nib.Nifti1Image(data.astype(np.float32, copy=False), affine)
