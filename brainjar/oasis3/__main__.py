"""Command-line interface for the OASIS-3 pipeline.

Cross-platform — runs on any OS with a Python interpreter::

    python -m brainjar.oasis3 prepare
    python -m brainjar.oasis3 fetch
    python -m brainjar.oasis3 process
    python -m brainjar.oasis3 all

Use ``--dest PATH`` on any subcommand to override the default cache
location (``platformdirs.user_data_dir('brainjar')/oasis3``). Pass
``--bundle PATH`` to ``prepare`` / ``all`` to skip the bundle download
(for offline use). ``all`` prompts for the NITRC-IR password once and
reuses it across ``prepare`` and ``fetch``.
"""

import argparse
import getpass

from brainjar.oasis3 import fetch, prepare, process


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m brainjar.oasis3",
        description=(
            "Build the OASIS-3 CDR-prediction cohort derivative. "
            "Inclusion: subject has a tensor-fittable DWI + a complete "
            "CDR (UDS B4) visit, paired within 365 days. Outputs three "
            "voxelwise NIfTIs per subject (T1, FA, MD) in MNI152 space "
            "plus a per-subject covariates row (CDR Sum-of-Boxes + 6 "
            "component scores, demographics, APOE)."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prepare = sub.add_parser(
        "prepare",
        help="Fetch metadata bundle, build cohort + covariates (~10 s)",
    )
    p_prepare.add_argument(
        "--bundle",
        help="Path to a pre-downloaded OASIS3_data_files.zip. If "
             "omitted, the bundle is fetched from NITRC-IR.",
    )
    p_prepare.add_argument("--dest", help="Cache dir override")
    p_prepare.add_argument(
        "--user",
        help="NITRC-IR username (prompted if omitted; ignored when "
             "--bundle is given)",
    )

    p_fetch = sub.add_parser(
        "fetch",
        help="Download cohort T1+DWI imaging (~3 hr, ~50 GB on disk)",
    )
    p_fetch.add_argument("--dest", help="Cache dir override")
    p_fetch.add_argument(
        "--user",
        help="NITRC-IR username (prompted if omitted; password is "
             "always prompted via getpass, never saved)",
    )

    p_process = sub.add_parser(
        "process",
        help="DTI fit + MNI registration (~2 hr on a 32-core box "
             "with --n-jobs 8)",
    )
    p_process.add_argument("--dest", help="Cache dir override")
    p_process.add_argument(
        "--n-jobs", type=int, default=1,
        help="Parallel workers for SyN registration (default: 1)",
    )

    p_all = sub.add_parser(
        "all",
        help="Run prepare -> fetch -> process in sequence; prompts for "
             "the NITRC-IR password once and reuses across stages",
    )
    p_all.add_argument("--bundle", help="Path to a pre-downloaded bundle zip")
    p_all.add_argument("--dest", help="Cache dir override")
    p_all.add_argument(
        "--user", help="NITRC-IR username (prompted if omitted)",
    )
    p_all.add_argument(
        "--n-jobs", type=int, default=1, help="Parallel workers for process",
    )

    args = parser.parse_args(argv)

    if args.cmd == "prepare":
        prepare(bundle=args.bundle, dest=args.dest, nitrc_user=args.user)
    elif args.cmd == "fetch":
        fetch(dest=args.dest, nitrc_user=args.user)
    elif args.cmd == "process":
        process(dest=args.dest, n_jobs=args.n_jobs)
    elif args.cmd == "all":
        # Collect credentials once and pass through to prepare + fetch.
        # (fetch always needs them; prepare needs them unless --bundle
        # is provided, in which case it ignores the args).
        user = args.user
        if user is None:
            user = input("NITRC-IR username: ").strip()
            while not user:
                user = input("NITRC-IR username (required): ").strip()
        password = getpass.getpass(f"NITRC-IR password for {user}: ")
        prepare(bundle=args.bundle, dest=args.dest,
                nitrc_user=user, nitrc_password=password)
        fetch(dest=args.dest, nitrc_user=user, nitrc_password=password)
        process(dest=args.dest, n_jobs=args.n_jobs)
    else:
        parser.error(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
