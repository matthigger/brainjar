"""Stage 3: download the cohort's raw scans + PUP outputs via the
cloned NrgXnat/oasis-scripts.

Builds three one-column input CSVs from ``cohort_sessions.csv`` and
invokes the upstream bash scripts as subprocesses, inheriting stdin/
stdout so the user is prompted once per script for the NITRC-IR
password. Subjects whose target directory already exists under
``raw_dir`` are skipped — re-running ``process()`` after a partial
download resumes without re-fetching.

Output layout under ``raw_dir``:

    scans/<MR_ID>/anat?/<file>.nii.gz      # T1w
    scans/<MR_ID>/dwi?/<file>.{nii.gz,bval,bvec}
    pup/<PUP_ID>/<pup output files>        # AV45 + AV1451 SUVR NIfTIs
"""

import getpass
import os
import subprocess
from pathlib import Path

import pandas as pd
import yaml
from platformdirs import user_config_dir

SCAN_TYPES = "T1w,dwi"
TAU_PROJECT = "OASIS3_AV1451"

_CONFIG_PATH = Path(user_config_dir("brain_pipe")) / "oasis3.yaml"


def _load_config():
    if not _CONFIG_PATH.exists():
        return {}
    try:
        return yaml.safe_load(_CONFIG_PATH.read_text()) or {}
    except yaml.YAMLError:
        return {}


def _save_username(username):
    """Persist ``nitrc_ir_user`` to the config file (creating it if
    needed). Username is identity, not a secret — fine to keep on disk
    with default permissions. Never call this with a password.
    """
    cfg = _load_config()
    cfg["nitrc_ir_user"] = username
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(yaml.safe_dump(cfg, sort_keys=True))
    print(f"  saved username to {_CONFIG_PATH}")


def resolve_nitrc_user(arg_value=None):
    """Resolve the NITRC-IR username in priority order:

    1. explicit ``arg_value`` (passed to ``process(nitrc_user=...)``)
    2. ``NITRC_IR_USER`` env var
    3. ``~/.config/brain_pipe/oasis3.yaml`` ``nitrc_ir_user`` key
    4. interactive prompt (and offer to save to the config file)

    Returns the resolved username (never empty).
    """
    if arg_value:
        return arg_value
    if env := os.environ.get("NITRC_IR_USER"):
        return env
    if cfg_user := _load_config().get("nitrc_ir_user"):
        return cfg_user

    username = input("NITRC-IR username: ").strip()
    while not username:
        username = input("NITRC-IR username (required): ").strip()
    save = input(
        f"  save this username to {_CONFIG_PATH} so you don't get "
        f"asked again? [Y/n]: "
    ).strip().lower()
    if save in ("", "y", "yes"):
        _save_username(username)
    return username


def _write_id_csv(ids, path):
    """Write a one-column CSV of experiment IDs (Unix line endings, no
    header — what the upstream scripts expect)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="\n") as f:
        for i in ids:
            f.write(f"{i}\n")
    return path


def _existing_dirs(parent):
    """Set of immediate child dir names that already exist under ``parent``."""
    if not parent.exists():
        return set()
    return {p.name for p in parent.iterdir() if p.is_dir()}


def _filter_pending(ids, out_dir):
    """Drop IDs whose ``out_dir/<id>/`` directory already exists."""
    have = _existing_dirs(out_dir)
    return [i for i in ids if i not in have]


def _run_script(script, *args, password=None):
    """Invoke a bash script. If ``password`` is given, it's written to
    the child's stdin (followed by a newline) so the script's
    ``read -s -p ... PASSWORD`` consumes it without re-prompting. The
    password is not in argv, not in env, and not on disk — Python pipes
    it to stdin then closes the pipe.
    """
    cmd = ["bash", str(script), *args]
    print(f"  > {' '.join(cmd)}")
    if password is None:
        subprocess.run(cmd, check=True)
    else:
        subprocess.run(cmd, input=password + "\n", text=True, check=True)


def download_cohort(cohort_csv, raw_dir, scripts_dir, nitrc_user=None):
    """Download MR scans + PUP outputs for every subject in
    ``cohort_sessions.csv`` that isn't already on disk.

    Args:
        cohort_csv: ``cohort_sessions.csv`` path (output of
            :mod:`brain_pipe.oasis3.pipeline.manifest`).
        raw_dir: directory where raw downloads are written
            (``scans/`` and ``pup/`` subdirs created here).
        scripts_dir: local clone of ``oasis-scripts`` (output of
            :mod:`brain_pipe.oasis3.pipeline.install_scripts`).
        nitrc_user: NITRC-IR username. Prompted if ``None``.

    The scripts prompt for the password interactively. We invoke each
    script at most once (skipping if every ID is already present) so
    the user types their password at most three times total per run.
    """
    cohort_csv = Path(cohort_csv)
    raw_dir = Path(raw_dir)
    scripts_dir = Path(scripts_dir)

    nitrc_user = resolve_nitrc_user(nitrc_user)

    df = pd.read_csv(cohort_csv)

    scans_dir = raw_dir / "scans"
    pup_dir = raw_dir / "pup"

    # Decide up front what each script needs to fetch, so we can prompt
    # for the password just once and skip the prompt entirely if all
    # data is already on disk.
    mr_ids = sorted(set(df["av45_mr_id"]).union(df["dwi_mr_id"]))
    av45_ids = sorted(set(df["av45_pup_id"]))
    tau_ids = sorted(set(df["tau_pup_id"]))
    mr_pending = _filter_pending(mr_ids, scans_dir)
    av45_pending = _filter_pending(av45_ids, pup_dir)
    tau_pending = _filter_pending(tau_ids, pup_dir)

    if not (mr_pending or av45_pending or tau_pending):
        print("  all cohort sessions already on disk; nothing to fetch")
        return

    password = getpass.getpass(f"NITRC-IR password for {nitrc_user}: ")

    if mr_pending:
        ids_csv = raw_dir / "_input_mr.csv"
        _write_id_csv(mr_pending, ids_csv)
        print(f"[scans] downloading T1w+dwi for {len(mr_pending)} MR sessions")
        _run_script(
            scripts_dir / "download_scans" / "download_oasis_scans.sh",
            str(ids_csv), str(scans_dir), nitrc_user, SCAN_TYPES,
            password=password,
        )
    else:
        print(f"[scans] all {len(mr_ids)} MR sessions already on disk; skipping")

    if av45_pending:
        ids_csv = raw_dir / "_input_pup_av45.csv"
        _write_id_csv(av45_pending, ids_csv)
        print(f"[pup-av45] downloading {len(av45_pending)} AV45 PUP sessions")
        _run_script(
            scripts_dir / "download_pup" / "download_oasis_pup.sh",
            str(ids_csv), str(pup_dir), nitrc_user,
            password=password,
        )
    else:
        print(f"[pup-av45] all AV45 PUP sessions already on disk; skipping")

    if tau_pending:
        ids_csv = raw_dir / "_input_pup_tau.csv"
        _write_id_csv(tau_pending, ids_csv)
        print(f"[pup-tau] downloading {len(tau_pending)} AV1451 PUP sessions")
        _run_script(
            scripts_dir / "download_pup" / "download_oasis_pup.sh",
            str(ids_csv), str(pup_dir), nitrc_user, TAU_PROJECT,
            password=password,
        )
    else:
        print(f"[pup-tau] all AV1451 PUP sessions already on disk; skipping")
