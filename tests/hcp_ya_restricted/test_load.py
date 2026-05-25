"""Fast loader tests for brainjar.hcp_ya_restricted.

Build synthetic open + restricted caches in ``tmp_path`` and verify the
filter/reindex logic without any real HCP data.
"""

import pandas as pd
import pytest

from brainjar.hcp_ya_restricted.load import get_df_image, get_df_xfeat


def _make_open_cache(dest, subjects):
    dest.mkdir(parents=True, exist_ok=True)
    for sbj in subjects:
        (dest / f"{sbj}_fa.nii.gz").write_bytes(b"")
        (dest / f"{sbj}_md.nii.gz").write_bytes(b"")
    pd.DataFrame({"subject_id": list(subjects), "Age": [22] * len(subjects)}).to_csv(
        dest / "covariates.csv", index=False
    )
    (dest / ".complete").touch()


def _make_restricted_cache(dest, subjects):
    dest.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "subject_id": list(subjects),
            "Age_in_Yrs": [22] * len(subjects),
            "Handedness": [80] * len(subjects),
        }
    ).to_csv(dest / "covariates_restricted.csv", index=False)
    (dest / ".complete").touch()


def test_get_df_image_restricts_to_restricted_subjects(tmp_path, monkeypatch):
    open_cache = tmp_path / "open"
    restricted_cache = tmp_path / "restricted"
    _make_open_cache(open_cache, ["100307", "100408", "101107", "101309"])
    _make_restricted_cache(restricted_cache, ["100307", "101107"])

    monkeypatch.setenv("BRAINJAR_HCP_YA_OPEN_PATH", str(open_cache))

    df = get_df_image(dest=restricted_cache)

    assert list(df.index) == ["100307", "101107"]
    assert set(df.columns) == {"fa", "md"}


def test_get_df_image_raises_without_sentinel(tmp_path, monkeypatch):
    open_cache = tmp_path / "open"
    restricted_cache = tmp_path / "restricted"
    _make_open_cache(open_cache, ["100307"])
    restricted_cache.mkdir()
    monkeypatch.setenv("BRAINJAR_HCP_YA_OPEN_PATH", str(open_cache))

    with pytest.raises(FileNotFoundError, match="No processed HCP-YA Restricted"):
        get_df_image(dest=restricted_cache)


def test_get_df_xfeat_reads_restricted_csv_with_str_index(tmp_path):
    restricted_cache = tmp_path / "restricted"
    _make_restricted_cache(restricted_cache, ["099999", "100307"])

    df = get_df_xfeat(dest=restricted_cache)

    assert list(df.index) == ["099999", "100307"]
    assert pd.api.types.is_string_dtype(df.index.dtype)
    assert "Age_in_Yrs" in df.columns
    assert "Handedness" in df.columns


def test_get_df_xfeat_missing_csv_raises(tmp_path):
    restricted_cache = tmp_path / "restricted"
    restricted_cache.mkdir()
    (restricted_cache / ".complete").touch()
    with pytest.raises(FileNotFoundError, match="covariates_restricted.csv"):
        get_df_xfeat(dest=restricted_cache)
