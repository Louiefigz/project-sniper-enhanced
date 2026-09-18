#!/usr/bin/env python3
"""Studio-player compliance for every registered motion composition.

HyperFrames Studio's session lint is stricter than the render CLI: the root
composition element must declare data-start="0", comp scripts must be
deterministic (no Math.random()/Date.now() — repeated seeks must reproduce
identical frames), and data-composition-variables must be a valid declaration
array. The render pipeline tolerates violations; the Studio timeline does not.
"""
from __future__ import annotations

import glob
import html as html_mod
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from graphics.composition_transform import set_root_duration
from graphics.graphics_render import COMPOSITIONS_DIR

_ROOT_RE = re.compile(r'<[^>]*data-composition-id="[^"]*"[^>]*>')
_VARIABLES_RE = re.compile(
    r"data-composition-variables=(?P<quote>['\"])(?P<body>.*?)(?P=quote)",
    re.DOTALL)
_NONDETERMINISTIC_CALLS = ("Math.random(", "Date.now(", "new Date(")
_VARIABLE_TYPES = {"string", "number", "color", "boolean", "enum"}


def _comps() -> list[str]:
    paths = sorted(glob.glob(os.path.join(COMPOSITIONS_DIR, "*.html")))
    assert paths, f"no compositions found under {COMPOSITIONS_DIR}"
    return paths


class RootElementTests(unittest.TestCase):
    def test_root_declares_data_start_zero_and_duration(self):
        for path in _comps():
            with self.subTest(comp=os.path.basename(path)):
                with open(path, encoding="utf-8") as handle:
                    root = _ROOT_RE.search(handle.read())
                self.assertIsNotNone(root, "no data-composition-id root")
                tag = root.group(0)
                self.assertIn('data-start="0"', tag)
                self.assertIn("data-duration=", tag)

    def test_root_duration_rewrite_contract_still_holds(self):
        """graphics_render/comp-html rewrite the root's data-duration in
        place; the data-start attribute must never break that contract."""
        for path in _comps():
            with self.subTest(comp=os.path.basename(path)):
                with open(path, encoding="utf-8") as handle:
                    rewritten = set_root_duration(handle.read(), 2.5)
                tag = _ROOT_RE.search(rewritten).group(0)
                self.assertIn('data-duration="2.5"', tag)
                self.assertIn('data-start="0"', tag)


class DeterminismTests(unittest.TestCase):
    def test_no_nondeterministic_calls(self):
        for path in _comps():
            with self.subTest(comp=os.path.basename(path)):
                with open(path, encoding="utf-8") as handle:
                    source = handle.read()
                for call in _NONDETERMINISTIC_CALLS:
                    self.assertNotIn(
                        call, source,
                        f"{call}...) makes seeks non-reproducible; derive "
                        "pseudo-randomness from a seeded PRNG or from t")


class VariablesDeclarationTests(unittest.TestCase):
    def test_declarations_are_valid(self):
        for path in _comps():
            with self.subTest(comp=os.path.basename(path)):
                with open(path, encoding="utf-8") as handle:
                    match = _VARIABLES_RE.search(handle.read())
                self.assertIsNotNone(
                    match, "no data-composition-variables declaration")
                rows = json.loads(html_mod.unescape(match.group("body")))
                self.assertIsInstance(rows, list)
                for row in rows:
                    self._assert_row(row)

    def _assert_row(self, row: object) -> None:
        self.assertIsInstance(row, dict)
        for field in ("id", "type", "label", "default"):
            self.assertIn(field, row)
        self.assertIn(row["type"], _VARIABLE_TYPES)
        if row["type"] == "enum":
            options = row.get("options")
            self.assertIsInstance(options, list)
            self.assertTrue(options)
            for option in options:
                self.assertIsInstance(option, dict)
                self.assertIn("value", option)
                self.assertIn("label", option)


if __name__ == "__main__":
    unittest.main()
