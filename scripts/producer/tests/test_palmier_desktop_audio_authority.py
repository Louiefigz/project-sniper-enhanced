"""Adversarial local proof for Desktop audible-route authority."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from palmier.desktop_audio_authority import (audio_authority_receipt,
                                             require_audio_authority)
from palmier.desktop_authority import run_qc
from palmier.desktop_state import JOURNAL_NAME, now, save_state
from palmier.mcp_client import PalmierError
from palmier.timeline_authority import snapshot


class DesktopAudioAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.root = root
        self.master = root / "master.mp4"
        self.master.write_bytes(b"bound-master")
        self.digest = file_sha256(str(self.master))
        self.operations = root / "operations.json"
        self.timeline = {
            "id": "candidate", "fps": 24, "width": 1920, "height": 1080,
            "totalFrames": 120,
            "tracks": [
                {"id": "master-video-track", "type": "video", "clips": [{
                    "id": "master-video", "mediaRef": "master-media",
                    "frames": [0, 120],
                    "audio": {"id": "master-audio", "track": 1},
                }]},
                {"id": "master-audio-track", "type": "audio",
                 "linkedClips": 1},
            ],
        }
        self.state = {
            "audioAuthority": {
                "schemaVersion": 1, "mode": "mastered-stereo",
                "masterRoute": {
                    "assetHash": self.digest, "mediaRef": "master-media",
                    "clipId": "master-video", "audioClipId": "master-audio",
                    "trackId": "master-audio-track",
                },
            },
            "mediaLedger": {
                self.digest: {
                    "mediaRef": "master-media", "path": str(self.master),
                },
            },
        }
        self._declaration("mastered-stereo", "ready", None)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _found(self, timeline: dict | None = None):
        return snapshot("project", timeline or self.timeline)

    def _declaration(self, mode: str, status: str,
                     blocker: str | None) -> None:
        self.operations.write_text(json.dumps({
            "capability": {"audioAuthority": {
                "schemaVersion": 1, "mode": mode, "status": status,
                "blockerCode": blocker,
            }},
        }), encoding="utf-8")
        self.state["operations"] = {
            "path": str(self.operations),
            "hash": file_sha256(str(self.operations)),
        }

    def test_one_hash_and_id_bound_master_route_passes(self) -> None:
        receipt = require_audio_authority(self.state, self._found())
        self.assertEqual(receipt["status"], "pass")
        self.assertEqual(len(receipt["routes"]), 1)

    def test_two_audible_routes_fail_even_if_export_would_have_one_stream(
            self) -> None:
        timeline = copy.deepcopy(self.timeline)
        timeline["tracks"].extend([
            {"id": "source-video-track", "type": "video", "clips": [{
                "id": "source-video", "mediaRef": "source",
                "frames": [0, 120],
                "audio": {"id": "source-audio", "track": 3},
            }]},
            {"id": "source-audio-track", "type": "audio", "linkedClips": 1},
        ])
        receipt = audio_authority_receipt(self.state, self._found(timeline))
        self.assertEqual(receipt["blockerCode"], "multiple-audible-routes")
        with self.assertRaisesRegex(PalmierError, "multiple-audible-routes"):
            require_audio_authority(self.state, self._found(timeline))

    def test_one_route_cannot_hide_extra_audio_on_the_master_track(self) -> None:
        timeline = copy.deepcopy(self.timeline)
        timeline["tracks"][0]["clips"].append({
            "id": "foreign-video", "mediaRef": "foreign-media",
            "frames": [0, 120],
            "audio": {"id": "foreign-audio", "track": 1},
        })
        timeline["tracks"][1]["linkedClips"] = 2
        receipt = audio_authority_receipt(self.state, self._found(timeline))
        self.assertEqual(receipt["blockerCode"], "contaminated-master-route")

    def test_untyped_populated_track_cannot_be_ignored(self) -> None:
        timeline = copy.deepcopy(self.timeline)
        timeline["tracks"].append({
            "id": "unknown-track", "clips": [{
                "id": "unknown-clip", "mediaRef": "unknown",
                "frames": [0, 120],
            }],
        })
        receipt = audio_authority_receipt(self.state, self._found(timeline))
        self.assertEqual(
            receipt["blockerCode"], "routing-readback-unsupported")

    def test_missing_and_foreign_master_bindings_fail(self) -> None:
        missing = copy.deepcopy(self.state)
        missing.pop("audioAuthority")
        receipt = audio_authority_receipt(missing, self._found())
        self.assertEqual(receipt["blockerCode"], "missing-master-binding")
        foreign = copy.deepcopy(self.state)
        foreign["audioAuthority"]["masterRoute"]["clipId"] = "foreign"
        receipt = audio_authority_receipt(foreign, self._found())
        self.assertEqual(receipt["blockerCode"], "foreign-master-binding")

    def test_incomplete_readback_blocks_before_route_inference(self) -> None:
        timeline = copy.deepcopy(self.timeline)
        timeline["tracks"][0]["captionGroups"] = [{
            "clipCount": 201, "clips": [],
        }]
        receipt = audio_authority_receipt(self.state, self._found(timeline))
        self.assertEqual(receipt["blockerCode"], "incomplete-readback")

    def test_hidden_only_exact_reference_is_still_audible(self) -> None:
        timeline = copy.deepcopy(self.timeline)
        timeline["tracks"].extend([
            {"id": "reference-video-track", "type": "video",
             "hidden": True, "clips": [{
                 "id": "reference-video", "mediaRef": "reference",
                 "frames": [0, 120],
                 "audio": {"id": "reference-audio", "track": 3},
             }]},
            {"id": "reference-audio-track", "type": "audio",
             "linkedClips": 1},
        ])
        state = copy.deepcopy(self.state)
        state["exactMasterReference"] = {
            "status": "ready", "audioClipId": "reference-audio",
        }
        receipt = audio_authority_receipt(state, self._found(timeline))
        self.assertEqual(receipt["blockerCode"], "audible-exact-reference")

    def test_editable_stems_is_an_explicit_local_blocker(self) -> None:
        self._declaration(
            "editable-stems", "blocked", "routing-readback-unsupported")
        receipt = audio_authority_receipt(self.state, self._found())
        self.assertEqual(
            receipt["blockerCode"], "routing-readback-unsupported")

    def test_desktop_qc_blocks_before_exporting_unproved_stems(self) -> None:
        self._declaration(
            "editable-stems", "blocked", "routing-readback-unsupported")
        repo = self.root / "repo"
        repo.mkdir()
        journal = self.root / JOURNAL_NAME
        journal.write_text("", encoding="utf-8")
        found = self._found()
        state = {
            **self.state,
            "schemaVersion": 1, "kind": "palmier-desktop-authority",
            "status": "active", "stage": "visual",
            "outDir": str(self.root), "projectId": "project",
            "candidate": {
                "projectId": "project", "timelineId": "candidate",
                "fingerprint": found.fingerprint,
            },
            "expectedFingerprint": found.fingerprint,
            "journalPath": str(journal), "operationCount": 0,
            "verifiedOperationKeys": [], "pendingOperation": None,
            "updatedAt": now(),
        }
        save_state(str(repo), state)

        class Client:
            def call_json(_self, tool: str, _args: object = None) -> dict:
                if tool == "get_projects":
                    return {"projects": [{
                        "id": "project", "isActive": True,
                    }]}
                if tool == "get_timeline":
                    return copy.deepcopy(self.timeline)
                raise AssertionError(tool)

        with patch("palmier.native_qc_export.export_candidate") as export:
            with self.assertRaisesRegex(
                    PalmierError, "routing-readback-unsupported"):
                run_qc(Client(), str(repo))
            export.assert_not_called()


if __name__ == "__main__":
    unittest.main()
