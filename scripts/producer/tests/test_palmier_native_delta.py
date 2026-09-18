"""Offline Palmier-native reconcile, fork, mutation, and CLI contracts."""
import contextlib
import copy
import io
import hashlib
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from palmier.candidate_receipt import load_candidate
from palmier.mcp_client import PalmierError
from palmier.native_delta import NativeRequest, execute_native_candidate
from palmier.sync_lock import SyncLockState
from palmier.timeline_authority import (TimelineConflict, load_authority,
                                        record_authority,
                                        snapshot)
from palmier.timeline_guard import reconcile_working_authority
import palmier.native_delta_cli as native_cli


def _timeline(opacity: float = 1.0) -> dict:
    return {
        "id": "head", "name": "Human edit", "fps": 24,
        "width": 1920, "height": 1080, "totalFrames": 120,
        "tracks": [{"id": "track-1", "index": 0, "type": "video",
                    "clips": [{"id": "clip-1", "frames": [0, 120],
                               "mediaRef": "asset-1", "opacity": opacity,
                               "audio": {"id": "audio-1", "volume": 1}}]}],
    }


def _plan(authority: dict, opacity: float = 0.5) -> dict:
    return {
        "schemaVersion": 1,
        "parent": {key: authority[key] for key in
                   ("projectId", "timelineId", "fingerprint")},
        "requestHash": "b" * 64, "lanes": ["graphics", "motion"],
        "operations": [{
            "tool": "set_clip_properties",
            "args": {"clipIds": ["clip-1"], "opacity": opacity},
            "reason": "Keep the statement card subordinate to the speaker",
        }],
    }


class NativeClient:
    def __init__(self, project_id: str = "project-1"):
        self.project_id = project_id
        self.active = "head"
        self.timelines = {"head": _timeline()}
        self.calls = []
        self.mutations = []
        self.destructive = False
        self.unexpected_add = False
        self.noop = False
        self.restore_failure = False
        self.lock_probe = None

    def handshake(self):
        self._assert_lock()

    def _assert_lock(self):
        if self.lock_probe is not None:
            self.lock_probe()

    def call_json(self, tool, arguments=None):
        self._assert_lock()
        args = copy.deepcopy(arguments or {})
        self.calls.append((tool, args))
        if tool == "get_projects":
            return {"projects": [{"id": self.project_id, "isActive": True}]}
        if tool == "get_timeline":
            return copy.deepcopy(self.timelines[self.active])
        if tool == "create_timeline":
            return self._fork(args)
        if tool == "set_clip_properties":
            return self._set_properties(args)
        if tool == "set_active_timeline":
            if self.restore_failure:
                raise PalmierError("simulated parent restore failure")
            self.active = args["timelineId"]
            return {"timelineId": self.active}
        raise AssertionError(tool)

    def _fork(self, args):
        if args.get("from") != self.active:
            raise AssertionError("candidate did not fork the visible head")
        copied = copy.deepcopy(self.timelines[self.active])
        copied["id"], copied["name"] = "candidate", args["name"]
        copied["tracks"][0]["id"] = "track-copy"
        copied["tracks"][0]["clips"][0]["id"] = "clip-copy"
        copied["tracks"][0]["clips"][0]["audio"]["id"] = "audio-copy"
        self.timelines["candidate"] = copied
        self.active = "candidate"
        return {"timelineId": "candidate"}

    def _set_properties(self, args):
        self.mutations.append(copy.deepcopy(args))
        clips = self.timelines[self.active]["tracks"][0]["clips"]
        if args["clipIds"] != ["clip-copy"]:
            raise AssertionError("controller did not remap the regenerated id")
        if self.destructive:
            clips.clear()
            return {"updatedClipIds": [], "removedClipIds": []}
        if self.unexpected_add:
            extra = copy.deepcopy(clips[0])
            extra["id"], extra["audio"]["id"] = "surprise", "surprise-audio"
            clips.append(extra)
        if not self.noop:
            clips[0]["opacity"] = args["opacity"]
        return {"updatedClipIds": list(args["clipIds"])}


def _record(tmp: str, client: NativeClient) -> dict:
    with open(os.path.join(tmp, "palmier.sync.json"), "w") as handle:
        json.dump({"schemaVersion": 4, "ownership": "sniper",
                   "projectId": "project-1", "latestTimelineId": "head",
                   "lastPushPlanHash": "old", "verification": {"ok": True}}, handle)
    return record_authority(tmp, snapshot("project-1", client.timelines["head"]),
                            "sniper-bootstrap")


class NativeDeltaTests(unittest.TestCase):
    def test_manual_visible_revision_is_adopted_for_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            _record(tmp, client)
            client.timelines["head"]["tracks"][0]["clips"][0]["opacity"] = 0.8
            found, change = reconcile_working_authority(
                client, tmp, {"projectId": "project-1"})
            self.assertEqual(change, "content-changed")
            self.assertEqual(found["origin"], "palmier-manual")
            self.assertEqual(found["timeline"]["tracks"][0]["clips"][0]
                             ["opacity"], 0.8)
            with open(os.path.join(tmp, "palmier.sync.json")) as handle:
                state = json.load(handle)
            self.assertNotIn("verification", state)
            self.assertNotIn("lastPushPlanHash", state)
            self.assertNotIn("create_timeline", [name for name, _ in client.calls])

    def test_stale_two_phase_parent_is_adopted_then_rejected_before_fork(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            authority = _record(tmp, client)
            plan = _plan(authority)
            client.timelines["head"]["tracks"][0]["clips"][0]["opacity"] = 0.7
            request = NativeRequest({"projectId": "project-1"}, plan)
            with self.assertRaisesRegex(PalmierError, "parent authority is stale"):
                execute_native_candidate(client, tmp, request)
            self.assertEqual(load_authority(tmp)["origin"], "palmier-manual")
            self.assertNotIn("create_timeline", [name for name, _ in client.calls])

    def test_ids_are_remapped_and_final_receipt_never_promotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent_before = copy.deepcopy(client.timelines["head"])
            authority = _record(tmp, client)
            result = execute_native_candidate(
                client, tmp, NativeRequest({"projectId": "project-1"},
                                           _plan(authority)))
            self.assertEqual(client.mutations[0]["clipIds"], ["clip-copy"])
            self.assertEqual(result["status"], "edited")
            self.assertEqual(result["qc"], {"status": "pending", "approved": False})
            self.assertNotEqual(result["operations"][0]["beforeFingerprint"],
                                result["operations"][0]["afterFingerprint"])
            self.assertEqual(load_authority(tmp), authority)
            self.assertEqual(client.timelines["head"], parent_before)
            self.assertEqual(client.active, "head")
            self.assertEqual(result["parentRestoration"]["status"], "restored")

    def test_progress_reports_only_committed_visible_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            authority = _record(tmp, client)
            events = []
            result = execute_native_candidate(
                client, tmp, NativeRequest({"projectId": "project-1"},
                                           _plan(authority)), events.append)
            self.assertEqual(
                [event["status"] for event in events],
                ["candidate_active", "operation_applied", "parent_restored"])
            self.assertEqual(events[1]["tool"], "set_clip_properties")
            self.assertEqual(events[1]["index"], 1)
            self.assertEqual(events[1]["total"], 1)
            self.assertEqual(events[2]["candidateTimelineId"],
                             result["timelineId"])
            self.assertEqual(client.active, "head")

    def test_primary_build_keeps_the_verified_candidate_visible_for_qc(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            authority = _record(tmp, client)
            events = []
            request = NativeRequest(
                {"projectId": "project-1"}, _plan(authority),
                keep_candidate_active=True)
            result = execute_native_candidate(client, tmp, request, events.append)
            self.assertEqual(client.active, "candidate")
            self.assertEqual(result["parentRestoration"]["status"],
                             "deferred-until-qc")
            self.assertEqual(events[-1]["status"], "candidate_visible")
            self.assertEqual(load_authority(tmp), authority)

    def test_unexpected_removal_aborts_and_preserves_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            client.destructive = True
            parent_before = copy.deepcopy(client.timelines["head"])
            authority = _record(tmp, client)
            request = NativeRequest({"projectId": "project-1"}, _plan(authority))
            with self.assertRaisesRegex(PalmierError, "removed structure unexpectedly"):
                execute_native_candidate(client, tmp, request)
            self.assertEqual(load_authority(tmp), authority)
            self.assertEqual(client.timelines["head"], parent_before)
            self.assertEqual(client.active, "head")
            candidate = load_candidate(tmp)
            self.assertEqual(candidate["status"], "quarantined")
            self.assertEqual(candidate["parentRestoration"]["status"], "restored")
            found, change = reconcile_working_authority(
                client, tmp, {"projectId": "project-1"})
            self.assertEqual((found["timelineId"], change), ("head", "unchanged"))

    def test_unexpected_addition_also_aborts(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            client.unexpected_add = True
            authority = _record(tmp, client)
            request = NativeRequest({"projectId": "project-1"}, _plan(authority))
            with self.assertRaisesRegex(PalmierError, "added structure unexpectedly"):
                execute_native_candidate(client, tmp, request)
            self.assertEqual(load_authority(tmp), authority)

    def test_wrong_project_and_noop_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrong = NativeClient("other-project")
            with self.assertRaises(TimelineConflict):
                reconcile_working_authority(
                    wrong, tmp, {"projectId": "project-1"})
            self.assertNotIn("create_timeline", [name for name, _ in wrong.calls])
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            client.noop = True
            authority = _record(tmp, client)
            request = NativeRequest({"projectId": "project-1"}, _plan(authority))
            with self.assertRaisesRegex(PalmierError, "without an observable change"):
                execute_native_candidate(client, tmp, request)


class NativeCliTests(unittest.TestCase):
    def test_invalid_command_is_also_one_machine_readable_verdict(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = native_cli.main(["/not/used"])
        lines = output.getvalue().splitlines()
        self.assertEqual(code, 65)
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["status"], "rejected")

    def test_reconcile_outputs_one_verdict_and_holds_lock_for_every_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "palmier.sync.json"), "w") as handle:
                json.dump({"projectId": "project-1"}, handle)
            client, lease = NativeClient(), SimpleNamespace(active=True)
            lease.release = lambda: setattr(lease, "active", False)
            client.lock_probe = lambda: self.assertTrue(lease.active)
            acquired = SimpleNamespace(state=SyncLockState.ACQUIRED, lease=lease)
            output = io.StringIO()
            with patch.object(native_cli, "PalmierClient", return_value=client), \
                    patch.object(native_cli.SyncLock, "acquire", return_value=acquired), \
                    contextlib.redirect_stdout(output):
                code = native_cli.main([tmp, "--reconcile"])
            lines = output.getvalue().splitlines()
            self.assertEqual(code, 0)
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["status"], "reconciled")
            self.assertFalse(lease.active)

    def test_execute_uses_controller_json_and_keeps_lock_through_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            authority = _record(tmp, client)
            with open(os.path.join(tmp, "palmier.sync.json"), "w") as handle:
                json.dump({"projectId": "project-1"}, handle)
            plan_path = os.path.join(tmp, "native-plan.json")
            request = "Make the card more restrained"
            plan = _plan(authority)
            plan["requestHash"] = hashlib.sha256(request.encode()).hexdigest()
            with open(plan_path, "w") as handle:
                json.dump(plan, handle)
            gate_path = os.path.join(tmp, "gate.json")
            with open(gate_path, "w") as handle:
                json.dump({"schemaVersion": 1, "request": request,
                           "expectedLanes": plan["lanes"]}, handle)
            lease = SimpleNamespace(active=True)
            lease.release = lambda: setattr(lease, "active", False)
            client.lock_probe = lambda: self.assertTrue(lease.active)
            acquired = SimpleNamespace(state=SyncLockState.ACQUIRED, lease=lease)
            output = io.StringIO()
            with patch.object(native_cli, "PalmierClient", return_value=client), \
                    patch.object(native_cli.SyncLock, "acquire", return_value=acquired), \
                    contextlib.redirect_stdout(output):
                code = native_cli.main(
                    [tmp, "--execute", plan_path, "--gate-envelope", gate_path,
                     "--name", "AI review copy"])
            lines = output.getvalue().splitlines()
            self.assertEqual(code, 0)
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["status"], "candidate-staged")
            self.assertEqual(client.timelines["candidate"]["name"],
                             "AI review copy")
            self.assertFalse(lease.active)

    def test_execute_progress_is_opt_in_and_final_verdict_remains_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            authority = _record(tmp, client)
            with open(os.path.join(tmp, "palmier.sync.json"), "w") as handle:
                json.dump({"projectId": "project-1"}, handle)
            request = "Make the card more restrained"
            plan = _plan(authority)
            plan["requestHash"] = hashlib.sha256(request.encode()).hexdigest()
            plan_path = os.path.join(tmp, "native-plan.json")
            gate_path = os.path.join(tmp, "gate.json")
            with open(plan_path, "w") as handle:
                json.dump(plan, handle)
            with open(gate_path, "w") as handle:
                json.dump({"schemaVersion": 1, "request": request,
                           "expectedLanes": plan["lanes"]}, handle)
            lease = SimpleNamespace(active=True)
            lease.release = lambda: setattr(lease, "active", False)
            acquired = SimpleNamespace(state=SyncLockState.ACQUIRED, lease=lease)
            output = io.StringIO()
            with patch.object(native_cli, "PalmierClient", return_value=client), \
                    patch.object(native_cli.SyncLock, "acquire", return_value=acquired), \
                    contextlib.redirect_stdout(output):
                code = native_cli.main(
                    [tmp, "--execute", plan_path, "--gate-envelope", gate_path,
                     "--progress"])
            rows = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(code, 0)
            self.assertEqual(
                [row.get("status") for row in rows[:-1]],
                ["candidate_active", "operation_applied", "parent_restored"])
            self.assertEqual(rows[-1]["status"], "candidate-staged")

    def test_execute_without_locked_gate_envelope_never_forks(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            authority = _record(tmp, client)
            plan_path = os.path.join(tmp, "native-plan.json")
            with open(plan_path, "w") as handle:
                json.dump(_plan(authority), handle)
            output = io.StringIO()
            with patch.object(native_cli, "PalmierClient", return_value=client), \
                    contextlib.redirect_stdout(output):
                code = native_cli.main([tmp, "--execute", plan_path])
            self.assertEqual(code, 65)
            self.assertNotIn("candidate", client.timelines)

    def test_execute_regates_fresh_authority_under_the_same_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            authority = _record(tmp, client)
            request = "Make the card more restrained"
            plan = _plan(authority)
            plan["requestHash"] = hashlib.sha256(request.encode()).hexdigest()
            plan_path, gate_path = (os.path.join(tmp, "plan.json"),
                                    os.path.join(tmp, "gate.json"))
            with open(plan_path, "w") as handle:
                json.dump(plan, handle)
            with open(gate_path, "w") as handle:
                json.dump({"schemaVersion": 1, "request": request,
                           "expectedLanes": plan["lanes"]}, handle)
            client.timelines["head"]["tracks"][0]["clips"][0]["opacity"] = 0.8
            lease = SimpleNamespace(active=True)
            lease.release = lambda: setattr(lease, "active", False)
            client.lock_probe = lambda: self.assertTrue(lease.active)
            acquired = SimpleNamespace(state=SyncLockState.ACQUIRED, lease=lease)
            output = io.StringIO()
            with patch.object(native_cli, "PalmierClient", return_value=client), \
                    patch.object(native_cli.SyncLock, "acquire", return_value=acquired), \
                    contextlib.redirect_stdout(output):
                code = native_cli.main(
                    [tmp, "--execute", plan_path, "--gate-envelope", gate_path])
            self.assertEqual(code, 65)
            self.assertEqual(json.loads(output.getvalue())["status"], "rejected")
            self.assertNotIn("candidate", client.timelines)


if __name__ == "__main__":
    unittest.main()
