#!/usr/bin/env bash
# Install WashU's 4dfp suite (incl. nifti_4dfp) from source so the
# tests/oasis3/test_fourdfp.py::test_load_matches_washu_nifti_4dfp
# validation can run against the gold-standard converter.
#
# LINUX ONLY. The 4dfp build is a csh script with several gcc-specific
# tweaks; macOS/Windows users should follow the canonical docs at
# https://4dfp.readthedocs.io/en/latest/tools/interconvert-formats.html
# instead. Cross-platform doesn't make sense for an x86_64 Linux-first
# research toolchain — the upstream README only documents Linux too.
#
# What this does:
#   1. Sanity-check OS + build dependencies (tcsh, gcc, gfortran, git,
#      make). Exits with a clear error if any are missing.
#   2. Clones the robbisg/4dfp_tools community fork (the canonical
#      gcc-10+-friendly Ubuntu-ready fork of WashU's source) into
#      $NILSRC.
#   3. Runs the WashU build script (tcsh make_nil-tools.csh).
#   4. Reports the absolute PATH line you need to add to ~/.bashrc.
#
# Idempotent: if $NILSRC already exists, it pulls the latest. If
# $RELEASE/nifti_4dfp already exists, the build step is skipped.
#
# Customize via env vars (defaults in parens):
#   NILSRC   ($HOME/src/4dfp_tools)         clone destination
#   RELEASE  ($HOME/local/4dfp_tools/bin)   binary install dir

set -euo pipefail

# -- 0. OS check --------------------------------------------------------------

if [[ "$(uname -s)" != "Linux" ]]; then
    cat >&2 <<EOF
This script is Linux-only.

For macOS / Windows: follow the canonical install instructions at
  https://4dfp.readthedocs.io/en/latest/tools/interconvert-formats.html
EOF
    exit 1
fi

# -- 1. dependency check ------------------------------------------------------

missing=()
for cmd in tcsh gcc gfortran make git; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        missing+=("$cmd")
    fi
done
if (( ${#missing[@]} > 0 )); then
    echo "ERROR: missing build dependencies: ${missing[*]}" >&2
    echo "" >&2
    echo "On Debian / Ubuntu:" >&2
    echo "  sudo apt install ${missing[*]}" >&2
    exit 1
fi

# -- 2. paths -----------------------------------------------------------------

NILSRC="${NILSRC:-$HOME/src/4dfp_tools}"
RELEASE="${RELEASE:-$HOME/local/4dfp_tools/bin}"

echo "NILSRC  = $NILSRC"
echo "RELEASE = $RELEASE"
echo

# -- 3. clone / update --------------------------------------------------------

if [[ -d "$NILSRC/.git" ]]; then
    echo "[1/3] $NILSRC already present; pulling latest"
    git -C "$NILSRC" pull --ff-only
else
    echo "[1/3] cloning robbisg/4dfp_tools -> $NILSRC"
    mkdir -p "$(dirname "$NILSRC")"
    git clone https://github.com/robbisg/4dfp_tools.git "$NILSRC"
fi
echo

# -- 4. patch for modern gcc/gfortran ----------------------------------------
#
# The robbisg fork targets gcc 10; on gcc 13 / gfortran 13 (Ubuntu 24.04) two
# flags must be added:
#
#   -fcommon              C: gcc 10+ defaults to -fno-common, which rejects
#                         the suite's tentative file-scope globals (objects,
#                         cont, fitline, ...). Prepend -fcommon to every
#                         CFLAGS line in the .mak files.
#   -fallow-invalid-boz   Fortran: gfortran 10+ rejects VAX-style hex BOZ
#                         literals like '7fffffff'x. Inject it into the FC
#                         invocations in both make_nil-tools.csh and the
#                         per-tool .mak files.
#
# Idempotent: skips if the flag is already present on a given line.
#
# Note: this only gets the C-based tools (incl. nifti_4dfp) building. Some
# Fortran-only tools still fail on argument-mismatch errors that would need
# -fallow-argument-mismatch; we don't pursue them since we only need
# nifti_4dfp for the test suite.

cd "$NILSRC"

# Top-level FC variable in make_nil-tools.csh
if ! grep -q -- '-fallow-invalid-boz' make_nil-tools.csh; then
    sed -i 's|-ffixed-line-length-132 -fcray-pointer|-ffixed-line-length-132 -fallow-invalid-boz -fcray-pointer|' \
        make_nil-tools.csh
fi

# Per-tool .mak files
while IFS= read -r mak; do
    # Prepend -fcommon to CFLAGS lines that don't already have it
    sed -i '/^CFLAGS[[:space:]]*=.*-fcommon/!s|^CFLAGS\([[:space:]]*\)=\([[:space:]]*\)|CFLAGS\1= -fcommon\2|' "$mak"
    # Inject -fcommon and -fallow-invalid-boz into FC = gcc ... lines
    if grep -q '^[[:space:]]*FC[[:space:]]*=[[:space:]]*gcc' "$mak"; then
        sed -i '/^[[:space:]]*FC[[:space:]]*=[[:space:]]*gcc[^"]*-fcommon/!s|\(^[[:space:]]*FC[[:space:]]*=[[:space:]]*\)gcc |\1gcc -fcommon |' "$mak"
        sed -i '/^[[:space:]]*FC[[:space:]]*=.*-fallow-invalid-boz/!s|-ffixed-line-length-132 |-ffixed-line-length-132 -fallow-invalid-boz |' "$mak"
    fi
done < <(find . -name '*.mak' -type f)

echo "[1.5/3] patched make_nil-tools.csh and .mak files for gcc 13 / gfortran 13"
echo

# -- 5. build (skip if already built) ----------------------------------------

mkdir -p "$RELEASE"
export NILSRC RELEASE

if [[ -x "$RELEASE/nifti_4dfp" ]]; then
    echo "[2/3] nifti_4dfp already present at $RELEASE/nifti_4dfp; skipping build"
else
    echo "[2/3] building 4dfp suite (tcsh make_nil-tools.csh) -- takes ~5 min"
    cd "$NILSRC"
    # The suite-level script exits at the first per-tool failure. We tolerate
    # that here: with modern gfortran, a handful of Fortran-heavy tools
    # (dwi_xalign_4dfp etc.) fail on argument-mismatch errors we don't fix.
    # nifti_4dfp doesn't need those — its only deps are 4 C objects that
    # build earlier in the suite run (TRX/{endianio,Getifh,rec}.o and
    # imglin/t4_io.o). If the suite run bailed before reaching nifti_4dfp,
    # we build it standalone afterwards.
    tcsh make_nil-tools.csh || true

    if [[ ! -x "$RELEASE/nifti_4dfp" ]]; then
        echo "[2b/3] suite build did not produce nifti_4dfp; building it standalone"
        cd "$NILSRC/nifti_4dfp"
        make -f nifti_4dfp.mak release
    fi
fi
echo

# -- 5. verify ----------------------------------------------------------------

echo "[3/3] verifying nifti_4dfp"
if [[ ! -x "$RELEASE/nifti_4dfp" ]]; then
    echo "ERROR: build claimed to succeed but $RELEASE/nifti_4dfp is missing" >&2
    exit 1
fi

cat <<EOF

Build complete. nifti_4dfp installed at:
  $RELEASE/nifti_4dfp

To make it discoverable by the test suite (and by your shell), add:

  export PATH="$RELEASE:\$PATH"

…to your ~/.bashrc, then start a new shell. Verify with:

  which nifti_4dfp
  python3 -m pytest tests/oasis3/test_fourdfp.py -v

The previously-skipped test_load_matches_washu_nifti_4dfp should now
run against the OASIS-3 PUP file at
~/.local/share/brain_pipe/oasis3/raw/pup/OAS30003_AV45_PUPTIMECOURSE_d3731/.
EOF
