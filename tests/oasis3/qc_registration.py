"""OASIS-3 cohort registration QC — thin wrapper.

Defaults ``dest`` to the OASIS-3 cache and looks for
``mni_template.nii.gz`` alongside the cohort for the MI-to-template
disambiguation. The shared algorithm lives in
:mod:`brainjar._dwi_pipeline.qc_registration`.

Usage::

    python tests/oasis3/qc_registration.py                          # uses default oasis3 dest
    python tests/oasis3/qc_registration.py <dir>                    # any dir with the naming pattern
    python tests/oasis3/qc_registration.py <dir> --z-threshold 3    # stricter outlier cutoff
"""

from __future__ import annotations

import argparse
from pathlib import Path

from brainjar._dwi_pipeline.qc_registration import run


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "dest", nargs="?", default=None,
        help="directory of <sbj>_<mod>.nii.gz files. Defaults to "
             "the brainjar.oasis3 default cache.",
    )
    p.add_argument(
        "--mask", default=None,
        help="path to the brain mask NIfTI (default: <dest>/group_mask.nii.gz)",
    )
    p.add_argument(
        "--template", default=None,
        help="path to the template NIfTI for the MI disambiguation "
             "metric (default: <dest>/mni_template.nii.gz; skip if missing)",
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
        from brainjar.oasis3.fetch import _resolve_dest
        args.dest = _resolve_dest()

    # OASIS-3 default: register-to-MNI152, so mni_template.nii.gz is
    # an *independent* reference and the MI metric carries real signal.
    if args.template is None:
        candidate = Path(args.dest) / "mni_template.nii.gz"
        if candidate.exists():
            args.template = candidate

    run(
        args.dest, mask_path=args.mask, template_path=args.template,
        output_dir=args.output_dir, z_threshold=args.z_threshold,
    )


if __name__ == "__main__":
    main()
