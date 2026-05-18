"""Stage 6: assemble covariates.csv from the OASIS-3 metadata CSVs.

Joins ``cohort_sessions.csv`` against the demographic and per-session
CSVs and emits one row per subject who has all four image outputs in
``dest``. Clinical fields (CDR / MMSE / dx) and ``centiloid`` are
emitted as NaN — the NITRC-IR ``0AS_data_files`` bundle this pipeline
expects does not ship them. Chase those via
``oasis-brains@nrg.wustl.edu`` and fold them in here later.
"""

from pathlib import Path

import pandas as pd

_REQUIRED_MODALITIES = ("amyloid_suvr", "tau_suvr", "fa", "md")


def _subjects_with_all_outputs(dest):
    """Subjects that have ``<sbj>_<modality>.nii.gz`` for every
    required modality in ``dest``.
    """
    by_sbj = {}
    for f in dest.glob("*.nii.gz"):
        # Files like OAS30001_amyloid_suvr.nii.gz; everything before
        # the first underscore is the subject.
        name = f.name[: -len(".nii.gz")]
        parts = name.split("_", 1)
        if len(parts) != 2 or not parts[0].startswith("OAS"):
            continue
        sbj, mod = parts
        by_sbj.setdefault(sbj, set()).add(mod)
    return {s for s, mods in by_sbj.items()
            if all(m in mods for m in _REQUIRED_MODALITIES)}


def produce_covariates(raw_dir, dest, cohort_csv):
    """Write ``covariates.csv`` to ``dest``.

    Args:
        raw_dir: contains the OASIS-3 metadata CSVs read by stage 1.
        dest: pipeline output dir (where the 4 image features per
            subject live, and where ``covariates.csv`` is written).
        cohort_csv: ``cohort_sessions.csv`` written by stage 1.
    """
    raw_dir = Path(raw_dir)
    dest = Path(dest)

    cohort = pd.read_csv(cohort_csv)
    sbj = pd.read_csv(raw_dir / "sbj.csv")
    sbj = sbj[sbj["Subject"] != "0AS_data_files"]
    mr = pd.read_csv(raw_dir / "mr.csv")
    mr = mr[mr["Subject"] != "0AS_data_files"]

    # Age at the tau-anchored MR session (cohort.tau_mr_id refers to the
    # MR session paired with the tau PUP via FSId/MRId).
    age_by_mr = mr.set_index("MR ID")["Age"].to_dict()
    cohort["age"] = cohort["tau_mr_id"].map(age_by_mr)

    sex_by_sbj = sbj.set_index("Subject")["M/F"].to_dict()
    cohort["sex"] = cohort["subject_id"].map(sex_by_sbj)

    # Clinical + centiloid: not in this bundle. Emit NaN.
    for col in ("cdr", "mmse", "dx", "centiloid"):
        cohort[col] = pd.NA

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
