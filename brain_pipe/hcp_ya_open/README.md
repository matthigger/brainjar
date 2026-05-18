# brain_pipe.hcp_ya_open

100 unrelated subjects from the **Human Connectome Project – Young Adult,
Open Access** release. Per-subject FA and MD volumes from a DIPY tensor
fit, SyN-registered (CC metric) to a mean-FA template, with a group
intersection brain mask.

- Source: <https://db.humanconnectome.org>
- DUA: <https://www.humanconnectome.org/study/hcp-young-adult/document/wu-minn-hcp-consortium-open-access-data-use-terms>
- Deposited derivative: [Zenodo 10.5281/zenodo.17306498](https://zenodo.org/records/17306498)

## Use

```python
from brain_pipe.hcp_ya_open import process, get_df_image, get_df_xfeat, LABELS

process()                              # interactive: download from Zenodo
                                       # (default), or run pipeline locally
df_image = get_df_image()              # columns: fa, md (absolute Paths)
df_xfeat = get_df_xfeat()              # ~580 columns: age, sex, behaviorals,
                                       # FreeSurfer volumes, etc.

LABELS["fa"]                           # 'Fractional Anisotropy'
LABELS["age"]                          # 'Age (years, 5-yr bucket)'
```

Non-interactive flavors:

```python
process(download=True)                              # always Zenodo
process(download=False)                             # always pipeline,
                                                    # uses <dest>/raw/
process(download=False, raw_dir='/path/to/hcp/raw') # explicit raw_dir
```

Cache: `platformdirs.user_data_dir('brain_pipe') / hcp_ya_open/` by
default. Override per-call (`process(dest=...)`) or globally
(`BRAIN_PIPE_HCP_YA_OPEN_PATH`). A `.complete` sentinel inside the
cache marks a finished run.

## Reproducing the pipeline locally

You'll need raw HCP-YA data downloaded under your own ConnectomeDB Open
Access agreement. The expected layout is the standard HCP per-subject
tree containing `data.nii.gz`, `bvals`, `bvecs`, and `nodif_brain_mask.nii.gz`.

By default the pipeline looks for raw data at `<dest>/raw/` (i.e.
`~/.local/share/brain_pipe/hcp_ya_open/raw/` unless overridden). Place
the subject folders and the `HCP_YA_subjects_*.csv` export there, or
pass `raw_dir=...` explicitly.

Install the pipeline extra into a fresh venv:

```bash
python -m venv .venv && source .venv/bin/activate
pip install "brain_pipe[hcp_ya_open-pipeline]"
```

Then:

```python
from brain_pipe.hcp_ya_open import process
process(download=False)                              # use default raw_dir
process(download=False, raw_dir="/path/to/hcp/raw")  # or be explicit
```

That runs four stages (see `pipeline/`):

1. **`zip_check.py`** — md5-verify and extract any HCP zip archives.
   By default `delete=False` (zips kept on disk after extraction); pass
   `delete=True` to reclaim the space, since the extracted folder is
   the same size as the zip.
2. **`dti.py`** — DIPY `TensorModel` per subject; saves `fa.nii.gz` and
   `md.nii.gz` alongside each subject's `data.nii.gz`.
3. **`reg.py`** — average-FA template, SyN-register each subject to it
   (CC metric, 4-level pyramid), warp MD with the same transform, warp
   each subject's brain mask, intersect for a group mask, multiply
   warped FA/MD by the group mask.
4. **`covariates.py`** — read the ConnectomeDB Subjects CSV from
   `raw_dir` and emit `covariates.csv` restricted to subjects that
   completed stage 3.

## Covariates

`get_df_xfeat()` reads `covariates.csv` from the processed directory.
The pipeline produces it from the **HCP-YA ConnectomeDB Subjects export**:
on the ConnectomeDB project page (*WU-Minn HCP Data – 1200 Subjects*),
go to the Subjects tab, click **Export CSV**, and select **all
non-restricted columns**. Save the file (named
`HCP_YA_subjects_<timestamp>.csv`) into the same `raw_dir` you pass to
`get_path(raw_dir=...)`.

Stage 4 of the pipeline (`pipeline/covariates.py`) reads that CSV,
renames `Subject`→`subject_id`, `Gender`→`sex`, `Age`→`age` (5-year
bucket strings like `"26-30"`), keeps every other column verbatim, and
restricts to the subjects that successfully completed the DTI stage.
The output has ~580 columns: demographics, NIH Toolbox cognition,
NEO-FFI, FreeSurfer volumes/thickness/area, task-fMRI behaviorals,
etc.

## Provenance

`manifest.yaml` records the source URL, DUA, Zenodo DOI, and the env
intended to be used by the pipeline. Two fields are not yet populated:

- `zenodo.md5` — the md5 of the deposit archive (for download
  verification).
- `pipeline.python` and `pipeline/requirements.lock` — the exact
  Python and `pip freeze` output that produced the deposited
  derivative.

Populate them on the next clean reprocess run:

```bash
pip freeze > brain_pipe/hcp_ya_open/pipeline/requirements.lock
python -c 'import sys; print(".".join(map(str, sys.version_info[:3])))'
```

Then update `manifest.yaml: pipeline.python` and the
`[hcp_ya_open-pipeline]` extra in the top-level `pyproject.toml` to
match.
