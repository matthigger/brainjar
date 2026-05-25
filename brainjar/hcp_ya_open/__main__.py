"""Command-line interface for the HCP-YA Open pipeline.

Cross-platform — runs on any OS with a Python interpreter::

    python -m brainjar.hcp_ya_open                    # interactive: prompts Zenodo Y/N
    python -m brainjar.hcp_ya_open --download         # force Zenodo download (DUA prompt follows)
    python -m brainjar.hcp_ya_open --no-download \\
        --raw-dir /path/to/hcp/raw --n-jobs 8           # local pipeline on raw HCP data

Use ``--dest PATH`` to override the default cache location
(``platformdirs.user_data_dir('brainjar')/hcp_ya_open``).
"""

import argparse

from brainjar.hcp_ya_open import process


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m brainjar.hcp_ya_open",
        description=(
            "Build the HCP-YA Open processed derivative (100 unrelated "
            "young-adult subjects; FA + MD in a study-specific FA template). "
            "Default action: prompt whether to download the pre-processed "
            "Zenodo deposit (~440 MB, ~3 min) or run the pipeline locally "
            "on raw HCP data (~14 min SyN on a 32-core box)."
        ),
    )
    src = parser.add_mutually_exclusive_group()
    src.add_argument(
        "--download", dest="download", action="store_true", default=None,
        help="Download the pre-processed derivative from Zenodo (skips "
             "the interactive Y/N prompt; DUA confirmation is still "
             "required).",
    )
    src.add_argument(
        "--no-download", dest="download", action="store_false",
        help="Run the pipeline locally on raw HCP data; requires "
             "--raw-dir.",
    )

    parser.add_argument(
        "--raw-dir",
        help="When running the pipeline locally (--no-download), where "
             "the raw HCP data lives. Defaults to <dest>/raw/.",
    )
    parser.add_argument("--dest", help="Cache dir override")
    parser.add_argument(
        "--n-jobs", type=int, default=1,
        help="Parallel workers for SyN registration (stage 3). Each "
             "worker pins ITK to 1 thread to avoid oversubscription. "
             "(default: 1)",
    )
    parser.add_argument(
        "--n-jobs-dti", type=int, default=None,
        help="Parallel workers for DTI fitting (stage 2). DTI holds the "
             "full DWI volume in memory (~12-15 GB per HCP subject), so "
             "this is typically smaller than --n-jobs. Defaults to "
             "min(--n-jobs, 4).",
    )

    args = parser.parse_args(argv)

    process(
        download=args.download,
        raw_dir=args.raw_dir,
        dest=args.dest,
        n_jobs=args.n_jobs,
        n_jobs_dti=args.n_jobs_dti,
    )


if __name__ == "__main__":
    main()
