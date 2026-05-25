"""Cohort selection + covariates from OASIS-3 bundle CSVs.

A subject is in the cohort iff:

1. they have at least one MR session with a tensor-fittable DWI run
   (i.e. some run whose ``SeriesDescription`` is not in the
   ``_DEGENERATE_DWI_SERIES`` set; T1 is implied — every OASIS-3 MR
   session ships a T1w),
2. they have at least one complete UDS Form B4 (CDR) visit (non-null
   ``CDRSUM`` and the six component scores), and
3. some (DWI session, CDR visit) pair for the subject falls within a
   ``COHORT_WINDOW_DAYS``-day gap.

For each cohort subject we select the (DWI MR session, CDR visit) pair
that minimizes ``|day(DWI) - day(CDR)|``, with a deterministic
tiebreak by earliest DWI day then earliest CDR day. The chosen CDR
visit drives the CDR target columns (CDRSUM + six components). The
chosen MR session's age is computed as ``AgeatEntry + dwi_day/365.25``.
Demographics (sex, education, APOE, family history) come from
``OASIS3_demographics.csv``.

Cohort D (the current target population, focused on CDR prediction):
PET is intentionally excluded — OASIS-3's tau PET (AV1451) was
preferentially given to cognitively-healthy participants, so the prior
A/T/N cohort had no CDR variance.
"""

import re
from pathlib import Path

import pandas as pd

COHORT_WINDOW_DAYS = 365

# DWI ``SeriesDescription`` values known to be 1-direction (1 b0 + 1
# b1000) trace-weighted localizers — mathematically singular for any
# tensor fit. Identified empirically from the OASIS-3 bundle (the
# OASIS3_MR_json.csv ships per-run SeriesDescription but no direct
# n_dirs / n_volumes column). The Biograph_mMR PET/MR sites used this
# 2-volume ``Axial_DWI`` as their entire diffusion acquisition for a
# subset of subjects.
_DEGENERATE_DWI_SERIES = frozenset({"Axial_DWI"})

# CDR Sum-of-Boxes is the regression target; the six component scores
# are also returned so downstream models can fit either CDRSUM or its
# components.
_CDR_COMPONENTS = ("memory", "orient", "judgment", "commun", "homehobb", "perscare")

_DAY_RE = re.compile(r"_d(\d+)$")


def _extract_day(series):
    return series.str.extract(_DAY_RE, expand=False).astype(int)


def _mr_sessions_with_dwi(mr_json_csv):
    """Return DataFrame of (Subject, mr_id, day, scanner,
    dwi_series_descriptions) for MR sessions containing at least one
    DWI scan whose acquisition can support a tensor fit.

    Filtering rule: drop sessions whose every DWI run has a
    ``SeriesDescription`` in :data:`_DEGENERATE_DWI_SERIES` (e.g.,
    ``Axial_DWI`` = 1 b0 + 1 b1000, mathematically singular).
    """
    mr = pd.read_csv(mr_json_csv, low_memory=False)
    dwi_rows = mr[mr["scan category"] == "dwi"][
        ["subject_id", "label", "ManufacturersModelName", "SeriesDescription"]
    ].copy()

    grouped = dwi_rows.groupby(["subject_id", "label"], dropna=False).agg(
        scanner=("ManufacturersModelName",
                 lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        dwi_series_descriptions=("SeriesDescription",
                                 lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
    ).reset_index()

    def _has_non_degenerate(desc_str):
        descs = set(desc_str.split("|")) if desc_str else set()
        if not descs:
            return True  # unknown != degenerate (runtime check in dti.py)
        return any(d not in _DEGENERATE_DWI_SERIES for d in descs)

    keep = grouped["dwi_series_descriptions"].apply(_has_non_degenerate)
    dropped = int((~keep).sum())
    if dropped:
        print(f"    dropped {dropped} DWI sessions whose only run is "
              f"a degenerate {sorted(_DEGENERATE_DWI_SERIES)} series")
    sessions = grouped[keep].rename(
        columns={"subject_id": "Subject", "label": "mr_id"}
    ).copy()
    sessions["day"] = _extract_day(sessions["mr_id"])
    return sessions[
        ["Subject", "mr_id", "day", "scanner", "dwi_series_descriptions"]
    ].sort_values(["Subject", "day", "mr_id"]).reset_index(drop=True)


def _complete_cdr_visits(udsb4_csv):
    """UDS Form B4 visits with non-null CDRSUM + the six component
    scores. Returned columns: ``OASISID``, ``days_to_visit``,
    ``CDRSUM``, and the six components.
    """
    uds = pd.read_csv(udsb4_csv, low_memory=False)
    need = ["CDRSUM"] + list(_CDR_COMPONENTS)
    uds = uds.dropna(subset=need).copy()
    return uds[["OASISID", "days_to_visit"] + need].sort_values(
        ["OASISID", "days_to_visit"]
    ).reset_index(drop=True)


def _best_pair(dwi_rows, cdr_rows):
    """Return ``(dwi_idx, cdr_idx, gap)`` for the pair minimizing
    ``|dwi_day - cdr_day|``. Deterministic tiebreak: smallest DWI day,
    then smallest CDR day. ``dwi_rows`` / ``cdr_rows`` are sorted by
    day already so iteration order is reproducible.
    """
    best = None
    for di, dday in enumerate(dwi_rows["day"].values):
        for ci, cday in enumerate(cdr_rows["days_to_visit"].values):
            gap = abs(int(dday) - int(cday))
            if best is None:
                best = (gap, di, ci, int(dday), int(cday))
                continue
            cur = (gap, int(dday), int(cday))
            ref = (best[0], best[3], best[4])
            if cur < ref:
                best = (gap, di, ci, int(dday), int(cday))
    return best[1], best[2], best[0]


def _build_sessions(mr_dwi, cdr_visits, window_days):
    """Per-subject session selection: pick the (DWI, CDR) pair
    minimizing |gap|; drop subjects whose best pair exceeds
    ``window_days``.
    """
    subjects = sorted(set(mr_dwi["Subject"]) & set(cdr_visits["OASISID"]))
    rows = []
    for sbj in subjects:
        dwi_sub = mr_dwi[mr_dwi["Subject"] == sbj].reset_index(drop=True)
        cdr_sub = cdr_visits[cdr_visits["OASISID"] == sbj].reset_index(drop=True)
        di, ci, gap = _best_pair(dwi_sub, cdr_sub)
        if gap > window_days:
            continue
        dr = dwi_sub.iloc[di]
        cr = cdr_sub.iloc[ci]
        rows.append({
            "subject_id":              sbj,
            "dwi_mr_id":               dr["mr_id"],
            "dwi_day":                 int(dr["day"]),
            "cdr_visit_day":           int(cr["days_to_visit"]),
            "dwi_scanner":             dr["scanner"],
            "dwi_series_descriptions": dr["dwi_series_descriptions"],
            "worst_gap_days":          int(gap),
            # Carried for covariates.csv but not written to cohort_sessions.csv.
            "_cdr_sum":                float(cr["CDRSUM"]),
            **{f"_cdr_{c}": float(cr[c]) for c in _CDR_COMPONENTS},
        })
    return pd.DataFrame(rows)


def _build_covariates(cohort, demographics_csv):
    """Build covariates.csv columns from the cohort + demographics.

    Sex: OASIS encodes GENDER as 1 = Male, 2 = Female (matches NACC /
    OASIS data dictionary v2.3). Age at the chosen MR session is
    ``AgeatEntry + dwi_day / 365.25`` (AgeatEntry is years at subject
    enrollment; days are wall-clock days from enrollment).
    """
    demo = pd.read_csv(demographics_csv, low_memory=False)
    sex_map = {1: "M", 2: "F"}
    demo_idx = demo.set_index("OASISID")
    rows = []
    for _, row in cohort.iterrows():
        sbj = row["subject_id"]
        if sbj in demo_idx.index:
            d = demo_idx.loc[sbj]
            age = float(d["AgeatEntry"]) + float(row["dwi_day"]) / 365.25
            sex = sex_map.get(int(d["GENDER"])) if pd.notna(d["GENDER"]) else pd.NA
            educ = d["EDUC"]
            apoe = d["APOE"]
            daddem = d["daddem"]
            momdem = d["momdem"]
        else:
            age = pd.NA
            sex = pd.NA
            educ = pd.NA
            apoe = pd.NA
            daddem = pd.NA
            momdem = pd.NA
        rows.append({
            "subject_id": sbj,
            "age":        age,
            "sex":        sex,
            "educ":       educ,
            "apoe":       apoe,
            "daddem":     daddem,
            "momdem":     momdem,
            "cdr_sum":    row["_cdr_sum"],
            "memory":     row["_cdr_memory"],
            "orient":     row["_cdr_orient"],
            "judgment":   row["_cdr_judgment"],
            "commun":     row["_cdr_commun"],
            "homehobb":   row["_cdr_homehobb"],
            "perscare":   row["_cdr_perscare"],
        })
    return pd.DataFrame(rows)


def build(bundle_paths, dest, cohort_window_days=COHORT_WINDOW_DAYS):
    """Build cohort_sessions.csv + covariates.csv from extracted bundle CSVs.

    Args:
        bundle_paths: dict from :func:`brainjar.oasis3.pipeline.bundle.extract`
            mapping logical names ('mr_json', 'udsb4', 'demographics',
            ...) to ``Path``.
        dest: directory where cohort_sessions.csv + covariates.csv land.
        cohort_window_days: drop subjects whose best (DWI, CDR) pair
            has |gap| above this. Default 365 days.

    Returns:
        dict ``{'cohort_csv': Path, 'covariates_csv': Path}``.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    print("  reading bundle CSVs")
    mr_dwi = _mr_sessions_with_dwi(bundle_paths["mr_json"])
    cdr = _complete_cdr_visits(bundle_paths["udsb4"])
    print(f"    MR sessions with non-degenerate DWI: {len(mr_dwi)} "
          f"({mr_dwi['Subject'].nunique()} subjects); "
          f"complete UDSb4 visits: {len(cdr)} "
          f"({cdr['OASISID'].nunique()} subjects)")

    print(f"  selecting cohort (|DWI - CDR| <= {cohort_window_days} days)")
    cohort = _build_sessions(mr_dwi, cdr, cohort_window_days)
    print(f"    cohort: {len(cohort)} subjects")

    cohort_out = cohort[[
        "subject_id", "dwi_mr_id", "dwi_day", "cdr_visit_day",
        "dwi_scanner", "dwi_series_descriptions", "worst_gap_days",
    ]]
    cohort_csv = dest / "cohort_sessions.csv"
    cohort_out.to_csv(cohort_csv, index=False)
    print(f"    wrote {cohort_csv}")

    print("  building covariates")
    cov = _build_covariates(cohort, bundle_paths["demographics"])
    cov_csv = dest / "covariates.csv"
    cov.to_csv(cov_csv, index=False)
    print(f"    wrote {cov_csv}")

    return {"cohort_csv": cohort_csv, "covariates_csv": cov_csv}
