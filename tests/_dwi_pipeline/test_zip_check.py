"""Fast tests for brainjar._dwi_pipeline.zip_check."""

import hashlib
import zipfile

import pytest

from brainjar._dwi_pipeline.zip_check import check_and_unzip, md5sum


def _make_zip(folder, name, payload):
    zip_path = folder / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{name}/hello.txt", payload)
    return zip_path


def test_md5sum_matches_hashlib(tmp_path):
    f = tmp_path / "blob"
    f.write_bytes(b"the quick brown fox")
    assert md5sum(f) == hashlib.md5(b"the quick brown fox").hexdigest()


def test_check_and_unzip_extracts_when_md5_matches(tmp_path):
    zip_path = _make_zip(tmp_path, "bundle", "hi")
    (zip_path.with_suffix(".zip.md5")).write_text(md5sum(zip_path) + "  bundle.zip\n")

    check_and_unzip(tmp_path)

    extracted = tmp_path / "bundle" / "bundle" / "hello.txt"
    assert extracted.exists()
    assert extracted.read_text() == "hi"
    # delete=False by default → original zip should remain.
    assert zip_path.exists()


def test_check_and_unzip_skips_on_md5_mismatch(tmp_path, capsys):
    zip_path = _make_zip(tmp_path, "bundle", "hi")
    (zip_path.with_suffix(".zip.md5")).write_text("0" * 32 + "  bundle.zip\n")

    check_and_unzip(tmp_path)

    assert "md5 mismatch" in capsys.readouterr().out
    assert not (tmp_path / "bundle" / "bundle" / "hello.txt").exists()


def test_check_and_unzip_deletes_zip_when_requested(tmp_path):
    zip_path = _make_zip(tmp_path, "bundle", "hi")
    (zip_path.with_suffix(".zip.md5")).write_text(md5sum(zip_path) + "  bundle.zip\n")

    check_and_unzip(tmp_path, delete=True)
    assert not zip_path.exists()


def test_check_and_unzip_skip_existing(tmp_path):
    zip_path = _make_zip(tmp_path, "bundle", "hi")
    (zip_path.with_suffix(".zip.md5")).write_text(md5sum(zip_path) + "  bundle.zip\n")
    target = tmp_path / "bundle"
    target.mkdir()  # pre-existing target should cause skip

    check_and_unzip(tmp_path, skip_existing=True)

    # No nested bundle/bundle/hello.txt should be produced.
    assert not (target / "bundle" / "hello.txt").exists()
