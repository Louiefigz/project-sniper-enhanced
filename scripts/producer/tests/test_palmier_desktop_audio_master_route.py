"""Adversarial Desktop worklist/readback tests for mastered-stereo."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from palmier.desktop_audio_authority import audio_authority_receipt
from palmier.desktop_audio_declaration import manifest_audio_authority
from palmier.desktop_audio_master_binding import (
    bind_mastered_stereo_operation, expected_route_args)
from palmier.desktop_audio_master_readback import \
    observe_mastered_stereo_operation
from palmier.desktop_bound_operations import recover_desktop_operation
from palmier.desktop_element_types import ElementObservation, RecoveryObservation
from palmier.mcp_client import PalmierError
from palmier.timeline_authority import snapshot

COVERAGE = {"complete": True}

class MasteredStereoRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.wav = root / "master.wav"
        self.final = root / "final.mp4"
        self.proof = root / "master.wav.proof.json"
        self.wav.write_bytes(b"pcm")
        self.final.write_bytes(b"final")
        self.proof.write_text("{}", encoding="utf-8")
        self.asset_hash = file_sha256(str(self.wav))
        self.step = {
            "op": "native-audio-master", "lane": "audio-master",
            "key": "mastered-stereo-authority",
            "elementId": "mastered-stereo-authority",
            "path": str(self.wav), "fileHash": self.asset_hash,
            "assetPath": str(self.wav), "assetHash": self.asset_hash,
            "startFrame": 0, "endFrame": 120,
            "sourceFinalPath": str(self.final),
            "sourceFinalHash": file_sha256(str(self.final)),
            "derivationProofPath": str(self.proof),
            "derivationProofHash": file_sha256(str(self.proof)),
            "pcm": {
                "codec": "pcm_s32le", "sampleFormat": "s32",
                "sampleRate": 48_000, "channels": 2,
                "channelLayout": "stereo", "decodedSamples": 240_000,
            },
            "projectFrameRate": "24/1",
            "importName": "Sniper · mastered stereo · test",
            "trackPolicy": "auto-create-dedicated-standalone-audio",
            "requiredNextOp": "mastered-stereo-route",
        }
        self.route_step = {
            "op": "mastered-stereo-route", "lane": "audio-master",
            "elementId": "mastered-stereo-authority",
            "mediaKey": "mastered-stereo-authority",
            "requiredPriorOp": "native-audio-master",
            "masterTrackFlags": {"muted": False, "syncLocked": True},
            "otherContentAudioFlags": {"muted": True},
            "trackPolicy": "fresh-content-bearing-audio-readback",
            "preserveExactMasterReference": True,
        }
        self.plan = root / "plan.json"
        self.plan.write_text(json.dumps({
            "audioAuthorityMode": "mastered-stereo"}), encoding="utf-8")
        self.operations = root / "operations.json"
        self.operations.write_text(json.dumps({
            "capability": {"audioAuthority": {
                "schemaVersion": 1, "mode": "mastered-stereo",
                "status": "ready", "blockerCode": None,
            }},
            "steps": [self.step, self.route_step],
        }), encoding="utf-8")
        self.state = {
            "operations": {
                "path": str(self.operations),
                "hash": file_sha256(str(self.operations)),
            },
            "mediaLedger": {
                self.asset_hash: {
                    "mediaRef": "master-media", "path": str(self.wav),
                },
            },
        }
        self.before = self._timeline()

    def tearDown(self) -> None:
        self.temp.cleanup()
    @staticmethod
    def _timeline() -> dict:
        return {
            "id": "candidate", "fps": 24, "width": 1920, "height": 1080,
            "totalFrames": 120, "tracks": [
                {"type": "video", "clips": [{
                    "id": "source-video", "mediaRef": "source",
                    "frames": [0, 120],
                    "audio": {"id": "source-audio", "track": 1},
                }]},
                {"type": "audio", "linkedClips": 1},
                {"type": "video", "hidden": True, "syncLocked": True,
                 "clips": [{
                     "id": "reference-video", "mediaRef": "reference",
                     "frames": [0, 120],
                     "audio": {"id": "reference-audio", "track": 3},
                 }]},
                {"type": "audio", "linkedClips": 1,
                 "muted": True, "syncLocked": True},
            ],
        }
    def _patched(self) -> ExitStack:
        stack = ExitStack()
        for target in (
            "palmier.desktop_audio_master_binding."
            "validate_mastered_stereo_assets",
            "palmier.desktop_audio_master_readback."
            "validate_mastered_stereo_assets",
            "palmier.desktop_audio_master_route."
            "validate_mastered_stereo_assets",
        ):
            stack.enter_context(patch(target, side_effect=lambda value: value))
        return stack

    def _add(self, state: dict | None = None,
             before: dict | None = None) -> tuple[dict, dict, dict]:
        target_state = state or self.state
        old = before or self.before
        after = copy.deepcopy(old)
        after["tracks"].append({
            "type": "audio", "clips": [{
                "id": "master-clip", "mediaRef": "master-media",
                "mediaType": "audio", "frames": [0, 120],
            }],
        })
        args = {"entries": [{
            "mediaRef": "master-media", "startFrame": 0, "endFrame": 120,
        }]}
        binding = bind_mastered_stereo_operation(
            "add_clips", args, target_state, old)
        pending = {"binding": binding, "tool": "add_clips"}
        observe_mastered_stereo_operation(ElementObservation(
            target_state, pending, old, after, {}, COVERAGE))
        return after, binding, pending

    @staticmethod
    def _routed(after_add: dict, args: dict) -> dict:
        result = copy.deepcopy(after_add)
        for row in args["set"]:
            track = result["tracks"][row["index"]]
            for key in ("muted", "syncLocked"):
                if row.get(key) is True:
                    track[key] = True
                elif row.get(key) is False:
                    track.pop(key, None)
        return result

    def _isolate(self, after_add: dict, state: dict | None = None) -> dict:
        target_state = state or self.state
        args = expected_route_args(target_state, after_add)
        binding = bind_mastered_stereo_operation(
            "manage_tracks", args, target_state, after_add)
        routed = self._routed(after_add, args)
        observe_mastered_stereo_operation(ElementObservation(
            target_state, {"binding": binding, "tool": "manage_tracks"},
            after_add, routed, {}, COVERAGE))
        return routed

    def test_declaration_is_ready_only_with_both_hash_bound_steps(self) -> None:
        ready = manifest_audio_authority(
            str(self.plan), [self.step, self.route_step])
        self.assertEqual((ready["status"], ready["blockerCode"]),
                         ("ready", None))
        blocked = manifest_audio_authority(str(self.plan), [self.step])
        self.assertEqual(blocked["blockerCode"],
                         "master-route-worklist-incomplete")
        forged = manifest_audio_authority(str(self.plan), [], True)
        self.assertEqual(forged["blockerCode"],
                         "master-route-worklist-incomplete")

    def test_import_add_isolate_yields_no_track_id_authority(self) -> None:
        expected_import = {
            "source": {"path": str(self.wav)},
            "name": self.step["importName"],
        }
        with self._patched():
            imported = bind_mastered_stereo_operation(
                "import_media", expected_import, self.state, self.before)
            self.assertEqual(imported["kind"], "resource")
            after_add, _binding, _pending = self._add()
            self.assertNotIn("audioAuthority", self.state)
            args = expected_route_args(self.state, after_add)
            self.assertEqual(args, {"set": [
                {"index": 1, "muted": True},
                {"index": 4, "muted": False, "syncLocked": True},
            ]})
            routed = self._isolate(after_add)
            route = self.state["audioAuthority"]["masterRoute"]
            self.assertIsNone(route["trackIdentity"]["id"])
            self.state["exactMasterReference"] = {
                "audioClipId": "reference-audio"}
            receipt = audio_authority_receipt(
                self.state, snapshot("project", routed))
            self.assertEqual(receipt["status"], "pass")

    def test_add_rejects_dirty_shared_track_wrong_window_and_partial_readback(
            self) -> None:
        with self._patched():
            after, binding, pending = self._add()
            dirty = copy.deepcopy(after)
            dirty["tracks"][4]["clips"].append({
                "id": "foreign", "mediaRef": "foreign",
                "mediaType": "audio", "frames": [0, 120],
            })
            fresh = copy.deepcopy(self.state)
            fresh.pop("audioMasterRoute")
            with self.assertRaisesRegex(PalmierError, "unrelated clip"):
                observe_mastered_stereo_operation(ElementObservation(
                    fresh, pending, self.before, dirty, {}, COVERAGE))
            wrong = copy.deepcopy(after)
            wrong["tracks"][4]["clips"][0]["frames"] = [0, 119]
            with self.assertRaisesRegex(PalmierError, "clean dedicated"):
                observe_mastered_stereo_operation(ElementObservation(
                    fresh, pending, self.before, wrong, {}, COVERAGE))
            with self.assertRaisesRegex(PalmierError, "incomplete"):
                observe_mastered_stereo_operation(ElementObservation(
                    fresh, pending, self.before, after, {},
                    {"complete": False}))

    def test_route_rejects_video_flag_drift_and_extra_audible_route(self) -> None:
        with self._patched():
            after_add, _binding, _pending = self._add()
            args = expected_route_args(self.state, after_add)
            binding = bind_mastered_stereo_operation(
                "manage_tracks", args, self.state, after_add)
            drifted = self._routed(after_add, args)
            drifted["tracks"][0]["hidden"] = True
            with self.assertRaisesRegex(PalmierError, "unrelated"):
                observe_mastered_stereo_operation(ElementObservation(
                    self.state, {"binding": binding}, after_add,
                    drifted, {}, COVERAGE))
            routed = self._isolate(after_add)
            extra = copy.deepcopy(routed)
            extra["tracks"][1].pop("muted")
            receipt = audio_authority_receipt(
                self.state, snapshot("project", extra))
            self.assertEqual(receipt["blockerCode"],
                             "multiple-audible-routes")

    def test_wrong_master_fails_but_empty_audio_track_is_not_a_route(self) -> None:
        with self._patched():
            after_add, _binding, _pending = self._add()
            routed = self._isolate(after_add)
            routed["tracks"].append({"type": "audio", "clips": []})
            receipt = audio_authority_receipt(
                self.state, snapshot("project", routed))
            self.assertEqual(receipt["status"], "pass")
            shared = copy.deepcopy(routed)
            shared["tracks"][0]["clips"][0]["audio"]["track"] = 4
            shared["tracks"][1]["linkedClips"] = 0
            receipt = audio_authority_receipt(self.state, snapshot("project", shared))
            self.assertEqual(receipt["blockerCode"], "contaminated-master-route")
            foreign = copy.deepcopy(self.state)
            foreign["audioAuthority"]["masterRoute"]["clipId"] = "wrong"
            receipt = audio_authority_receipt(
                foreign, snapshot("project", routed))
            self.assertEqual(receipt["blockerCode"], "foreign-master-binding")

    def test_recovery_and_replay_use_the_same_readback_contract(self) -> None:
        with self._patched():
            after_add = copy.deepcopy(self.before)
            after_add["tracks"].append({
                "type": "audio", "clips": [{
                    "id": "master-clip", "mediaRef": "master-media",
                    "mediaType": "audio", "frames": [0, 120],
                }],
            })
            args = {"entries": [{
                "mediaRef": "master-media",
                "startFrame": 0, "endFrame": 120,
            }]}
            binding = bind_mastered_stereo_operation(
                "add_clips", args, self.state, self.before)
            recover_desktop_operation(RecoveryObservation(
                self.state, {"binding": binding}, self.before, after_add,
                object(), coverage=COVERAGE))
            route_args = expected_route_args(self.state, after_add)
            route_binding = bind_mastered_stereo_operation(
                "manage_tracks", route_args, self.state, after_add)
            routed = self._routed(after_add, route_args)
            recover_desktop_operation(RecoveryObservation(
                self.state, {"binding": route_binding}, after_add, routed,
                object(), coverage=COVERAGE))
            with self.assertRaisesRegex(PalmierError, "placed twice"):
                bind_mastered_stereo_operation(
                    "add_clips", args, self.state, routed)

if __name__ == "__main__":
    unittest.main(verbosity=2)
