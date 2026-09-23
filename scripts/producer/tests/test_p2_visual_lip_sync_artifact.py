"""Retained visual-lip-sync acceptance evidence must match a fresh run."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.live_p2_visual_lip_sync_acceptance import build_artifact

ARTIFACT = (
    Path(__file__).resolve().parents[1]
    / "artifacts" / "p2-visual-lip-sync-controlled-media-2026-09-23.json")


class VisualLipSyncArtifactTests(unittest.TestCase):
    def test_retained_artifact_matches_fresh_controlled_media_run(self) -> None:
        with open(ARTIFACT, encoding="utf-8") as stream:
            retained = json.load(stream)
        self.assertEqual(retained, build_artifact())
        self.assertEqual(retained["status"], "measured-pass")
        self.assertTrue(
            retained["media"]["positiveCandidateConstruction"]
            ["reencodedFromSelectedSourceBytes"])
        self.assertEqual(
            set(retained["negativeCases"].values()), {
                "VISIBLE_SPEECH_AV_OFFSET",
                "VISUAL_SPEECH_OCCLUDED_OR_SUBSTITUTED",
                "VISUAL_ORACLE_UNMEASURABLE",
                "VISUAL_ORACLE_AMBIGUOUS_MAPPING",
            })


if __name__ == "__main__":
    unittest.main(verbosity=2)
