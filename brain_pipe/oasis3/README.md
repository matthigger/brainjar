# brain_pipe.oasis3

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
Use Agreement, so the pipeline doesn't prompt for it again. OASIS-3
raw and PUP-derived data are DUA-restricted and not redistributable —
`process()` requires you to point at your own NITRC-IR-authenticated
download.

The pipeline runs in three stages — `prepare` → `fetch` → `process`:

```python
from brain_pipe.oasis3 import prepare, fetch, process, get_df_image, get_df_xfeat, LABELS

prepare()    # ~seconds. Downloads the ~67 MB metadata bundle from
             # NITRC-IR, builds cohort_sessions.csv + covariates.csv.
fetch()      # ~90 min, ~21 GB. Downloads T1w + DWI scans plus the
             # SUVR triplets of both AV45 and AV1451 PUPs.
process()    # DTI fit + MNI152 registration. Produces the four 3D
             # NIfTIs per subject + covariates.csv. ~20 min on a
             # 32-core box (n_jobs=8); count on ~1-2 hours on a
             # 4-core laptop.

df_image = get_df_image()  # cols: amyloid_suvr, tau_suvr, fa, md
df_xfeat = get_df_xfeat()  # cols: age, sex, cdr, mmse, dx, centiloid
LABELS['amyloid_suvr']     # 'Amyloid SUVR (AV45)'
```

Pass `bundle='/path/to/OASIS3_data_files.zip'` to `prepare()` to skip
the metadata download (offline / pre-downloaded use).

Cache: `platformdirs.user_data_dir('brain_pipe') / oasis3` by default.
Override per-call (`process(dest=...)`) or globally
(`BRAIN_PIPE_OASIS3_PATH`).

## Cohort

OASIS-3 ships ~1,400 subjects across 2,842 MR sessions and 2,157 PET
sessions; AV1451 (tau) is a separate sub-project (`OASIS3_AV1451`) with
449 baseline tau sessions. Downloading the whole release is ~3–7 TB.
This pipeline restricts to a **biologically time-matched A/T/N subset**:

1. AV45 amyloid PUP exists.
2. AV1451 baseline tau PUP exists (`OASIS3_AV1451` only;
   `OASIS3_AV1451L` longitudinal follow-up is excluded).
3. A DWI MR session exists.
4. Worst pairwise temporal gap ≤ 60 days across the chosen AV45,
   AV1451, and DWI sessions.

The 60-day cutoff is informed by the bimodal worst-gap distribution:
a tight mode within ~1 year (clustered visits) and a wide mode 2–4
years out (late AV1451 follow-ups). 60 days excludes the late mode.

**Result: 67 subjects.** Every subject's amyloid, tau, and diffusion
measurements represent the same biological state within ~2 months.

Filter logic: `pipeline/cohort.py`. The cohort CSV is regenerated from
the OASIS-3 metadata bundle each `prepare()` run, not committed.

### Why AV45 over PIB

OASIS-3 has both ¹¹C-PIB (~717 subjects with PUP) and ¹⁸F-AV45 (~572
subjects with PUP) amyloid scans. Voxelwise SUVR is comparable across
subjects only **within tracer** — PIB and AV45 have different binding
affinities and dynamic ranges; centiloid harmonizes them globally but
not at the voxel level. Picking a single tracer eliminates this. AV45
wins on two counts:

1. **Era-matched with AV1451**: both ¹⁸F, both came online ~2014–2015
   at WashU. AV45 subjects are far more likely to *also* have a
   temporally-close AV1451 tau scan; PIB sessions skew earlier.
2. **ADNI interoperability**: ADNI's primary amyloid tracer is AV45.
   Models trained here transfer directly to ADNI without tracer
   harmonization.

Cost: smaller N than PIB.

## Image features (`get_df_image`)

Per-subject 3D NIfTIs, all warped to **MNI152** so voxel `[x,y,z]` means
the same anatomical location across every subject:

| column          | source                                                  |
|-----------------|---------------------------------------------------------|
| `amyloid_suvr`  | PUP SUVR (AV45)   → MNI via per-subject T1→MNI          |
| `tau_suvr`      | PUP SUVR (AV1451) → MNI via per-subject T1→MNI          |
| `fa`            | DIPY tensor fit on DWI → MNI via composed b0→T1→MNI     |
| `md`            | DIPY tensor fit on DWI → MNI via composed b0→T1→MNI     |

MNI152 is the field default for multimodal aging/AD studies: standard
atlases (Braak, Desikan-Killiany) live there, ADNI ships in MNI, and a
single T1→MNI nonlinear warp per subject serves all four modalities.
(The diffusion-only `brain_pipe.hcp_ya_open` uses a study-specific FA
template instead — a single-modality healthy-young setting where no
atlas dependency applies.)

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

## Status

- 2026-05-18: cohort definition locked — AV45 ∩ AV1451-baseline ∩ DWI,
  ≤60d worst pairwise gap, 67 subjects.
- 2026-05-20: full pipeline end-to-end on one machine. `prepare()` +
  `fetch()` ≈ 90 min (driven by NITRC-IR PUP fetch latency, ~21 GB
  raw on disk). `process()` runs the 67-subject cohort in ~18 min
  wall time (n_jobs=8) on a 32-core box. Deliverable: 67 × 4 = 268
  MNI152-space NIfTIs (~6.7 GB) + `mni_template.nii.gz` +
  `group_mask.nii.gz` + `cohort_sessions.csv` + `covariates.csv`.
