#!/usr/bin/env python3
"""Aggregate runner — discovers and runs the split suite under tests/.

The suite was split from a 1841-line monolith into tests/test_*.py by
subsystem; shared fixtures + package-alias imports live in tests/_common.py.
Run this file (or any tests/test_*.py standalone) with the repo .venv python.
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))   # scripts/producer (on sys.path[0] when run by path)
_TESTS = os.path.join(_HERE, "tests")
sys.path.insert(0, _TESTS)                            # so test_*.py can `from _common import *`

if __name__ == "__main__":
    suite = unittest.TestLoader().discover(
        start_dir=_TESTS, top_level_dir=_TESTS, pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
