"""Command-line interface for the OASIS-3 pipeline.

Cross-platform — runs on any OS with a Python interpreter::

    python -m brain_pipe.oasis3 prepare
    python -m brain_pipe.oasis3 fetch
    python -m brain_pipe.oasis3 process
    python -m brain_pipe.oasis3 all

Use ``--dest PATH`` on any subcommand to override the default cache
location (``platformdirs.user_data_dir('brain_pipe')/oasis3``). Pass
``--bundle PATH`` to ``prepare`` / ``all`` to skip the bundle download
(for offline use).
"""

import argparse

from brain_pipe.oasis3 import fetch, prepare, process


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m brain_pipe.oasis3",
        description="Build the OASIS-3 A/T/N + DTI cohort derivative.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prepare = sub.add_parser(
        "prepare",
        help="Auto-fetch metadata bundle, build cohort + covariates",
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
        help="Download cohort imaging (prompts NITRC-IR creds, ~30 min)",
    )
    p_fetch.add_argument("--dest", help="Cache dir override")
    p_fetch.add_argument(
        "--user",
        help="NITRC-IR username (prompted if omitted; password is "
             "always prompted, never saved)",
    )

    p_process = sub.add_parser(
        "process",
        help="DTI fit + MNI registration (~hours of compute)",
    )
    p_process.add_argument("--dest", help="Cache dir override")
    p_process.add_argument(
        "--n-jobs", type=int, default=1,
        help="Parallel workers for SyN registration (default: 1)",
    )

    p_all = sub.add_parser(
        "all",
        help="Run prepare -> fetch -> process in sequence",
    )
    p_all.add_argument("--bundle", help="Path to a pre-downloaded bundle zip")
    p_all.add_argument("--dest", help="Cache dir override")
    p_all.add_argument(
        "--user", help="NITRC-IR username (prompted if omitted)",
    )
    p_all.add_argument(
        "--n-jobs", type=int, default=1, help="Parallel workers",
    )

    args = parser.parse_args(argv)

    if args.cmd == "prepare":
        prepare(bundle=args.bundle, dest=args.dest, nitrc_user=args.user)
    elif args.cmd == "fetch":
        fetch(dest=args.dest, nitrc_user=args.user)
    elif args.cmd == "process":
        process(dest=args.dest, n_jobs=args.n_jobs)
    elif args.cmd == "all":
        prepare(bundle=args.bundle, dest=args.dest, nitrc_user=args.user)
        fetch(dest=args.dest, nitrc_user=args.user)
        process(dest=args.dest, n_jobs=args.n_jobs)
    else:
        parser.error(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
