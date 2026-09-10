"""Freshness and exact-threshold gate for retained P5 review evidence."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from current_render_graph_contract import file_hash
from current_render_toolchain import current_toolchain_hash
from tests.live_p5_review_repair_acceptance import CLOSURE, REPO
from tests.p4_exit_media import source_closure, toolchain

ARTIFACT = REPO / (
    "docs/producer/command-driven-editing/contracts/"
    "p5-one-unit-review-repair-v1.json")


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _strings(child)]
    return []


class P5ReviewRepairArtifactTests(unittest.TestCase):
    def test_retained_review_repair_is_fresh_and_load_bearing(self) -> None:
        value = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(set(value), {
            "schemaVersion", "kind", "generatedAt", "execution",
            "elapsedSeconds", "resourceUsage", "sourceClosure", "toolchain",
            "evidence", "nonClaims", "passed",
        })
        self.assertEqual(
            value["kind"], "p5-lf14-50-scene-review-repair")
        self.assertTrue(value["passed"])
        self.assertEqual(value["toolchain"], toolchain())
        expected_toolchain = current_toolchain_hash()
        for label in ("first", "replay"):
            with self.subTest(implementation=label):
                self._assert_implementation(
                    value["evidence"][label]["implementation"],
                    expected_toolchain,
                )
        self.assertEqual(
            value["sourceClosure"], source_closure(REPO, CLOSURE))
        self.assertGreaterEqual(len(value["sourceClosure"]), 100)
        self.assertFalse(any(
            "/private/var/folders/" in text
            or "/tmp/sniper-p5-review-" in text
            for text in _strings(value)))
        self._assert_first(value["evidence"]["first"])
        self._assert_replay(value["evidence"]["replay"])
        self._assert_project(value["evidence"])
        self._assert_performance(value)
        self._assert_forced(value["evidence"])

    def _assert_implementation(
        self,
        implementation: dict,
        expected_toolchain: str,
    ) -> None:
        self.assertEqual(
            implementation["producerRenderToolchainHash"],
            expected_toolchain,
        )
        files = implementation["files"]
        self.assertIn("cross_runtime_canonical_json.py", files)
        producer = REPO / "scripts" / "producer"
        for relative, digest in files.items():
            with self.subTest(implementation_file=relative):
                self.assertEqual(digest, file_hash(producer / relative))

    def _assert_first(self, row: dict) -> None:
        fanout = row["projectFanout"]
        self.assertEqual(fanout["durationFrames"], 25_200)
        self.assertEqual(fanout["sceneCount"], 50)
        self.assertEqual(fanout["dirtySceneIds"], ["scene-045"])
        self.assertEqual(fanout["dirtySceneCount"], 1)
        self.assertEqual(fanout["reusedSceneCount"], 49)
        self.assertEqual(row["unitWork"], {
            "logicalDirtyUnitIds": ["unit-right"],
            "renderedUnitIds": ["unit-right"],
            "reusedUnitIds": ["unit-left"],
        })
        self.assertEqual(row["execution"]["unitRenderCount"], 1)
        self.assertEqual(row["execution"]["unitReuseCount"], 1)
        self.assertEqual(row["execution"]["fullBaseEncodeCount"], 0)
        self.assertEqual(row["execution"]["fullDurationOutputCount"], 0)
        self.assertEqual(row["promotion"]["activeMutationCount"], 0)
        self.assertEqual(
            row["channelNormalization"]["status"], "stereo-verified")
        self.assertTrue(row["baseUnchanged"])
        self.assertRegex(row["baseIdentity"]["mtimeNs"], r"^[0-9]+$")
        self.assertRegex(row["reviewIdentity"]["mtimeNs"], r"^[0-9]+$")
        self.assertEqual(row["decode"]["decodedFrames"], 180)
        self.assertEqual(
            row["decode"]["decodedSamplesPerChannel"], 288_000)
        self.assertEqual(row["decode"]["audioStreamCount"], 1)
        self.assertEqual(row["decode"]["fullDecode"], "ffmpeg-xerror-av-v1")
        self.assertEqual(row["bindingDelta"], {
            "actions": ["replace-media"],
            "bindingIds": ["scene-045-unit-right"],
            "preserved": ["scene-045-unit-left"],
        })
        self.assertGreaterEqual(
            len(row["implementation"]["files"]), 14)
        self.assertEqual(
            len(row["implementation"]["producerRenderToolchainHash"]), 64)

    def _assert_replay(self, row: dict) -> None:
        self.assertEqual(row["unitWork"]["logicalDirtyUnitIds"], ["unit-right"])
        self.assertEqual(row["unitWork"]["renderedUnitIds"], [])
        self.assertEqual(
            row["unitWork"]["reusedUnitIds"],
            ["unit-left", "unit-right"])
        self.assertEqual(row["execution"]["unitRenderCount"], 0)
        self.assertEqual(row["execution"]["fullBaseEncodeCount"], 0)
        self.assertEqual(row["promotion"]["activeMutationCount"], 0)

    def _assert_project(self, evidence: dict) -> None:
        project = evidence["project"]
        self.assertEqual(project["durationSeconds"], 840)
        self.assertEqual(project["durationFrames"], 25_200)
        self.assertEqual(project["sceneCount"], 50)
        self.assertEqual(project["validatedPackageCount"], 50)
        self.assertEqual(project["targetSceneId"], "scene-045")
        self.assertEqual(project["baseDecode"], {
            "width": 1920, "height": 1080, "pixelFormat": "yuv420p",
            "frameRate": "30/1", "decodedFrames": 25_200,
            "audio": {"sampleRate": 48_000, "channels": 2},
        })

    def _assert_performance(self, value: dict) -> None:
        stages = value["evidence"]["stageElapsedSeconds"]
        self.assertEqual(set(stages), {
            "basePreparation", "initialSceneRender",
            "projectAuthorityAndBaseProbe", "firstReviewRepair",
            "replayReview", "forcedControlAndOracle",
        })
        self.assertTrue(all(
            isinstance(seconds, (int, float)) and seconds > 0
            for seconds in stages.values()))
        self.assertLessEqual(stages["firstReviewRepair"], 120)
        usage = value["resourceUsage"]
        self.assertEqual(set(usage), {
            "processUserCpuSeconds", "processSystemCpuSeconds",
            "childUserCpuSeconds", "childSystemCpuSeconds",
            "processMaxRssBytes", "childMaxRssBytes",
        })
        self.assertTrue(all(amount >= 0 for amount in usage.values()))
        self.assertGreater(usage["childMaxRssBytes"], 0)

    def _assert_forced(self, evidence: dict) -> None:
        self.assertTrue(evidence["approvedBaseUnchanged"])
        self.assertFalse(evidence["forcedFullScene"]["cached"])
        oracle = evidence["forcedFullSceneWindowOracle"]
        self.assertTrue(oracle["passed"])
        self.assertTrue(oracle["decodedAudioMatch"])
        self.assertTrue(oracle["streamFactsMatch"])
        self.assertEqual(oracle["incrementalFrames"], 180)
        self.assertEqual(oracle["forcedFrames"], 180)
        metrics = oracle["pictureComparison"]["metrics"]
        self.assertGreaterEqual(metrics["meanSsim"], 0.995)
        self.assertGreaterEqual(metrics["minimumFrameSsim"], 0.985)


if __name__ == "__main__":
    unittest.main()
