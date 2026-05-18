"""Stage 1: build the OASIS-3 A/T/N cohort from metadata CSVs.

Reads the bundled `0AS_data_files` CSVs that the user downloaded from
NITRC-IR into ``raw_dir``, applies the AV45 ∩ AV1451-baseline ∩ DWI
inclusion filter, runs the tau-anchored minimum-worst-pairwise-gap
session selection at a configurable window, and writes
``cohort_sessions.csv`` to ``dest``. That CSV drives every downstream
stage.

Expected files in ``raw_dir``:

    mr.csv                          # OASIS3 MR sessions
    pup.csv                         # OASIS3 PUP-processed PET (PIB+AV45)
    sbj.csv                         # OASIS3 subject demographics
    1451/pet.csv                    # OASIS3_AV1451 baseline tau PET sessions
    1451/pup.csv                    # OASIS3_AV1451 baseline tau PUP

The trailing ``OASIS3_AV1451L`` longitudinal-followup project is
intentionally ignored (see package README).
"""

import re
from pathlib import Path

import pandas as pd

DEFAULT_WINDOW_DAYS = 60

_DAY_RE = re.compile(r"_d(\d+)$")
_DWI_RE = re.compile(r"dwi\(\d+\)", re.IGNORECASE)
_MR_FROM_PUP_RE = re.compile(r"^(OAS\d+)_MR_d\d+$")


def _extract_day(series):
    """Return the trailing ``_dNNNN`` integer of each ID string."""
    return series.str.extract(_DAY_RE, expand=False).astype(int)


def _load_mr_dwi(raw_dir):
    """MR sessions that contain at least one DWI scan."""
    mr = pd.read_csv(raw_dir / "mr.csv")
    mr = mr[mr["Subject"] != "0AS_data_files"].copy()
    mr["has_dwi"] = mr["Scans"].fillna("").str.contains(_DWI_RE)
    mr = mr[mr["has_dwi"]].copy()
    mr["day"] = _extract_day(mr["MR ID"])
    return mr[["Subject", "MR ID", "day"]].rename(columns={"MR ID": "mr_id"})


def _load_av45_pup(raw_dir):
    """PUP-processed AV45 amyloid scans (OASIS3 project)."""
    pup = pd.read_csv(raw_dir / "pup.csv")
    pup["Subject"] = pup["MRId"].str.extract(_MR_FROM_PUP_RE, expand=False)
    av45 = pup[pup["tracer"] == "AV45"].copy()
    av45["day"] = _extract_day(av45["PUP_PUPTIMECOURSEDATA ID"])
    return av45[["Subject", "PUP_PUPTIMECOURSEDATA ID", "MRId", "day"]].rename(
        columns={"PUP_PUPTIMECOURSEDATA ID": "pup_id", "MRId": "mr_id"}
    )


def _load_av1451_pup(raw_dir):
    """PUP-processed AV1451 tau scans (OASIS3_AV1451 baseline project only)."""
    pup = pd.read_csv(raw_dir / "1451" / "pup.csv")
    pup["Subject"] = pup["MRId"].str.extract(_MR_FROM_PUP_RE, expand=False)
    tau = pup[pup["Subject"].notna()].copy()
    tau["day"] = _extract_day(tau["PUP_PUPTIMECOURSEDATA ID"])
    return tau[["Subject", "PUP_PUPTIMECOURSEDATA ID", "MRId", "day"]].rename(
        columns={"PUP_PUPTIMECOURSEDATA ID": "pup_id", "MRId": "mr_id"}
    )


def _best_triplet(tau_day, av45_days, dwi_days):
    """For a single subject's tau day and lists of AV45 / DWI candidate
    days, return ``(av45_idx, dwi_idx, worst_pairwise_gap)`` for the
    triplet that minimizes the worst pairwise gap among the three
    sessions. Tau is fixed (one baseline scan).
    """
    best = None
    for ai, a in enumerate(av45_days):
        for di, d in enumerate(dwi_days):
            worst = max(abs(a - tau_day), abs(d - tau_day), abs(a - d))
            if best is None or worst < best[2]:
                best = (ai, di, worst)
    return best


def build_cohort(raw_dir, dest, window_days=DEFAULT_WINDOW_DAYS):
    """Build the cohort session-list CSV.

    Args:
        raw_dir: Path with the OASIS-3 / AV1451 metadata CSVs.
        dest: Path where ``cohort_sessions.csv`` is written.
        window_days: subjects whose best-triplet worst pairwise gap
            exceeds this are excluded. Default 60 (see README).

    Returns:
        ``Path`` to the written ``cohort_sessions.csv``.
    """
    raw_dir = Path(raw_dir)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    mr_dwi = _load_mr_dwi(raw_dir)
    av45 = _load_av45_pup(raw_dir)
    tau = _load_av1451_pup(raw_dir)

    cohort = (
        set(mr_dwi["Subject"]) & set(av45["Subject"]) & set(tau["Subject"])
    )

    rows = []
    for sbj in sorted(cohort):
        # baseline tau: a subject has 1 row in OASIS3_AV1451; if >1
        # ever appears, pick the earliest day defensively.
        tau_sub = tau[tau["Subject"] == sbj]
        tau_row = tau_sub.loc[tau_sub["day"].idxmin()]
        av45_sub = av45[av45["Subject"] == sbj].reset_index(drop=True)
        dwi_sub = mr_dwi[mr_dwi["Subject"] == sbj].reset_index(drop=True)
        ai, di, worst = _best_triplet(
            tau_row["day"], av45_sub["day"].values, dwi_sub["day"].values
        )
        if worst > window_days:
            continue
        ar, dr = av45_sub.iloc[ai], dwi_sub.iloc[di]
        rows.append({
            "subject_id":     sbj,
            "tau_pup_id":     tau_row["pup_id"],
            "tau_mr_id":      tau_row["mr_id"],
            "tau_day":        int(tau_row["day"]),
            "av45_pup_id":    ar["pup_id"],
            "av45_mr_id":     ar["mr_id"],
            "av45_day":       int(ar["day"]),
            "dwi_mr_id":      dr["mr_id"],
            "dwi_day":        int(dr["day"]),
            "worst_gap_days": int(worst),
        })

    df = pd.DataFrame(rows)
    out = dest / "cohort_sessions.csv"
    df.to_csv(out, index=False)
    print(f"  cohort: {len(df)} subjects @ ≤{window_days}d worst pairwise gap")
    print(f"  written: {out}")
    return out
