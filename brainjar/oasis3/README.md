# brainjar.oasis3

Aging / Alzheimer's cohort from the WashU OASIS-3 release. Three
per-subject 3D image features — `t1`, `fa`, `md` — paired with a 7-dim
CDR target (CDR Sum of Boxes plus six component scores) and basic
demographics. Designed for CDR prediction.

- Source: <https://sites.wustl.edu/oasisbrains/home/oasis-3/>
- Data dictionary: [OASIS-3 Imaging Methods & Data Dictionary v2.3, July 2022](https://sites.wustl.edu/oasisbrains/files/2024/04/OASIS-3_Imaging_Data_Dictionary_v2.3-a93c947a586e7367.pdf)
- DUA: OASIS Data Use Agreement (signed via NITRC-IR account)
- Hosting: NITRC-IR / XNAT — <https://nitrc.org/ir>
- Download tooling: <https://github.com/NrgXnat/oasis-scripts> (cloned at runtime)

## Use

**Prereq** (one-time): get a NITRC-IR account at
<https://www.nitrc.org/ir/>. Account signup enforces the OASIS Data
Use Agreement, so the pipeline doesn't prompt for it again. OASIS-3
raw data is DUA-restricted and not redistributable — `process()`
requires you to point at your own NITRC-IR-authenticated download.

The pipeline runs in three stages — `prepare` → `fetch` → `process`.
Either invoke from the shell (CLI) or from Python.

### CLI

```bash
# Run everything in one go — prompts for NITRC-IR password once and
# reuses it across prepare + fetch. ~5 hr wall on a 32-core box.
python -m brainjar.oasis3 all --user YOUR_NITRC_USERNAME --n-jobs 8

# Or run the stages separately (e.g., to background the long fetch):
python -m brainjar.oasis3 prepare --user YOUR_NITRC_USERNAME    # ~10 s
python -m brainjar.oasis3 fetch   --user YOUR_NITRC_USERNAME    # ~3 hr
python -m brainjar.oasis3 process --n-jobs 8                    # ~2 hr

python -m brainjar.oasis3 --help                                # subcommand reference
```

All subcommands accept `--dest PATH` to override the cache location.
`prepare` and `all` accept `--bundle PATH` to point at a
pre-downloaded `OASIS3_data_files.zip` (skips the metadata-bundle
download — useful for offline use). Password is always prompted via
`getpass`, never read from arguments or env.

### Python API

```python
from brainjar.oasis3 import prepare, fetch, process, get_df_image, get_df_xfeat, LABELS

prepare()    # ~seconds. Downloads the ~67 MB metadata bundle from
             # NITRC-IR, builds cohort_sessions.csv + covariates.csv.
fetch()      # ~3 hr. Downloads T1w + DWI scans for the ~1013 cohort
             # subjects (no PET — see Cohort below).
process()    # DTI fit + MNI152 registration. Produces the three 3D
             # NIfTIs per subject + covariates.csv. ~2 hr on a
             # 32-core box (n_jobs=8).

df_image = get_df_image()  # cols: t1, fa, md
df_xfeat = get_df_xfeat()  # cols: age, sex, educ, apoe, daddem, momdem,
                           #        cdr_sum, memory, orient, judgment,
                           #        commun, homehobb, perscare
LABELS['cdr_sum']          # 'CDR Sum of Boxes'
```

Pass `bundle='/path/to/OASIS3_data_files.zip'` to `prepare()` to skip
the metadata download (offline / pre-downloaded use).

Cache: `platformdirs.user_data_dir('brainjar') / oasis3` by default.
Override per-call (`process(dest=...)`) or globally
(`BRAINJAR_OASIS3_PATH`).

## Cohort

OASIS-3 ships ~1,400 subjects across 2,842 MR sessions. This pipeline
restricts to a **CDR-prediction cohort** ("cohort D"): subjects with
both diffusion imaging that can support a tensor fit and a complete
CDR visit within a year of the DWI session.

1. The subject has at least one MR session with a tensor-fittable DWI
   run (i.e. some run whose `SeriesDescription` is not `"Axial_DWI"`).
   T1 is implied — every OASIS-3 MR session ships a T1w. The
   Biograph_mMR PET/MR sites recorded a 2-volume `Axial_DWI`
   trace-weighted localizer as their only diffusion acquisition for a
   subset of subjects; DIPY silently emits noise on a tensor fit of
   fewer than 6 independent directions, so those sessions are
   excluded at cohort-selection time. Sessions whose only DWI run has
   `SeriesDescription == "Axial_DWI"` are dropped; the runtime check
   in `pipeline/dti.py` re-validates from the bval file as a backstop.
2. The subject has at least one **complete** UDS Form B4 (CDR) visit:
   non-null `CDRSUM` and all six component scores (memory,
   orientation, judgment, community affairs, home & hobbies, personal
   care).
3. Some (DWI session, CDR visit) pair for the subject has
   `|day(DWI) - day(CDR)| ≤ 365`.

For each cohort subject, the selected MR session and CDR visit are
the pair minimizing `|day(DWI) - day(CDR)|`, with a deterministic
tiebreak by earliest DWI day then earliest CDR day. Cohort selection
is reproducible.

**Result: 1013 subjects.** Filter logic: `pipeline/cohort.py`. The
cohort CSV is regenerated from the OASIS-3 metadata bundle each
`prepare()` run, not committed.

## Image features (`get_df_image`)

Per-subject 3D NIfTIs, all warped to **MNI152** so voxel `[x,y,z]`
means the same anatomical location across every subject:

| column | source                                                   |
|--------|----------------------------------------------------------|
| `t1`   | T1w from the chosen MR session → MNI152 (SyN)            |
| `fa`   | DIPY tensor fit on DWI → MNI via composed b0→T1→MNI      |
| `md`   | DIPY tensor fit on DWI → MNI via composed b0→T1→MNI      |

MNI152 is the field default for multimodal aging/AD studies: standard
atlases (Braak, Desikan-Killiany) live there, ADNI ships in MNI, and a
single T1→MNI nonlinear warp per subject serves all three modalities.

FA/MD are computed locally from raw DWI via the same DIPY tensor fit
used in `brainjar.hcp_ya_open`.

## Tabular features (`get_df_xfeat`)

Demographics:

| column     | description                                          |
|------------|------------------------------------------------------|
| `age`      | years at the chosen MR session (AgeatEntry + dwi_day/365.25) |
| `sex`      | M / F (OASIS GENDER: 1 → M, 2 → F)                   |
| `educ`     | years of education (demographics.EDUC)               |
| `apoe`     | APOE genotype (e.g. 33, 34, 24; demographics.APOE)   |
| `daddem`   | paternal history of dementia (NACC coding)           |
| `momdem`   | maternal history of dementia (NACC coding)           |

CDR target (the prediction outcome — all from the chosen UDSb4 visit):

| column     | description                                          |
|------------|------------------------------------------------------|
| `cdr_sum`  | CDR Sum of Boxes, 0–18 continuous (= CDRSUM)         |
| `memory`   | CDR memory component (0 / 0.5 / 1 / 2 / 3)           |
| `orient`   | CDR orientation                                      |
| `judgment` | CDR judgment & problem solving                       |
| `commun`   | CDR community affairs                                |
| `homehobb` | CDR home & hobbies                                   |
| `perscare` | CDR personal care                                    |

## Status

- 2026-05-18: cohort definition initial pass — AV45 ∩ AV1451-baseline ∩
  DWI, ≤60d worst pairwise gap; produced 67 subjects.
- 2026-05-20: full pipeline end-to-end on one machine. `prepare()` +
  `fetch()` ≈ 90 min, `process()` ~18 min wall time (n_jobs=8) on a
  32-core box. Pairwise-correlation QC on FA revealed a sharp two-block
  cohort structure traceable to a degenerate 2-volume `Axial_DWI`
  acquisition on the Biograph_mMR PET/MR sites. Added a tensor-fittable
  filter at cohort-selection time and hard/warn cardinality checks in
  `pipeline/dti.py`. Cohort reduced to 41.
- 2026-05-21: rebuilt cohort for CDR-prediction goal; PET removed (tau
  PET was preferentially given to CDR=0 subjects, so the prior A/T/N
  cohort had no CDR variance — 50/55 were CDR=0). Cohort = T1 + DWI
  (tensor-fittable) + CDR at 365 d, target = CDRSUM + 6 component CDR
  scores. **N = 1013.**
