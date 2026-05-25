"""Fast tests for brainjar.hcp_ya_restricted.fetch.

Exercises the filter/rename logic in ``process()`` against a synthetic
``hcp_ya_open`` cache + ``RESTRICTED_*.csv`` in ``tmp_path``. Does not
touch the real HCP DUA prompt — restricted DUA is bypassed via the
``.dua_agreed`` marker.
"""

import pandas as pd
import pytest

from brainjar.hcp_ya_restricted.fetch import _resolve_dest, process


def _make_open_cache(dest, subjects):
    dest.mkdir(parents=True, exist_ok=True)
    for sbj in subjects:
        (dest / f"{sbj}_fa.nii.gz").write_bytes(b"")
        (dest / f"{sbj}_md.nii.gz").write_bytes(b"")
    pd.DataFrame({"subject_id": list(subjects), "Age": [22] * len(subjects)}).to_csv(
        dest / "covariates.csv", index=False
    )
    (dest / ".complete").touch()


def test_download_true_raises(tmp_path):
    with pytest.raises(NotImplementedError, match="no Zenodo deposit"):
        process(download=True, dest=tmp_path)


def test_resolve_dest_uses_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAINJAR_HCP_YA_RESTRICTED_PATH", str(tmp_path))
    assert _resolve_dest() == tmp_path


def test_process_short_circuits_on_sentinel(tmp_path):
    (tmp_path / ".complete").touch()
    assert process(dest=tmp_path) == tmp_path


def test_process_filters_and_renames(tmp_path, monkeypatch):
    open_cache = tmp_path / "open"
    restricted_cache = tmp_path / "restricted"
    _make_open_cache(open_cache, ["100307", "100408", "101107"])
    monkeypatch.setenv("BRAINJAR_HCP_YA_OPEN_PATH", str(open_cache))

    raw = restricted_cache / "raw"
    raw.mkdir(parents=True)
    pd.DataFrame(
        {
            "Subject": ["100307", "101107", "999999"],  # 999999 is not in open
            "Age_in_Yrs": [22, 30, 40],
            "Handedness": [80, -50, 100],
        }
    ).to_csv(raw / "RESTRICTED_test_20260518.csv", index=False)

    # Pre-create the DUA marker so process() doesn't prompt.
    restricted_cache.mkdir(exist_ok=True)
    (restricted_cache / ".dua_agreed").touch()

    out = process(dest=restricted_cache)

    assert out == restricted_cache
    assert (restricted_cache / ".complete").exists()

    df = pd.read_csv(restricted_cache / "covariates_restricted.csv",
                     dtype={"subject_id": str})
    assert list(df["subject_id"]) == ["100307", "101107"]  # 999999 dropped
    assert "Subject" not in df.columns
    assert set(df.columns) >= {"subject_id", "Age_in_Yrs", "Handedness"}


def test_process_picks_newest_restricted_csv(tmp_path, monkeypatch):
    open_cache = tmp_path / "open"
    restricted_cache = tmp_path / "restricted"
    _make_open_cache(open_cache, ["100307"])
    monkeypatch.setenv("BRAINJAR_HCP_YA_OPEN_PATH", str(open_cache))

    raw = restricted_cache / "raw"
    raw.mkdir(parents=True)
    # Older export has wrong handedness value; newest export wins.
    pd.DataFrame({"Subject": ["100307"], "Handedness": [-100]}).to_csv(
        raw / "RESTRICTED_test_20260101.csv", index=False
    )
    pd.DataFrame({"Subject": ["100307"], "Handedness": [99]}).to_csv(
        raw / "RESTRICTED_test_20260518.csv", index=False
    )

    restricted_cache.mkdir(exist_ok=True)
    (restricted_cache / ".dua_agreed").touch()

    process(dest=restricted_cache)
    df = pd.read_csv(restricted_cache / "covariates_restricted.csv")
    assert df.loc[0, "Handedness"] == 99


def test_process_raises_when_no_restricted_csv(tmp_path, monkeypatch):
    open_cache = tmp_path / "open"
    restricted_cache = tmp_path / "restricted"
    _make_open_cache(open_cache, ["100307"])
    monkeypatch.setenv("BRAINJAR_HCP_YA_OPEN_PATH", str(open_cache))

    raw = restricted_cache / "raw"
    raw.mkdir(parents=True)
    restricted_cache.mkdir(exist_ok=True)
    (restricted_cache / ".dua_agreed").touch()

    with pytest.raises(FileNotFoundError, match="No RESTRICTED_"):
        process(dest=restricted_cache)


def test_process_raises_on_empty_overlap(tmp_path, monkeypatch):
    open_cache = tmp_path / "open"
    restricted_cache = tmp_path / "restricted"
    _make_open_cache(open_cache, ["100307"])
    monkeypatch.setenv("BRAINJAR_HCP_YA_OPEN_PATH", str(open_cache))

    raw = restricted_cache / "raw"
    raw.mkdir(parents=True)
    pd.DataFrame({"Subject": ["999999"], "Age_in_Yrs": [99]}).to_csv(
        raw / "RESTRICTED_test_20260518.csv", index=False
    )

    restricted_cache.mkdir(exist_ok=True)
    (restricted_cache / ".dua_agreed").touch()

    with pytest.raises(RuntimeError, match="No overlap"):
        process(dest=restricted_cache)
