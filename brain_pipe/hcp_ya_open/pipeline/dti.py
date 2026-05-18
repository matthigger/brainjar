import nibabel as nib
from dipy.core.gradients import gradient_table
from dipy.io.gradients import read_bvals_bvecs
from dipy.reconst.dti import TensorModel


def process_dti(file, dti_fnc_dict):
    _folder = file.parent
    for label in dti_fnc_dict.keys():
        _file = _folder / f"{label}.nii.gz"
        if not _file.exists():
            break
    else:
        print(f"already processed, skipping: {file}")
        return

    dwi_img = nib.load(str(file))
    dwi_data = dwi_img.get_fdata()
    bvals, bvecs = read_bvals_bvecs(str(_folder / "bvals"),
                                    str(_folder / "bvecs"))

    gtab = gradient_table(bvals, bvecs)
    dti_model = TensorModel(gtab)
    dti_fit = dti_model.fit(dwi_data)

    for label, fnc in dti_fnc_dict.items():
        img = nib.Nifti1Image(fnc(dti_fit.evals), dwi_img.affine)
        path_out = _folder / f"{label}.nii.gz"
        nib.save(img, path_out)
        print(f"created: {path_out}")


if __name__ == "__main__":
    import sys
    import pathlib
    from joblib import Parallel, delayed
    import tqdm
    from dipy.reconst.dti import fractional_anisotropy, mean_diffusivity

    n_jobs = 4
    folder = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                          else "/home/matt/data/hcp100_aug25")
    dti_fnc_dict = {
        "fa": fractional_anisotropy,
        "md": mean_diffusivity,
    }

    files = list(folder.glob("**/data.nii.gz"))
    Parallel(n_jobs=n_jobs)(
        delayed(process_dti)(f, dti_fnc_dict)
        for f in tqdm.tqdm(files, desc="DTI per img")
    )
