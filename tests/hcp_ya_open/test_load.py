"""Fast loader tests for brainjar.hcp_ya_open.

Synthesize a tiny processed cache in ``tmp_path`` and exercise
``get_df_image`` / ``get_df_xfeat`` against it. No real HCP data needed.
"""

from pathlib import Path

import pandas as pd
import pytest

from brainjar.hcp_ya_open import labels as labels_mod
from brainjar.hcp_ya_open.load import get_df_image, get_df_xfeat


def _make_cache(dest, subjects=("100307", "100408", "101107")):
    dest.mkdir(parents=True, exist_ok=True)
    for sbj in subjects:
        for modality in ("fa", "md"):
            (dest / f"{sbj}_{modality}.nii.gz").write_bytes(b"")
    # extra non-matching files that must be ignored
    (dest / "fa_template.nii.gz").write_bytes(b"")
    (dest / "group_mask.nii.gz").write_bytes(b"")
    return dest


def test_get_df_image_parses_subject_filenames(tmp_path):
    _make_cache(tmp_path)
    pd.DataFrame({"subject_id": ["100307", "100408", "101107"], "Age": [22, 25, 30]}).to_csv(
        tmp_path / "covariates.csv", index=False
    )
    (tmp_path / ".complete").touch()

    df = get_df_image(dest=tmp_path)

    assert list(df.index) == ["100307", "100408", "101107"]
    assert df.index.name == "subject_id"
    assert set(df.columns) == {"fa", "md"}
    assert all(isinstance(p, Path) for p in df["fa"])
    assert df.loc["100307", "fa"].name == "100307_fa.nii.gz"


def test_get_df_image_raises_without_sentinel(tmp_path):
    _make_cache(tmp_path)
    with pytest.raises(FileNotFoundError, match="No processed HCP-YA Open data"):
        get_df_image(dest=tmp_path)


def test_get_df_xfeat_reads_covariates_with_str_index(tmp_path):
    _make_cache(tmp_path)
    # leading zero in subject_id would be lost if pandas inferred numeric.
    pd.DataFrame(
        {"subject_id": ["099999", "100307"], "Age": [22, 25], "Gender": ["F", "M"]}
    ).to_csv(tmp_path / "covariates.csv", index=False)
    (tmp_path / ".complete").touch()

    df = get_df_xfeat(dest=tmp_path)

    # Leading-zero preservation in the assert above is the actual contract;
    # also verify pandas didn't infer numeric.
    assert list(df.index) == ["099999", "100307"]
    assert pd.api.types.is_string_dtype(df.index.dtype)
    assert set(df.columns) == {"Age", "Gender"}


def test_get_df_xfeat_missing_csv_raises(tmp_path):
    _make_cache(tmp_path)
    (tmp_path / ".complete").touch()
    with pytest.raises(FileNotFoundError, match="covariates.csv not found"):
        get_df_xfeat(dest=tmp_path)


def test_labels_attrs_populated_when_columns_match(tmp_path):
    _make_cache(tmp_path)
    pd.DataFrame({"subject_id": ["100307"], "Age": [22]}).to_csv(
        tmp_path / "covariates.csv", index=False
    )
    (tmp_path / ".complete").touch()

    img = get_df_image(dest=tmp_path)
    assert "labels" in img.attrs
    for col, label in img.attrs["labels"].items():
        assert labels_mod.LABELS[col] == label
