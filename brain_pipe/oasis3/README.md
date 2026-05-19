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

**Prereqs** (one-time):

1. Sign the [OASIS DUA](https://www.oasis-brains.org) and get a
   NITRC-IR account.

2. Pull OASIS-3 metadata from NITRC-IR in **two passes**: one for
   per-session imaging listings (used to select the cohort), one for
   the clinical/cognitive data bundle (used to populate xfeat). NITRC-IR
   exposes these via different UI flows; we're working on consolidating
   but for now both passes are needed.

   ### Pass 1 — per-session imaging listings (XNAT search export)

   These are the simple session-listing CSVs the cohort-selection stage
   reads from the top of ``raw_dir``. Repeat once per project
   (OASIS3 and OASIS3_AV1451):

   1. Log into <https://www.nitrc.org/ir/>.
   2. **Projects** → **OASIS3**.
   3. From the **MR Sessions** tab, **Options** → **Edit Columns** →
      include `MR ID`, `Date`, `Subject`, `Age`, `Scanner`, `Scans`,
      `PUP Timecourses`, `Freesurfers`. Then **Options** →
      **Spreadsheet** → save as ``raw_dir/mr.csv``.
   4. Same drill from the **PET Sessions** tab → save as
      ``raw_dir/pet.csv``. (Columns: XNAT_PETSESSIONDATA ID, Subject,
      Date, Age, ...)
   5. Same drill for **PUP Timecourses** (Advanced Search → data type
      "PUP Timecourse" → Edit Columns to include
      `PUP_PUPTIMECOURSEDATA ID`, `Date`, `procType`, `model`,
      `tracer`, `FSId`, `MRId`, `mocoError`, `regError`) → save as
      ``raw_dir/pup.csv``.
   6. **Subjects** tab → Spreadsheet → save as ``raw_dir/sbj.csv``
      (columns: Subject, M/F, Hand, YOB, MR Sessions, PET Sessions,
      CT Sessions).
   7. Repeat steps 2–6 for project **OASIS3_AV1451**, saving the four
      CSVs into ``raw_dir/1451/`` (only PET, PUP, and Subjects there;
      no MR sessions are needed since AV1451 tau scans use the MR
      session that's already in OASIS3).

   Optional but consistent: ``raw_dir/ct.csv`` and
   ``raw_dir/freesurfer.csv`` (same drill from those tabs). The
   pipeline ignores them but they're useful reference.

   ### Pass 2 — clinical / cognitive bundle download

   All the clinical, cognitive, centiloid, and reference data lives in
   one bundle inside the `0AS_data_files` pseudo-subject:

   1. **Projects** → **OASIS3**.
   2. **Subjects** tab → sort by Subject ID ascending. The first row
      is `0AS_data_files` — click it.
   3. You'll see one experiment: an MR-session-styled entry called
      **`OASIS3_data_files`**. Click it.
   4. The "scans" list shows ~30 assessment bundles (UDS forms,
      cognitive assessments, JSON imaging metadata, data dictionaries,
      centiloid values, etc.).
   5. Check the box at the top of the list to **select all**, then
      **Bulk Action → Download**. You'll get
      `OASIS3_data_files.zip` (~67 MB).
   6. ``unzip OASIS3_data_files.zip -d <raw_dir>`` so the tree lands
      at ``<raw_dir>/OASIS3_data_files/scans/...``.

   `covariates.py` globs through that tree by filename to read the
   four files it actually needs:

   | xfeat field   | source (anywhere under `<raw_dir>/OASIS3_data_files/`) |
   |---------------|--------------------------------------------------------|
   | `cdr`         | `OASIS3_UDSb4_cdr.csv`                                 |
   | `mmse`        | `OASIS3_UDSc1_cognitive_assessments.csv`               |
   | `dx`          | `OASIS3_UDSd1_diagnoses.csv`                           |
   | `centiloid`   | `OASIS3_amyloid_centiloid.csv`                         |

   The bundle's other contents (per-scan JSON CSVs, demographic
   extras, 14 other UDS forms, data dictionary PDFs) are downloaded
   but unused by the current pipeline. Don't bother deselecting —
   the click cost outweighs the disk cost (~67 MB total).

   You'll also see an **`OASIS_cohort_files.zip`** offered alongside
   the data-files zip. It contains a single CSV listing subjects whose
   CDR stayed at 0 across all visits (a curated cognitively-normal
   subset). This pipeline doesn't use it (we build the cohort by
   imaging modality availability, not by clinical status). Safe to
   skip — or grab it if you ever want a confirmed-healthy overlay.

   ### Resulting `raw_dir` layout

   After both passes:

   ```
   <raw_dir>/
   ├── mr.csv          # pass 1: OASIS3 MR session listing
   ├── pup.csv         # pass 1: OASIS3 PUP timecourses (PIB + AV45)
   ├── pet.csv         # pass 1: OASIS3 PET session listing
   ├── sbj.csv         # pass 1: OASIS3 subject demographics
   ├── 1451/
   │   ├── pet.csv     # pass 1: OASIS3_AV1451 PET sessions
   │   ├── pup.csv     # pass 1: OASIS3_AV1451 PUP timecourses (tau)
   │   └── sbj.csv     # pass 1: OASIS3_AV1451 subjects
   └── OASIS3_data_files/  # pass 2: extracted clinical bundle
       └── scans/.../OASIS3_UDSb4_cdr.csv  (etc.)
   ```

**Just want the raw cohort data on disk?** (e.g. running your own
downstream analysis instead of the bundled pipeline):

```python
from brain_pipe.oasis3 import download_raw

# Runs cohort selection + downloads raw scans/PUP for the 68-subject
# A/T/N+DTI cohort. One password prompt; ~10-20 min, ~5 GB on disk.
download_raw(raw_dir='/path/to/your/oasis3_dir')
```

**Full processed derivative** (cohort + raw fetch + DTI + MNI registration
+ covariates):

```python
from brain_pipe.oasis3 import process, get_df_image, get_df_xfeat, LABELS

process(raw_dir='/path/to/your/oasis3_dir')   # six stages
df_image = get_df_image()                     # cols: amyloid_suvr, tau_suvr, fa, md
df_xfeat = get_df_xfeat()                     # cols: age, sex, cdr, mmse, dx, centiloid

LABELS['amyloid_suvr']  # 'Amyloid SUVR (AV45)'
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

The full filter logic lives in `pipeline/manifest.py`; the cohort
session-list CSV is regenerated from the OASIS-3 metadata at pipeline
run time, not committed.

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

## oasis-scripts — cloned at runtime, pinned to a SHA

The download tooling lives at <https://github.com/NrgXnat/oasis-scripts>
but has no tags, releases, **or a LICENSE file**. Without a license the
default is "all rights reserved," so we can't legally vendor the
scripts inside the `brain_pipe` wheel. Instead, on first pipeline run
we **clone the upstream repo at the pinned SHA** into the local cache:

```
<dest>/oasis-scripts/    # git clone @ pinned SHA, cached locally
```

The user fetches from the original source — we just automate the
fetch and pin the version. Subsequent pipeline runs reuse the local
clone and run offline.

Manifest records the pin:

```yaml
oasis_scripts:
  url:      https://github.com/NrgXnat/oasis-scripts
  commit:   f95ef430f9d2b194a8eccac032106b55f518ad50
  retrieved: 2026-05-18
```

To bump: update the `commit` in `manifest.yaml`, commit the change.
Next pipeline run re-checks out the new SHA. Worth opening an issue
upstream asking them to add a permissive license — once that lands we
can switch to true vendoring for an offline-from-first-run experience.

Requires `git` on the host at first pipeline run (universally
available).

### NITRC-IR username — resolution order

The download scripts always prompt for the **password** interactively
(never stored). The **username** is resolved in this order:

1. ``process(nitrc_user='...')`` explicit arg
2. ``$NITRC_IR_USER`` environment variable
3. ``~/.config/brain_pipe/oasis3.yaml`` (key: ``nitrc_ir_user``)
4. Interactive prompt — and we offer to save to (3) so subsequent runs
   skip the prompt

Username is identity, not a secret, and storing it on disk is no
different from your git email in ``~/.gitconfig``. The password is the
secret; that one stays interactive.

## Pipeline (planned)

`process(download=False, raw_dir=...)` runs five stages. There is **no**
`download=True` path — OASIS-3 is DUA-restricted and the pipeline
cannot fetch a redistributed derivative.

1. **`manifest.py`** — read OASIS-3 metadata CSVs from `raw_dir`
   (`mr.csv`, `pup.csv`, `1451/pet.csv`, `1451/pup.csv`, `sbj.csv`),
   apply the inclusion filter above, write `cohort_sessions.csv` to
   `dest`.
2. **`fetch_scripts.py`** — invoke vendored `download_oasis_scans.sh`
   (T1w + DWI per chosen MR session) and `download_oasis_pup.sh`
   (AV45 + AV1451 PUP SUVR volumes) for the 68 cohort subjects.
   Prompts for NITRC-IR password once. Chunked by subject to keep
   peak disk use manageable.
3. **`dti.py`** — DIPY `TensorModel` per subject → `fa.nii.gz`,
   `md.nii.gz`. Same code as `hcp_ya_open.pipeline.dti`.
4. **`reg.py`** — per subject: rigid b0↔T1w (ANTs) **and** SyN
   T1w→MNI152 (ANTs). Compose the two transforms to bring FA/MD from
   DWI native into MNI. Apply the T1→MNI warp directly to the AV45
   and AV1451 PUP SUVR NIfTIs (they're already in T1 space from PUP).
   Outputs: `<sbj>_fa.nii.gz`, `<sbj>_md.nii.gz`,
   `<sbj>_amyloid_suvr.nii.gz`, `<sbj>_tau_suvr.nii.gz` — all in MNI152
   on the same grid, plus `mni_template.nii.gz` and
   `group_mask.nii.gz` (intersection of warped brain masks).
5. **`covariates.py`** — assemble `xfeat` from demographics + clinical
   CSVs, restricted to subjects that completed stage 4.

Raw downloads can be deleted after stage 4 produces derivatives;
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
