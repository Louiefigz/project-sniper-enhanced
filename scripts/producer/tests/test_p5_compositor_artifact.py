"""Freshness and exact-threshold gate for retained P5 compositor evidence."""
from __future__ import annotations

import json
import unittest

from tests.live_p5_compositor_acceptance import CLOSURE, REPO
from tests.p4_exit_media import source_closure, toolchain

ARTIFACT = REPO / (
    "docs/producer/command-driven-editing/contracts/"
    "p5-24-overlay-one-pass-2026-09-23.json")


class P5CompositorArtifactTests(unittest.TestCase):
    def test_retained_twenty_four_overlay_proof_is_fresh(self) -> None:
        value = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(set(value), {
            "schemaVersion", "kind", "generatedAt", "execution",
            "elapsedSeconds", "sourceClosure", "toolchain", "evidence",
            "nonClaims", "passed",
        })
        self.assertEqual(value["kind"], "p5-24-overlay-one-pass")
        self.assertTrue(value["passed"])
        self.assertEqual(value["sourceClosure"], source_closure(REPO, CLOSURE))
        self.assertEqual(value["toolchain"], toolchain())
        evidence = value["evidence"]
        self.assertEqual(evidence["overlayCount"], 24)
        self.assertEqual(evidence["production"]["reportedPasses"], 1)
        self.assertEqual(evidence["production"]["ffmpegCommandCount"], 1)
        self.assertEqual(evidence["production"]["pictureEncodeCount"], 1)
        self.assertEqual(evidence["production"]["inputCount"], 24)
        self.assertEqual(evidence["production"]["filterOverlayCount"], 24)
        self.assertEqual(
            [evidence["production"]["decode"][key]
             for key in ("width", "height")],
            [1920, 1080],
        )
        self.assertEqual(
            evidence["legacyControl"]["pictureEncodeCount"], 3)
        oracle = evidence["legacyEquivalenceOracle"]
        self.assertTrue(oracle["passed"])
        self.assertTrue(oracle["decodedAudioMatch"])
        self.assertTrue(oracle["streamFactsMatch"])
        self.assertTrue(
            oracle["pictureComparison"]["codecFloorEquivalent"])
        sample = evidence["visibleOverlaySample"]
        self.assertGreater(sample["outputRgb"][1], sample["baseRgb"][1] + 60)


if __name__ == "__main__":
    unittest.main()
