"""Fast tests for brainjar.hcp_ya_open.fetch — path resolution + DUA prompt.

Pipeline execution (``_process_local`` / ``_download_zenodo``) is covered
by the slow repro tests, not here.
"""

from pathlib import Path

import pytest

from brainjar.hcp_ya_open import fetch
from brainjar.hcp_ya_open.fetch import (
    _resolve_dest,
    process,
    prompt_dua,
    resolve_dest,
)


def test_resolve_dest_explicit_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAINJAR_HCP_YA_OPEN_PATH", "/should/not/be/used")
    assert resolve_dest("hcp_ya_open", tmp_path) == tmp_path


def test_resolve_dest_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAINJAR_FOO_PATH", str(tmp_path))
    assert resolve_dest("foo") == tmp_path


def test_resolve_dest_falls_back_to_user_data_dir(monkeypatch):
    monkeypatch.delenv("BRAINJAR_HCP_YA_OPEN_PATH", raising=False)
    out = _resolve_dest()
    assert out.name == "hcp_ya_open"
    assert "brainjar" in out.parts


def test_process_short_circuits_on_sentinel(tmp_path):
    (tmp_path / ".complete").touch()
    # No raw_dir, no download — should just return because sentinel exists.
    assert process(dest=tmp_path) == tmp_path


def test_process_local_raises_without_raw(tmp_path):
    with pytest.raises(FileNotFoundError, match="raw HCP data not found"):
        process(download=False, dest=tmp_path)


def test_prompt_dua_accepts_exact_phrase(monkeypatch, tmp_path):
    monkeypatch.setattr("builtins.input", lambda *a, **k: "I agree")
    marker = tmp_path / ".dua_agreed"
    prompt_dua(
        {"url": "http://example.invalid", "prompt": "I agree"},
        header="TEST",
        body="body",
        marker=marker,
    )
    assert marker.exists()


def test_prompt_dua_rejects_wrong_phrase(monkeypatch, tmp_path):
    monkeypatch.setattr("builtins.input", lambda *a, **k: "nope")
    with pytest.raises(SystemExit):
        prompt_dua(
            {"url": "http://example.invalid", "prompt": "I agree"},
            header="TEST",
            body="body",
            marker=tmp_path / ".dua_agreed",
        )


def test_prompt_dua_skips_when_marker_exists(tmp_path):
    marker = tmp_path / ".dua_agreed"
    marker.touch()
    # No monkeypatch on input: if prompt_dua tried to call input(), the
    # test would hang. Reaching the return proves it short-circuited.
    prompt_dua(
        {"url": "http://example.invalid", "prompt": "I agree"},
        header="TEST",
        body="body",
        marker=marker,
    )
