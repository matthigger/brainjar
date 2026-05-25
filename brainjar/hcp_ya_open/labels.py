"""Plot-ready labels for HCP-YA Open columns."""

LABELS = {
    # imaging modalities (columns of get_df_image)
    "fa": "Fractional Anisotropy",
    "md": "Mean Diffusivity (mm$^2$/s)",
    "mask": "Brain Mask",
    # covariates (columns of get_df_xfeat)
    "age": "Age (years, 5-yr bucket)",
    "sex": "Sex",
}
