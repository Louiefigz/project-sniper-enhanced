#!/usr/bin/env python3
"""Capability artifacts fail closed when evidence is unavailable or stale."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from _common import *  # noqa: F401,F403
import gate_policy as gpol
import plan_lint_comps as plc
from graphics.comp_capability_artifact import SCHEMA_VERSION, build_artifact
from test_plan_lint_comps import _entry, _plan, _write_matrix


class MatrixAvailabilityTests(unittest.TestCase):
    def test_missing_matrix_is_one_fail_with_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "comp_capabilities.json")
            verdicts = plc.matrix_verdicts(
                _plan([_entry(), _entry()]), matrix_path=missing)
        self.assertEqual([v.severity for v in verdicts], ["FAIL"])
        self.assertIn("2 graphicsTrack entries unchecked",
                      verdicts[0].evidence)
        out = gpol.to_gate_json(verdicts, {"mode": "short"})
        self.assertFalse(out["ok"])
        self.assertIn("matrix file missing", out["errors"][0])

    def test_malformed_matrix_is_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "comp_capabilities.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            (unreadable,) = plc.matrix_verdicts(
                _plan([_entry()]), matrix_path=path)
            self.assertIn("matrix unreadable", unreadable.evidence)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"schemaVersion": SCHEMA_VERSION, "comps": {}},
                          handle)
            (empty,) = plc.matrix_verdicts(
                _plan([_entry()]), matrix_path=path)
            self.assertIn("no comps map", empty.evidence)

    def test_stale_source_and_tampered_rows_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_matrix(tmp)
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            data["sourceDigest"] = "0" * 64
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            (stale,) = plc.matrix_verdicts(
                _plan([_entry()]), matrix_path=path)
            self.assertIn("source digest changed", stale.evidence)
            data["sourceDigest"] = build_artifact(data["comps"])["sourceDigest"]
            data["comps"]["line-swap"]["aspect"] = "16:9"
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            (tampered,) = plc.matrix_verdicts(
                _plan([_entry()]), matrix_path=path)
            self.assertIn("capability digest", tampered.evidence)

    def test_empty_track_emits_nothing(self) -> None:
        self.assertEqual(
            plc.matrix_verdicts(_plan([]), matrix_path="/nope"), [])

    def test_unknown_and_unproved_rows_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            matrix = _write_matrix(tmp)
            (unknown,) = plc.matrix_verdicts(
                _plan([_entry(kind="mystery-comp")]), matrix_path=matrix)
            (static,) = plc.matrix_verdicts(
                _plan([_entry(kind="marker-highlight")]), matrix_path=matrix)
            (errored,) = plc.matrix_verdicts(
                _plan([_entry(kind="ui-focus-zoom")]), matrix_path=matrix)
        self.assertIn("unavailable comp", unknown.evidence)
        self.assertIn("fadeClass is missing", static.evidence)
        self.assertIn("hyperframes died", errored.evidence)


if __name__ == "__main__":
    unittest.main(verbosity=2)
