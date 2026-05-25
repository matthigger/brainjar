# brainjar.hcp_ya_open

100 unrelated subjects from the **Human Connectome Project – Young Adult,
Open Access** release. Per-subject FA and MD volumes from a DIPY tensor
fit, SyN-registered (CC metric) to a mean-FA template, with a group
intersection brain mask.

- Source: <https://db.humanconnectome.org>
- DUA: <https://www.humanconnectome.org/study/hcp-young-adult/document/wu-minn-hcp-consortium-open-access-data-use-terms>
- Deposited derivative: [Zenodo 10.5281/zenodo.20275749](https://zenodo.org/records/20275749) (v2; seeded, bit-deterministic. v1 at [17306498](https://zenodo.org/records/17306498) was unseeded.)

## Use

### CLI

```bash
# Interactive: prompts to download from Zenodo (default) or run locally
python -m brainjar.hcp_ya_open

# Force Zenodo download (DUA prompt still follows)
python -m brainjar.hcp_ya_open --download

# Run pipeline locally on raw HCP data
python -m brainjar.hcp_ya_open --no-download \
    --raw-dir /path/to/hcp/raw --n-jobs 8

python -m brainjar.hcp_ya_open --help   # full option reference
```

### Python API

```python
from brainjar.hcp_ya_open import process, get_df_image, get_df_xfeat, LABELS

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

Cache: `platformdirs.user_data_dir('brainjar') / hcp_ya_open/` by
default. Override per-call (`process(dest=...)`) or globally
(`BRAINJAR_HCP_YA_OPEN_PATH`). A `.complete` sentinel inside the
cache marks a finished run.

## Reproducing the pipeline locally

You'll need raw HCP-YA data downloaded under your own ConnectomeDB Open
Access agreement. The expected layout is the standard HCP per-subject
tree containing `data.nii.gz`, `bvals`, `bvecs`, and `nodif_brain_mask.nii.gz`.

By default the pipeline looks for raw data at `<dest>/raw/` (i.e.
`~/.local/share/brainjar/hcp_ya_open/raw/` unless overridden). Place
the subject folders and the `HCP_YA_subjects_*.csv` export there, or
pass `raw_dir=...` explicitly.

Install the pipeline extra into a fresh venv:

```bash
python -m venv .venv && source .venv/bin/activate
pip install "brainjar[hcp_ya_open-pipeline]"
```

Then:

```python
from brainjar.hcp_ya_open import process
process(download=False)                              # use default raw_dir
process(download=False, raw_dir="/path/to/hcp/raw")  # or be explicit
```

That runs four stages:

1. **`brainjar/_dwi_pipeline/zip_check.py`** — md5-verify and extract
   any HCP zip archives. By default `delete=False` (zips kept on disk
   after extraction); pass `delete=True` to reclaim space.
2. **`brainjar/_dwi_pipeline/dti.py`** — DIPY `TensorModel` per
   subject; saves `fa.nii.gz` and `md.nii.gz` alongside each subject's
   `data.nii.gz`.
3. **`brainjar/_dwi_pipeline/reg.py`** — average-FA template,
   SyN-register each subject to it (CC metric, 4-level pyramid,
   `random_seed=1`), warp MD with the same transform, warp each
   subject's brain mask, intersect for a group mask, multiply warped
   FA/MD by the group mask.
4. **`brainjar/hcp_ya_open/pipeline/covariates.py`** — read the
   ConnectomeDB Subjects CSV from `raw_dir` and emit `covariates.csv`
   restricted to subjects that completed stage 3.

## Covariates

`get_df_xfeat()` reads `covariates.csv` from the processed directory.
The pipeline produces it from the **HCP-YA ConnectomeDB Subjects export**:
on the ConnectomeDB project page (*WU-Minn HCP Data – 1200 Subjects*),
go to the Subjects tab, click **Export CSV**, and select **all
non-restricted columns**. Save the file (named
`HCP_YA_subjects_<timestamp>.csv`) into the same `raw_dir` you pass to
`process(raw_dir=...)`.

Stage 4 of the pipeline (`pipeline/covariates.py`) reads that CSV,
renames `Subject`→`subject_id`, `Gender`→`sex`, `Age`→`age` (5-year
bucket strings like `"26-30"`), keeps every other column verbatim, and
restricts to the subjects that successfully completed the DTI stage.
The output has ~580 columns: demographics, NIH Toolbox cognition,
NEO-FFI, FreeSurfer volumes/thickness/area, task-fMRI behaviorals,
etc.

## Provenance

`manifest.yaml` records the source URL, DUA, Zenodo deposit, and the
exact env used to produce the deposited derivative:

- `pipeline.python: "3.12.3"`
- `pipeline.lockfile: pipeline/requirements.lock` (pip freeze of the
  validated venv)
- `pipeline.env.ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS: "1"` and
  `pipeline.env.ANTS_RANDOM_SEED: "1"` (enforced in
  `fetch.py:_process_local`)
- `pipeline.syn_random_seed: 1` (passed to `ants.registration`)

Two independent end-to-end runs of the seeded pipeline produced
**203/203 md5-identical** output files. To re-verify after any change,
see [Testing](#testing) below.

`zenodo.md5` is still TODO — record the md5 of the deposit archive
once the v2 deposit is uploaded.

## Testing

Three regression tests live in `tests/test_repro_hcp_ya_open.py`. They
are excluded from default pytest discovery (see `tests/conftest.py`)
because they're slow and require raw data. Invoke explicitly:

```bash
# Run all three (DTI + SyN + Zenodo)
pytest tests/test_repro_hcp_ya_open.py -v

# Or individually:
pytest tests/test_repro_hcp_ya_open.py::test_dti_single_subject_deterministic
pytest tests/test_repro_hcp_ya_open.py::test_syn_bit_identical_to_reference
pytest tests/test_repro_hcp_ya_open.py::test_zenodo_download_md5_matches_reference
```

| Test | Wall time | What it checks |
|------|-----------|----------------|
| `test_dti_single_subject_deterministic` | ~3 min | Re-runs DIPY TensorModel on one subject in a tmp dir, md5-compares fa/md against the cached values. |
| `test_syn_bit_identical_to_reference` | ~14 min (scales with `os.cpu_count()`) | Full seeded SyN re-run into a tmp dir, md5-compares all 203 outputs against `tests/reference/hcp_ya_open_v2_md5.txt`. |
| `test_zenodo_download_md5_matches_reference` | seconds–minutes | Calls `process(download=True)`. If the default cache is populated, returns instantly and md5-compares. If empty, prompts you to type the HCP DUA agreement and downloads to the default cache (~3 min). If you decline the DUA, the test errors. |

To force a true round-trip test of the Zenodo download (rather than
testing whatever's already in the default cache), clear the deposit
files first:

```bash
cd ~/.local/share/brainjar/hcp_ya_open
rm -f *.nii.gz covariates.csv .complete    # preserves raw/ subdir
pytest tests/test_repro_hcp_ya_open.py::test_zenodo_download_md5_matches_reference
```

…or override the cache path with `BRAINJAR_HCP_YA_OPEN_PATH=/tmp/hcp_test`.
