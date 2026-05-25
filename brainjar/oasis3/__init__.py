"""OASIS-3 — time-matched A/T/N + DTI subset registered to MNI152.

Three-stage flow:

    from brain_pipe.oasis3 import prepare, fetch, process

    prepare()    # auto-fetches the ~67 MB metadata bundle from NITRC-IR
    fetch()      # downloads cohort imaging from NITRC-IR
    process()    # DTI + MNI registration

Loaders:

    from brain_pipe.oasis3 import get_df_image, get_df_xfeat, LABELS
"""

from brain_pipe.oasis3.fetch import fetch, prepare, process
from brain_pipe.oasis3.labels import LABELS
from brain_pipe.oasis3.load import get_df_image, get_df_xfeat

__all__ = [
    "prepare", "fetch", "process",
    "get_df_image", "get_df_xfeat",
    "LABELS",
]
