"""Freshness gate for retained P0 render-effect parity evidence."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.p0_render_effect_parity_artifact import (
    ParityArtifactError,
    validate_case,
    validate_retained_parity,
)


class P0RenderEffectParityArtifactTests(unittest.TestCase):
    def test_short_and_lf14_retained_evidence_is_current(self) -> None:
        try:
            value = validate_retained_parity()
        except ParityArtifactError as error:
            self.fail(str(error))
        self.assertEqual(set(value), {"short", "lf14"})
        for case, summary in value.items():
            with self.subTest(case=case):
                self.assertEqual(summary["baseline"], case)
                self.assertEqual(summary["dirtyNodeIds"], [
                    "node-scene-0000", "node-composite", "node-final"])
                self.assertEqual(summary["reusedNodeIds"], [
                    "node-source", "node-timeline", "node-base"])
                self.assertEqual(
                    summary["forcedExecutionMode"], "forced-full")

    def test_unknown_or_missing_case_fails_without_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaisesRegex(
                    ParityArtifactError, "unknown retained parity case"):
                validate_case(root, "unknown")
            with self.assertRaisesRegex(
                    ParityArtifactError, "retained parity case is absent"):
                validate_case(root, "short")


if __name__ == "__main__":
    unittest.main()
