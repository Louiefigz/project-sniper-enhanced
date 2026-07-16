"""Managed Palmier working-view lifecycle tests (no live MCP)."""
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from palmier.draft import DraftContext, DraftInput, create_draft
from palmier.timeline_authority import record_active_authority


DRAFT = DraftInput("/source/raw.mp4", "a" * 64, 5.0, 24.0, 1920, 1080)


class DraftClient:
    def __init__(self):
        self.active = "human"
        self.timelines = {"human": "Human Cut"}
        self.calls = []

    def call_json(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        if tool == "get_projects":
            return {"active": {"name": "demo", "path": "/demo.palmier"},
                    "projects": [{"id": "project", "name": "demo",
                                  "path": "/demo.palmier", "isActive": True}]}
        if tool == "get_timeline":
            return {"id": self.active, "name": self.timelines[self.active],
                    "fps": 24, "width": 1920, "height": 1080,
                    "totalFrames": 0, "tracks": []}
        if tool == "create_timeline":
            self.active = "draft"
            self.timelines["draft"] = arguments["name"]
            return {"timelineId": "draft"}
        if tool == "get_media":
            return {"timelines": [{"timelineId": ident, "name": name}
                                    for ident, name in self.timelines.items()]}
        raise AssertionError(tool)

    def call(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        if tool == "set_active_timeline":
            self.active = arguments["timelineId"]
        if tool == "organize_media":
            for rename in arguments.get("renames", []):
                self.timelines[rename["item"]] = rename["name"]
        return "ok"


class DraftExecutor:
    def __init__(self, *_args):
        self.project_fps = 0
        self.media = {}
        self.media_s = {}

    def run(self, _step):
        return None


def _library(*_args):
    return SimpleNamespace(ensure=lambda *_a: SimpleNamespace(
        refs={"src": "source-ref"}, seconds={"src": 5.0},
        media_map={"src:key": {"ref": "source-ref", "seconds": 5.0}}))


class ManagedDraftTests(unittest.TestCase):
    def test_draft_is_viewable_but_never_claims_verified_authority(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("palmier.draft._draft_input", return_value=DRAFT), \
                patch("palmier.draft.MediaLibrary", side_effect=_library), \
                patch("palmier.draft.Executor", DraftExecutor):
            client = DraftClient()
            create_draft(client, DraftContext(tmp, "/manifest.json",
                                              "demo", "longform"))
            with open(os.path.join(tmp, "palmier.sync.json")) as handle:
                state = json.load(handle)
            self.assertEqual(client.active, "draft")
            self.assertEqual(state["workspaceMode"], "managed-draft")
            self.assertEqual(state["ownership"], "sniper")
            self.assertFalse(state["draft"]["authoritative"])
            self.assertEqual(state["draft"]["assetKind"], "source")
            self.assertNotIn("verification", state)
            self.assertNotIn("parity", state)
            self.assertNotIn("lastPushPlanHash", state)

    def test_verified_workspace_is_not_replaced_by_draft_initializer(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("palmier.draft._draft_input", return_value=DRAFT):
            state = {"schemaVersion": 4, "ownership": "sniper",
                     "workspaceMode": "verified-mirror",
                     "mirrorMode": "visual-master"}
            with open(os.path.join(tmp, "palmier.sync.json"), "w") as handle:
                json.dump(state, handle)
            client = DraftClient()
            create_draft(client, DraftContext(tmp, "/manifest.json",
                                              "demo", "longform"))
            self.assertEqual(client.calls, [])
            with open(os.path.join(tmp, "palmier.sync.json")) as handle:
                self.assertEqual(json.load(handle), state)

    def test_reopening_draft_preserves_a_new_manual_timeline(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("palmier.draft._draft_input", return_value=DRAFT):
            client = DraftClient()
            client.timelines["draft"] = "Sniper working view"
            client.active = "draft"
            record_active_authority(client, tmp, "project", "sniper-bootstrap")
            state = {
                "schemaVersion": 4, "ownership": "sniper",
                "workspaceMode": "managed-draft", "projectId": "project",
                "projectName": "demo", "projectPath": "/demo.palmier",
                "projectSettings": {"fps": 24, "width": 1920, "height": 1080},
                "latestTimelineId": "draft",
                "draft": {"sourceHash": DRAFT.source_hash},
            }
            with open(os.path.join(tmp, "palmier.sync.json"), "w") as handle:
                json.dump(state, handle)
            client.timelines["manual"] = "My revision"
            client.active = "manual"

            create_draft(client, DraftContext(tmp, "/manifest.json",
                                              "demo", "longform"))

            self.assertEqual(client.active, "manual")
            with open(os.path.join(tmp, "palmier.timeline-authority.json")) as handle:
                authority = json.load(handle)
            self.assertEqual(authority["timelineId"], "manual")
            self.assertEqual(authority["origin"], "palmier-manual")


if __name__ == "__main__":
    unittest.main()
