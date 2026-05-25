# brainjar

Reproducible processing pipelines and uniform loaders for brain imaging
datasets.

## Data access

`brainjar` ships code, not data. For most datasets you must obtain
the raw data yourself under the dataset's own Data Use Agreement;
redistribution is not permitted and `process()` cannot download
anything — you point at your own copy:

```python
process(download=False, raw_dir='/data/hcp_ya_open/raw')   # pipeline runs locally
```

The exceptions, where the processed derivative is openly redistributable
and `process(download=True)` will fetch it from Zenodo:

- **HCP-YA Open** (HCP Consortium Open Access Data Use Terms)

## Install

```bash
pip install brainjar
```

That gives you every dataset *loader*. To re-run a pipeline, install
its extra into a dedicated venv:

```bash
python -m venv .venv && source .venv/bin/activate
pip install "brainjar[hcp_ya_open-pipeline]"
```

Pipeline extras install the exact pins recorded in each dataset's
`manifest.yaml`. Different datasets may have conflicting pins — install
one at a time.

## Use

```python
from brainjar.hcp_ya_open import process, get_df_image, get_df_xfeat, LABELS

process()                      # ensures the processed derivative exists
                               # (prompts: download the deposited derivative
                               # from Zenodo, or run the pipeline locally)
df_image = get_df_image()      # index: subject_id; cols: fa, md -> absolute Paths
df_xfeat = get_df_xfeat()      # index: subject_id; cols: age, sex,
                               # Release, ... (~580 columns from ConnectomeDB)

LABELS['age']                  # 'Age (years, 5-yr bucket)'
LABELS['fa']                   # 'Fractional Anisotropy'
```

`process()` is the entry point that gets data into place. Pass
``download=True`` / ``False`` to skip the prompt, or ``raw_dir=...``
to point at raw data when running locally.

Every dataset module exposes the same names: `process`, `get_df_image`,
`get_df_xfeat`, `LABELS`.

## Datasets

Access procedure, DUA, provenance, and pipeline extra for each are in
the subpackage README:

- [`brainjar.hcp_ya_open`](brainjar/hcp_ya_open/README.md)
- [`brainjar.oasis3`](brainjar/oasis3/README.md)
- [`brainjar.camcan`](brainjar/camcan/README.md)
- [`brainjar.hcp_ya_restricted`](brainjar/hcp_ya_restricted/README.md)
- [`brainjar.hcp_aging`](brainjar/hcp_aging/README.md)
- [`brainjar.hcp_development`](brainjar/hcp_development/README.md)

## Cache

Default: `platformdirs.user_data_dir('brainjar') / <dataset>`.
Override per call (`process(dest=...)`) or globally
(`BRAINJAR_<DATASET>_PATH`). A `.complete` sentinel marks a finished
run.
