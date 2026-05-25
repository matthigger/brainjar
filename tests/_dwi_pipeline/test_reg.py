"""Fast tests for brainjar._dwi_pipeline.reg helpers.

Covers the cheap, dep-light helpers: ``collect_subject_files`` regex
grouping and ``build_template`` averaging. The SyN registration loop
(``_register_one`` / ``register_and_warp``) is exercised by the slow
``test_repro_syn_*`` test in ``tests/hcp_ya_open/test_repro.py``.

The reg module imports antspyx at module top, so this whole file is
skipped without the pipeline extra.
"""

import pytest

pytest.importorskip("ants")

import numpy as np  # noqa: E402

from brainjar._dwi_pipeline.reg import collect_subject_files  # noqa: E402


def test_collect_subject_files_groups_by_subject_regex(tmp_path):
    # Mimic HCP-style layout: 6-digit subject ID embedded in path.
    for sbj in ("100307", "100408"):
        d = tmp_path / sbj / "T1w" / "Diffusion"
        d.mkdir(parents=True)
        (d / "fa.nii.gz").write_bytes(b"")
        (d / "md.nii.gz").write_bytes(b"")

    out = collect_subject_files(tmp_path, r"\d{6}", ["fa", "md"])

    assert set(out.keys()) == {"100307", "100408"}
    for sbj, mods in out.items():
        assert set(mods.keys()) == {"fa", "md"}
        assert mods["fa"].name == "fa.nii.gz"
        assert sbj in str(mods["fa"])


def test_collect_subject_files_warns_and_skips_unmatched(tmp_path, capsys):
    # File without a 6-digit ID in its path.
    (tmp_path / "fa.nii.gz").write_bytes(b"")

    out = collect_subject_files(tmp_path, r"\d{6}", ["fa"])

    assert out == {}
    assert "No subject ID found" in capsys.readouterr().out


def test_collect_subject_files_ignores_nonmatching_modalities(tmp_path):
    d = tmp_path / "100307"
    d.mkdir()
    (d / "fa.nii.gz").write_bytes(b"")
    (d / "other.nii.gz").write_bytes(b"")

    out = collect_subject_files(tmp_path, r"\d{6}", ["fa"])
    assert out["100307"].keys() == {"fa"}


def test_build_template_averages_input_arrays(tmp_path):
    import ants

    from brainjar._dwi_pipeline.reg import build_template

    paths = []
    for i, val in enumerate((1.0, 3.0, 5.0)):
        arr = np.full((4, 4, 4), val, dtype=np.float32)
        img = ants.from_numpy(arr)
        p = tmp_path / f"fa_{i}.nii.gz"
        img.to_file(str(p))
        paths.append(p)

    template = build_template(paths)
    # Mean of (1, 3, 5) = 3.0 everywhere.
    np.testing.assert_allclose(template.numpy(), 3.0, rtol=1e-5)
