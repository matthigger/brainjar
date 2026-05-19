"""Cohort selection + covariates from OASIS-3 bundle CSVs.

A subject is in the cohort iff:
1. they have an AV45 PUP entry (amyloid),
2. they have a baseline AV1451 PUP entry (tau, OASIS3_AV1451 project — the
   longitudinal-follow-up OASIS3_AV1451L project is excluded),
3. they have an MR session with a DWI scan,
4. and the (av45_pup, av1451_pup, dwi_mr) triplet that minimizes the
   worst pairwise |days-from-entry| gap has a worst gap of at most
   ``COHORT_WINDOW_DAYS`` (default 60).

For each cohort subject we also pull from UDS form B4 (which carries
CDR, MMSE, free-text dx, and per-visit age in one row) and the
centiloid table to populate the xfeat fields. Sex comes from
``OASIS3_demographics.csv``.
"""

import re
from pathlib import Path

import pandas as pd

COHORT_WINDOW_DAYS = 60
CLINICAL_WINDOW_DAYS = 365  # NACC standard

_DAY_RE = re.compile(r"_d(\d+)$")
_MR_FROM_PUP_RE = re.compile(r"^(OAS\d+)_MR_d\d+$")


def _extract_day(series):
    return series.str.extract(_DAY_RE, expand=False).astype(int)


def _mr_sessions_with_dwi(mr_json_csv):
    """Return DataFrame of (Subject, mr_id, day) for MR sessions
    containing at least one DWI scan. Bundle's per-scan CSV is
    dedup'ed by session label.
    """
    mr = pd.read_csv(mr_json_csv, low_memory=False)
    dwi_rows = mr[mr["scan category"] == "dwi"][["subject_id", "label"]]
    sessions = dwi_rows.drop_duplicates().rename(
        columns={"subject_id": "Subject", "label": "mr_id"}
    )
    sessions["day"] = _extract_day(sessions["mr_id"])
    return sessions.reset_index(drop=True)


def _av45_pup(pup_csv):
    """PUP-processed AV45 amyloid scans (from OASIS3_PUP.csv, filtered
    to tracer == 'AV45')."""
    pup = pd.read_csv(pup_csv, low_memory=False)
    pup = pup[pup["tracer"] == "AV45"].copy()
    pup["Subject"] = pup["MRId"].str.extract(_MR_FROM_PUP_RE, expand=False)
    pup = pup.dropna(subset=["Subject"]).copy()
    pup["day"] = _extract_day(pup["PUP_PUPTIMECOURSEDATA ID"])
    return pup[
        ["Subject", "PUP_PUPTIMECOURSEDATA ID", "MRId", "day"]
    ].rename(columns={"PUP_PUPTIMECOURSEDATA ID": "pup_id", "MRId": "mr_id"}
             ).reset_index(drop=True)


def _av1451_pup_baseline(av1451_csv):
    """PUP-processed AV1451 tau scans, baseline-only — the file ships a
    handful of OASIS3_AV1451L rows mixed in; we filter on Project."""
    pup = pd.read_csv(av1451_csv, low_memory=False)
    pup = pup[pup["Project"] == "OASIS3_AV1451"].copy()
    pup["Subject"] = pup["MRId"].str.extract(_MR_FROM_PUP_RE, expand=False)
    pup = pup.dropna(subset=["Subject"]).copy()
    pup["day"] = _extract_day(pup["PUP_PUPTIMECOURSEDATA ID"])
    return pup[
        ["Subject", "PUP_PUPTIMECOURSEDATA ID", "MRId", "day"]
    ].rename(columns={"PUP_PUPTIMECOURSEDATA ID": "pup_id", "MRId": "mr_id"}
             ).reset_index(drop=True)


def _best_triplet(tau_day, av45_days, dwi_days):
    """Return ``(av45_idx, dwi_idx, worst_pairwise_gap)`` for the triplet
    that minimizes the worst pairwise gap among (tau, av45, dwi). Tau
    is fixed; we sweep all (av45, dwi) candidate pairs."""
    best = None
    for ai, a in enumerate(av45_days):
        for di, d in enumerate(dwi_days):
            worst = max(abs(a - tau_day), abs(d - tau_day), abs(a - d))
            if best is None or worst < best[2]:
                best = (ai, di, worst)
    return best


def _build_sessions(mr_dwi, av45, tau, window_days):
    """Per-subject session selection: AV1451-anchored on baseline tau
    visit; pick the (av45, dwi) pair minimizing worst pairwise gap;
    drop subjects whose best triplet exceeds ``window_days``."""
    subjects = set(mr_dwi["Subject"]) & set(av45["Subject"]) & set(tau["Subject"])
    rows = []
    for sbj in sorted(subjects):
        tau_sub = tau[tau["Subject"] == sbj]
        # baseline tau == earliest day for this subject in the AV1451 file
        tau_row = tau_sub.loc[tau_sub["day"].idxmin()]
        av45_sub = av45[av45["Subject"] == sbj].reset_index(drop=True)
        dwi_sub = mr_dwi[mr_dwi["Subject"] == sbj].reset_index(drop=True)
        ai, di, worst = _best_triplet(
            tau_row["day"], av45_sub["day"].values, dwi_sub["day"].values,
        )
        if worst > window_days:
            continue
        ar = av45_sub.iloc[ai]
        dr = dwi_sub.iloc[di]
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
    return pd.DataFrame(rows)


def _attach_clinical(cohort, udsb4_csv, window_days):
    """Match each cohort subject's tau_day to the UDSb4 visit closest in
    time within ±window_days. UDSb4 carries CDR + MMSE + free-text dx +
    age all on the same row, so this is one join across all four."""
    udsb4 = pd.read_csv(udsb4_csv, low_memory=False)
    out = cohort.copy()
    for col in ("cdr", "mmse", "dx", "age"):
        out[col] = pd.NA
    for i, row in out.iterrows():
        visits = udsb4[udsb4["OASISID"] == row["subject_id"]]
        if visits.empty:
            continue
        gap = (visits["days_to_visit"] - row["tau_day"]).abs()
        in_window = visits[gap <= window_days]
        if in_window.empty:
            continue
        best = in_window.loc[gap[in_window.index].idxmin()]
        out.at[i, "cdr"]  = best["CDRTOT"]
        out.at[i, "mmse"] = best["MMSE"]
        out.at[i, "dx"]   = best["dx1"]
        out.at[i, "age"]  = best["age at visit"]
    return out


def _attach_demographics(cohort, demographics_csv):
    """Pull sex from OASIS3_demographics.csv. NACC encodes GENDER as
    1 = Male, 2 = Female — remap to 'M'/'F' for human-readable xfeat.
    """
    demo = pd.read_csv(demographics_csv, low_memory=False)
    sex_map = {1: "M", 2: "F"}
    sex_by_sbj = demo.set_index("OASISID")["GENDER"].map(sex_map).to_dict()
    out = cohort.copy()
    out["sex"] = out["subject_id"].map(sex_by_sbj)
    return out


def _attach_centiloid(cohort, centiloid_csv):
    """Match each cohort row's av45_day to the centiloid row for that
    subject's AV45 session. Centiloid_fSUVR_TOT_CORTMEAN is the
    standard SUVR-derived centiloid."""
    cl = pd.read_csv(centiloid_csv, low_memory=False)
    av45 = cl[cl["tracer"] == "AV45"].copy()
    av45["day"] = _extract_day(av45["oasis_session_id"])
    out = cohort.copy()
    out["centiloid"] = pd.NA
    for i, row in out.iterrows():
        match = av45[
            (av45["subject_id"] == row["subject_id"])
            & (av45["day"] == row["av45_day"])
        ]
        if not match.empty:
            out.at[i, "centiloid"] = match.iloc[0]["Centiloid_fSUVR_TOT_CORTMEAN"]
    return out


def build(bundle_paths, dest,
          cohort_window_days=COHORT_WINDOW_DAYS,
          clinical_window_days=CLINICAL_WINDOW_DAYS):
    """Build cohort_sessions.csv + covariates.csv from extracted bundle CSVs.

    Args:
        bundle_paths: dict from :func:`brain_pipe.oasis3.pipeline.bundle.extract`
            mapping logical names ('mr_json', 'pup', 'av1451_pup',
            'demographics', 'udsb4', 'centiloid') to Path.
        dest: directory where cohort_sessions.csv + covariates.csv land.
        cohort_window_days: drop subjects whose worst pairwise gap
            between (AV45, AV1451, DWI) sessions exceeds this.
        clinical_window_days: drop the UDS visit if no row falls within
            this of the subject's tau session (cdr/mmse/dx/age NaN).

    Returns:
        dict ``{'cohort_csv': Path, 'covariates_csv': Path}``.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    print("  reading bundle CSVs")
    mr_dwi = _mr_sessions_with_dwi(bundle_paths["mr_json"])
    av45 = _av45_pup(bundle_paths["pup"])
    tau = _av1451_pup_baseline(bundle_paths["av1451_pup"])
    print(f"    MR sessions with DWI: {len(mr_dwi)}, AV45 PUP: {len(av45)}, "
          f"AV1451 PUP (baseline): {len(tau)}")

    print(f"  selecting cohort (worst pairwise gap <= {cohort_window_days} days)")
    cohort = _build_sessions(mr_dwi, av45, tau, cohort_window_days)
    print(f"    cohort: {len(cohort)} subjects")

    cohort_csv = dest / "cohort_sessions.csv"
    cohort.to_csv(cohort_csv, index=False)
    print(f"    wrote {cohort_csv}")

    print("  building covariates")
    cov = cohort.copy()
    cov = _attach_demographics(cov, bundle_paths["demographics"])
    cov = _attach_clinical(cov, bundle_paths["udsb4"], clinical_window_days)
    cov = _attach_centiloid(cov, bundle_paths["centiloid"])

    cov_out = cov[["subject_id", "age", "sex", "cdr", "mmse", "dx", "centiloid"]]
    cov_csv = dest / "covariates.csv"
    cov_out.to_csv(cov_csv, index=False)
    print(f"    wrote {cov_csv}")

    return {"cohort_csv": cohort_csv, "covariates_csv": cov_csv}
