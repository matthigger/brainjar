"""Selectively extract the OASIS-3 data-files bundle.

The bundle (``OASIS3_data_files.zip``, ~67 MB) ships ~40 files: per-scan
JSON metadata CSVs, all UDS clinical forms (A1–D2), psychometrics,
centiloid, BRAAK tauopathy, dataset descriptions, data dictionaries
(PDF/XLSX), and the DUA itself. This pipeline only needs ~7 of them.
Rather than unpack the whole tree into the cache, we extract only what
we read so the cache stays tidy.

Mapping of logical name -> bundle filename:

    mr_json        OASIS3_MR_json.csv                 (per-scan MR metadata)
    pup            OASIS3_PUP.csv                     (PIB + AV45 PUP, with tracer col)
    av1451_pup     OASIS3_AV1451_PUP.csv              (baseline tau PUP)
    demographics   OASIS3_demographics.csv            (sbj-level age, sex, etc.)
    udsb4          OASIS3_UDSb4_cdr.csv               (CDR + MMSE + dx by visit)
    centiloid      OASIS3_amyloid_centiloid.csv       (centiloid per amyloid scan)
"""

import zipfile
from pathlib import Path

# Bundle file basenames the pipeline reads. (Bundle paths inside the
# zip are nested like ``OASIS3_data_files/scans/<scan_id>-<descriptor>/
# resources/csv/files/<basename>``; we ignore the path and match on
# the basename only.)
BUNDLE_FILES = {
    "mr_json":      "OASIS3_MR_json.csv",
    "pup":          "OASIS3_PUP.csv",
    "av1451_pup":   "OASIS3_AV1451_PUP.csv",
    "demographics": "OASIS3_demographics.csv",
    "udsb4":        "OASIS3_UDSb4_cdr.csv",
    "centiloid":    "OASIS3_amyloid_centiloid.csv",
}


def extract(bundle_zip, dest):
    """Extract the needed CSVs from ``bundle_zip`` into ``dest``.

    Args:
        bundle_zip: path to the OASIS3_data_files.zip downloaded from
            NITRC-IR.
        dest: directory under which extracted CSVs land at their
            bundle-relative paths. ``dest/OASIS3_data_files/scans/.../
            <basename>.csv`` — flattening would lose useful provenance
            (the scan-id-and-descriptor parent dir documents which
            assessment the CSV came from).

    Returns:
        dict ``{logical_name: Path}`` for each CSV the pipeline reads.
        Raises ``FileNotFoundError`` for any missing basename.

    Idempotent: re-running over an already-extracted dest is a no-op.
    """
    bundle_zip = Path(bundle_zip)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    if not bundle_zip.exists():
        raise FileNotFoundError(
            f"bundle zip not found: {bundle_zip}. Download "
            f"OASIS3_data_files.zip from NITRC-IR's OASIS3 project "
            f"-> 0AS_data_files -> OASIS3_data_files -> Bulk Action Download "
            f"and pass its path to prepare(bundle=...)."
        )

    wanted = set(BUNDLE_FILES.values())
    extracted = {}

    with zipfile.ZipFile(bundle_zip) as zf:
        for info in zf.infolist():
            basename = Path(info.filename).name
            if basename not in wanted:
                continue
            out = dest / info.filename
            if not out.exists():
                zf.extract(info, dest)
            extracted[basename] = out

    paths = {}
    for logical, basename in BUNDLE_FILES.items():
        if basename not in extracted:
            raise FileNotFoundError(
                f"{basename} not found in {bundle_zip}. Bundle layout "
                f"may have changed; re-download from NITRC-IR or update "
                f"BUNDLE_FILES in this module."
            )
        paths[logical] = extracted[basename]
    return paths
