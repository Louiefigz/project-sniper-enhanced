"""Manifest reachability tests for the mastered-stereo Desktop lane."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from palmier.desktop_audio_master_media import MasteredStereoAsset
from palmier.desktop_audio_master_plan import (
    MasteredStereoPlanRequest, prepare_mastered_stereo_steps,
    preserved_mastered_stereo_authority)
from palmier.desktop_bound_operations import bind_desktop_operation
from palmier.desktop_manifest import prepare_desktop_manifest
from palmier.desktop_state import DesktopStageInput
from palmier.master import MasterFacts
from palmier.mcp_client import PalmierError


def _write_json(path: str, value: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle)


def _preserved_route(root: str, frames: int = 240) -> dict:
    wav = os.path.join(root, "master.wav")
    final = os.path.join(root, "final.mp4")
    proof = os.path.join(root, "master.proof.json")
    for path, value in ((wav, b"pcm"), (final, b"final"), (proof, b"proof")):
        with open(path, "wb") as handle:
            handle.write(value)
    return {
        "routeKind": "standalone-audio",
        "elementId": "mastered-stereo-authority",
        "assetHash": file_sha256(wav), "assetPath": wav,
        "sourceFinalPath": final, "sourceFinalHash": file_sha256(final),
        "derivationProofPath": proof,
        "derivationProofHash": file_sha256(proof),
        "pcm": {
            "codec": "pcm_s32le", "sampleFormat": "s32",
            "sampleRate": 48_000, "channels": 2,
            "channelLayout": "stereo",
            "decodedSamples": frames * 2_000,
        },
        "projectFrameRate": "24/1", "mediaRef": "master-media",
        "clipId": "master-clip", "startFrame": 0, "endFrame": frames,
        "trackIdentity": {"id": None, "indexAtBinding": 4},
    }


def _prior_worklist(root: str, route: dict) -> dict:
    keys = (
        "assetPath", "assetHash", "sourceFinalPath", "sourceFinalHash",
        "derivationProofPath", "derivationProofHash", "pcm",
        "projectFrameRate", "startFrame", "endFrame",
    )
    placement = {"op": "native-audio-master"}
    placement.update({key: route[key] for key in keys})
    path = os.path.join(root, "prior-operations.json")
    _write_json(path, {
        "capability": {"audioAuthority": {
            "schemaVersion": 1, "mode": "mastered-stereo",
            "status": "ready", "blockerCode": None,
        }},
        "steps": [placement],
    })
    return {"path": path, "hash": file_sha256(path)}


class MasteredStereoManifestTests(unittest.TestCase):
    def test_visual_manifest_orders_complete_audio_lane_last(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.mp4")
            wav = os.path.join(tmp, "master.wav")
            proof = wav + ".proof.json"
            for path, data in ((source, b"final"), (wav, b"pcm"),
                               (proof, b"proof")):
                with open(path, "wb") as handle:
                    handle.write(data)
            plan_path = os.path.join(tmp, "edit_plan.json")
            manifest_path = os.path.join(tmp, "asset_manifest.json")
            with open(plan_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "target": {"mode": "longform"},
                    "audioAuthorityMode": "mastered-stereo",
                    "cutTrack": [{
                        "sourceId": "src", "start": 0, "end": 5,
                    }],
                }, handle)
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump({"sources": [{
                    "id": "src", "role": "primary", "path": source,
                    "fps": 24, "resolution": [1920, 1080],
                }]}, handle)
            inputs = DesktopStageInput(
                tmp, tmp, plan_path, manifest_path, "visual")
            master = MasterFacts(
                source, file_sha256(source), 5.0, 24.0,
                1920, 1080, 120, "24/1")
            asset = MasteredStereoAsset(
                wav, file_sha256(wav), source, file_sha256(source),
                proof, file_sha256(proof), {
                    "codec": "pcm_s32le", "sampleFormat": "s32",
                    "sampleRate": 48_000, "channels": 2,
                    "channelLayout": "stereo",
                    "decodedSamples": 240_000,
                }, "24/1", 120)
            probe = SimpleNamespace(
                audio_present=True, audio_channels=2,
                audio_sample_rate=48_000)
            project = {"projectName": "demo", "projectSettings": {
                "fps": 24, "width": 1920, "height": 1080}}
            with patch(
                    "palmier.desktop_frame_authority.approved_master",
                    return_value=master), patch(
                    "palmier.desktop_exact_master_plan.approved_master",
                    return_value=master), patch(
                        "palmier.desktop_exact_master_plan.probe_media",
                        return_value=probe), patch(
                            "palmier.desktop_audio_master_plan."
                            "prepare_mastered_stereo_asset",
                            return_value=asset):
                content = prepare_desktop_manifest(
                    inputs, project)["content"]
            ops = [row["op"] for row in content["steps"]]
            self.assertEqual(ops[-2:], [
                "native-audio-master", "mastered-stereo-route"])
            self.assertLess(
                ops.index("exact-master-reference-disable"),
                ops.index("native-audio-master"))
            declaration = content["capability"]["audioAuthority"]
            self.assertEqual((declaration["status"],
                              declaration["blockerCode"]), ("ready", None))
            placement = content["steps"][-2]
            self.assertEqual(placement["fileHash"], placement["assetHash"])

    def test_later_stage_reuses_only_a_fresh_timing_compatible_asset(self) -> None:
        route = {
            "routeKind": "standalone-audio", "assetPath": "/tmp/master.wav",
            "assetHash": "a" * 64, "sourceFinalPath": "/tmp/final.mp4",
            "sourceFinalHash": "b" * 64,
            "derivationProofPath": "/tmp/master.wav.proof.json",
            "derivationProofHash": "c" * 64,
            "pcm": {"decodedSamples": 240_000},
            "elementId": "mastered-stereo-authority",
            "projectFrameRate": "24/1", "startFrame": 0, "endFrame": 120,
            "mediaRef": "master-media", "clipId": "master-clip",
            "trackIdentity": {"id": None, "indexAtBinding": 4},
        }
        request = MasteredStereoPlanRequest(
            {"audioAuthorityMode": "mastered-stereo"}, SimpleNamespace(),
            SimpleNamespace(), {
                "projectSettings": {"fps": 24},
                "audioAuthority": {
                    "mode": "mastered-stereo", "masterRoute": route,
                },
            }, 120, "/tmp/cache")
        with patch(
                "palmier.desktop_audio_master_plan."
                "validate_mastered_stereo_assets",
                side_effect=lambda value: value), patch(
                    "palmier.desktop_audio_master_plan."
                    "prepare_mastered_stereo_asset",
                    side_effect=AssertionError("must preserve current asset")):
            steps = prepare_mastered_stereo_steps(request)
        self.assertEqual(steps, [])

    def test_repair_preserves_hash_bound_route_and_is_visual_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.mp4")
            graphic = os.path.join(tmp, "new.mov")
            for path, value in ((source, b"source"), (graphic, b"graphic")):
                with open(path, "wb") as handle:
                    handle.write(value)
            old_path, new_path = (
                os.path.join(tmp, "old.json"), os.path.join(tmp, "new.json"))
            old = {
                "target": {"mode": "longform"},
                "audioAuthorityMode": "mastered-stereo",
                "cutTrack": [{"sourceId": "src", "start": 0, "end": 10}],
                "graphicsTrack": [{
                    "id": "graphic-1", "kind": "statement-card",
                    "outStart": 1, "outEnd": 4, "spec": {"text": "Before"},
                }],
            }
            new = copy.deepcopy(old)
            new["graphicsTrack"][0]["spec"]["text"] = "After"
            _write_json(old_path, old)
            _write_json(new_path, new)
            manifest_path = os.path.join(tmp, "manifest.json")
            _write_json(manifest_path, {"sources": [{
                "id": "src", "role": "primary", "path": source,
                "fps": 24, "resolution": [1920, 1080],
            }]})
            route = _preserved_route(tmp)
            project = {
                "projectName": "demo", "projectSettings": {
                    "fps": 24, "width": 1920, "height": 1080},
                "expectedFingerprint": "d" * 64,
                "plan": {"path": old_path, "hash": file_sha256(old_path)},
                "operations": _prior_worklist(tmp, route),
                "audioAuthority": {
                    "schemaVersion": 1, "mode": "mastered-stereo",
                    "masterRoute": route,
                },
                "exactMasterReference": {
                    "status": "ready", "startFrame": 0, "endFrame": 240,
                    "hidden": True, "muted": True,
                    "assetPath": route["sourceFinalPath"],
                    "assetHash": route["sourceFinalHash"],
                },
                "elementLedger": {"schemaVersion": 1, "elements": {
                    "graphic-1": {
                        "status": "current", "lane": "graphics",
                        "clipId": "old-card", "mediaRef": "old-media",
                        "assetHash": "old", "assetPath": "/old.mov",
                        "startFrame": 24, "endFrame": 96, "trackIndex": 0,
                    },
                }},
            }
            rendered = {
                "path": graphic, "cached": False, "key": "render-key",
                "kind": "statement-card", "fmt": "mov",
                "proof": {"schemaVersion": 1},
            }
            with open(graphic + ".placement.json", "w",
                      encoding="utf-8") as handle:
                json.dump({"schemaVersion": 1}, handle)
            inputs = DesktopStageInput(
                tmp, tmp, new_path, manifest_path, "repair")
            with patch(
                    "palmier.desktop_audio_master_plan."
                    "validate_mastered_stereo_assets",
                    side_effect=lambda value: value), patch(
                        "palmier.desktop_frame_authority."
                        "validate_mastered_stereo_assets",
                        side_effect=lambda value: value), patch(
                        "palmier.desktop_repair.render_entry",
                        return_value=rendered), patch(
                            "palmier.desktop_repair.bake_rendered_graphic",
                            return_value=rendered):
                content = prepare_desktop_manifest(
                    inputs, project)["content"]
            self.assertEqual(
                [row["op"] for row in content["steps"]],
                ["import", "replace-overlay"])
            proof = content["capability"]["preservedMasteredStereoAuthority"]
            self.assertEqual(proof["route"], route)
            self.assertEqual(content["capability"]["audioAuthority"]["status"],
                             "ready")

    def test_preservation_rejects_tampered_route_and_timing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            route = _preserved_route(tmp)
            request = MasteredStereoPlanRequest(
                {"audioAuthorityMode": "mastered-stereo"},
                SimpleNamespace(), SimpleNamespace(), {
                    "projectSettings": {"fps": 24},
                    "expectedFingerprint": "d" * 64,
                    "operations": _prior_worklist(tmp, route),
                    "audioAuthority": {
                        "mode": "mastered-stereo", "masterRoute": route,
                    },
                }, 240, tmp)
            with patch(
                    "palmier.desktop_audio_master_plan."
                    "validate_mastered_stereo_assets",
                    side_effect=lambda value: value):
                changed = copy.deepcopy(request.project)
                changed["audioAuthority"]["masterRoute"][
                    "assetHash"] = "e" * 64
                bad_route = MasteredStereoPlanRequest(
                    request.plan, request.inputs, request.authority,
                    changed, request.target_frames, request.cache_dir)
                with self.assertRaisesRegex(PalmierError, "prior worklist"):
                    preserved_mastered_stereo_authority(bad_route)
                timing = copy.deepcopy(request.project)
                timing["audioAuthority"]["masterRoute"]["endFrame"] = 241
                bad_timing = MasteredStereoPlanRequest(
                    request.plan, request.inputs, request.authority,
                    timing, request.target_frames, request.cache_dir)
                with self.assertRaisesRegex(PalmierError, "project timing"):
                    preserved_mastered_stereo_authority(bad_timing)

    def test_unbound_manage_tracks_is_never_a_generic_mutation(self) -> None:
        with self.assertRaisesRegex(PalmierError, "unbound"):
            bind_desktop_operation("manage_tracks", {"set": []}, {}, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
