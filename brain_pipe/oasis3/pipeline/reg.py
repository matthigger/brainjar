"""Stage 5: register every cohort subject's image features to MNI152.

Per subject (parallel over the cohort):

1. ``SyN`` register T1w → MNI152 (the per-subject anchor).
2. ``Rigid`` register b0 → T1w (b0 = mean of the DWI's b=0 volumes).
3. Apply the T1→MNI warp to the T1 itself.
4. Compose (b0→T1) ∘ (T1→MNI) and apply to FA, MD.

All output NIfTIs are multiplied by the MNI brain mask before writing
— every subject lives in the same template space, so the group mask is
canonical; pre-masking removes downstream mask-juggling and fixes
viewer dynamic-range issues caused by out-of-brain outliers (e.g. MD
values up to ~50 mm/ms in CSF and air dominating the colormap). This
is the same convention used by ADNI / fMRIPrep / HCP-A/D for atlas-
space deliverables.

Outputs in ``dest`` (all in MNI152 on the same grid, brain-masked):

    <sbj>_t1.nii.gz
    <sbj>_fa.nii.gz
    <sbj>_md.nii.gz
    mni_template.nii.gz
    group_mask.nii.gz
"""

import shutil
from pathlib import Path

import numpy as np
import pandas as pd


# Templateflow identifier — recorded redundantly with manifest.yaml so a
# typo in one place doesn't silently drift from the other.
TEMPLATE = "MNI152NLin2009cAsym"
TEMPLATE_RES_MM = 1


def _resolve_mni(dest):
    """Fetch the MNI152 T1w + brain mask via templateflow, return both
    as on-disk paths under ``<dest>/mni152/``.

    templateflow handles its own cache (``~/.cache/templateflow``) so
    we don't re-download; we copy into ``<dest>/mni152/`` so the
    processed bundle is self-contained.
    """
    import templateflow.api as tflow

    out_dir = Path(dest) / "mni152"
    out_dir.mkdir(parents=True, exist_ok=True)

    t1 = out_dir / f"{TEMPLATE}_T1w.nii.gz"
    mask = out_dir / f"{TEMPLATE}_brain_mask.nii.gz"
    if not t1.exists():
        src = tflow.get(TEMPLATE, resolution=TEMPLATE_RES_MM,
                        desc=None, suffix="T1w", extension=".nii.gz")
        shutil.copy(src, t1)
    if not mask.exists():
        src = tflow.get(TEMPLATE, resolution=TEMPLATE_RES_MM,
                        desc="brain", suffix="mask", extension=".nii.gz")
        shutil.copy(src, mask)
    return t1, mask


def _find_t1(scans_dir, mr_id):
    """T1w nifti from the XNAT-delivered layout::

        <scans_dir>/<mr_id>/<mr_id>/scans/anat*-T1w/resources/NIFTI/files/
            sub-*_T1w.nii.gz
    """
    session_root = scans_dir / mr_id / mr_id / "scans"
    if not session_root.exists():
        return None
    for d in sorted(session_root.glob("anat*-T1w")):
        nifti_files = d / "resources" / "NIFTI" / "files"
        niftis = sorted(nifti_files.glob("sub-*_T1w.nii.gz"))
        if niftis:
            return niftis[0]
    return None


def _find_dwi(scans_dir, mr_id):
    """DWI nifti + sibling fa/md from the XNAT-delivered layout.

    Returns ``(nifti_files_dir, dwi_nii)``; the directory is needed so
    callers can pick up the sibling ``fa.nii.gz`` / ``md.nii.gz`` that
    :mod:`dti` writes alongside, and the BIDS-style ``*.bval`` two
    levels over for b0 extraction.
    """
    session_root = scans_dir / mr_id / mr_id / "scans"
    if not session_root.exists():
        return None
    for d in sorted(session_root.glob("dwi*-dwi")):
        nifti_files = d / "resources" / "NIFTI" / "files"
        dwi = next(iter(nifti_files.glob("sub-*_dwi.nii.gz")), None)
        if dwi is not None:
            return nifti_files, dwi
    return None


def _extract_b0(dwi_nii, bval_path):
    """Mean over the DWI's b=0 volumes; written as ``b0.nii.gz``
    next to the DWI. Idempotent.
    """
    import nibabel as nib

    folder = dwi_nii.parent
    b0_path = folder / "b0.nii.gz"
    if b0_path.exists():
        return b0_path

    bvals = np.loadtxt(bval_path)
    img = nib.load(str(dwi_nii))
    data = img.get_fdata()
    # threshold for "b≈0" — OASIS-3 nominal b0s often record as small
    # positive numbers due to scanner roundoff; 50 is a safe shoulder.
    is_b0 = bvals < 50
    if not is_b0.any():
        raise RuntimeError(f"No b≈0 volumes in {dwi_nii}")
    b0 = data[..., is_b0].mean(axis=-1)
    nib.save(nib.Nifti1Image(b0, img.affine, img.header), str(b0_path))
    return b0_path


def _register_one(sbj, t1_path, dwi_dir, dwi_nii, bval_path,
                  mni_t1_path, mni_mask_path,
                  dest, random_seed=1):
    """Register one subject; write t1/fa/md MNI-space NIfTIs into ``dest``."""
    import ants

    mni = ants.image_read(str(mni_t1_path))
    mni_mask = ants.image_read(str(mni_mask_path))
    t1 = ants.image_read(str(t1_path))

    # 1. T1 -> MNI nonlinear
    t1_to_mni = ants.registration(
        fixed=mni, moving=t1,
        type_of_transform="SyN", metric="CC",
        random_seed=random_seed,
    )
    t1_to_mni_xforms = t1_to_mni["fwdtransforms"]

    # 2. b0 -> T1 rigid
    b0_path = _extract_b0(dwi_nii, bval_path)
    b0 = ants.image_read(str(b0_path))
    b0_to_t1 = ants.registration(
        fixed=t1, moving=b0,
        type_of_transform="Rigid",
        random_seed=random_seed,
    )
    b0_to_t1_xforms = b0_to_t1["fwdtransforms"]

    # ANTs convention: transforms in transformlist apply right-to-left.
    # b0 space -> MNI: apply b0->T1 first, then T1->MNI ->
    # [t1_to_mni, b0_to_t1].
    b0_to_mni_xforms = t1_to_mni_xforms + b0_to_t1_xforms

    fa_path = dwi_dir / "fa.nii.gz"
    md_path = dwi_dir / "md.nii.gz"

    def _warp(moving_path, out_name, xforms, interp="linear"):
        moving = ants.image_read(str(moving_path))
        out = ants.apply_transforms(
            fixed=mni, moving=moving,
            transformlist=xforms,
            interpolator=interp,
        )
        # Zero out non-brain voxels: every subject is on the same MNI
        # grid as the canonical group mask, so masking here means
        # downstream voxelwise stats can drop the mask-juggling and
        # viewers auto-fit colormaps to the in-brain dynamic range.
        (out * mni_mask).to_file(str(Path(dest) / f"{sbj}_{out_name}.nii.gz"))

    _warp(t1_path, "t1", t1_to_mni_xforms)
    _warp(fa_path, "fa", b0_to_mni_xforms)
    _warp(md_path, "md", b0_to_mni_xforms)

    print(f"[DONE] {sbj}")


def register_cohort(cohort_csv, raw_dir, dest, manifest, n_jobs=1):
    """Register every cohort subject to MNI152; write t1, fa, md
    plus ``mni_template.nii.gz`` and ``group_mask.nii.gz``.
    """
    from joblib import Parallel, delayed

    cohort_csv = Path(cohort_csv)
    raw_dir = Path(raw_dir)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    scans_dir = raw_dir / "scans"

    print("  resolving MNI152 template")
    mni_t1, mni_mask = _resolve_mni(dest)
    # Copy into the processed bundle as the canonical names the README
    # documents.
    shutil.copy(mni_t1, dest / "mni_template.nii.gz")
    shutil.copy(mni_mask, dest / "group_mask.nii.gz")

    df = pd.read_csv(cohort_csv)
    work = []
    missing = []
    for _, row in df.iterrows():
        sbj = row["subject_id"]
        t1 = _find_t1(scans_dir, row["dwi_mr_id"])
        dwi_found = _find_dwi(scans_dir, row["dwi_mr_id"])
        if not (t1 and dwi_found):
            missing.append(sbj)
            continue
        dwi_dir, dwi_nii = dwi_found
        # bval/bvec live two levels over in BIDS/files/, alongside the
        # *_dwi.json sidecar (the dti stage symlinks them in as 'bvals'/
        # 'bvecs' under NIFTI/files/ — but for b0 extraction we want the
        # original .bval to pair voxel-wise with the dwi nifti).
        bids_files = dwi_dir.parent.parent / "BIDS" / "files"
        bval = next(iter(sorted(bids_files.glob("*.bval"))), None)
        if bval is None:
            missing.append(sbj)
            continue
        work.append((sbj, t1, dwi_dir, dwi_nii, bval))

    if missing:
        print(f"  [WARN] skipping {len(missing)} subjects with missing inputs: "
              f"{', '.join(missing[:5])}"
              f"{'...' if len(missing) > 5 else ''}")

    print(f"  registering {len(work)} subjects (n_jobs={n_jobs})")
    Parallel(n_jobs=n_jobs, verbose=10)(
        delayed(_register_one)(
            sbj, t1, dwi_dir, dwi_nii, bval,
            mni_t1, mni_mask, dest,
        )
        for sbj, t1, dwi_dir, dwi_nii, bval in work
    )
