"""Loaders for the HCP-YA Restricted processed derivative.

Imaging is reused from ``hcp_ya_open`` (same FA/MD volumes); this
package only adds the restricted-access covariates and restricts the
subject set to those present in the user-supplied RESTRICTED_*.csv.
"""

import pandas as pd

from brainjar import hcp_ya_open
from brainjar.hcp_ya_restricted.fetch import _resolve_dest
from brainjar.hcp_ya_restricted.labels import LABELS


def _check_ready(dest):
    if not (dest / ".complete").exists():
        raise FileNotFoundError(
            f"No processed HCP-YA Restricted data at {dest}. Run "
            f"`brainjar.hcp_ya_restricted.process()` first."
        )


def _restricted_subjects(dest):
    return set(
        pd.read_csv(
            dest / "covariates_restricted.csv", dtype={"subject_id": str}
        )["subject_id"]
    )


def get_df_image(dest=None):
    """Per-subject FA/MD paths, restricted to subjects with restricted covariates.

    Index: subject ID (6-digit HCP identifier, str).
    Columns: ``fa``, ``md`` — absolute :class:`pathlib.Path` to volumes
    that live in the ``hcp_ya_open`` cache.

    Also stashes plot-ready strings in ``df.attrs['labels']``.
    """
    dest = _resolve_dest(dest)
    _check_ready(dest)

    df = hcp_ya_open.get_df_image()
    keep = _restricted_subjects(dest)
    df = df[df.index.isin(keep)].copy()
    df.attrs["labels"] = {c: LABELS[c] for c in df.columns if c in LABELS}
    return df


def get_df_xfeat(dest=None):
    """Restricted-access covariates DataFrame indexed by subject ID.

    Reads ``covariates_restricted.csv`` from the processed directory —
    the RESTRICTED_*.csv ConnectomeDB export, filtered to subjects in
    the hcp_ya_open derivative, with ``Subject`` renamed to
    ``subject_id``. All other columns pass through verbatim.

    Also stashes plot-ready strings in ``df.attrs['labels']``.
    """
    dest = _resolve_dest(dest)
    _check_ready(dest)

    csv = dest / "covariates_restricted.csv"
    if not csv.exists():
        raise FileNotFoundError(
            f"covariates_restricted.csv not found at {csv}. Run "
            f"`brainjar.hcp_ya_restricted.process()` first."
        )
    df = pd.read_csv(csv, dtype={"subject_id": str}).set_index("subject_id")
    df.sort_index(inplace=True)
    df.attrs["labels"] = {c: LABELS[c] for c in df.columns if c in LABELS}
    return df
