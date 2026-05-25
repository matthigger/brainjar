"""Plot-ready labels for OASIS-3 columns."""

LABELS = {
    # imaging modalities (columns of get_df_image)
    "t1": "T1-weighted (MNI-space)",
    "fa": "Fractional Anisotropy",
    "md": "Mean Diffusivity (mm$^2$/s)",
    # covariates (columns of get_df_xfeat)
    "age":      "Age (years)",
    "sex":      "Sex",
    "educ":     "Years of Education",
    "apoe":     "APOE Genotype",
    "daddem":   "Paternal History of Dementia",
    "momdem":   "Maternal History of Dementia",
    # CDR targets (the prediction outcome)
    "cdr_sum":  "CDR Sum of Boxes",
    "memory":   "CDR: Memory",
    "orient":   "CDR: Orientation",
    "judgment": "CDR: Judgment & Problem Solving",
    "commun":   "CDR: Community Affairs",
    "homehobb": "CDR: Home & Hobbies",
    "perscare": "CDR: Personal Care",
}
