"""Orchestrate per-cohort-subject XNAT downloads.

Reads ``cohort_sessions.csv`` and, for each subject, fetches the
``T1w + DWI`` scans from the chosen MR session (``dwi_mr_id``) via the
:class:`NitrcXnat` client.

Idempotent: per-experiment directories that already exist with content
are skipped, so re-running after a partial fetch resumes without
re-downloading.
"""

from pathlib import Path

import pandas as pd
from tqdm.auto import tqdm

SCAN_TYPES = "T1w,dwi"


def fetch_cohort(cohort_csv, raw_dir, xnat):
    """Download imaging for every cohort subject via the authenticated
    XNAT client.

    Args:
        cohort_csv: ``cohort_sessions.csv`` written by the prepare stage.
        raw_dir: output dir; ``raw_dir/scans/<MR_ID>/`` is populated.
        xnat: an open :class:`NitrcXnat` instance.
    """
    cohort_csv = Path(cohort_csv)
    raw_dir = Path(raw_dir)
    scans_dir = raw_dir / "scans"

    df = pd.read_csv(cohort_csv)
    print(f"  cohort: {len(df)} subjects")

    mr_ids = sorted(set(df["dwi_mr_id"]))
    print(f"  [scans] {len(mr_ids)} MR sessions (T1w+DWI)")
    for mr_id in tqdm(mr_ids, desc="MR scans", unit="sess"):
        xnat.download_mr_scans(mr_id, SCAN_TYPES, scans_dir)
