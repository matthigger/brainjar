"""Stage 5: register every cohort subject's four image features to MNI152.

Per subject (parallel over the cohort):

1. ``SyN`` register T1w → MNI152 (the per-subject anchor).
2. ``Rigid`` register b0 → T1w (b0 = mean of the DWI's b=0 volumes).
3. Apply the T1→MNI warp to the PUP AV45 SUVR and PUP AV1451 SUVR
   (both are already in T1 space, courtesy of PUP).
4. Compose (b0→T1) ∘ (T1→MNI) and apply to FA, MD.

After all subjects finish, copy the MNI152 brain mask to
``group_mask.nii.gz`` (a fixed reference is preferable to a
per-cohort intersection here — every subject lives in the same
template space, and the MNI brain mask is the field-standard
"voxels in brain" indicator).

Outputs in ``dest`` (all in MNI152 on the same grid):

    <sbj>_amyloid_suvr.nii.gz
    <sbj>_tau_suvr.nii.gz
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
    """T1w nifti from ``<scans_dir>/<mr_id>/anat*/*.nii.gz``."""
    session = scans_dir / mr_id
    if not session.exists():
        return None
    anat_dirs = sorted(session.glob("anat*"))
    for d in anat_dirs:
        # download_oasis_scans.sh + scan_type=T1w lands T1ws here; JSON
        # sidecars are present too. Skip those.
        niftis = sorted(d.glob("*.nii.gz"))
        if niftis:
            return niftis[0]
    return None


def _find_dwi(scans_dir, mr_id):
    """DWI nifti + sibling fa/md written by stage 4."""
    session = scans_dir / mr_id
    if not session.exists():
        return None
    dwi_dirs = sorted(session.glob("dwi*"))
    for d in dwi_dirs:
        niftis = sorted(d.glob("*.nii.gz"))
        # Exclude fa/md that stage 4 wrote into the same dir.
        niftis = [n for n in niftis if n.stem not in ("fa", "md",
                                                      "fa.nii", "md.nii")]
        if niftis:
            return d, niftis[0]
    return None


def _find_pup_suvr(pup_dir, pup_id):
    """A PUP session's SUVR NIfTI. Prefer PVC-corrected if present.

    PUP outputs include both raw SUVR and partial-volume-corrected
    SUVR (suffix ``_PVC``). Papers typically report PVC; we prefer it
    but fall back to the non-PVC if the PVC file isn't present (older
    PUP versions, etc.).
    """
    session = pup_dir / pup_id
    if not session.exists():
        return None
    candidates = list(session.glob("**/*SUVR*.nii*"))
    if not candidates:
        return None
    pvc = [c for c in candidates if "PVC" in c.name.upper()]
    return (pvc or candidates)[0]


def _extract_b0(dwi_nii, bval_path):
    """Mean over the DWI's b=0 volumes; written as ``b0.nii.gz``
    next to the DWI. Idempotent.
    """
    import ants
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
                  amyloid_path, tau_path, mni_t1_path, mni_mask_path,
                  dest, random_seed=1):
    """Register one subject; write four MNI-space NIfTIs into ``dest``."""
    import ants

    mni = ants.image_read(str(mni_t1_path))
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
    # Moving an image from b0 space -> MNI: apply b0->T1 first, then
    # T1->MNI -> [t1_to_mni, b0_to_t1].
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
        out.to_file(str(Path(dest) / f"{sbj}_{out_name}.nii.gz"))

    _warp(fa_path, "fa", b0_to_mni_xforms)
    _warp(md_path, "md", b0_to_mni_xforms)
    _warp(amyloid_path, "amyloid_suvr", t1_to_mni_xforms)
    _warp(tau_path, "tau_suvr", t1_to_mni_xforms)

    print(f"[DONE] {sbj}")


def register_cohort(cohort_csv, raw_dir, dest, manifest, n_jobs=1):
    """Register every cohort subject to MNI152; write the four
    image features plus ``mni_template.nii.gz`` and ``group_mask.nii.gz``.
    """
    from joblib import Parallel, delayed

    cohort_csv = Path(cohort_csv)
    raw_dir = Path(raw_dir)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    scans_dir = raw_dir / "scans"
    pup_dir = raw_dir / "pup"

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
        amyloid = _find_pup_suvr(pup_dir, row["av45_pup_id"])
        tau = _find_pup_suvr(pup_dir, row["tau_pup_id"])
        if not (t1 and dwi_found and amyloid and tau):
            missing.append(sbj)
            continue
        dwi_dir, dwi_nii = dwi_found
        bval = next(iter(sorted(dwi_dir.glob("*.bval"))), None)
        if bval is None:
            missing.append(sbj)
            continue
        work.append((sbj, t1, dwi_dir, dwi_nii, bval, amyloid, tau))

    if missing:
        print(f"  [WARN] skipping {len(missing)} subjects with missing inputs: "
              f"{', '.join(missing[:5])}"
              f"{'...' if len(missing) > 5 else ''}")

    print(f"  registering {len(work)} subjects (n_jobs={n_jobs})")
    Parallel(n_jobs=n_jobs, verbose=10)(
        delayed(_register_one)(
            sbj, t1, dwi_dir, dwi_nii, bval, amyloid, tau,
            mni_t1, mni_mask, dest,
        )
        for sbj, t1, dwi_dir, dwi_nii, bval, amyloid, tau in work
    )
