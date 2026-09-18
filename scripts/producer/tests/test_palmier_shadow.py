"""Shadow lifecycle: focus safety, identity guards, restore, and naming."""
import unittest

from _common import *  # noqa: F401,F403
from palmier.mcp_client import PalmierError, PalmierWaiting
from palmier.shadow import ShadowSession, SyncRequest


LANES = {"project": {"name": "target", "fps": 24,
                     "width": 1920, "height": 1080}}
STATE = {"projectId": "p-target", "projectName": "target",
         "projectPath": "/target.palmier"}


class ShadowClient:
    def __init__(self, active_project="p-target"):
        self.active_project = active_project
        self.active_timeline = "human"
        self.calls = []
        self.timelines = {"human": "Human Cut"}

    def _projects(self):
        rows = [
            {"id": "p-target", "name": "target", "path": "/target.palmier",
             "isActive": self.active_project == "p-target"},
            {"id": "p-other", "name": "other", "path": "/other.palmier",
             "isActive": self.active_project == "p-other"},
        ]
        active = next(row for row in rows if row["isActive"])
        return {"active": {"name": active["name"], "path": active["path"]},
                "projects": rows}

    def call_json(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        if tool == "get_projects":
            return self._projects()
        if tool == "get_timeline":
            return {"id": self.active_timeline, "name": self.timelines[self.active_timeline],
                    "fps": 24, "width": 1920, "height": 1080,
                    "totalFrames": 0, "tracks": []}
        if tool == "create_timeline":
            self.active_timeline = "shadow"
            self.timelines["shadow"] = arguments["name"]
            return {"timelineId": "shadow"}
        if tool == "get_media":
            return {"timelines": [{"timelineId": key, "name": value,
                                    "active": key == self.active_timeline}
                                   for key, value in self.timelines.items()]}
        raise AssertionError(tool)

    def call(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        if tool == "set_active_timeline":
            self.active_timeline = arguments["timelineId"]
        if tool == "organize_media":
            for rename in arguments.get("renames", []):
                self.timelines[rename["item"]] = rename["name"]
        return "ok"


class ShadowSessionTests(unittest.TestCase):
    def _session(self, client):
        request = SyncRequest(
            "/tmp", "src", "12345678abcdef",
            {"schemaVersion": 1, "fullyEditable": True})
        return ShadowSession(client, request, LANES, STATE)

    def test_other_active_project_waits_without_focus_changing_call(self):
        client = ShadowClient("p-other")
        with self.assertRaises(PalmierWaiting):
            self._session(client).ensure_project()
        tools = [tool for tool, _args in client.calls]
        self.assertNotIn("open_project", tools)
        self.assertNotIn("create_timeline", tools)

    def test_ready_shadow_becomes_the_active_generated_timeline(self):
        client = ShadowClient()
        session = self._session(client)
        session.ensure_project()
        session.create_shadow()
        self.assertEqual(client.active_timeline, "shadow")
        session.restore_human(strict=True)
        self.assertEqual(client.active_timeline, "human")
        name, records = session.finalize([])
        self.assertEqual(name, "sniper-v12345678")
        self.assertEqual(client.timelines["shadow"], name)
        self.assertEqual(records[0]["id"], "shadow")
        session.activate_generated()
        self.assertEqual(client.active_timeline, "shadow")

    def test_generated_activation_rejects_id_outside_target_project(self):
        client = ShadowClient()
        session = self._session(client)
        session.ensure_project()
        with self.assertRaisesRegex(PalmierError, "not in target project"):
            session.activate_generated("not-a-timeline", require_human=False)
        self.assertEqual(client.active_timeline, "human")

    def test_identity_switch_blocks_next_mutation_boundary(self):
        client = ShadowClient()
        session = self._session(client)
        session.ensure_project()
        session.create_shadow()
        client.active_timeline = "human"
        with self.assertRaises(PalmierError):
            session.assert_build("cuts")

    def test_partial_shadow_is_failed_after_restore(self):
        client = ShadowClient()
        session = self._session(client)
        session.ensure_project()
        session.create_shadow()
        session.restore_human(strict=False)
        session.mark_failed()
        self.assertTrue(client.timelines["shadow"].endswith("-FAILED"))
        self.assertEqual(client.active_timeline, "human")


if __name__ == "__main__":
    unittest.main()
