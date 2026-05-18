# brain_pipe

Reproducible processing pipelines and uniform loaders for brain imaging
datasets.

## Data access

`brain_pipe` ships code, not data. For most datasets you must obtain
the raw data yourself under the dataset's own Data Use Agreement;
redistribution is not permitted and `process()` cannot download
anything — you point at your own copy:

```python
process(download=False, raw_dir='/data/camcan/raw')   # pipeline runs locally
```

The exceptions, where the processed derivative is openly redistributable
and `process(download=True)` will fetch it from Zenodo:

- **HCP-YA Open** (HCP Consortium Open Access Data Use Terms)

## Install

```bash
pip install brain_pipe
```

That gives you every dataset *loader*. To re-run a pipeline, install
its extra into a dedicated venv:

```bash
python -m venv .venv && source .venv/bin/activate
pip install "brain_pipe[camcan-pipeline]"
```

Pipeline extras install the exact pins recorded in each dataset's
`manifest.yaml`. Different datasets may have conflicting pins — install
one at a time.

## Use

```python
from brain_pipe.camcan import process, get_df_image, get_df_xfeat, LABELS

process()                      # ensures the processed derivative exists
                               # (prompts: download a deposited derivative
                               # if one exists, or run the pipeline locally)
df_image = get_df_image()      # index: subject_id; cols: fa, md, mask -> absolute Paths
df_xfeat = get_df_xfeat()      # index: subject_id; cols: age, sex, dx, ...

LABELS['age']                  # 'Age (years)'
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

- [`brain_pipe.hcp_ya_open`](brain_pipe/hcp_ya_open/README.md)
- [`brain_pipe.oasis3`](brain_pipe/oasis3/README.md)
- [`brain_pipe.camcan`](brain_pipe/camcan/README.md)
- [`brain_pipe.hcp_ya_restricted`](brain_pipe/hcp_ya_restricted/README.md)
- [`brain_pipe.hcp_aging`](brain_pipe/hcp_aging/README.md)
- [`brain_pipe.hcp_development`](brain_pipe/hcp_development/README.md)

## Cache

Default: `platformdirs.user_data_dir('brain_pipe') / <dataset>`.
Override per call (`get_path(dest=...)`) or globally
(`BRAIN_PIPE_<DATASET>_PATH`). A `.complete` sentinel marks a finished
run.
