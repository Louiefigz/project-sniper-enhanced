"""Freshness and exact-threshold gate for retained P4 live evidence."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests.live_p4_exit_closure_acceptance import CLOSURE, REPO
from tests.p4_exit_media import source_closure, toolchain

ARTIFACT = REPO / (
    "docs/producer/command-driven-editing/contracts/"
    "p4-live-exit-closure-v1.json")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _strings(child)]
    return []


class P4ExitClosureArtifactTests(unittest.TestCase):
    def test_retained_live_closure_is_fresh_complete_and_load_bearing(self) -> None:
        value = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(set(value), {
            "schemaVersion", "kind", "generatedAt", "execution",
            "sourceClosure", "toolchain", "cohorts", "nonClaims", "passed",
        })
        self.assertEqual(value["schemaVersion"], 1)
        self.assertEqual(value["kind"], "p4-live-exit-closure")
        self.assertTrue(value["passed"])
        self.assertEqual(
            value["sourceClosure"], source_closure(REPO, CLOSURE))
        self.assertEqual(value["toolchain"], toolchain())
        for row in value["toolchain"].values():
            self.assertTrue(Path(row["path"]).is_absolute())
            self.assertRegex(row["sha256"], SHA256)
        self.assertFalse(any(
            "/private/var/folders/" in text or "/tmp/sniper-p4-" in text
            for text in _strings(value)))
        self._assert_geometry(value["cohorts"]["geometry4k"]["evidence"])
        scene = value["cohorts"]["sceneIncremental"]["evidence"]
        self._assert_copy(scene["copyRepair"])
        self._assert_timing(scene["timingMove"])
        self._assert_treatments(value["cohorts"]["treatments"]["evidence"])

    def _assert_geometry(self, row: dict) -> None:
        self.assertTrue(row["passed"])
        self.assertEqual(row["placedBBox"], [0, 0, 3840, 2160])
        self.assertEqual(row["deliveryCanvas"], [3840, 2160])
        self.assertEqual(
            [row["authoredComposition"][key] for key in ("width", "height")],
            [1920, 1080])
        self.assertEqual(
            [row["output"][key] for key in ("width", "height")],
            [3840, 2160])
        for identity in ("sourceIdentity", "outputIdentity"):
            self.assertRegex(row[identity]["mtimeNs"], r"^[0-9]+$")
        edges = row["greenBorderFractions"]
        self.assertGreaterEqual(edges["sourceBeforeWindow"], 0.98)
        self.assertGreaterEqual(edges["outputBeforeWindow"], 0.98)
        self.assertLessEqual(edges["outputInsideWindow"], 0.01)
        self.assertTrue(all(
            result["status"] == "pass"
            for result in row["placementAudit"]))

    def _assert_copy(self, row: dict) -> None:
        self.assertTrue(row["passed"])
        self.assertEqual(row["initialCached"], {
            "unit-left": False, "unit-right": False})
        self.assertEqual(row["changedCached"], {
            "unit-left": True, "unit-right": False})
        self.assertEqual(row["forcedCached"], {
            "unit-left": False, "unit-right": False})
        self.assertTrue(row["leftMediaUnchanged"])
        self.assertEqual(len(row["newCacheMedia"]), 1)
        self.assertTrue(all(row["forcedUnitHashesMatch"].values()))
        self.assertEqual(row["bindingDelta"], {
            "actions": ["replace-media"],
            "bindingIds": ["scene-045-unit-right"],
            "preserved": ["scene-045-unit-left"],
        })
        self.assertGreaterEqual(row["forcedFullOracle"]["colorSsim"], 0.995)
        self.assertGreaterEqual(row["forcedFullOracle"]["alphaSsim"], 0.995)

    def _assert_timing(self, row: dict) -> None:
        self.assertTrue(row["passed"])
        self.assertEqual(row["unitCacheHits"], [True, True])
        self.assertTrue(row["cacheMediaUnchanged"])
        self.assertEqual(
            row["bindingDelta"]["actions"],
            ["move-placement", "move-placement"])
        oracle = row["forcedTimelineOracle"]
        self.assertTrue(oracle["passed"])
        self.assertTrue(oracle["decodedAudioMatch"])
        self.assertTrue(oracle["streamFactsMatch"])
        self.assertTrue(oracle["pictureComparison"]["pixelIdentical"])

    def _assert_treatments(self, row: dict) -> None:
        self.assertTrue(row["passed"])
        transition = row["transition"]
        self.assertTrue(transition["passed"])
        self.assertGreater(transition["decodedChangedInsideDirtyWindows"], 0)
        self.assertEqual(transition["decodedChangedOutsideDirtyWindows"], 0)
        self.assertTrue(transition["forcedFullOracle"]["passed"])
        sfx = row["sfx"]
        self.assertTrue(sfx["passed"])
        self.assertTrue(sfx["picturePacketReused"])
        self.assertTrue(sfx["pictureFrameMd5Reused"])
        self.assertTrue(sfx["audioChanged"])
        self.assertTrue(sfx["forcedFullOracle"]["decodedAudioMatch"])
        grade = row["grade"]
        self.assertTrue(grade["passed"])
        self.assertEqual(
            grade["decodedChangedFrames"], row["source"]["decodedFrames"])
        self.assertTrue(grade["forcedFullOracle"]["passed"])


if __name__ == "__main__":
    unittest.main()
