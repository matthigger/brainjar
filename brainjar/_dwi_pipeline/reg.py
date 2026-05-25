import re
from pathlib import Path

import ants
import numpy as np
from joblib import Parallel, delayed


def build_template(fa_files):
    """Build a simple average FA template."""
    images = [ants.image_read(str(f)) for f in fa_files]
    arrs = [img.numpy() for img in images]
    avg_arr = np.mean(arrs, axis=0)
    template = ants.from_numpy(
        avg_arr,
        origin=images[0].origin,
        spacing=images[0].spacing,
        direction=images[0].direction,
    )
    return template


def collect_subject_files(path_in, sbj_regex, img_regex_list):
    """Scan folder for images matching patterns, group by subject ID.

    Returns dict ``{sbj: {modality: Path}}``.
    """
    path_in = Path(path_in)
    sbj_dict = {}

    for regex in img_regex_list:
        files = path_in.glob(f"**/*{regex}.nii.gz")
        for f in files:
            sbj_match = re.search(sbj_regex, str(f))
            if sbj_match is None:
                print(f"[WARN] No subject ID found for {f}")
                continue
            sbj = sbj_match.group(0)
            if sbj not in sbj_dict:
                sbj_dict[sbj] = {}
            sbj_dict[sbj][regex] = f

    return sbj_dict


def _register_one(sbj, imgs, template_path, path_out, register_on, random_seed=1):
    """Register one subject. Returns warped-mask ndarray or None.

    ``template_path`` is the on-disk template path (re-loaded in each
    worker because ANTs image objects don't pickle reliably).
    ``random_seed`` is forwarded to ``ants.registration``; together with
    ``ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=1`` and ``ANTS_RANDOM_SEED``
    in the env, this drives the SyN optimizer toward bit-identical
    outputs across runs.
    """
    if register_on not in imgs:
        print(f"[WARN] Subject {sbj} has no {register_on} image. Skipping.")
        return None

    template = ants.image_read(str(template_path))
    moving_img = ants.image_read(str(imgs[register_on]))
    reg = ants.registration(
        fixed=template,
        moving=moving_img,
        type_of_transform="SyN",
        metric="CC",
        reg_iterations=[100, 70, 50, 20],
        random_seed=random_seed,
    )

    warped_reg_img = reg["warpedmovout"]
    warped_reg_img.to_file(str(path_out / f"{sbj}_{register_on}.nii.gz"))

    for modality, path in imgs.items():
        if modality == register_on or modality == "nodif_brain_mask":
            continue
        img = ants.image_read(str(path))
        warped_img = ants.apply_transforms(
            fixed=template,
            moving=img,
            transformlist=reg["fwdtransforms"],
        )
        warped_img.to_file(str(path_out / f"{sbj}_{modality}.nii.gz"))

    warped_mask = None
    if "nodif_brain_mask" in imgs:
        mask_img = ants.image_read(str(imgs["nodif_brain_mask"]))
        warped_mask_img = ants.apply_transforms(
            fixed=template,
            moving=mask_img,
            transformlist=reg["fwdtransforms"],
            interpolator="nearestNeighbor",
        )
        warped_mask = warped_mask_img.numpy()

    print(f"[DONE] Subject {sbj} registered and warped.")
    return warped_mask


def register_and_warp(sbj_dict, path_out, register_on="fa", n_jobs=1):
    """Build template (average), register and warp subject images, group-mask.

    Args:
        sbj_dict: ``{sbj_id: {modality: Path}}`` from
            :func:`collect_subject_files`.
        path_out: output directory.
        register_on: modality used to drive the SyN registration.
        n_jobs: parallel workers for the per-subject SyN loop. Each
            worker should use ``ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=1``
            (set in the parent before spawning) to avoid over-subscription.
    """
    path_out = Path(path_out)
    path_out.mkdir(parents=True, exist_ok=True)

    fa_files = [d[register_on] for d in sbj_dict.values() if register_on in d]
    if not fa_files:
        raise RuntimeError(f"No {register_on} images found in subject dict")

    template = build_template(fa_files)
    template_path = path_out / f"{register_on}_template.nii.gz"
    template.to_file(str(template_path))

    items = list(sbj_dict.items())
    warped_masks = Parallel(n_jobs=n_jobs, verbose=10)(
        delayed(_register_one)(sbj, imgs, template_path, path_out, register_on)
        for sbj, imgs in items
    )
    warped_masks = [m for m in warped_masks if m is not None]

    if warped_masks:
        group_mask_arr = np.logical_and.reduce(warped_masks).astype(np.uint8)
        group_mask = ants.from_numpy(
            group_mask_arr,
            origin=template.origin,
            spacing=template.spacing,
            direction=template.direction,
        )
        group_mask.to_file(str(path_out / "group_mask.nii.gz"))
        print(f'[INFO] Group mask saved at {path_out / "group_mask.nii.gz"}')

        # Mask the per-subject warped FA/MD; parallelize since each file
        # is independent.
        def _mask_one(f, group_mask_path):
            gm = ants.image_read(str(group_mask_path))
            img = ants.image_read(str(f))
            (img * gm).to_file(str(f))

        gm_path = path_out / "group_mask.nii.gz"
        targets = [
            f for f in path_out.glob("*.nii.gz")
            if f.name.endswith("_fa.nii.gz") or f.name.endswith("_md.nii.gz")
        ]
        Parallel(n_jobs=n_jobs)(
            delayed(_mask_one)(f, gm_path) for f in targets
        )


if __name__ == "__main__":
    import sys
    path_in = sys.argv[1] if len(sys.argv) > 1 else "/home/matt/data/hcp100_aug25"
    path_out = sys.argv[2] if len(sys.argv) > 2 else "/home/matt/data/hcp100_aug25_registered"
    sbj_regex = r"[\d]{6}"
    img_regex_list = ["fa", "md", "nodif_brain_mask"]
    register_on = "fa"

    sbj_dict = collect_subject_files(path_in, sbj_regex, img_regex_list)
    register_and_warp(sbj_dict, path_out, register_on=register_on)
