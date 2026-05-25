"""Pytest config for brainjar tests.

Auto-discovery (`pytest` with no args) runs only fast tests. Slow tests
that re-run the dataset pipeline must be invoked by explicit path:

    pytest tests/hcp_ya_open/test_repro.py             # all repro tests
    pytest tests/hcp_ya_open/test_repro.py::test_dti_single_subject_deterministic

Add new slow test files to ``collect_ignore_glob`` below.
"""

collect_ignore_glob = [
    "*/test_repro.py",
]
