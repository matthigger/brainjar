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

import warnings
from pathlib import Path

import pandas as pd
from joblib import Parallel, delayed

# DIPY's diffusion-tensor fit requires at least 6 independent gradient
# directions (the tensor has 6 unique entries). With <= 5 volumes total,
# the system is mathematically singular and DIPY emits noise without an
# error — we hard-fail instead. The "workable but noisy" floor (30) is
# below the standard 30-direction recommendation for tensor fits but
# above the OASIS-3 Vida shard size (13) we currently accept.
_HARD_FLOOR_N_VOLS = 6
_NOISY_FLOOR_N_VOLS = 30


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


def _count_dwi_volumes(bval_path):
    """Return the number of volumes in a BIDS ``*.bval`` file.

    bval files are a single line of whitespace-separated floats, one
    per volume. We just count tokens — sufficient for the cardinality
    gate (we don't need to parse the values themselves).
    """
    text = Path(bval_path).read_text()
    return len(text.split())


def _check_dwi_acquisition(subject_id, dwi_mr_id, bval_path):
    """Cardinality gate for the DWI acquisition.

    Hard-fails (ValueError) if the bval file has < :data:`_HARD_FLOOR_N_VOLS`
    volumes — DIPY's tensor fit is singular below that floor and emits
    noise without an error. Warns (UserWarning) if 6 <= n < 30 — workable
    but below the standard tensor-fit recommendation; FA/MD will be
    noisy. This is the post-fetch backstop for the
    :data:`brain_pipe.oasis3.pipeline.cohort._DEGENERATE_DWI_SERIES`
    pre-fetch filter: if a degenerate session sneaks past the bundle
    metadata (e.g. unfamiliar SeriesDescription), this still fails loud.
    """
    n_vols = _count_dwi_volumes(bval_path)
    if n_vols < _HARD_FLOOR_N_VOLS:
        raise ValueError(
            f"DTI tensor fit requires at least {_HARD_FLOOR_N_VOLS} "
            f"DWI volumes (6 independent gradient directions); got "
            f"{n_vols} for subject {subject_id} session {dwi_mr_id} at "
            f"{bval_path}. This session likely captured only a "
            f"trace-weighted localizer; exclude it from the cohort "
            f"(see pipeline/cohort.py::_DEGENERATE_DWI_SERIES)."
        )
    if n_vols < _NOISY_FLOOR_N_VOLS:
        warnings.warn(
            f"subject {subject_id} session {dwi_mr_id} has only "
            f"{n_vols} DWI volumes (< {_NOISY_FLOOR_N_VOLS}); tensor "
            f"fit will be workable but noisy. Consider treating FA/MD "
            f"for this subject with caution.",
            stacklevel=2,
        )
    return n_vols


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
        # Fail loud if a degenerate session slipped past cohort filter.
        _check_dwi_acquisition(row["subject_id"], row["dwi_mr_id"], bval)
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
