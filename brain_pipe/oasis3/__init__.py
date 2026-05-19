"""OASIS-3 — time-matched A/T/N + DTI subset registered to MNI152.

Use:
    from brain_pipe.oasis3 import (
        prepare, process, download_raw,
        get_df_image, get_df_xfeat, LABELS,
    )
"""

from brain_pipe.oasis3.fetch import download_raw, prepare, process
from brain_pipe.oasis3.labels import LABELS
from brain_pipe.oasis3.load import get_df_image, get_df_xfeat

__all__ = [
    "prepare", "process", "download_raw",
    "get_df_image", "get_df_xfeat",
    "LABELS",
]
