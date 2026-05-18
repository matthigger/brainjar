"""Stage 4: DIPY tensor fit (FA + MD) per cohort subject.

Thin per-dataset adapter over :func:`brain_pipe._dwi_pipeline.dti.process_dti`
that handles OASIS-3's downloaded layout. The shared module expects
``bvals`` / ``bvecs`` files named exactly that next to the DWI nifti;
OASIS-3's ``download_oasis_scans.sh`` writes them as ``*.bval`` /
``*.bvec``, so we symlink them to the expected names before
dispatching. Outputs ``fa.nii.gz`` and ``md.nii.gz`` next to each
subject's DWI nifti.
"""

from pathlib import Path

import pandas as pd
from joblib import Parallel, delayed


def _find_subject_dwi(scans_dir, mr_id):
    """Locate the DWI nifti + bval + bvec under
    ``<scans_dir>/<mr_id>/dwi*/``. Returns ``(dwi_nii, bval, bvec)`` or
    ``None`` if the subject's DWI isn't on disk yet (download failed
    silently? skip with a warning).
    """
    session_dir = scans_dir / mr_id
    if not session_dir.exists():
        return None
    # download_oasis_scans.sh names dirs like "dwi1", "dwi2", etc.
    dwi_dirs = sorted(session_dir.glob("dwi*"))
    if not dwi_dirs:
        return None
    # Multiple dwi dirs in one session = opposite-phase-encode pairs.
    # Pick the first; refining (e.g., merge with topup) would be a
    # dataset-specific decision and is out of scope for this baseline.
    d = dwi_dirs[0]
    niftis = sorted(d.glob("*.nii.gz"))
    bvals = sorted(d.glob("*.bval"))
    bvecs = sorted(d.glob("*.bvec"))
    if not (niftis and bvals and bvecs):
        return None
    return niftis[0], bvals[0], bvecs[0]


def _prep_subject(dwi_nii, bval, bvec):
    """Symlink ``*.bval``/``*.bvec`` to ``bvals``/``bvecs`` next to the
    DWI nifti (the names the shared DTI fit expects). Idempotent.
    """
    folder = dwi_nii.parent
    for src, name in [(bval, "bvals"), (bvec, "bvecs")]:
        link = folder / name
        if link.exists():
            continue
        link.symlink_to(src.name)  # relative symlink within the folder


def process_cohort(cohort_csv, raw_dir, n_jobs=1):
    """Run the DIPY tensor fit for every cohort subject with on-disk DWI.

    Args:
        cohort_csv: ``cohort_sessions.csv`` path.
        raw_dir: parent of ``scans/`` (where ``fetch_scripts`` wrote
            downloads).
        n_jobs: parallel workers; each holds the full DWI volume
            (~1-3 GB for OASIS-3) in memory, so keep this conservative.

    Skips subjects whose DWI download is missing; logs them so the user
    can re-run ``fetch_scripts`` if needed.
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
