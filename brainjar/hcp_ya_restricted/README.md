# brainjar.hcp_ya_restricted

Same FA/MD imaging as [`brainjar.hcp_ya_open`](../hcp_ya_open/README.md),
layered with the **HCP-YA Restricted Access** covariates (exact age,
family structure, handedness, drug screens, ...). The restricted
covariate CSV is not redistributable, so this package has no Zenodo
download path — you export the CSV from ConnectomeDB and `process()`
builds the cache locally.

- Source: <https://db.humanconnectome.org>
- DUA: WU-Minn HCP Restricted Data Use Terms (separate from Open Access).
  See `manifest.yaml` for the URL.

## Use

### CLI

```bash
# Default cache, look for RESTRICTED_*.csv in <dest>/raw/
python -m brainjar.hcp_ya_restricted

# Explicit raw_dir
python -m brainjar.hcp_ya_restricted --raw-dir /path/to/restricted/csv/dir

python -m brainjar.hcp_ya_restricted --help   # full option reference
```

### Python API

```python
from brainjar.hcp_ya_restricted import process, get_df_image, get_df_xfeat, LABELS

process()                              # ensures hcp_ya_open is processed
                                       # and filters the RESTRICTED CSV
                                       # to that subject set
df_image = get_df_image()              # columns: fa, md (Paths in the
                                       # hcp_ya_open cache), reindexed
                                       # to restricted subjects
df_xfeat = get_df_xfeat()              # restricted covariates verbatim
                                       # (Subject -> subject_id)

LABELS["Age_in_Yrs"]                   # 'Age (years)'
LABELS["Handedness"]                   # 'Edinburgh Handedness (-100..100)'
```

`process()` will (1) call `hcp_ya_open.process()` first — which is
interactive and may download the open derivative from Zenodo — then
(2) prompt you to accept the HCP Restricted DUA, then (3) read the
`RESTRICTED_*.csv` you placed in `raw_dir` and write a filtered
`covariates_restricted.csv` into the cache.

The DUA agreement is cached in `<dest>/.dua_agreed` so you are only
prompted once.

## Getting the restricted CSV

The restricted columns require an upgraded ConnectomeDB account.

1. Apply for restricted access via the ConnectomeDB account page; you
   sign the Restricted Data Use Terms and your PI countersigns.
2. Once approved, on the ConnectomeDB project page (*WU-Minn HCP Data –
   1200 Subjects*), enable **"Use Restricted Data"** at the top of the
   Subjects tab.
3. With restricted data on, click **Export CSV** and select **all
   columns** (the export will include the restricted-only columns
   alongside the non-restricted ones).
4. Save the file — it will be named
   `RESTRICTED_<your-username>_<timestamp>.csv` — into the `raw_dir`
   you pass to `process(raw_dir=...)`, or the default
   `<dest>/raw/`.

## Cache

`platformdirs.user_data_dir('brainjar') / hcp_ya_restricted/` by
default. Override per-call (`process(dest=...)`) or globally
(`BRAINJAR_HCP_YA_RESTRICTED_PATH`). A `.complete` sentinel inside
the cache marks a finished run; `.dua_agreed` marks consent.

The cache only contains `covariates_restricted.csv` and the two
sentinels — the FA/MD volumes themselves live in the `hcp_ya_open`
cache and are not duplicated.

## What process() does

1. **Ensure hcp_ya_open is processed.** Calls
   `brainjar.hcp_ya_open.process()`. If you haven't run it, this is
   interactive (download from Zenodo, or process raw HCP locally).
2. **DUA confirmation.** Prompts for the Restricted DUA on first run;
   caches consent in `<dest>/.dua_agreed`.
3. **Find the export.** Looks for `RESTRICTED_*.csv` in `raw_dir`
   (newest by name wins).
4. **Filter and write.** Renames `Subject` → `subject_id`, restricts
   to the subjects that completed the hcp_ya_open pipeline, writes
   `covariates_restricted.csv`, drops `.complete`.

No DTI or registration is re-run; this package is purely a covariate
overlay on the open-access imaging.
