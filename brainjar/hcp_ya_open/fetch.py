"""Ensure the HCP-YA Open processed derivative exists at the cache, by
downloading from Zenodo or running the pipeline locally."""

import hashlib
import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import yaml
from platformdirs import user_data_dir

_PKG_DIR = Path(__file__).resolve().parent
_MANIFEST = _PKG_DIR / "manifest.yaml"

DEFAULT_CACHE = Path(user_data_dir("brain_pipe")) / "hcp_ya_open"
_PATH_ENV = "BRAIN_PIPE_HCP_YA_OPEN_PATH"


def resolve_dest(name, dest=None):
    """Resolve the cache directory for a dataset's processed derivative.

    Shared helper for any ``brain_pipe.<name>`` subpackage:
    explicit ``dest`` wins; else ``BRAIN_PIPE_<NAME>_PATH`` env var;
    else ``platformdirs.user_data_dir('brain_pipe') / name``.
    """
    if dest is not None:
        return Path(dest)
    env = os.environ.get(f"BRAIN_PIPE_{name.upper()}_PATH")
    return Path(env) if env else Path(user_data_dir("brain_pipe")) / name


def _resolve_dest(dest=None):
    return resolve_dest("hcp_ya_open", dest)


def process(download=None, raw_dir=None, dest=None, n_jobs=1, n_jobs_dti=None):
    """Ensure the HCP-YA Open processed derivative exists; return its path.

    Args:
        download: ``True`` to download the pre-processed derivative from
            Zenodo (after a HCP DUA confirmation prompt). ``False`` to
            run the pipeline locally on raw HCP data. ``None`` (default)
            to prompt the user interactively.
        raw_dir: when running the pipeline locally, where the raw HCP
            data lives. Defaults to ``<dest>/raw/``.
        dest: cache location for the processed output. Defaults to
            ``$BRAIN_PIPE_HCP_YA_OPEN_PATH`` if set, else
            ``platformdirs.user_data_dir('brain_pipe')/hcp_ya_open``.
        n_jobs: parallel workers for SyN registration (stage 3). Each
            worker pins ITK to 1 thread to avoid over-subscription.
        n_jobs_dti: parallel workers for DTI fitting (stage 2). DTI
            holds the full DWI volume in memory (~12–15 GB per worker
            for HCP), so this is typically a smaller number than
            ``n_jobs``. Defaults to ``min(n_jobs, 4)``.

    Returns:
        ``pathlib.Path`` to a directory of ``<sbj>_fa.nii.gz`` and
        ``<sbj>_md.nii.gz`` registered into ``fa_template.nii.gz``,
        plus ``group_mask.nii.gz`` and ``covariates.csv``.
    """
    dest = _resolve_dest(dest)
    sentinel = dest / ".complete"
    if sentinel.exists():
        return dest

    manifest = yaml.safe_load(_MANIFEST.read_text())

    if download is None:
        download = _prompt_download(manifest)

    if download:
        _download_zenodo(dest, manifest)
    else:
        raw = Path(raw_dir) if raw_dir is not None else (dest / "raw")
        if not raw.exists():
            raise FileNotFoundError(
                f"raw HCP data not found at {raw}. Place it there, or "
                f"call process(download=False, raw_dir=...) with an "
                f"explicit path."
            )
        _process_local(raw, dest, n_jobs=n_jobs, n_jobs_dti=n_jobs_dti)

    dest.mkdir(parents=True, exist_ok=True)
    sentinel.touch()
    return dest


def _prompt_download(manifest):
    zen = manifest.get("zenodo") or {}
    print()
    print("=" * 70)
    print("HCP-YA Open — choose data source")
    print("=" * 70)
    print()
    print("  [Y] download the pre-processed derivative from Zenodo")
    print(f"      ({zen.get('doi', '<doi>')}, ~440 MB; HCP DUA prompt follows)")
    print("  [n] run the pipeline locally on raw HCP data")
    print()
    answer = input("Download from Zenodo? [Y/n]: ").strip().lower()
    return answer in ("", "y", "yes")


def prompt_dua(dua, header, body, marker=None):
    """Confirm a Data Use Agreement interactively.

    Shared helper for any ``brain_pipe.<name>`` subpackage. Prints the
    DUA banner + URL and refuses to proceed unless the user types the
    exact phrase in ``dua["prompt"]``. If ``marker`` (a ``Path``) is
    given, the prompt is skipped when it already exists and the file
    is touched on successful consent so the user is asked once.
    """
    if marker is not None and marker.exists():
        return
    print()
    print("=" * 70)
    print(header)
    print("=" * 70)
    print()
    print(body)
    print()
    print(f"  DUA: {dua['url']}")
    print()
    response = input(f'Type "{dua["prompt"]}" to proceed: ')
    if response.strip() != dua["prompt"]:
        raise SystemExit("Cancelled: data use terms not confirmed.")
    if marker is not None:
        marker.touch()


def _md5(path, blocksize=65536):
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(blocksize), b""):
            h.update(chunk)
    return h.hexdigest()


def _progress(block_num, block_size, total_size):
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100, downloaded * 100 / total_size)
        mb_done = downloaded / 1024 ** 2
        mb_total = total_size / 1024 ** 2
        print(
            f"\r  downloading: {mb_done:.0f}/{mb_total:.0f} MB ({pct:.0f}%)",
            end="",
            flush=True,
        )


def _download_zenodo(dest, manifest):
    prompt_dua(
        manifest["dua"],
        header="HCP-YA OPEN ACCESS DATA USE TERMS",
        body=(
            "This dataset is derived from the Human Connectome Project (HCP)\n"
            "Young Adult Open Access release. You must agree to the WU-Minn\n"
            "HCP Consortium Open Access Data Use Terms before proceeding."
        ),
    )
    zen = manifest["zenodo"]

    print(f"\n  destination: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "archive.zip"
        print(f'  source: {zen["url"]}')
        urllib.request.urlretrieve(zen["url"], zip_path, reporthook=_progress)
        print()

        expected_md5 = zen.get("md5")
        if expected_md5:
            actual = _md5(zip_path)
            if actual != expected_md5:
                raise RuntimeError(
                    f"md5 mismatch: got {actual}, expected {expected_md5}"
                )

        print("  extracting...")
        with zipfile.ZipFile(zip_path) as zf:
            extract_dir = Path(tmp) / "extract"
            zf.extractall(extract_dir)
            top = list(extract_dir.iterdir())
            src = top[0] if len(top) == 1 and top[0].is_dir() else extract_dir

            # Move each entry from `src` into `dest`, replacing same-name
            # entries but preserving unrelated siblings (e.g. ``raw/``,
            # which holds HCP raw downloads and is co-located with the
            # processed derivative under the default cache).
            dest.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                target = dest / item.name
                if target.exists():
                    if target.is_dir() and not target.is_symlink():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                shutil.move(str(item), str(target))

    print(f"  done: {dest}")


def _process_local(raw_dir, dest, n_jobs=1, n_jobs_dti=None):
    """Run the four pipeline stages on raw HCP data at ``raw_dir``."""
    if n_jobs_dti is None:
        n_jobs_dti = min(n_jobs, 4)
    # Pin ITK to 1 thread per worker so ``n_jobs`` joblib processes
    # don't over-subscribe the CPU (each ANTs SyN otherwise grabs many
    # ITK threads by default). The fixed ANTS_RANDOM_SEED + single
    # ITK thread + the explicit random_seed arg in reg.py make SyN
    # reproducible run-to-run.
    os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = "1"
    os.environ["ANTS_RANDOM_SEED"] = "1"

    # imported lazily so a loader-only install can still `from
    # brain_pipe.hcp_ya_open import process` without dipy / antspyx
    try:
        from dipy.reconst.dti import fractional_anisotropy, mean_diffusivity
    except ImportError as e:
        raise ImportError(
            "Reprocessing requires the pipeline extra; install with:\n"
            "    pip install 'brain_pipe[hcp_ya_open-pipeline]'\n"
            "into a fresh venv."
        ) from e

    from joblib import Parallel, delayed

    from brain_pipe._dwi_pipeline import dti, reg, zip_check
    from brain_pipe.hcp_ya_open.pipeline import covariates

    dest.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] zip_check on {raw_dir}")
    zip_check.check_and_unzip(raw_dir, delete=False, skip_existing=True)

    print(f"[2/4] DTI fitting (FA + MD) — n_jobs_dti={n_jobs_dti}")
    dti_fnc_dict = {"fa": fractional_anisotropy, "md": mean_diffusivity}
    files = list(raw_dir.glob("**/data.nii.gz"))
    Parallel(n_jobs=n_jobs_dti, verbose=10)(
        delayed(dti.process_dti)(f, dti_fnc_dict) for f in files
    )

    print(f"[3/4] registration to FA template — n_jobs={n_jobs}")
    sbj_dict = reg.collect_subject_files(
        raw_dir, r"[\d]{6}", ["fa", "md", "nodif_brain_mask"]
    )
    reg.register_and_warp(sbj_dict, dest, register_on="fa", n_jobs=n_jobs)

    print("[4/4] covariates.csv from ConnectomeDB Subjects export")
    covariates.produce_covariates(raw_dir, dest, sbj_ids=sbj_dict.keys())
