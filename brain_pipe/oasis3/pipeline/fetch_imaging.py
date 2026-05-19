"""Orchestrate per-cohort-subject XNAT downloads.

Reads ``cohort_sessions.csv`` and, for each subject, fetches via the
:class:`NitrcXnat` client:

- ``T1w + DWI`` from the chosen MR session (``dwi_mr_id``)
- ``AV45 SUVR`` files from the chosen AV45 PUP (``av45_pup_id``)
- ``AV1451 SUVR`` files from the chosen baseline tau PUP (``tau_pup_id``)

Idempotent: per-experiment / per-PUP directories that already exist
with content are skipped, so re-running after a partial fetch resumes
without re-downloading.
"""

from pathlib import Path

import pandas as pd
from tqdm.auto import tqdm

SCAN_TYPES = "T1w,dwi"
# Match exactly the volumetric SUVR triplet — `*_msum_SUVR.4dfp.{img,hdr,ifh}`.
# Excludes the `_g8` Gaussian-smoothed variant (we apply our own SyN
# warp with built-in smoothing) and the hundreds of per-ROI scalar
# tables PUP emits as `*.suvr` / `*_SUVR_*.txt` files.
PUP_FILE_PATTERN = r"_SUVR\.4dfp\."


def fetch_cohort(cohort_csv, raw_dir, xnat):
    """Download imaging for every cohort subject via the authenticated
    XNAT client.

    Args:
        cohort_csv: ``cohort_sessions.csv`` written by the prepare stage.
        raw_dir: output dir; ``raw_dir/scans/<MR_ID>/`` and
            ``raw_dir/pup/<PUP_ID>/`` get populated.
        xnat: an open :class:`NitrcXnat` instance.
    """
    cohort_csv = Path(cohort_csv)
    raw_dir = Path(raw_dir)
    scans_dir = raw_dir / "scans"
    pup_dir = raw_dir / "pup"

    df = pd.read_csv(cohort_csv)
    print(f"  cohort: {len(df)} subjects")

    # MR sessions: union of av45_mr_id and dwi_mr_id (almost always
    # overlapping — the cohort filter usually picks an MR session that
    # served both the AV45 PUP and DWI).
    mr_ids = sorted(set(df["av45_mr_id"]).union(df["dwi_mr_id"]))
    print(f"  [scans] {len(mr_ids)} MR sessions (T1w+DWI)")
    for mr_id in tqdm(mr_ids, desc="MR scans", unit="sess"):
        xnat.download_mr_scans(mr_id, SCAN_TYPES, scans_dir)

    av45_ids = sorted(set(df["av45_pup_id"]))
    print(f"  [pup-av45] {len(av45_ids)} AV45 PUP SUVR files")
    for pup_id in tqdm(av45_ids, desc="AV45 SUVR", unit="sess"):
        xnat.download_pup_filtered(pup_id, PUP_FILE_PATTERN, pup_dir)

    tau_ids = sorted(set(df["tau_pup_id"]))
    print(f"  [pup-tau] {len(tau_ids)} AV1451 PUP SUVR files")
    for pup_id in tqdm(tau_ids, desc="AV1451 SUVR", unit="sess"):
        xnat.download_pup_filtered(pup_id, PUP_FILE_PATTERN, pup_dir)
