"""Produce ``covariates.csv`` from the HCP-YA ConnectomeDB Subjects export."""

from pathlib import Path

import pandas as pd

_RENAME = {
    "Subject": "subject_id",
    "Gender": "sex",
    "Age": "age",   # 5-year bucket string, e.g. "26-30"
}


def find_subjects_csv(raw_dir: Path) -> Path:
    """Locate the HCP-YA subjects CSV in ``raw_dir``.

    Matches the filename pattern produced by ConnectomeDB's
    *Subjects > Export CSV* workflow: ``HCP_YA_subjects_<timestamp>.csv``.
    """
    matches = sorted(Path(raw_dir).glob("HCP_YA_subjects_*.csv"))
    if not matches:
        raise FileNotFoundError(
            f"No HCP_YA_subjects_*.csv in {raw_dir}. Export it from "
            f"ConnectomeDB: WU-Minn HCP Data > Subjects tab > Export CSV "
            f"with 'all non-restricted columns' selected."
        )
    if len(matches) > 1:
        print(f"[WARN] Multiple subjects CSVs found; using newest: {matches[-1].name}")
    return matches[-1]


def produce_covariates(raw_dir, dest, sbj_ids=None):
    """Read the ConnectomeDB Subjects export and write ``covariates.csv``.

    Args:
        raw_dir: directory containing the ``HCP_YA_subjects_*.csv`` export.
        dest: output directory (the processed-derivative dir).
        sbj_ids: if given, restrict the output to these 6-digit subject
            IDs (e.g. only the subjects that actually completed the DTI
            pipeline). If None, all rows are kept.

    Renames ``Subject``→``subject_id``, ``Gender``→``sex``, ``Age``→``age``;
    keeps every other column verbatim. Writes ``dest/covariates.csv``.
    """
    raw_dir = Path(raw_dir)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    src = find_subjects_csv(raw_dir)
    df = pd.read_csv(src, dtype={"Subject": str})
    df = df.rename(columns=_RENAME)

    if sbj_ids is not None:
        df = df[df["subject_id"].isin(set(sbj_ids))]

    cols = ["subject_id", "age", "sex"] + [
        c for c in df.columns if c not in ("subject_id", "age", "sex")
    ]
    df = df[cols].set_index("subject_id").sort_index()

    out = dest / "covariates.csv"
    df.to_csv(out)
    print(f"[DONE] {out}  ({len(df)} subjects, {len(df.columns)} cols)")
    return out
