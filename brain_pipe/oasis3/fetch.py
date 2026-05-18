"""Build the OASIS-3 processed derivative under the local cache.

Unlike ``brain_pipe.hcp_ya_open``, there is no Zenodo download path —
OASIS-3 raw and derived data is restricted by the OASIS DUA and cannot
be redistributed. ``process(raw_dir=...)`` requires the caller to point
at their own NITRC-IR-authenticated copy (the bundled `0AS_data_files`
metadata CSVs, at minimum; downstream stages fetch the actual scan
files via the vendored oasis-scripts).
"""

import os
from pathlib import Path

import yaml

from brain_pipe.hcp_ya_open.fetch import resolve_dest

_PKG_DIR = Path(__file__).resolve().parent
_MANIFEST = _PKG_DIR / "manifest.yaml"


def _resolve_dest(dest=None):
    return resolve_dest("oasis3", dest)


def download_raw(raw_dir=None, dest=None, nitrc_user=None):
    """Run only stages 1-3: build the cohort manifest, fetch
    ``oasis-scripts`` at the pinned SHA, and download every cohort
    subject's raw scans + PUP outputs into ``raw_dir``.

    Use this when you want OASIS-3 cohort data on disk for your own
    downstream analysis. Skips the DTI fit, MNI registration, and
    covariate assembly stages of :func:`process`.

    Calling :func:`process` afterwards is idempotent: the download
    stage early-outs once data is present, so the second call just
    picks up at stages 4-6.

    Args:
        raw_dir: directory with the OASIS-3 metadata CSVs
            (``mr.csv``, ``pup.csv``, ``sbj.csv``, ``1451/pet.csv``,
            ``1451/pup.csv``); downloads land here under ``scans/``
            and ``pup/``. Defaults to ``<dest>/raw/``.
        dest: where ``cohort_sessions.csv`` and the cloned
            ``oasis-scripts`` repo are cached. Defaults to
            ``$BRAIN_PIPE_OASIS3_PATH`` or
            ``platformdirs.user_data_dir('brain_pipe')/oasis3``.
        nitrc_user: NITRC-IR username; see :func:`process` docstring
            for the resolution order. Password is prompted once and
            piped to each downloader via stdin.

    Returns:
        ``Path`` to ``raw_dir`` (where the downloaded files live).
    """
    dest = _resolve_dest(dest)
    manifest = yaml.safe_load(_MANIFEST.read_text())

    raw = Path(raw_dir) if raw_dir is not None else (dest / "raw")
    if not raw.exists():
        raise FileNotFoundError(
            f"OASIS-3 raw_dir not found at {raw}. Place the metadata "
            f"CSVs (mr.csv, pup.csv, sbj.csv, 1451/pet.csv, "
            f"1451/pup.csv) downloaded from the NITRC-IR "
            f"`0AS_data_files` pseudo-subject there, or pass "
            f"raw_dir=... explicitly. See README for the navigation."
        )

    from brain_pipe.hcp_ya_open.fetch import prompt_dua
    from brain_pipe.oasis3.pipeline import (
        fetch_scripts,
        install_scripts,
        manifest as manifest_stage,
    )

    prompt_dua(
        manifest["dua"],
        header="OASIS DATA USE AGREEMENT",
        body=(
            "OASIS-3 imaging data is restricted by the OASIS Data Use\n"
            "Agreement. Subjects, derived data, and processed outputs\n"
            "may not be redistributed."
        ),
        marker=dest / ".dua_confirmed",
    )

    dest.mkdir(parents=True, exist_ok=True)

    print("[1/3] cohort selection from metadata CSVs")
    cohort_csv = manifest_stage.build_cohort(raw, dest)

    print("[2/3] ensure oasis-scripts at pinned SHA")
    scripts_dir = install_scripts.ensure_scripts(dest, manifest)

    print(f"[3/3] fetching scans + PUP via oasis-scripts -> {raw}")
    fetch_scripts.download_cohort(
        cohort_csv, raw, scripts_dir=scripts_dir, nitrc_user=nitrc_user,
    )
    return raw


def process(raw_dir=None, dest=None, n_jobs=1, n_jobs_dti=None,
            nitrc_user=None):
    """Build the OASIS-3 processed derivative; return its cache path.

    Args:
        raw_dir: directory containing the OASIS-3 metadata CSVs
            (``mr.csv``, ``pup.csv``, ``sbj.csv``, ``1451/pet.csv``,
            ``1451/pup.csv``) downloaded from NITRC-IR's
            ``0AS_data_files`` pseudo-subject. Defaults to
            ``<dest>/raw/``. The pipeline also writes downloaded scan
            files under ``<raw_dir>/scans/`` and ``<raw_dir>/pup/``.
        dest: cache location for the processed output. Defaults to
            ``$BRAIN_PIPE_OASIS3_PATH`` if set, else
            ``platformdirs.user_data_dir('brain_pipe')/oasis3``.
        n_jobs: parallel workers for SyN registration (stage 4).
        n_jobs_dti: parallel workers for DTI fitting (stage 3); defaults
            to ``min(n_jobs, 4)`` since each holds the DWI volume in RAM.
        nitrc_user: NITRC-IR username for the download scripts. If
            ``None``, resolution falls through ``$NITRC_IR_USER`` ->
            ``~/.config/brain_pipe/oasis3.yaml`` -> interactive prompt
            (with an offer to save). The password is always prompted
            interactively by the upstream scripts; never stored.

    Returns:
        ``pathlib.Path`` to a directory of
        ``<sbj>_{amyloid_suvr,tau_suvr,fa,md}.nii.gz`` (all in MNI152),
        plus ``mni_template.nii.gz``, ``group_mask.nii.gz``,
        ``cohort_sessions.csv``, and ``covariates.csv``.
    """
    dest = _resolve_dest(dest)
    sentinel = dest / ".complete"
    if sentinel.exists():
        return dest

    manifest = yaml.safe_load(_MANIFEST.read_text())

    raw = Path(raw_dir) if raw_dir is not None else (dest / "raw")
    if not raw.exists():
        raise FileNotFoundError(
            f"OASIS-3 raw_dir not found at {raw}. Place the metadata "
            f"CSVs (mr.csv, pup.csv, sbj.csv, 1451/pet.csv, "
            f"1451/pup.csv) downloaded from the NITRC-IR "
            f"`0AS_data_files` pseudo-subject there, or pass "
            f"raw_dir=... explicitly. See README for the navigation."
        )

    _process_local(
        raw, dest, manifest,
        n_jobs=n_jobs, n_jobs_dti=n_jobs_dti,
        nitrc_user=nitrc_user,
    )

    dest.mkdir(parents=True, exist_ok=True)
    sentinel.touch()
    return dest


def _process_local(raw_dir, dest, manifest, n_jobs, n_jobs_dti, nitrc_user):
    """Run the five OASIS-3 pipeline stages."""
    if n_jobs_dti is None:
        n_jobs_dti = min(n_jobs, 4)
    os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = "1"

    # Imports are lazy so a loader-only install can still do
    # `from brain_pipe.oasis3 import process` without antspyx / dipy.
    try:
        import dipy  # noqa: F401
        import ants  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "Reprocessing requires the pipeline extra; install with:\n"
            "    pip install 'brain_pipe[oasis3-pipeline]'\n"
            "into a fresh venv."
        ) from e

    from brain_pipe.hcp_ya_open.fetch import prompt_dua
    from brain_pipe.oasis3.pipeline import (
        covariates,
        dti,
        fetch_scripts,
        install_scripts,
        manifest as manifest_stage,
        reg,
    )

    prompt_dua(
        manifest["dua"],
        header="OASIS DATA USE AGREEMENT",
        body=(
            "OASIS-3 imaging data is restricted by the OASIS Data Use\n"
            "Agreement. Subjects, derived data, and processed outputs\n"
            "may not be redistributed."
        ),
        marker=dest / ".dua_confirmed",
    )

    dest.mkdir(parents=True, exist_ok=True)

    print("[1/6] cohort selection from metadata CSVs")
    cohort_csv = manifest_stage.build_cohort(raw_dir, dest)

    print("[2/6] ensure oasis-scripts at pinned SHA")
    scripts_dir = install_scripts.ensure_scripts(dest, manifest)

    print(f"[3/6] fetching scans + PUP via oasis-scripts -> {raw_dir}")
    fetch_scripts.download_cohort(
        cohort_csv, raw_dir, scripts_dir=scripts_dir, nitrc_user=nitrc_user,
    )

    print(f"[4/6] DTI fitting (FA + MD) — n_jobs_dti={n_jobs_dti}")
    dti.process_cohort(cohort_csv, raw_dir, n_jobs=n_jobs_dti)

    print(f"[5/6] registration to MNI152 — n_jobs={n_jobs}")
    reg.register_cohort(cohort_csv, raw_dir, dest, manifest=manifest,
                        n_jobs=n_jobs)

    print("[6/6] covariates.csv")
    covariates.produce_covariates(raw_dir, dest, cohort_csv)
