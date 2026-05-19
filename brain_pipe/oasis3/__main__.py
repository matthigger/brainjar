"""Command-line interface for the OASIS-3 pipeline.

Cross-platform — runs on any OS with a Python interpreter::

    python -m brain_pipe.oasis3 prepare ~/Downloads/OASIS3_data_files.zip
    python -m brain_pipe.oasis3 fetch
    python -m brain_pipe.oasis3 process
    python -m brain_pipe.oasis3 all ~/Downloads/OASIS3_data_files.zip

Use ``--dest PATH`` on any subcommand to override the default cache
location (``platformdirs.user_data_dir('brain_pipe')/oasis3``).
"""

import argparse
import sys

from brain_pipe.oasis3 import fetch, prepare, process


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m brain_pipe.oasis3",
        description="Build the OASIS-3 A/T/N + DTI cohort derivative.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prepare = sub.add_parser(
        "prepare",
        help="Extract metadata bundle, build cohort + covariates "
             "(no creds, ~seconds)",
    )
    p_prepare.add_argument(
        "bundle",
        help="Path to OASIS3_data_files.zip (downloaded from NITRC-IR's "
             "OASIS3 -> 0AS_data_files -> Bulk Action Download)",
    )
    p_prepare.add_argument("--dest", help="Cache dir override")

    p_fetch = sub.add_parser(
        "fetch",
        help="Download cohort imaging (prompts NITRC-IR creds, ~10-20 min)",
    )
    p_fetch.add_argument("--dest", help="Cache dir override")
    p_fetch.add_argument(
        "--user",
        help="NITRC-IR username (prompted if omitted; password is "
             "always prompted, never saved)",
    )

    p_process = sub.add_parser(
        "process",
        help="DTI fit + MNI registration + final covariates "
             "(~hours of compute)",
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
    p_all.add_argument("bundle", help="Path to OASIS3_data_files.zip")
    p_all.add_argument("--dest", help="Cache dir override")
    p_all.add_argument(
        "--user", help="NITRC-IR username (prompted if omitted)",
    )
    p_all.add_argument(
        "--n-jobs", type=int, default=1, help="Parallel workers",
    )

    args = parser.parse_args(argv)

    if args.cmd == "prepare":
        prepare(bundle=args.bundle, dest=args.dest)
    elif args.cmd == "fetch":
        fetch(dest=args.dest, nitrc_user=args.user)
    elif args.cmd in ("process", "all"):
        sys.stderr.write(
            "error: process/all are not yet wired to the new "
            "bundle-driven prepare/fetch flow. The compute stages "
            "(DTI + MNI registration + final covariates) are being "
            "rewritten next. For now, use `prepare` and `fetch`.\n"
        )
        sys.exit(2)
    else:
        parser.error(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
