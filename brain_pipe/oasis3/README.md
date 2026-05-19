# brain_pipe.oasis3 — STUB (cohort definition locked, pipeline in progress)

Aging / Alzheimer's cohort from the WashU OASIS-3 release. Four per-subject
3D image features — `amyloid_suvr`, `tau_suvr`, `fa`, `md` — plus
demographics and clinical scores, restricted to a tightly time-matched
A/T/N subset.

- Source: <https://sites.wustl.edu/oasisbrains/home/oasis-3/>
- Data dictionary: [OASIS-3 Imaging Methods & Data Dictionary v2.3, July 2022](https://sites.wustl.edu/oasisbrains/files/2024/04/OASIS-3_Imaging_Data_Dictionary_v2.3-a93c947a586e7367.pdf)
- DUA: OASIS Data Use Agreement (signed via NITRC-IR account)
- Hosting: NITRC-IR / XNAT — <https://nitrc.org/ir>
- Download tooling: <https://github.com/NrgXnat/oasis-scripts> (cloned at runtime)

## Use

**Prereq** (one-time): get a NITRC-IR account at
<https://www.nitrc.org/ir/>. Account signup enforces the OASIS Data
Use Agreement, so the pipeline doesn't prompt for it again.

The pipeline runs in three stages — `prepare` → `fetch` → `process`:

```python
from brain_pipe.oasis3 import prepare, fetch, process, get_df_image, get_df_xfeat, LABELS

prepare()    # ~seconds. Downloads the ~67 MB metadata bundle from
             # NITRC-IR, builds cohort_sessions.csv + covariates.csv.
fetch()      # ~30 min, ~5 GB. Downloads T1w + DWI + PUP SUVR for
             # the 68 cohort subjects.
process()    # DTI fit + MNI152 registration. Produces the four 3D
             # NIfTIs per subject + covariates.csv.

df_image = get_df_image()  # cols: amyloid_suvr, tau_suvr, fa, md
df_xfeat = get_df_xfeat()  # cols: age, sex, cdr, mmse, dx, centiloid
LABELS['amyloid_suvr']     # 'Amyloid SUVR (AV45)'
```

Each network stage prompts once for NITRC-IR credentials (password
never stored). Username can be passed via ``prepare(nitrc_user=...)`` /
``fetch(nitrc_user=...)`` to skip that prompt.

**Offline / pre-downloaded bundle.** If you already have
``OASIS3_data_files.zip`` on disk, pass its path to skip the bundle
download:

```python
prepare(bundle='/path/to/OASIS3_data_files.zip')
```

(To get the zip manually: NITRC-IR → OASIS3 → 0AS_data_files →
OASIS3_data_files → Bulk Action → Download.)

**Idempotent.** The bundle zip is cached at
``<dest>/raw/OASIS3_data_files.zip``; re-running ``prepare()`` reuses
it (delete the file to force a re-download). ``fetch()`` skips any
subject already present on disk, so interrupted runs resume cleanly.

Pipeline extras are required to reprocess (loader-only install gives
you `get_df_image` / `get_df_xfeat` against an existing derivative):

```bash
pip install "brain_pipe[oasis3-pipeline]"   # in a dedicated venv
```

Pipeline extras are required to reprocess (loader-only install gives
you `get_df_image` / `get_df_xfeat` against an existing derivative):

```bash
pip install "brain_pipe[oasis3-pipeline]"   # in a dedicated venv
```

Cache: `platformdirs.user_data_dir('brain_pipe') / oasis3` by default.
Override per-call (`process(dest=...)`) or globally
(``BRAIN_PIPE_OASIS3_PATH``).

## Cohort

OASIS-3 ships ~1,400 subjects across 2,842 MR sessions and 2,157 PET
sessions; tau (AV1451) is a separate sub-project (`OASIS3_AV1451`) with
449 baseline tau sessions. Downloading the whole release is ~3–7 TB and
no analysis uses all of it. This pipeline restricts to a **biologically
time-matched A/T/N subset**:

**Inclusion criteria:**

1. **AV45 amyloid PUP** exists (we pick AV45 over PIB to match ADNI's
   primary amyloid tracer — direct cross-cohort transfer becomes
   possible, no cross-tracer harmonization needed).
2. **AV1451 baseline tau PUP** exists (project `OASIS3_AV1451` only; we
   skip `OASIS3_AV1451L`, which is longitudinal follow-up scans on a
   subset of the same subjects).
3. **DWI MR session** exists.
4. **Worst pairwise temporal gap ≤ 60 days** between the chosen AV45,
   AV1451, and DWI sessions: `max(|AV45−AV1451|, |DWI−AV1451|, |AV45−DWI|) ≤ 60d`.

Why ≤60 days: the per-subject worst-gap distribution is sharply bimodal
— a tight mode within ~1 year (subjects whose A/T/N imaging was
clustered in one visit) and a wide mode 2–4 years later (subjects whose
AV1451 was a late follow-up). 60 days is a defensible "same imaging
visit" cutoff that excludes the late mode entirely.

**Result: ~68 subjects.** Modest but defensible — every subject's
amyloid, tau, and diffusion measurements represent the same biological
state within ~2 months.

The full filter logic lives in `pipeline/cohort.py`; the cohort
session-list CSV is regenerated from the OASIS-3 bundle CSVs each
time ``prepare()`` runs, not committed.

## Why we picked AV45 over PIB

OASIS-3 has both ¹¹C-PIB (~717 subjects with PUP) and ¹⁸F-AV45 (~572
subjects with PUP) amyloid scans. Voxelwise SUVR is comparable across
subjects only **within tracer** — PIB and AV45 have different binding
affinities and dynamic ranges. Centiloid harmonizes them at a global
level but not at the voxel level.

Picking one tracer eliminates the cross-tracer voxelwise problem
outright. **AV45 wins because:**

1. **Era-matched with AV1451**: both ¹⁸F, both came online ~2014–2015
   at WashU. Subjects who got AV45 are far more likely to *also* have
   AV1451 tau scans temporally close to their amyloid scan. PIB
   sessions skew earlier and predate AV1451, often by years.
2. **ADNI interoperability**: ADNI's primary amyloid tracer is AV45.
   Models trained on OASIS-3 AV45 transfer directly to ADNI without
   tracer harmonization.

Cost: smaller N than PIB. Worth it.

Consequence: there is **no** `amyloid_tracer` column in `xfeat` — the
cohort is single-tracer by construction.

## Image features (`get_df_image`)

Per-subject 3D NIfTIs, all warped to **MNI152** so voxel `[x,y,z]` means
the same anatomical location across every subject:

| column          | source                                                       |
|-----------------|--------------------------------------------------------------|
| `amyloid_suvr`  | PUP `*_SUVR_*.nii` (AV45)  → MNI via per-subject T1→MNI       |
| `tau_suvr`      | PUP `*_SUVR_*.nii` (AV1451)→ MNI via per-subject T1→MNI       |
| `fa`            | DIPY tensor fit on DWI → MNI via b0→T1→MNI composed warp     |
| `md`            | DIPY tensor fit on DWI → MNI via b0→T1→MNI composed warp     |

Registration choice rationale: MNI152 is the field default for
multimodal aging/AD studies — standard atlases (Braak, Desikan-Killiany)
are in MNI, ADNI ships in MNI (we picked AV45 specifically for ADNI
interoperability), and a single T1→MNI nonlinear warp per subject
serves all four modalities. The diffusion-only `brain_pipe.hcp_ya_open`
uses a study-specific FA template for different reasons (no atlas
dependency, single modality, healthy young cohort) — we don't follow
that pattern here.

PUP (PET Unified Pipeline; Su et al., NeuroImage 2013) is the WashU
pipeline used in every OASIS-3 paper — its 3D SUVR outputs are
peer-reviewed off-the-shelf. FA/MD are computed locally from raw DWI
via the same DIPY tensor fit used in `brain_pipe.hcp_ya_open`.

## Tabular features (`get_df_xfeat`)

| column       | description                                          |
|--------------|------------------------------------------------------|
| `age`        | age at the tau session (years)                       |
| `sex`        | M / F                                                |
| `cdr`        | Clinical Dementia Rating at the matched visit        |
| `mmse`       | Mini-Mental State Examination at the matched visit   |
| `dx`         | clinical diagnosis label at the matched visit        |
| `centiloid`  | global amyloid burden (from PUP)                     |

No FreeSurfer ROI volumes or cortical thickness — those would be
per-region scalar tables that overlap with the 3D image features.
No `amyloid_tracer` — single tracer by construction.

## NITRC-IR credentials

`prepare()` and `fetch()` each prompt once for username + password
(password via `getpass`, never stored). Pass `nitrc_user='...'` to
either function to skip the username prompt — username is identity,
not a secret.

## Pipeline

Three entry points run sequentially:

1. **`prepare()`** → `pipeline/bundle.py` + `pipeline/cohort.py` —
   auto-fetches `OASIS3_data_files.zip` from NITRC-IR (or accepts a
   pre-downloaded path), extracts the six CSVs the pipeline reads,
   applies the cohort inclusion filter, and writes
   `cohort_sessions.csv` + `covariates.csv` to `dest`.
2. **`fetch()`** → `pipeline/fetch_imaging.py` + `pipeline/xnat.py` —
   for each cohort subject, downloads T1w + DWI scans, the AV45 PUP
   SUVR volume, and the AV1451 PUP SUVR volume via the XNAT REST API.
   Pure Python, single password prompt, resumable.
3. **`process()`** → `pipeline/dti.py` + `pipeline/reg.py` —
   - **`dti.py`**: DIPY `TensorModel` per subject → `fa.nii.gz`,
     `md.nii.gz`. Same code as `hcp_ya_open.pipeline.dti`.
   - **`reg.py`**: per subject, rigid b0↔T1w (ANTs) and SyN T1w→MNI152
     (ANTs). Compose the two transforms to bring FA/MD from DWI native
     into MNI. Apply the T1→MNI warp directly to the AV45 and AV1451
     PUP SUVR NIfTIs (they're already in T1 space from PUP). Outputs:
     `<sbj>_fa.nii.gz`, `<sbj>_md.nii.gz`, `<sbj>_amyloid_suvr.nii.gz`,
     `<sbj>_tau_suvr.nii.gz` — all in MNI152 on the same grid, plus
     `mni_template.nii.gz` and `group_mask.nii.gz` (intersection of
     warped brain masks).

Raw downloads can be deleted after `process()` produces derivatives;
processed footprint per subject is ~80–100 MB → ~7 GB for the full
cohort.

## Storage strategy

- Raw download: ~70 MB/subject × 68 ≈ 5 GB. Driven mostly by
  T1w + DWI scans (~3 GB total across the cohort); PUP SUVR files are
  fetched via filename-filtered downloader (~30 MB/session × 136 ≈ 4 GB)
  rather than the full PUP dirs (which would be ~2.7 GB each → ~370 GB).
- Processed derivatives: ~80 MB/subject × 68 ≈ 5–6 GB
- Default cache: `platformdirs.user_data_dir('brain_pipe') / oasis3`
- Override per call (`process(dest=...)`) or globally
  (`BRAIN_PIPE_OASIS3_PATH`)

## No Zenodo redistribution

OASIS-3 raw and PUP-derived data are subject to the OASIS DUA; we
cannot redistribute. `process()` requires `raw_dir` pointing at your
own NITRC-IR-authenticated download.

## Status

- 2026-05-18: cohort definition locked (AV45 ∩ AV1451-baseline ∩ DWI,
  ≤60d worst pairwise gap, ~68 subjects). Pipeline code in progress.
