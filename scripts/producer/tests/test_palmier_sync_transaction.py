"""Palmier sync transaction activation, verification, and rollback tests."""
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from palmier.mcp_client import PalmierError
from palmier.shadow import SyncRequest
from palmier.sync import lane_fingerprints, parse_steps, run_sync
from palmier.timeline_authority import record_authority, snapshot


STEPS = [
    {"op": "project", "name": "target", "fps": 24,
     "width": 1920, "height": 1080, "mirrorMode": "visual-master",
     "masterHash": "master-hash"},
    {"op": "import", "key": "master", "path": "/approved/final.mp4"},
    {"op": "mirror", "entry": {
        "mediaKey": "master", "source": [0.0, 1.0],
        "startFrame": 0, "endFrame": 24, "speed": 1.0,
        "masterHash": "master-hash"}},
]
MIRROR_PARITY = {"schemaVersion": 1, "fullyEditable": False,
                 "mirrorReady": True, "mirrorMode": "visual-master"}


class SyncClient:
    def __init__(self):
        self.active_timeline = "human"
        self.timelines = {"human": "Human Cut"}
        self.calls = []

    def call_json(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        if tool == "get_projects":
            return {"active": {"name": "target", "path": "/target.palmier"},
                    "projects": [{"id": "project", "name": "target",
                                  "path": "/target.palmier", "isActive": True}]}
        if tool == "get_timeline":
            return {"id": self.active_timeline,
                    "name": self.timelines[self.active_timeline],
                    "fps": 24, "width": 1920, "height": 1080,
                    "totalFrames": 0, "tracks": []}
        if tool == "create_timeline":
            self.active_timeline = "shadow"
            self.timelines["shadow"] = arguments["name"]
            return {"timelineId": "shadow"}
        if tool == "get_media":
            return {"timelines": [
                {"timelineId": key, "name": value,
                 "active": key == self.active_timeline}
                for key, value in self.timelines.items()]}
        raise AssertionError(tool)

    def call(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        if tool == "set_active_timeline":
            self.active_timeline = arguments["timelineId"]
        elif tool == "organize_media":
            for rename in arguments.get("renames", []):
                self.timelines[rename["item"]] = rename["name"]
        return "ok"


def _bindings(*_args):
    return SimpleNamespace(refs={"master": "master-ref"},
                           seconds={"master": 1.0},
                           media_map={"master:master-hash": {
                               "ref": "master-ref", "seconds": 1.0}},
                           component_status={})


def _executor():
    return SimpleNamespace(expected_end_frame=24, project_fps=24)


def _verification(*_args):
    return {"ok": True, "verifiedAt": "2026-07-12T18:00:00+00:00",
            "timelineId": "shadow", "expected": {"totalFrames": 24},
            "actual": {"totalFrames": 24},
            "visualMaster": {"mediaRef": "master-ref",
                             "masterHash": "master-hash",
                             "singleVisibleClip": True}}


class SyncTransactionTests(unittest.TestCase):
    def run_transaction(self, tmp: str, verification=_verification):
        client = SyncClient()
        request = SyncRequest(tmp, "source-hash", "plan-hash", MIRROR_PARITY,
                              master_path="/approved/final.mp4",
                              master_hash="master-hash")
        with patch("palmier.sync.ensure_mirror_bindings",
                   side_effect=_bindings), \
                patch("palmier.sync.validate_mirror_request"), \
                patch("palmier.sync.validate_master_binding"), \
                patch("palmier.sync._apply_all", return_value=_executor()), \
                patch("palmier.sync.verify_generated_timeline",
                      side_effect=verification):
            run_sync(client, STEPS, request)
        return client

    def test_success_persists_proof_and_leaves_generated_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self.run_transaction(tmp)
            self.assertEqual(client.active_timeline, "shadow")
            with open(os.path.join(tmp, "palmier.sync.json")) as handle:
                state = json.load(handle)
            self.assertEqual(state["latestTimelineId"], "shadow")
            self.assertEqual(state["parity"], MIRROR_PARITY)
            self.assertEqual(state["ownership"], "sniper")
            self.assertEqual(state["mirrorMode"], "visual-master")
            self.assertTrue(state["verification"]["ok"])
            self.assertEqual(state["verification"]["planHash"], "plan-hash")
            self.assertEqual(state["timelineIds"][0]["status"], "ready")

    def test_failed_verification_restores_human_and_quarantines_shadow(self):
        def rejected(*_args):
            raise PalmierError("structural mismatch")

        with tempfile.TemporaryDirectory() as tmp:
            client = SyncClient()
            request = SyncRequest(tmp, "source-hash", "plan-hash", MIRROR_PARITY,
                                  master_path="/approved/final.mp4",
                                  master_hash="master-hash")
            with patch("palmier.sync.ensure_mirror_bindings",
                       side_effect=_bindings), \
                    patch("palmier.sync.validate_mirror_request"), \
                    patch("palmier.sync.validate_master_binding"), \
                    patch("palmier.sync._apply_all", return_value=_executor()), \
                    patch("palmier.sync.verify_generated_timeline",
                          side_effect=rejected):
                with self.assertRaisesRegex(PalmierError, "structural mismatch"):
                    run_sync(client, STEPS, request)
            self.assertEqual(client.active_timeline, "human")
            self.assertTrue(client.timelines["shadow"].endswith("-FAILED"))
            self.assertFalse(os.path.exists(os.path.join(tmp, "palmier.sync.json")))

    def test_sync_rejects_an_unsafe_mirror_checkpoint(self):
        client = SyncClient()
        request = SyncRequest(
            "/tmp", "source-hash", "plan-hash",
            {"schemaVersion": 1, "fullyEditable": False,
             "mirrorReady": False}, master_path="/approved/final.mp4",
            master_hash="master-hash")
        with self.assertRaisesRegex(PalmierError, "safe parity"):
            with patch("palmier.sync.validate_mirror_request"):
                run_sync(client, STEPS, request)
        self.assertEqual(client.calls, [])

    def test_palmier_ownership_blocks_automatic_sniper_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "palmier.sync.json"), "w") as handle:
                json.dump({"ownership": "palmier"}, handle)
            client = SyncClient()
            request = SyncRequest(
                tmp, "source-hash", "plan-hash", MIRROR_PARITY,
                master_path="/approved/final.mp4", master_hash="master-hash")
            with patch("palmier.sync.validate_mirror_request"):
                with self.assertRaisesRegex(PalmierError, "Palmier owns"):
                    run_sync(client, STEPS, request)
            self.assertEqual(client.calls, [])

    def test_up_to_date_sync_activates_the_verified_generated_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = SyncClient()
            client.timelines["shadow"] = "sniper-vplanhash"
            request = SyncRequest(tmp, "source-hash", "plan-hash", MIRROR_PARITY,
                                  master_path="/approved/final.mp4",
                                  master_hash="master-hash")
            lanes = parse_steps(STEPS)
            state = {
                "schemaVersion": 4, "ownership": "sniper",
                "mirrorMode": "visual-master", "projectId": "project",
                "projectName": "target", "projectPath": "/target.palmier",
                "lastPushPlanHash": "plan-hash",
                "laneFp": lane_fingerprints(lanes, "master-hash"),
                "parity": MIRROR_PARITY,
                "latestTimelineId": "shadow",
                "verification": {"ok": True, "timelineId": "shadow",
                                 "expected": {}, "actual": {},
                                 "visualMaster": {
                                     "masterHash": "master-hash"}},
            }
            with open(os.path.join(tmp, "palmier.sync.json"), "w") as handle:
                json.dump(state, handle)
            client.active_timeline = "shadow"
            record_authority(
                tmp, snapshot("project", client.call_json("get_timeline", {})),
                "sniper-bootstrap")
            with patch("palmier.sync.validate_mirror_request"):
                run_sync(client, STEPS, request)
            self.assertEqual(client.active_timeline, "shadow")

    def test_checkpoint_failure_restores_human_after_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = SyncClient()
            request = SyncRequest(tmp, "source-hash", "plan-hash", MIRROR_PARITY,
                                  master_path="/approved/final.mp4",
                                  master_hash="master-hash")
            with patch("palmier.sync.ensure_mirror_bindings",
                       side_effect=_bindings), \
                    patch("palmier.sync.validate_mirror_request"), \
                    patch("palmier.sync.validate_master_binding"), \
                    patch("palmier.sync._apply_all", return_value=_executor()), \
                    patch("palmier.sync.verify_generated_timeline",
                          side_effect=_verification), \
                    patch("palmier.sync._write_json_atomic",
                          side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    run_sync(client, STEPS, request)
            self.assertEqual(client.active_timeline, "human")
            self.assertTrue(client.timelines["shadow"].endswith("-FAILED"))


if __name__ == "__main__":
    unittest.main()
