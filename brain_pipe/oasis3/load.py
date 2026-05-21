"""Loaders for the OASIS-3 processed derivative."""

import re

import pandas as pd

from brain_pipe.hcp_ya_open.fetch import resolve_dest
from brain_pipe.oasis3.labels import LABELS

_SBJ_RE = re.compile(r"^(OAS\d+)_(t1|fa|md)\.nii\.gz$")


def _resolve_dest(dest=None):
    return resolve_dest("oasis3", dest)


def _check_ready(dest):
    if not (dest / ".complete").exists():
        raise FileNotFoundError(
            f"No processed OASIS-3 data at {dest}. Run "
            f"`brain_pipe.oasis3.process(raw_dir=...)` first."
        )


def get_df_image(dest=None):
    """Return a DataFrame of per-subject image paths.

    Index: subject ID (str, e.g. ``OAS30001``).
    Columns: ``t1``, ``fa``, ``md`` — absolute
    :class:`pathlib.Path` to the MNI152-registered per-subject volume.
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

    Reads ``covariates.csv`` from the processed directory. Demographic
    columns: ``age``, ``sex``, ``educ``, ``apoe``, ``daddem``, ``momdem``.
    CDR target columns (the prediction outcome): ``cdr_sum`` (CDR Sum of
    Boxes, 0-18) and the six component scores ``memory``, ``orient``,
    ``judgment``, ``commun``, ``homehobb``, ``perscare`` (each
    0/0.5/1/2/3). NaN-filled where the OASIS-3 metadata did not supply
    a value.
    """
    dest = _resolve_dest(dest)
    _check_ready(dest)

    csv = dest / "covariates.csv"
    if not csv.exists():
        raise FileNotFoundError(
            f"covariates.csv not found at {csv}. Re-run "
            f"brain_pipe.oasis3.process(raw_dir=...)."
        )
    df = pd.read_csv(csv, dtype={"subject_id": str}).set_index("subject_id")
    df.sort_index(inplace=True)
    df.attrs["labels"] = {c: LABELS[c] for c in df.columns if c in LABELS}
    return df
