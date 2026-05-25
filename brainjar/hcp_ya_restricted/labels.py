"""Plot-ready labels for HCP-YA Restricted columns.

Inherits imaging labels (``fa``, ``md``, ``mask``, ...) from
``brainjar.hcp_ya_open`` and adds entries for the restricted-access
covariate columns. The restricted CSV is exposed verbatim by
``get_df_xfeat``; only columns that get plotted need a label here.
"""

from brainjar.hcp_ya_open import LABELS as _OPEN_LABELS

LABELS = {
    **_OPEN_LABELS,
    # restricted-access covariates (ConnectomeDB "Restricted" columns)
    "Age_in_Yrs": "Age (years)",
    "Handedness": "Edinburgh Handedness (-100..100)",
    "Race": "Race",
    "Ethnicity": "Ethnicity",
    "BMI": "Body Mass Index",
    "Family_ID": "HCP Family ID",
    "ZygosityGT": "Zygosity (genotyped)",
    "ZygositySR": "Zygosity (self-reported)",
    "Mother_ID": "Mother ID",
    "Father_ID": "Father ID",
}
