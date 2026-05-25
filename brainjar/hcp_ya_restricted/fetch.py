"""Build the HCP-YA Restricted processed cache: hcp_ya_open imaging
subjects filtered to those present in the user-supplied RESTRICTED_*.csv,
with the restricted covariates written alongside.
"""

from pathlib import Path

import pandas as pd
import yaml

from brainjar import hcp_ya_open
from brainjar.hcp_ya_open.fetch import prompt_dua, resolve_dest

_PKG_DIR = Path(__file__).resolve().parent
_MANIFEST = _PKG_DIR / "manifest.yaml"


def _resolve_dest(dest=None):
    return resolve_dest("hcp_ya_restricted", dest)


def process(download=None, raw_dir=None, dest=None):
    """Ensure the HCP-YA Restricted processed derivative exists; return its path.

    Args:
        download: must be ``None`` or ``False``. The restricted dataset
            has no Zenodo deposit (not redistributable); ``True`` raises.
            Kept in the signature for cross-dataset API consistency.
        raw_dir: directory holding the ``RESTRICTED_*.csv`` export from
            ConnectomeDB. Defaults to ``<dest>/raw/``.
        dest: cache location for the processed output. Defaults to
            ``$BRAINJAR_HCP_YA_RESTRICTED_PATH`` if set, else
            ``platformdirs.user_data_dir('brainjar')/hcp_ya_restricted``.

    Returns:
        ``pathlib.Path`` to a directory containing ``covariates_restricted.csv``.
        Imaging stays in the ``hcp_ya_open`` cache; ``get_df_image()``
        reads from there and reindexes to the restricted subjects.
    """
    if download is True:
        raise NotImplementedError(
            "HCP-YA Restricted has no Zenodo deposit (not redistributable). "
            "Use process(download=False, raw_dir=...) and supply the "
            "RESTRICTED_*.csv export from ConnectomeDB."
        )

    dest = _resolve_dest(dest)
    sentinel = dest / ".complete"
    if sentinel.exists():
        return dest

    # 1. ensure hcp_ya_open is processed; we layer onto its subject set.
    open_dest = hcp_ya_open.process()

    # 2. DUA confirmation (cached in .dua_agreed so we don't ask twice).
    manifest = yaml.safe_load(_MANIFEST.read_text())
    dest.mkdir(parents=True, exist_ok=True)
    prompt_dua(
        manifest["dua"],
        header="HCP-YA RESTRICTED DATA USE TERMS",
        body=(
            "HCP-YA Restricted-access data (exact age, family structure,\n"
            "handedness, drug screens, ...) is governed by a separate, more\n"
            "restrictive DUA than the Open Access release. You must agree to\n"
            "the WU-Minn HCP Restricted Data Use Terms before proceeding."
        ),
        marker=dest / ".dua_agreed",
    )

    # 3. locate the restricted CSV in raw_dir.
    raw = Path(raw_dir) if raw_dir is not None else (dest / "raw")
    if not raw.exists():
        raise FileNotFoundError(
            f"raw_dir not found: {raw}. Place the RESTRICTED_*.csv export "
            f"there, or pass process(raw_dir=...) explicitly."
        )
    csvs = sorted(raw.glob("RESTRICTED_*.csv"))
    if not csvs:
        raise FileNotFoundError(
            f"No RESTRICTED_*.csv in {raw}. From ConnectomeDB's "
            f"WU-Minn HCP project page: enable restricted data on your "
            f"account, open the Subjects tab, click 'Export CSV', and "
            f"save the file (named RESTRICTED_<user>_<timestamp>.csv) "
            f"into {raw}."
        )
    csv = csvs[-1]  # newest by lexical sort (timestamp suffix)

    # 4. read, normalize subject_id, restrict to hcp_ya_open subjects.
    df = pd.read_csv(csv, dtype={"Subject": str})
    if "Subject" not in df.columns:
        raise ValueError(
            f"{csv.name} has no 'Subject' column; is this the right export?"
        )
    df = df.rename(columns={"Subject": "subject_id"})

    open_subjects = set(hcp_ya_open.get_df_image(dest=open_dest).index)
    df = df[df["subject_id"].isin(open_subjects)].sort_values("subject_id")

    if df.empty:
        raise RuntimeError(
            f"No overlap between {csv.name} and hcp_ya_open subjects at "
            f"{open_dest}. Check that the restricted export covers the "
            f"100 unrelated subjects in the open derivative."
        )

    # 5. write filtered restricted covariates + sentinel.
    df.to_csv(dest / "covariates_restricted.csv", index=False)
    sentinel.touch()
    return dest
