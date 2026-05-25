"""Tests for the bundle auto-fetch path.

Covers ``NitrcXnat.download_data_files_bundle`` and the
``prepare()`` -> ``_fetch_bundle`` flow that wires it in. Network
is mocked — these are fast unit tests.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys
import brainjar.oasis3  # ensures the submodule is loaded into sys.modules
oasis3_fetch = sys.modules["brainjar.oasis3.fetch"]
from brainjar.oasis3.pipeline.xnat import BUNDLE_URL, NitrcXnat


@pytest.fixture
def fake_xnat():
    """A NitrcXnat instance with a mocked requests.Session — no real
    network. Bypasses ``__init__``'s JSESSION call."""
    inst = NitrcXnat.__new__(NitrcXnat)
    inst.session = MagicMock()
    inst._open = True
    return inst


def _streaming_response(payload):
    """Build a MagicMock that mimics a streamed requests response."""
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.headers = {"content-length": str(len(payload))}
    resp.iter_content.return_value = [payload]
    resp.raise_for_status.return_value = None
    return resp


def test_download_data_files_bundle_writes_file(tmp_path, fake_xnat):
    payload = b"PKfake-zip-bytes" * 100
    fake_xnat.session.get.return_value = _streaming_response(payload)

    out = tmp_path / "raw" / "OASIS3_data_files.zip"
    fake_xnat.download_data_files_bundle(out)

    assert out.exists()
    assert out.read_bytes() == payload
    fake_xnat.session.get.assert_called_once()
    assert fake_xnat.session.get.call_args[0][0] == BUNDLE_URL


def test_download_data_files_bundle_reuses_existing(
    tmp_path, fake_xnat, capsys,
):
    out = tmp_path / "OASIS3_data_files.zip"
    out.write_bytes(b"already here")

    fake_xnat.download_data_files_bundle(out)

    fake_xnat.session.get.assert_not_called()
    assert out.read_bytes() == b"already here"
    assert "reusing" in capsys.readouterr().out


def test_fetch_bundle_reuses_zip_without_prompting(tmp_path, monkeypatch, capsys):
    """If the bundle is already at <raw>/OASIS3_data_files.zip,
    _fetch_bundle must skip the password prompt and the network call.
    """
    raw = tmp_path / "raw"
    raw.mkdir()
    existing = raw / "OASIS3_data_files.zip"
    existing.write_bytes(b"cached")

    # If anything tried to prompt or instantiate the XNAT client, the
    # test would either hang or raise — reaching the assertion proves
    # the early-return fired.
    def _explode(*a, **k):
        raise AssertionError("should not be called when zip exists")

    monkeypatch.setattr("builtins.input", _explode)
    monkeypatch.setattr(
        "brainjar.oasis3.pipeline.xnat.NitrcXnat.__init__", _explode,
    )

    out = oasis3_fetch._fetch_bundle(raw, nitrc_user="anyone")
    assert out == existing
    assert "reusing" in capsys.readouterr().out


def test_fetch_bundle_downloads_when_absent(tmp_path, monkeypatch):
    raw = tmp_path / "raw"

    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "pw")
    # Stub out NitrcXnat so no real network happens and no JSESSION login.
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = False

    def _capture_dl(out_path):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"downloaded")
        return out_path
    fake_client.download_data_files_bundle.side_effect = _capture_dl

    monkeypatch.setattr(
        "brainjar.oasis3.pipeline.xnat.NitrcXnat",
        lambda *a, **k: fake_client,
    )

    out = oasis3_fetch._fetch_bundle(raw, nitrc_user="someone")
    assert out == raw / "OASIS3_data_files.zip"
    assert out.read_bytes() == b"downloaded"
    fake_client.download_data_files_bundle.assert_called_once_with(out)
