"""Plot-ready labels for OASIS-3 columns."""

LABELS = {
    # imaging modalities (columns of get_df_image)
    "amyloid_suvr": "Amyloid SUVR (AV45)",
    "tau_suvr": "Tau SUVR (AV1451)",
    "fa": "Fractional Anisotropy",
    "md": "Mean Diffusivity (mm$^2$/s)",
    # covariates (columns of get_df_xfeat)
    "age": "Age (years)",
    "sex": "Sex",
    "cdr": "Clinical Dementia Rating",
    "mmse": "Mini-Mental State Examination",
    "dx": "Diagnosis",
    "centiloid": "Centiloid (global amyloid)",
}
