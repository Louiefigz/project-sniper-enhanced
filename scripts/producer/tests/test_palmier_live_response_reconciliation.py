"""Tool-specific readback for every non-journal response-loss boundary."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from palmier.live_response_reconciliation import reconcile_response_loss
from palmier.mcp_client import PalmierError


class ReadClient:
    def __init__(self, projects=None, timeline=None):
        self.projects = projects or []
        self.timeline = timeline or {
            "id": "timeline-new", "name": "Candidate",
            "totalFrames": 60, "tracks": [],
        }
        self.deadline = SimpleNamespace(remaining=lambda: 30.0)

    def call_json(self, tool, _args):
        if tool == "get_projects":
            return {
                "openCount": sum(
                    row.get("isOpen") is True for row in self.projects),
                "projects": self.projects,
            }
        if tool == "get_timeline":
            return self.timeline
        if tool == "get_media":
            return {"assets": []}
        raise AssertionError(tool)


def _decode(result):
    raw, proof = result
    return json.loads(raw), proof


class ResponseReconciliationTests(unittest.TestCase):
    def test_project_lifecycle_readbacks(self):
        project = {
            "id": "project", "name": "Probe",
            "path": "/tmp/Probe.palmier",
            "isOpen": True, "isActive": True,
        }
        client = ReadClient([project])
        value, proof = _decode(reconcile_response_loss(
            client, "new_project", {"name": "Probe"}, "project-lifecycle"))
        self.assertEqual(value["id"], "project")
        self.assertEqual(proof["kind"], "new-project-readback")
        value, _proof = _decode(reconcile_response_loss(
            client, "open_project", {"path": project["path"]},
            "project-lifecycle"))
        self.assertEqual(value["path"], project["path"])
        client.projects[0].update({"isActive": False, "isOpen": False})
        value, _proof = _decode(reconcile_response_loss(
            client, "close_project", {"path": project["path"]},
            "cleanup-restore"))
        self.assertTrue(value["closed"])

    def test_close_readback_rejects_inactive_but_still_open_project(self):
        project = {
            "id": "project", "name": "Probe",
            "path": "/tmp/Probe.palmier",
            "isOpen": True, "isActive": False,
        }
        with self.assertRaisesRegex(PalmierError, "remains open"):
            reconcile_response_loss(
                ReadClient([project]), "close_project",
                {"path": project["path"]}, "cleanup-restore")

    def test_timeline_fork_activation_and_clip_readbacks(self):
        timeline = {
            "id": "timeline-new", "name": "Candidate",
            "totalFrames": 60, "tracks": [{"clips": [{
                "id": "clip", "mediaRef": "media",
                "frames": [0, 60], "opacity": 0.731,
            }]}],
        }
        client = ReadClient(timeline=timeline)
        value, _proof = _decode(reconcile_response_loss(
            client, "set_active_timeline",
            {"timelineId": "timeline-new"}, "project-lifecycle"))
        self.assertEqual(value["id"], "timeline-new")
        value, _proof = _decode(reconcile_response_loss(
            client, "create_timeline",
            {"name": "Candidate", "from": "timeline-old"},
            "candidate-fork"))
        self.assertEqual(value["timelineId"], "timeline-new")
        _value, proof = _decode(reconcile_response_loss(
            client, "add_clips", {"entries": [{
                "mediaRef": "media", "startFrame": 0, "endFrame": 60,
            }]}, "bootstrap-authority"))
        self.assertEqual(proof["kind"], "added-clips-readback")
        _value, proof = _decode(reconcile_response_loss(
            client, "set_clip_properties", {
                "clipIds": ["clip"], "opacity": 0.731,
            }, "manual-preservation"))
        self.assertEqual(proof["clipIds"], ["clip"])

    def test_import_export_and_caption_readbacks(self):
        client = ReadClient(timeline={
            "id": "timeline", "totalFrames": 60,
            "tracks": [{"captionGroups": [{
                "captionGroupId": "captions", "clipCount": 250,
            }]}],
        })
        with patch(
                "palmier.live_response_reconciliation.recover_media_ref",
                return_value="media"):
            value, proof = _decode(reconcile_response_loss(
                client, "import_media", {
                    "source": {"path": "/tmp/source.mp4"},
                    "name": "source",
                }, "bootstrap-authority"))
        self.assertEqual(value["mediaRef"], "media")
        self.assertEqual(proof["kind"], "imported-media-readback")
        value, proof = _decode(reconcile_response_loss(
            client, "add_captions", {}, "bootstrap-authority"))
        self.assertTrue(value["reconciled"])
        self.assertEqual(proof["captionGroupCounts"], [250])
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp, "candidate.mp4")
            output.write_bytes(b"partial")
            value, proof = _decode(reconcile_response_loss(
                client, "export_project", {
                    "timelineId": "timeline", "outputPath": str(output),
                }, "qc-export"))
        self.assertTrue(value["reconciled"])
        self.assertGreater(proof["observedBytes"], 0)

    def test_unknown_mutation_has_no_guessing_fallback(self):
        with self.assertRaisesRegex(PalmierError, "no 'future_tool'"):
            reconcile_response_loss(
                ReadClient(), "future_tool", {}, "project-lifecycle")
