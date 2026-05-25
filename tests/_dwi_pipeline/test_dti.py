"""Fast wrapper test for brainjar._dwi_pipeline.dti.process_dti.

This checks the I/O contract — does the wrapper read DWI + bvals/bvecs,
call dipy's tensor model, and write fa/md NIfTIs with the right shape
and affine? It does NOT verify numerical reproducibility against the
HCP-YA Open deposit; that's the slow repro test's job.

The dti module imports dipy at module top, so this whole file is
skipped without the pipeline extra.
"""

import pytest

pytest.importorskip("dipy")
pytest.importorskip("nibabel")

import numpy as np  # noqa: E402


def _write_synthetic_dwi(folder):
    """Build a tiny anisotropic 4D DWI volume + bvals/bvecs in ``folder``.

    Shape: (4, 4, 2, 7) — one b=0 volume + 6 weighted directions.
    The signal is computed from a fixed diffusion tensor so the fitter
    has something physically meaningful to recover.
    """
    import nibabel as nib

    nx, ny, nz = 4, 4, 2
    bvals = np.array([0.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0])
    bvecs = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.707, 0.707, 0.0],
            [0.707, 0.0, 0.707],
            [0.0, 0.707, 0.707],
        ]
    )

    # Anisotropic tensor: large eigenvalue along x, small along y/z.
    D = np.diag([1.7e-3, 0.3e-3, 0.3e-3])
    s0 = 1000.0

    data = np.zeros((nx, ny, nz, len(bvals)), dtype=np.float32)
    for i, (b, g) in enumerate(zip(bvals, bvecs)):
        signal = s0 * np.exp(-b * (g @ D @ g))
        data[..., i] = signal

    nib.save(nib.Nifti1Image(data, affine=np.eye(4)), str(folder / "data.nii.gz"))
    np.savetxt(folder / "bvals", bvals[None, :], fmt="%.1f")
    np.savetxt(folder / "bvecs", bvecs.T, fmt="%.6f")


def test_process_dti_writes_fa_md_with_correct_shape_and_affine(tmp_path):
    import nibabel as nib
    from dipy.reconst.dti import fractional_anisotropy, mean_diffusivity

    from brainjar._dwi_pipeline.dti import process_dti

    _write_synthetic_dwi(tmp_path)

    process_dti(
        tmp_path / "data.nii.gz",
        {"fa": fractional_anisotropy, "md": mean_diffusivity},
    )

    for label in ("fa", "md"):
        out = tmp_path / f"{label}.nii.gz"
        assert out.exists(), f"{label}.nii.gz not written"
        img = nib.load(str(out))
        assert img.shape == (4, 4, 2), f"{label} shape mismatch: {img.shape}"
        np.testing.assert_array_equal(img.affine, np.eye(4))

    fa = nib.load(str(tmp_path / "fa.nii.gz")).get_fdata()
    md = nib.load(str(tmp_path / "md.nii.gz")).get_fdata()
    # Anisotropic tensor → FA should be well above zero everywhere.
    assert (fa > 0.5).all(), f"FA unexpectedly low: min={fa.min()}, max={fa.max()}"
    assert fa.max() <= 1.0
    # MD should match (1.7+0.3+0.3)/3 * 1e-3 ≈ 7.7e-4.
    np.testing.assert_allclose(md, 7.7e-4, rtol=0.05)


def test_process_dti_skips_when_outputs_exist(tmp_path):
    from dipy.reconst.dti import fractional_anisotropy

    from brainjar._dwi_pipeline.dti import process_dti

    _write_synthetic_dwi(tmp_path)
    (tmp_path / "fa.nii.gz").write_bytes(b"prior")  # sentinel

    process_dti(tmp_path / "data.nii.gz", {"fa": fractional_anisotropy})

    # No clobber: the placeholder content survives.
    assert (tmp_path / "fa.nii.gz").read_bytes() == b"prior"
