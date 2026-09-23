"""Freshness and exact-threshold gate for retained P4 live evidence."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from tests.live_p4_exit_closure_acceptance import CLOSURE, REPO, HISTORICAL, HISTORICAL_SHA256, runtime_identity
from tests.p4_exit_media import frame_card_geometry, source_closure, toolchain

ARTIFACT = REPO / (
    "docs/producer/command-driven-editing/contracts/"
    "p4-live-exit-closure-v2.json")
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
            "sourceClosure", "toolchain", "cohorts", "nonClaims", "passed", "historicalEvidence", "sceneRuntimeIdentity",
        })
        self.assertEqual(value["schemaVersion"], 2)
        self.assertEqual(value["kind"], "p4-live-catalog-exit-closure")
        self.assertEqual(value["historicalEvidence"], {"path": HISTORICAL, "sha256": HISTORICAL_SHA256})
        self.assertEqual(source_closure(REPO, (HISTORICAL,))[HISTORICAL], HISTORICAL_SHA256)
        self.assertEqual(value["execution"], {"mode": "native-macos-real-browser-media",
                                              "networkDenialClaimed": False})
        self.assertIn("not retired transition rendering or SFX picture-reuse qualification", value["nonClaims"])
        self.assertTrue(value["passed"])
        self.assertEqual(
            value["sourceClosure"], source_closure(REPO, CLOSURE))
        self.assertEqual(value["toolchain"], toolchain())
        self.assertRegex(value["sceneRuntimeIdentity"], SHA256)
        self.assertEqual(value["sceneRuntimeIdentity"], runtime_identity())
        for row in value["toolchain"].values():
            self.assertTrue(Path(row["path"]).is_absolute())
            self.assertRegex(row["sha256"], SHA256)
        self.assertFalse(any(
            "/private/var/folders/" in text or "/tmp/sniper-p4-" in text
            for text in _strings(value)))
        self._assert_geometry(value["cohorts"]["catalogGeometry2xPortrait"]["evidence"])
        scene = value["cohorts"]["sceneIncremental"]["evidence"]
        self._assert_copy(scene["copyRepair"])
        self._assert_timing(scene["timingMove"])
        self._assert_treatments(value["cohorts"]["treatments"]["evidence"])

    def _assert_geometry(self, row: dict) -> None:
        self.assertTrue(row["passed"])
        self.assertEqual(row["geometryPolicy"], "line-swap-portrait-own-screen-2x-v2")
        self.assertEqual(row["placedBBox"], [0, 0, 2160, 3840])
        self.assertEqual(row["deliveryCanvas"], [2160, 3840])
        for key, dims, frames in (("authoredComposition", [1080, 1920], 84),
                                  ("output", [2160, 3840], 96), ("source", [2160, 3840], 96)):
            self.assertEqual([row[key][axis] for axis in ("width", "height")], dims)
            self.assertEqual(row[key]["decodedFrames"], frames)
            self.assertEqual(row[key]["frameRate"], "24/1")
        for identity in ("sourceIdentity", "outputIdentity"):
            self.assertRegex(row[identity]["mtimeNs"], r"^[0-9]+$")
        edges = row["greenBorderFractions"]
        for key in ("sourceBeforeWindow", "outputBeforeWindow", "outputAfterWindow"):
            self.assertGreaterEqual(edges[key], 0.98)
        for key in ("outputFirstHold", "outputSecondHold"):
            self.assertLessEqual(edges[key], 0.01)
        self.assertTrue(row["nativeToDeliveryBoundsMatch"])
        self.assertEqual(len(row["cardGeometry"]), 2)
        for pair, frames in zip(row["cardGeometry"], ((24, 30), (60, 66))):
            for key, scale, frame in (("native", 1, frames[0]), ("delivery", 2, frames[1])):
                self._assert_card(pair[key], scale, frame)
            for native, delivery in zip(pair["native"]["whiteBBox"], pair["delivery"]["whiteBBox"]):
                self.assertLessEqual(abs(delivery / 2 - native), 3)
        self.assertTrue(all(result["status"] == "pass" for result in row["placementAudit"]))

    def _assert_card(self, row: dict, scale: int, frame: int) -> None:
        self.assertTrue(row["passed"])
        self.assertEqual((row["frame"], row["scale"]), (frame, scale))
        self.assertEqual(len(row["whiteBBox"]), 4)
        for actual, native in zip(row["whiteBBox"], (60, 751.5, 930, 958.5)):
            self.assertLessEqual(abs(actual - native * scale), 3 * scale)
        self.assertGreaterEqual(row["whiteAreaFraction"], 0.70)
        self.assertGreaterEqual(row["paddingWhiteFraction"], 0.95)
        self.assertGreaterEqual(row["textDarkFraction"], 0.005)
        self.assertLessEqual(row["textDarkFraction"], 0.30)

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
        self.assertNotIn("transition", row)
        self.assertNotIn("sfx", row)
        rejection = row["retiredExecutionRejection"]
        self.assertTrue(rejection["passed"])
        self.assertEqual(rejection["scope"], "real-policy-refusal-with-forbidden-work-instrumentation")
        expected = {(api, kind, sound) for api, sounds in (
            ("apply_transitions", (False, True, "click")), ("repair_transition_sfx", (True,)))
            for kind in ("white-flash", "light-leak", "zoom-pull") for sound in sounds}
        self.assertEqual(len(rejection["cases"]), len(expected))
        self.assertEqual({(case["api"], case["kind"], case["sfx"]) for case in rejection["cases"]}, expected)
        for case in rejection["cases"]:
            self.assertTrue(case["passed"] and case["rejected"] and case["outputAbsent"])
            self.assertTrue(case["directoryUnchanged"])
            self.assertEqual(case["dependentWorkCalls"], 0)
        grade = row["grade"]
        self.assertTrue(grade["passed"])
        self.assertEqual(
            grade["decodedChangedFrames"], row["source"]["decodedFrames"])
        self.assertTrue(grade["forcedFullOracle"]["passed"])
        self.assertTrue(grade["forcedFullOracle"]["decodedAudioMatch"])
        self.assertTrue(grade["forcedFullOracle"]["streamFactsMatch"])
        self.assertEqual(len(grade["fullDecode"]), 3)
        self.assertTrue(all(item["decodedFrames"] == 120 for item in grade["fullDecode"]))


class CardGeometryMeasurementTests(unittest.TestCase):
    """Artwork measurement must reject blank, misplaced and incomplete frames."""

    def _frame(self, offset: int = 0) -> np.ndarray:
        """Build a white card separated from white canvas by its dark shadow."""
        rgb = np.full((1920, 1080, 3), 255, dtype=np.uint8)
        rgb[742:968, 50 + offset:940 + offset] = 220
        rgb[752:958, 60 + offset:930 + offset] = 251
        rgb[825:885, 300 + offset:600 + offset] = 11
        return rgb

    def _measure(self, rgb: np.ndarray) -> dict:
        """Exercise the actual pixel measurement with a controlled decoded frame."""
        with patch("tests.p4_exit_media._rgb_frame", return_value=(1080, 1920, rgb.tobytes())):
            return frame_card_geometry(Path("controlled-frame"), 24, 1)

    def test_shadow_isolates_card_from_white_video_canvas(self) -> None:
        result = self._measure(self._frame())
        self.assertTrue(result["passed"])
        self.assertEqual(result["whiteBBox"], [60, 752, 930, 958])

    def test_white_canvas_cannot_count_as_card(self) -> None:
        self.assertFalse(self._measure(np.full((1920, 1080, 3), 255, dtype=np.uint8))["passed"])

    def test_shifted_artwork_fails_authored_bounds(self) -> None:
        self.assertFalse(self._measure(self._frame(12))["passed"])

    def test_empty_card_fails_nonempty_text(self) -> None:
        rgb = self._frame()
        rgb[825:885, 300:600] = 251
        self.assertFalse(self._measure(rgb)["passed"])


if __name__ == "__main__":
    unittest.main()
