"""Strict scene-authoring packet and attempt boundary tests."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from graphics.scene_authoring_stage import stage_scene_authoring
from graphics.scene_contract import SceneContractError, canonical_json
from graphics.scene_package_cli import run


def _packet() -> dict:
    return {
        "schemaVersion": 1, "attemptId": "attempt-scene-045",
        "brief": "Blue fire card left; sparkling title card right.",
        "sceneAuthority": {
            "sceneId": "scene-045",
            "timing": {
                "startFrame": 1350, "endFrameExclusive": 1530,
                "fps": {"numerator": "30", "denominator": "1"},
                "timelineMapHash": "a" * 64,
            },
            "durationFrames": 180,
            "canvas": {"width": 1920, "height": 1080},
            "renderMode": "overlay-alpha",
            "captionPolicy": "suppress-overlap",
            "provenance": {
                "origin": "reference-style",
                "requestId": "request-fire-sparkles",
                "stylePackHash": "b" * 64,
            },
        },
        "brandTokens": {"accent": "#054BC9", "cornerRadius": 28},
        "approvedAssets": [{
            "assetId": "fire-texture", "sha256": "c" * 64,
            "mime": "image/png", "bundleMember": "media/fire.png",
        }],
        "examples": [{
            "bundleId": "verified-example", "bundleHash": "d" * 64,
        }],
        "constraints": {
            "hyperframesVersion": "0.7.33",
            "declaredVariables": True, "pausedSeekableTimeline": True,
            "rootDuration": True, "deterministicSeed": True,
            "vendoredRuntimeOnly": True, "renderTimeNetwork": False,
        },
    }


class SceneAuthoringStageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_stage_is_owned_but_does_not_overclaim_isolation(self) -> None:
        attempt = self.root / "attempt"
        receipt = stage_scene_authoring(_packet(), str(attempt))
        self.assertEqual(
            stat.S_IMODE(attempt.stat().st_mode), 0o700)
        boundary = receipt["filesystemBoundary"]
        self.assertTrue(boundary["attemptOwned"])
        self.assertTrue(boundary["applicationPathContractOnly"])
        self.assertFalse(boundary["osSandboxProved"])
        self.assertFalse(boundary["modelWriteIsolationProved"])
        packet_path = attempt / "authoring-packet.json"
        stored = json.loads(packet_path.read_text(encoding="utf-8"))
        self.assertEqual(stored, _packet())
        stage_receipt = json.loads(
            (attempt / "stage-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(
            canonical_json(stage_receipt), canonical_json(receipt))

    def test_runtime_versions_are_preserved_in_staged_packets(self) -> None:
        """Staging keeps old declarations truthful and accepts the new target."""
        for version in ("0.7.33", "0.8.31"):
            packet = _packet()
            packet["constraints"]["hyperframesVersion"] = version
            before = canonical_json(packet)
            attempt = self.root / f"runtime-{version}"
            stage_scene_authoring(packet, str(attempt))
            stored = json.loads((attempt / "authoring-packet.json").read_text())
            self.assertEqual(canonical_json(stored), before)
            self.assertEqual(canonical_json(packet), before)

    def test_unsupported_runtime_fails_before_staging(self) -> None:
        """Reject unknown versions and typed lookalikes without reserving work."""
        for index, version in enumerate((
                None, True, 8.31, "0.7.34", "0.8.30", "^0.8.31", "0.8.31 ", {})):
            packet = _packet()
            packet["constraints"]["hyperframesVersion"] = version
            attempt = self.root / f"invalid-{index}"
            with self.assertRaisesRegex(SceneContractError, "schema"):
                stage_scene_authoring(packet, str(attempt))
            self.assertFalse(attempt.exists())

    def test_invalid_packet_fails_before_reserving_attempt(self) -> None:
        packet = _packet()
        packet["sceneAuthority"]["durationFrames"] = 179
        attempt = self.root / "bad-attempt"
        with self.assertRaisesRegex(SceneContractError, "durationFrames"):
            stage_scene_authoring(packet, str(attempt))
        self.assertFalse(attempt.exists())
        odd = _packet()
        odd["sceneAuthority"]["canvas"]["width"] = 1919
        with self.assertRaisesRegex(SceneContractError, "even"):
            stage_scene_authoring(odd, str(self.root / "odd-attempt"))
        unreduced = _packet()
        unreduced["sceneAuthority"]["timing"]["fps"] = {
            "numerator": "60", "denominator": "2",
        }
        with self.assertRaisesRegex(SceneContractError, "reduced"):
            stage_scene_authoring(
                unreduced, str(self.root / "unreduced-attempt"))

    def test_attempt_is_never_reused_and_cli_requires_canonical_input(self) -> None:
        packet_path = self.root / "packet.json"
        packet_path.write_text(json.dumps(_packet()), encoding="utf-8")
        attempt = self.root / "cli-attempt"
        receipt = run([
            "stage-authoring", str(packet_path),
            "--attempt-dir", str(attempt),
        ])
        self.assertEqual(receipt["kind"], "scene-authoring-stage")
        with self.assertRaisesRegex(SceneContractError, "unused"):
            stage_scene_authoring(_packet(), str(attempt))
        relative = os.path.relpath(packet_path, Path.cwd())
        with self.assertRaisesRegex(SceneContractError, "canonical"):
            run([
                "stage-authoring", relative,
                "--attempt-dir", str(self.root / "relative"),
            ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
