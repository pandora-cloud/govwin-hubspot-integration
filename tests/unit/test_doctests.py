"""Run doctests from src/ helpers that have inline examples.

This file is the registration point for doctest coverage. Add the module's
import path to ``DOCTEST_MODULES`` when you write inline ``>>>`` examples in
a helper function. The targeted approach (vs ``--doctest-modules``) keeps
the test suite from importing every Lambda handler at collection time,
which would force the whole AWS dependency stack to load.
"""

from __future__ import annotations

import doctest

import pytest

DOCTEST_MODULES: list[str] = [
    "src.ace.mapper",
]


@pytest.mark.parametrize("module_path", DOCTEST_MODULES)
def test_doctests(module_path: str) -> None:
    module = __import__(module_path, fromlist=["_"])
    results = doctest.testmod(module, verbose=False)
    assert results.failed == 0, f"{results.failed} doctest failures in {module_path}"
