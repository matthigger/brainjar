"""Loaders for the HCP-YA Open processed derivative."""

import re
from pathlib import Path

import pandas as pd

from brain_pipe.hcp_ya_open.fetch import _resolve_dest
from brain_pipe.hcp_ya_open.labels import LABELS

_SBJ_RE = re.compile(r"^(\d{6})_(fa|md)\.nii\.gz$")


def _check_ready(dest):
    if not (dest / ".complete").exists():
        raise FileNotFoundError(
            f"No processed HCP-YA Open data at {dest}. Run "
            f"`brain_pipe.hcp_ya_open.process()` first."
        )


def get_df_image(dest=None):
    """Return a DataFrame of per-subject image paths.

    Index: subject ID (str, 6-digit HCP identifier).
    Columns: ``fa``, ``md`` — absolute :class:`pathlib.Path` to the
    registered per-subject volume.

    Also stashes plot-ready strings in ``df.attrs['labels']``.
    """
    dest = _resolve_dest(dest)
    _check_ready(dest)

    rows = {}
    for f in sorted(dest.glob("*.nii.gz")):
        m = _SBJ_RE.match(f.name)
        if not m:
            continue
        sbj, modality = m.group(1), m.group(2)
        rows.setdefault(sbj, {})[modality] = f.resolve()

    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "subject_id"
    df.sort_index(inplace=True)
    df.attrs["labels"] = {c: LABELS[c] for c in df.columns if c in LABELS}
    return df


def get_df_xfeat(dest=None):
    """Return a covariates DataFrame indexed by subject ID.

    Reads ``covariates.csv`` from the processed directory. See
    ``README.md`` for the column set (sourced from the ConnectomeDB
    Subjects "all non-restricted columns" export).

    Also stashes plot-ready strings in ``df.attrs['labels']``.
    """
    dest = _resolve_dest(dest)
    _check_ready(dest)

    csv = dest / "covariates.csv"
    if not csv.exists():
        raise FileNotFoundError(
            f"covariates.csv not found at {csv}. The pipeline produces "
            f"it from an HCP_YA_subjects_*.csv export placed in raw_dir."
        )
    df = pd.read_csv(csv, dtype={"subject_id": str}).set_index("subject_id")
    df.sort_index(inplace=True)
    df.attrs["labels"] = {c: LABELS[c] for c in df.columns if c in LABELS}
    return df
