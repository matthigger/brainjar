"""HCP-YA Open cohort registration QC — thin wrapper.

Defaults ``dest`` to the HCP-YA Open cache. Does *not* default to the
shipped ``fa_template.nii.gz`` for the MI-to-template metric: that
template is the cohort mean, so MI to it is degenerate with cohort
similarity and adds no disambiguation. Pass ``--template <path>`` with
an *external* reference (e.g. an FMRIB58 or MNI152 NIfTI on the same
voxel grid) to opt in.

The shared algorithm lives in
:mod:`brainjar._dwi_pipeline.qc_registration`.

Usage::

    python tests/hcp_ya_open/qc_registration.py                          # uses default hcp_ya_open dest
    python tests/hcp_ya_open/qc_registration.py <dir>                    # any dir with the naming pattern
    python tests/hcp_ya_open/qc_registration.py <dir> --z-threshold 3    # stricter outlier cutoff
"""

from __future__ import annotations

import argparse

from brainjar._dwi_pipeline.qc_registration import run


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "dest", nargs="?", default=None,
        help="directory of <sbj>_<mod>.nii.gz files. Defaults to "
             "the brainjar.hcp_ya_open default cache.",
    )
    p.add_argument(
        "--mask", default=None,
        help="path to the brain mask NIfTI (default: <dest>/group_mask.nii.gz)",
    )
    p.add_argument(
        "--template", default=None,
        help="path to an *external* reference template NIfTI for the "
             "MI disambiguation metric. Skipped by default: the shipped "
             "fa_template.nii.gz is the cohort mean and would be "
             "degenerate with cohort similarity.",
    )
    p.add_argument(
        "--output-dir", default=None,
        help="where to write outputs (default: <dest>/qc/)",
    )
    p.add_argument(
        "--z-threshold", type=float, default=2.0,
        help="|z| above this flags a subject as an outlier (default: 2.0)",
    )
    args = p.parse_args(argv)

    if args.dest is None:
        from brainjar.hcp_ya_open.fetch import _resolve_dest
        args.dest = _resolve_dest()

    run(
        args.dest, mask_path=args.mask, template_path=args.template,
        output_dir=args.output_dir, z_threshold=args.z_threshold,
    )


if __name__ == "__main__":
    main()
