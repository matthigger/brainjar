"""Command-line interface for the HCP-YA Restricted pipeline.

Cross-platform — runs on any OS with a Python interpreter::

    python -m brain_pipe.hcp_ya_restricted --raw-dir /path/to/restricted/csv/dir

Use ``--dest PATH`` to override the default cache location
(``platformdirs.user_data_dir('brain_pipe')/hcp_ya_restricted``).

There is no Zenodo path: the Restricted-access export (exact age,
family structure, handedness, drug screens, ...) is governed by the
WU-Minn HCP Restricted Data Use Terms and cannot be redistributed.
Supply your own ``RESTRICTED_*.csv`` export from ConnectomeDB; see
the package README for how to obtain it.
"""

import argparse

from brain_pipe.hcp_ya_restricted import process


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m brain_pipe.hcp_ya_restricted",
        description=(
            "Build the HCP-YA Restricted processed derivative: filters "
            "the hcp_ya_open imaging subjects to those covered by the "
            "user-supplied RESTRICTED_*.csv export from ConnectomeDB, "
            "and writes restricted covariates alongside. Prompts for the "
            "WU-Minn HCP Restricted Data Use Terms on first run."
        ),
    )
    parser.add_argument(
        "--raw-dir",
        help="Directory holding the RESTRICTED_*.csv export from "
             "ConnectomeDB. Defaults to <dest>/raw/.",
    )
    parser.add_argument("--dest", help="Cache dir override")

    args = parser.parse_args(argv)

    process(
        download=False,
        raw_dir=args.raw_dir,
        dest=args.dest,
    )


if __name__ == "__main__":
    main()
