"""Ensure the NrgXnat/oasis-scripts repo is checked out locally at the
manifest-pinned commit.

Vendoring isn't an option (upstream has no LICENSE), so we clone at
runtime into ``<dest>/oasis-scripts/`` and verify the SHA. The SHA is
authoritative — if the local clone doesn't match the manifest pin, we
fetch and check it out so the pipeline always runs against the exact
script versions PR-reviewed in ``manifest.yaml``.
"""

import subprocess
from pathlib import Path


def _run(args, **kw):
    """subprocess.run with check=True and captured output."""
    return subprocess.run(args, check=True, capture_output=True, text=True, **kw)


def _git_available():
    try:
        _run(["git", "--version"])
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _head_sha(repo):
    return _run(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.strip()


def ensure_scripts(dest, manifest):
    """Clone or update ``oasis-scripts`` at the manifest-pinned commit.

    Args:
        dest: pipeline cache root. The clone lives at
            ``<dest>/oasis-scripts/``.
        manifest: parsed ``manifest.yaml`` dict (must have
            ``oasis_scripts.url`` and ``oasis_scripts.commit``).

    Returns:
        ``Path`` to the local clone.

    Raises:
        RuntimeError: if ``git`` is not on PATH, or if the post-checkout
            SHA doesn't match the manifest pin.
    """
    if not _git_available():
        raise RuntimeError(
            "git is required to fetch the OASIS download scripts but was "
            "not found on PATH. Install git and re-run."
        )

    cfg = manifest["oasis_scripts"]
    url, pinned = cfg["url"], cfg["commit"]
    repo = Path(dest) / "oasis-scripts"

    if not (repo / ".git").exists():
        print(f"  cloning {url} -> {repo}")
        repo.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--quiet", url, str(repo)])
    elif _head_sha(repo) == pinned:
        print(f"  oasis-scripts already at pinned SHA {pinned[:10]}")
        return repo

    print(f"  checking out pinned SHA {pinned[:10]}")
    try:
        _run(["git", "-C", str(repo), "checkout", "--quiet", pinned])
    except subprocess.CalledProcessError:
        # commit not in local objects (e.g. shallow clone, stale repo)
        _run(["git", "-C", str(repo), "fetch", "--quiet", "origin"])
        _run(["git", "-C", str(repo), "checkout", "--quiet", pinned])

    actual = _head_sha(repo)
    if actual != pinned:
        raise RuntimeError(
            f"oasis-scripts SHA mismatch after checkout: expected {pinned}, "
            f"got {actual}. Inspect {repo}."
        )
    return repo
