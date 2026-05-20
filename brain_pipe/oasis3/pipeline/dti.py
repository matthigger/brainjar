"""Stage 4: DIPY tensor fit (FA + MD) per cohort subject.

Thin per-dataset adapter over :func:`brain_pipe._dwi_pipeline.dti.process_dti`
that handles OASIS-3's XNAT-delivered layout::

    raw/scans/<MR_ID>/<MR_ID>/scans/dwi*-dwi/
        resources/NIFTI/files/sub-*_dwi.nii.gz
        resources/BIDS/files/sub-*_dwi.{bval,bvec,json}

The shared DTI fit expects ``bvals`` / ``bvecs`` files (no extension)
next to the DWI nifti; we symlink the BIDS-style ``*.bval`` / ``*.bvec``
into ``NIFTI/files/`` to satisfy that contract. Outputs ``fa.nii.gz``
and ``md.nii.gz`` land alongside the DWI in ``NIFTI/files/``.
"""

from pathlib import Path

import pandas as pd
from joblib import Parallel, delayed


def _find_subject_dwi(scans_dir, mr_id):
    """Locate the DWI nifti + sibling bval/bvec for one subject.

    Walks the XNAT-delivered tree ``<scans_dir>/<mr_id>/<mr_id>/scans/
    dwi*-dwi/resources/{NIFTI,BIDS}/files/``. Returns
    ``(dwi_nii, bval, bvec)`` or ``None`` if any piece is missing
    (interrupted download, etc.).
    """
    # XNAT zips wrap the experiment_id directory once around themselves,
    # so the on-disk session root is doubled.
    session_root = scans_dir / mr_id / mr_id / "scans"
    if not session_root.exists():
        return None
    # OASIS-3 scan-type folders are e.g. "dwi1-dwi", "dwi2-dwi" — one
    # per acquired run (typically opposite-phase-encode pairs). Pick the
    # first run; merging via topup is out of scope for this baseline.
    dwi_dirs = sorted(session_root.glob("dwi*-dwi"))
    if not dwi_dirs:
        return None
    for d in dwi_dirs:
        nifti_files = d / "resources" / "NIFTI" / "files"
        bids_files = d / "resources" / "BIDS" / "files"
        dwi = next(iter(nifti_files.glob("sub-*_dwi.nii.gz")), None)
        bval = next(iter(bids_files.glob("*.bval")), None)
        bvec = next(iter(bids_files.glob("*.bvec")), None)
        if dwi and bval and bvec:
            return dwi, bval, bvec
    return None


def _prep_subject(dwi_nii, bval, bvec):
    """Symlink BIDS-style ``*.bval``/``*.bvec`` into the NIFTI/files/
    dir as ``bvals``/``bvecs`` (the names the shared DTI fit expects).
    Idempotent.
    """
    folder = dwi_nii.parent
    for src, name in [(bval, "bvals"), (bvec, "bvecs")]:
        link = folder / name
        if link.exists():
            continue
        # Cross-directory link from NIFTI/files/ -> BIDS/files/.
        link.symlink_to(Path("..") / ".." / "BIDS" / "files" / src.name)


def process_cohort(cohort_csv, raw_dir, n_jobs=1):
    """Run the DIPY tensor fit for every cohort subject with on-disk DWI.

    Args:
        cohort_csv: ``cohort_sessions.csv`` path.
        raw_dir: parent of ``scans/`` (where :func:`fetch` wrote
            downloads).
        n_jobs: parallel workers; each holds the full DWI volume
            (~1-3 GB for OASIS-3) in memory, so keep this conservative.

    Skips subjects whose DWI download is missing; logs them so the user
    can re-run :func:`fetch` if needed.
    """
    # Lazy import — the shared module is in the pipeline extra.
    from dipy.reconst.dti import fractional_anisotropy, mean_diffusivity

    from brain_pipe._dwi_pipeline.dti import process_dti

    cohort_csv = Path(cohort_csv)
    raw_dir = Path(raw_dir)
    scans_dir = raw_dir / "scans"
    df = pd.read_csv(cohort_csv)

    dti_fnc_dict = {"fa": fractional_anisotropy, "md": mean_diffusivity}

    work = []
    missing = []
    for _, row in df.iterrows():
        found = _find_subject_dwi(scans_dir, row["dwi_mr_id"])
        if found is None:
            missing.append(row["subject_id"])
            continue
        dwi_nii, bval, bvec = found
        _prep_subject(dwi_nii, bval, bvec)
        work.append(dwi_nii)

    if missing:
        print(f"  [WARN] DWI not on disk for {len(missing)} subjects: "
              f"{', '.join(missing[:5])}"
              f"{'...' if len(missing) > 5 else ''}")

    print(f"  fitting DTI for {len(work)} subjects (n_jobs={n_jobs})")
    Parallel(n_jobs=n_jobs, verbose=10)(
        delayed(process_dti)(f, dti_fnc_dict) for f in work
    )
