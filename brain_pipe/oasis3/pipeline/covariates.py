"""Stage 6: assemble covariates.csv from the OASIS-3 metadata CSVs.

For each cohort subject:

- ``age``       MR session's recorded Age at the tau-anchored visit
- ``sex``       sbj.csv's M/F
- ``cdr``       OASIS3_UDSb4_cdr.csv's ``CDRTOT`` at the visit closest to
                the subject's tau session (within ±365 d)
- ``mmse``      same source, ``MMSE`` column
- ``dx``        same source, ``dx1`` column (free-text primary diagnosis)
- ``centiloid`` OASIS3_amyloid_centiloid.csv's
                ``Centiloid_fSUVR_TOT_CORTMEAN`` for the subject's AV45
                session (matched by subject + day)

UDSb4 (the CDR form) doubles as our source for MMSE and dx because it
carries all three at the same visit — keeping them coupled to a single
visit avoids the awkward case where CDR, MMSE, and dx come from
different clinic visits months apart. UDSc1 (psychometrics) has richer
neuropsych subscores if we ever want to expand xfeat beyond the three
scalars.

The clinical and centiloid CSVs come from the OASIS3_data_files bundle
(see ``README.md`` "Pass 2 — clinical / cognitive bundle download").
They live anywhere under ``raw_dir`` post-extraction; we glob for them
by basename. If a file isn't present, the corresponding columns are
NaN — the pipeline still completes; user can re-run after fetching.
"""

from pathlib import Path

import pandas as pd

_REQUIRED_MODALITIES = ("amyloid_suvr", "tau_suvr", "fa", "md")
_CLINICAL_WINDOW_DAYS = 365


def _subjects_with_all_outputs(dest):
    """Subjects with ``<sbj>_<modality>.nii.gz`` for every required
    modality in ``dest``.
    """
    by_sbj = {}
    for f in dest.glob("*.nii.gz"):
        name = f.name[: -len(".nii.gz")]
        parts = name.split("_", 1)
        if len(parts) != 2 or not parts[0].startswith("OAS"):
            continue
        sbj, mod = parts
        by_sbj.setdefault(sbj, set()).add(mod)
    return {s for s, mods in by_sbj.items()
            if all(m in mods for m in _REQUIRED_MODALITIES)}


def _find_csv(raw_dir, basename):
    """Locate ``basename`` anywhere under ``raw_dir`` (e.g. inside an
    extracted OASIS3_data_files/ bundle). Returns ``Path`` or ``None``.
    """
    hits = list(Path(raw_dir).rglob(basename))
    if not hits:
        return None
    if len(hits) > 1:
        print(f"  [WARN] multiple {basename} found, using first: {hits[0]}")
    return hits[0]


def _join_clinical(cohort, raw_dir, window_days=_CLINICAL_WINDOW_DAYS):
    """Populate cdr/mmse/dx from OASIS3_UDSb4_cdr.csv. For each cohort
    row, find the UDS visit closest to that subject's ``tau_day``
    within ±``window_days``. Missing files or no-in-window matches
    leave those columns as ``pd.NA``.
    """
    path = _find_csv(raw_dir, "OASIS3_UDSb4_cdr.csv")
    if path is None:
        print("  [INFO] OASIS3_UDSb4_cdr.csv not found; cdr/mmse/dx -> NaN")
        return cohort
    print(f"  reading clinical from {path}")
    udsb4 = pd.read_csv(path)

    out = cohort.copy()
    # Pull age from UDSb4's "age at visit" — mr.csv's Age column has
    # many NaNs across sessions, while UDSb4 records age at every visit.
    for col in ("cdr", "mmse", "dx", "uds_age"):
        out[col] = pd.NA

    for i, row in out.iterrows():
        sbj_visits = udsb4[udsb4["OASISID"] == row["subject_id"]]
        if sbj_visits.empty:
            continue
        gap = (sbj_visits["days_to_visit"] - row["tau_day"]).abs()
        in_window = sbj_visits[gap <= window_days]
        if in_window.empty:
            continue
        best = in_window.loc[gap[in_window.index].idxmin()]
        out.at[i, "cdr"]     = best["CDRTOT"]
        out.at[i, "mmse"]    = best["MMSE"]
        out.at[i, "dx"]      = best["dx1"]
        out.at[i, "uds_age"] = best["age at visit"]
    return out


def _join_centiloid(cohort, raw_dir):
    """Populate centiloid from OASIS3_amyloid_centiloid.csv. One row per
    amyloid PET session; match each cohort subject to the row whose
    session_id encodes the same day as ``av45_day``. Missing file or
    no match leaves the column as ``pd.NA``.
    """
    path = _find_csv(raw_dir, "OASIS3_amyloid_centiloid.csv")
    if path is None:
        print("  [INFO] OASIS3_amyloid_centiloid.csv not found; centiloid -> NaN")
        cohort = cohort.copy()
        cohort["centiloid"] = pd.NA
        return cohort
    print(f"  reading centiloid from {path}")
    cl = pd.read_csv(path)
    av45 = cl[cl["tracer"] == "AV45"].copy()
    # session_id like 'OAS30001_AV45_d2430'; pull the trailing day.
    av45["day"] = av45["oasis_session_id"].str.extract(r"_d(\d+)$").astype(int)

    out = cohort.copy()
    out["centiloid"] = pd.NA
    for i, row in out.iterrows():
        match = av45[
            (av45["subject_id"] == row["subject_id"])
            & (av45["day"] == row["av45_day"])
        ]
        if match.empty:
            continue
        out.at[i, "centiloid"] = match.iloc[0]["Centiloid_fSUVR_TOT_CORTMEAN"]
    return out


def produce_covariates(raw_dir, dest, cohort_csv):
    """Write ``covariates.csv`` to ``dest``.

    Args:
        raw_dir: contains the OASIS-3 metadata CSVs read by stage 1
            plus, optionally, the extracted OASIS3_data_files bundle
            for clinical + centiloid data.
        dest: pipeline output dir; covariates.csv is written here.
        cohort_csv: ``cohort_sessions.csv`` from stage 1.
    """
    raw_dir = Path(raw_dir)
    dest = Path(dest)

    cohort = pd.read_csv(cohort_csv)
    sbj = pd.read_csv(raw_dir / "sbj.csv")
    sbj = sbj[sbj["Subject"] != "0AS_data_files"]
    mr = pd.read_csv(raw_dir / "mr.csv")
    mr = mr[mr["Subject"] != "0AS_data_files"]

    sex_by_sbj = sbj.set_index("Subject")["M/F"].to_dict()
    cohort["sex"] = cohort["subject_id"].map(sex_by_sbj)

    cohort = _join_clinical(cohort, raw_dir)
    cohort = _join_centiloid(cohort, raw_dir)

    # Prefer UDS-visit age (always recorded); fall back to mr.csv's
    # per-session Age (often NaN); fall back to NaN.
    age_by_mr = mr.set_index("MR ID")["Age"].to_dict()
    cohort["age"] = (
        cohort["uds_age"]
        .combine_first(cohort["tau_mr_id"].map(age_by_mr))
    )
    cohort = cohort.drop(columns=["uds_age"])

    keep = _subjects_with_all_outputs(dest)
    out = cohort[cohort["subject_id"].isin(keep)][
        ["subject_id", "age", "sex", "cdr", "mmse", "dx", "centiloid"]
    ].copy()
    out_path = dest / "covariates.csv"
    out.to_csv(out_path, index=False)
    print(f"  covariates: {len(out)} subjects -> {out_path}")
    if len(out) < len(cohort):
        missing = len(cohort) - len(out)
        print(f"  ({missing} cohort subjects had no/incomplete image outputs)")
