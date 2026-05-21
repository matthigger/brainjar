"""Cohort registration-quality QC: pairwise voxelwise correlation per modality.

Run on a directory of MNI-space per-subject NIfTIs named
``<sbj>_<modality>.nii.gz``. Each subject within a modality should
look very similar to every other subject (same anatomical structures
at the same MNI voxel locations); subjects with low mean similarity
to the cohort are candidates for a mis-registration that bypassed
the bit-equality / pipeline-output sanity checks.

Per modality, the script:

1. Loads every ``<sbj>_<modality>.nii.gz`` and flattens in-brain
   voxels to a 1D vector (in-brain selected by ``group_mask.nii.gz``).
2. Computes the N×N Pearson correlation across the cohort.
3. Sorts the matrix by per-subject mean similarity and saves a
   heatmap PNG.

Per cohort, it also writes:

- A strip plot of each subject's z-scored mean similarity, one row
  per modality, with ``|z| > z_threshold`` highlighted.
- A CSV of all (subject, modality, mean_sim, z_score, outlier) rows.
- A console summary of subjects flagged in any modality.

Usage::

    python tests/oasis3/qc_registration.py                          # uses default oasis3 dest
    python tests/oasis3/qc_registration.py <dir>                    # any dir with the naming pattern
    python tests/oasis3/qc_registration.py <dir> --z-threshold 3    # stricter outlier cutoff

Outputs land in ``<dir>/qc/`` by default. Cross-dataset reusable:
the only requirements are NIfTI files following the
``<sbj>_<modality>.nii.gz`` pattern, all on a shared voxel grid,
plus a sibling ``group_mask.nii.gz`` (or pass ``--mask <path>``).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless backend; PNGs only

import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
import pandas as pd


_SUBJ_MOD = re.compile(r"^(?P<sbj>[A-Za-z0-9]+)_(?P<mod>[a-z_]+?)\.nii\.gz$")


def discover(dest):
    """Walk ``dest`` and group ``<sbj>_<mod>.nii.gz`` paths by modality.

    Returns ``{modality: {subject_id: path, ...}, ...}``. Filenames
    without the expected pattern (e.g. ``group_mask.nii.gz``,
    ``mni_template.nii.gz``) are ignored.
    """
    out = defaultdict(dict)
    for p in sorted(Path(dest).iterdir()):
        m = _SUBJ_MOD.match(p.name)
        if not m:
            continue
        out[m.group("mod")][m.group("sbj")] = p
    return dict(out)


def load_cohort(subject_paths, mask):
    """Load every subject's image and return an ``(N_subjects, N_voxels)``
    float32 array of in-brain voxels.
    """
    N = len(subject_paths)
    n_in_brain = int(mask.sum())
    out = np.empty((N, n_in_brain), dtype=np.float32)
    for i, (sbj, path) in enumerate(subject_paths.items()):
        data = nib.load(str(path)).get_fdata(dtype=np.float32)
        if data.shape != mask.shape:
            raise ValueError(
                f"shape mismatch: {sbj}={data.shape} vs mask={mask.shape}"
            )
        out[i] = data[mask]
    return out


def pairwise_correlation(X):
    """N×N Pearson correlation across rows of X (rows = subjects)."""
    # np.corrcoef handles row-wise correlation natively.
    return np.corrcoef(X).astype(np.float32)


def mutual_information(x, y, bins=64):
    """Mutual information between two flat arrays, via 2D histogram.

    Pure numpy (no sklearn/skimage dep). Returns the raw MI in nats —
    the absolute scale isn't comparable across image pairs, but
    z-scoring within a cohort still tracks "more aligned" vs "less
    aligned" reliably.
    """
    hist, _, _ = np.histogram2d(x, y, bins=bins)
    p_xy = hist / hist.sum()
    p_x = p_xy.sum(axis=1)
    p_y = p_xy.sum(axis=0)
    # MI = Σ p(x,y) log[p(x,y) / (p(x) p(y))]; only sum non-zero bins.
    nz = p_xy > 0
    px_y = p_x[:, None] * p_y[None, :]
    return float((p_xy[nz] * np.log(p_xy[nz] / px_y[nz])).sum())


def mean_similarity(corr):
    """Per-subject mean similarity (mean of each row excluding the
    self-correlation diagonal)."""
    N = corr.shape[0]
    off_diag_sum = corr.sum(axis=1) - np.diag(corr)
    return off_diag_sum / (N - 1)


def save_heatmap(corr, subjects, modality, out_path):
    """Sort by mean similarity (ascending: worst at top-left), save PNG."""
    mean_sim = mean_similarity(corr)
    order = np.argsort(mean_sim)
    corr_sorted = corr[order][:, order]
    labels = [subjects[i] for i in order]

    fig, ax = plt.subplots(figsize=(10, 9))
    im = ax.imshow(corr_sorted, cmap="viridis", vmin=corr.min(), vmax=1.0)
    ax.set_title(
        f"Pairwise correlation: {modality}  "
        f"(N={len(subjects)}, sorted by mean similarity)"
    )
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=90, fontsize=6)
    ax.set_yticklabels(labels, fontsize=6)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="Pearson r")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def save_zscore_strip(scores_df, z_threshold, out_path):
    """One row per modality, x = subject (sorted), y = z-score.

    Subjects with ``|z| > z_threshold`` in this modality get red
    markers; others gray. Modality rows share an x-axis.
    """
    modalities = sorted(scores_df["modality"].unique())
    fig, axes = plt.subplots(
        len(modalities), 1, figsize=(12, 1.6 * len(modalities)),
        sharex=True,
    )
    if len(modalities) == 1:
        axes = [axes]

    subject_order = sorted(scores_df["subject"].unique())
    x_index = {s: i for i, s in enumerate(subject_order)}

    for ax, mod in zip(axes, modalities):
        sub = scores_df[scores_df["modality"] == mod]
        x = [x_index[s] for s in sub["subject"]]
        y = sub["z_score"].values
        flagged = sub["outlier"].values
        ax.axhline(0, color="gray", lw=0.5)
        ax.axhline(z_threshold, color="red", lw=0.5, ls="--", alpha=0.5)
        ax.axhline(-z_threshold, color="red", lw=0.5, ls="--", alpha=0.5)
        ax.scatter(np.array(x)[~flagged], y[~flagged], s=12, c="gray", alpha=0.6)
        ax.scatter(np.array(x)[flagged], y[flagged], s=20, c="red")
        for xi, yi, sbj in zip(x, y, sub["subject"]):
            if abs(yi) > z_threshold:
                ax.annotate(
                    sbj, (xi, yi), fontsize=6,
                    xytext=(2, 2), textcoords="offset points",
                )
        ax.set_ylabel(mod, fontsize=9)
        ax.set_ylim(min(-3.5, y.min() - 0.5), max(3.5, y.max() + 0.5))

    axes[-1].set_xticks(range(len(subject_order)))
    axes[-1].set_xticklabels(subject_order, rotation=90, fontsize=6)
    axes[-1].set_xlabel("subject")
    fig.suptitle(
        f"Per-modality registration outliers  "
        f"(red = |z| > {z_threshold} on mean cohort similarity)",
        y=1.0,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def save_cohort_vs_template_scatter(scores_df, z_threshold, out_path):
    """Per-modality scatter of cohort-similarity z vs MI-to-template z.

    Interpretation quadrants (bottom = anomalous):

        bottom-left:  low cohort + low template MI  -> registration failure
        bottom-right: low cohort + normal template  -> atypical biology
        upper-left:   normal cohort + low template  -> rare (template
                                                       wrong scale?)
        upper-right:  normal in both                -> healthy
    """
    modalities = sorted(scores_df["modality"].unique())
    n = len(modalities)
    cols = min(n, 2)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(5.5 * cols, 5 * rows), squeeze=False)
    axes_flat = axes.flatten()

    for ax, mod in zip(axes_flat, modalities):
        sub = scores_df[scores_df["modality"] == mod]
        x = sub["z_score"].values
        y = sub["z_mi_template"].values
        flagged = sub["outlier"].values

        ax.axhline(-z_threshold, color="red", lw=0.5, ls="--", alpha=0.5)
        ax.axvline(-z_threshold, color="red", lw=0.5, ls="--", alpha=0.5)
        ax.axhline(0, color="gray", lw=0.3)
        ax.axvline(0, color="gray", lw=0.3)

        ax.scatter(x[~flagged], y[~flagged], s=14, c="gray", alpha=0.6)
        ax.scatter(x[flagged], y[flagged], s=24, c="red")
        for xi, yi, sbj, fl in zip(x, y, sub["subject"], flagged):
            if fl:
                ax.annotate(
                    sbj, (xi, yi), fontsize=7,
                    xytext=(3, 3), textcoords="offset points",
                )

        ax.set_xlabel("cohort similarity z")
        ax.set_ylabel("MI to template z")
        ax.set_title(mod)

    for ax in axes_flat[n:]:
        ax.set_visible(False)

    fig.suptitle(
        "Registration outlier disambiguation: "
        "bottom-left = registration failure, "
        "bottom-right = atypical biology",
        y=1.0,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def run(dest, mask_path=None, template_path=None,
        output_dir=None, z_threshold=2.0):
    dest = Path(dest)
    if mask_path is None:
        mask_path = dest / "group_mask.nii.gz"
    if template_path is None:
        template_path = dest / "mni_template.nii.gz"
    else:
        template_path = Path(template_path)
    if output_dir is None:
        output_dir = dest / "qc"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    mask = nib.load(str(mask_path)).get_fdata().astype(bool)
    print(f"mask: {mask_path}  in-brain voxels: {int(mask.sum())}")

    template_data = None
    if template_path.exists():
        template_data = nib.load(str(template_path)).get_fdata(dtype=np.float32)
        if template_data.shape != mask.shape:
            raise ValueError(
                f"template shape {template_data.shape} != mask shape {mask.shape}"
            )
        template_data = template_data[mask]
        print(f"template: {template_path}")
    else:
        print(f"no template at {template_path}; skipping MI-to-template metric")

    by_mod = discover(dest)
    if not by_mod:
        raise SystemExit(
            f"No <sbj>_<mod>.nii.gz files matched in {dest}. "
            f"Filenames must look like 'OAS30003_fa.nii.gz'."
        )

    rows = []
    for modality, subject_paths in by_mod.items():
        if len(subject_paths) < 2:
            # The naming pattern catches non-subject files like
            # `mni_template.nii.gz` and `group_mask.nii.gz` (sbj="mni",
            # mod="template"; sbj="group", mod="mask"). Pairwise
            # correlation needs N>=2; skip the one-off matches.
            print(f"\n[{modality}] N={len(subject_paths)} — skipping (not a cohort modality)")
            continue
        print(f"\n[{modality}] N={len(subject_paths)} subjects")
        X = load_cohort(subject_paths, mask)
        corr = pairwise_correlation(X)
        mean_sim = mean_similarity(corr)

        # Per-subject MI to the MNI T1 — disambiguates "low cohort
        # similarity because of registration failure" (low MI too)
        # from "low cohort similarity because of atypical biology"
        # (MI to template is fine; subject is just anatomically
        # placed correctly but with an unusual signal pattern).
        if template_data is not None:
            mi_template = np.array(
                [mutual_information(X[i], template_data) for i in range(len(X))],
                dtype=np.float32,
            )
        else:
            mi_template = np.full(len(X), np.nan, dtype=np.float32)

        heatmap_path = output_dir / f"heatmap_{modality}.png"
        save_heatmap(corr, list(subject_paths), modality, heatmap_path)
        print(f"  wrote {heatmap_path}")

        z_cohort = (mean_sim - mean_sim.mean()) / mean_sim.std()
        if template_data is not None:
            z_template = (mi_template - mi_template.mean()) / mi_template.std()
        else:
            z_template = np.full(len(X), np.nan, dtype=np.float32)

        for sbj, ms, zi, mi, zt in zip(
            subject_paths, mean_sim, z_cohort, mi_template, z_template,
        ):
            rows.append({
                "subject": sbj,
                "modality": modality,
                "mean_similarity": float(ms),
                "z_score": float(zi),
                "mi_to_template": float(mi),
                "z_mi_template": float(zt),
                "outlier": bool(abs(zi) > z_threshold),
            })

    scores_df = pd.DataFrame(rows)
    csv_path = output_dir / "registration_outliers.csv"
    scores_df.to_csv(csv_path, index=False)
    print(f"\nwrote {csv_path}")

    strip_path = output_dir / "zscore_strip.png"
    save_zscore_strip(scores_df, z_threshold, strip_path)
    print(f"wrote {strip_path}")

    if template_data is not None:
        scatter_path = output_dir / "cohort_vs_template_z.png"
        save_cohort_vs_template_scatter(scores_df, z_threshold, scatter_path)
        print(f"wrote {scatter_path}")

    flagged = scores_df[scores_df["outlier"]]
    print(f"\n=== flagged subjects (|z| > {z_threshold} on cohort similarity) ===")
    if flagged.empty:
        print("  (none)")
    else:
        print(
            f"  {'subject':>14}  {'modality':>14}  "
            f"{'cohort z':>8}  {'tmpl z':>8}  classification"
        )
        for _, row in flagged.sort_values(["modality", "z_score"]).iterrows():
            zt = row["z_mi_template"]
            # Both low -> likely registration failure. Cohort low,
            # template ~normal -> likely atypical biology (the subject's
            # image is correctly placed in MNI brain tissue but their
            # signal pattern differs from peers).
            if np.isnan(zt):
                tag = "(no template metric)"
            elif zt < -z_threshold:
                tag = "likely registration failure"
            else:
                tag = "likely atypical biology"
            print(
                f"  {row['subject']:>14}  {row['modality']:>14}  "
                f"{row['z_score']:>+8.2f}  {zt:>+8.2f}  {tag}"
            )

    return scores_df


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "dest", nargs="?", default=None,
        help="directory of <sbj>_<mod>.nii.gz files. Defaults to "
             "the brain_pipe.oasis3 default cache.",
    )
    p.add_argument(
        "--mask", default=None,
        help="path to the brain mask NIfTI (default: <dest>/group_mask.nii.gz)",
    )
    p.add_argument(
        "--template", default=None,
        help="path to the template NIfTI for the MI disambiguation "
             "metric (default: <dest>/mni_template.nii.gz; skip if missing)",
    )
    p.add_argument(
        "--output-dir", default=None,
        help="where to write outputs (default: <dest>/qc/)",
    )
    p.add_argument(
        "--z-threshold", type=float, default=2.0,
        help="|z| above this flags a subject as an outlier (default: 2.0)",
    )
    args = p.parse_args(argv)

    if args.dest is None:
        from brain_pipe.oasis3.fetch import _resolve_dest
        args.dest = _resolve_dest()

    run(
        args.dest, mask_path=args.mask, template_path=args.template,
        output_dir=args.output_dir, z_threshold=args.z_threshold,
    )


if __name__ == "__main__":
    main()
