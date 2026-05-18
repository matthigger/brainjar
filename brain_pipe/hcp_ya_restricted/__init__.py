"""HCP-YA Restricted Access — same FA/MD images as hcp_ya_open, plus the
restricted-access covariates (exact age, family structure, handedness, ...).

Use:
    from brain_pipe.hcp_ya_restricted import process, get_df_image, get_df_xfeat, LABELS
"""

from brain_pipe.hcp_ya_restricted.fetch import process
from brain_pipe.hcp_ya_restricted.labels import LABELS
from brain_pipe.hcp_ya_restricted.load import get_df_image, get_df_xfeat

__all__ = ["process", "get_df_image", "get_df_xfeat", "LABELS"]
