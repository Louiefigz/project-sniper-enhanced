"""Desktop hook/recovery integration for the exact-master reference lane."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from exact_master_reference_fixture import (add_args, added_timeline,
                                            base_timeline, make_state)
from fingerprints import file_sha256
from palmier.candidate_receipt import load_candidate, save_candidate
from palmier.desktop_authority import reconcile, run_qc
from palmier.desktop_exact_master_binding import expected_disable_args
from palmier.desktop_hook import authorize_pre, observe_post
from palmier.desktop_state import (JOURNAL_NAME, load_state, now,
                                   save_state)
from palmier.mcp_client import PalmierError
from palmier.timeline_authority import snapshot


class HookClient:
    def __init__(self) -> None:
        self.timeline = base_timeline()

    def call_json(self, tool: str, _args: dict | None = None) -> dict:
        if tool == "get_projects":
            return {"projects": [{"id": "project", "isActive": True}]}
        if tool == "get_timeline":
            return json.loads(json.dumps(self.timeline))
        raise AssertionError(tool)


class ExactMasterDesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.temp.name, "repo")
        self.out = os.path.join(self.temp.name, "producer")
        os.makedirs(self.repo)
        os.makedirs(self.out)
        self.client = HookClient()
        partial = make_state(self.out)
        self._build_authority(partial)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, name: str, value: dict) -> str:
        path = os.path.join(self.out, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(value, handle)
        return path

    @staticmethod
    def _receipt(path: str) -> dict:
        return {"path": path, "hash": file_sha256(path)}

    def _build_authority(self, partial: dict) -> None:
        plan = self._write("plan.json", {"planVersion": 2})
        manifest = self._write("manifest.json", {"sources": []})
        with open(partial["operations"]["path"], encoding="utf-8") as handle:
            operations = json.load(handle)
        operations.update({"planHash": file_sha256(plan),
                           "manifestHash": file_sha256(manifest)})
        self._write("operations.json", operations)
        gates = self._write("gates.json", {
            "ok": True, "stage": "visual",
            "planHash": file_sha256(plan),
            "manifestHash": file_sha256(manifest),
        })
        found = snapshot("project", self.client.timeline)
        save_candidate(self.out, {
            "schemaVersion": 1, "status": "staged",
            "projectId": "project", "timelineId": "candidate",
            "fingerprint": found.fingerprint,
            "semanticFingerprint": found.semantic_fingerprint,
            "timeline": found.timeline, "readbackCoverage": found.coverage,
            "base": {"projectId": "project", "timelineId": "parent",
                     "fingerprint": "p" * 64},
        })
        journal = os.path.join(self.out, JOURNAL_NAME)
        open(journal, "w", encoding="utf-8").close()
        state = {
            **partial,
            "schemaVersion": 1, "kind": "palmier-desktop-authority",
            "status": "active", "updatedAt": now(),
            "expiresAt": "2099-01-01T00:00:00+00:00",
            "projectId": "project",
            "candidate": {"projectId": "project", "timelineId": "candidate",
                          "fingerprint": found.fingerprint},
            "expectedFingerprint": found.fingerprint,
            "plan": self._receipt(plan), "manifest": self._receipt(manifest),
            "gates": self._receipt(gates),
            "operations": self._receipt(
                os.path.join(self.out, "operations.json")),
            "journalPath": journal, "operationCount": 0,
            "verifiedOperationKeys": [], "pendingOperation": None,
        }
        save_state(self.repo, state)

    def _factory(self) -> HookClient:
        return self.client

    @staticmethod
    def _event(tool: str, args: dict) -> dict:
        return {"tool_name": f"mcp__palmier-pro__{tool}",
                "tool_input": args, "tool_response": {"ok": True}}

    def _place_with_hooks(self) -> None:
        event = self._event("add_clips", add_args())
        authorize_pre(event, self.repo, self._factory)
        self.client.timeline = added_timeline()
        observe_post(event, self.repo, self._factory)

    def test_hook_path_forces_disable_before_more_edits(self) -> None:
        self._place_with_hooks()
        state = load_state(self.out)
        self.assertEqual(
            state["exactMasterReference"]["status"], "disable-required")
        keyframe = self._event("set_keyframes", {
            "clipId": "base-video", "property": "opacity",
            "keyframes": [[0, 1.0]],
        })
        with self.assertRaisesRegex(PalmierError, "hidden/muted"):
            authorize_pre(keyframe, self.repo, self._factory)
        args = expected_disable_args(state)
        event = self._event("manage_tracks", args)
        authorize_pre(event, self.repo, self._factory)
        self.client.timeline = added_timeline(disabled=True)
        observe_post(event, self.repo, self._factory)
        result = load_state(self.out)
        self.assertEqual(result["exactMasterReference"]["status"], "ready")
        self.assertEqual(result["operationCount"], 2)

    def test_failed_disable_readback_pauses_authority(self) -> None:
        self._place_with_hooks()
        event = self._event(
            "manage_tracks", expected_disable_args(load_state(self.out)))
        authorize_pre(event, self.repo, self._factory)
        visible = added_timeline(disabled=True)
        visible["tracks"][0].pop("hidden")
        self.client.timeline = visible
        with self.assertRaisesRegex(PalmierError, "left a route active"):
            observe_post(event, self.repo, self._factory)
        self.assertEqual(load_state(self.out)["status"], "paused")

    def test_reconcile_uses_same_add_and_disable_readback(self) -> None:
        add = self._event("add_clips", add_args())
        authorize_pre(add, self.repo, self._factory)
        self.client.timeline = added_timeline()
        first = reconcile(self.client, self.repo)
        self.assertEqual(
            first["exactMasterReference"]["status"], "disable-required")
        disable = self._event(
            "manage_tracks", expected_disable_args(first))
        authorize_pre(disable, self.repo, self._factory)
        self.client.timeline = added_timeline(disabled=True)
        final = reconcile(self.client, self.repo)
        self.assertEqual(final["exactMasterReference"]["status"], "ready")
        self.assertEqual(final["operationCount"], 2)

    def test_reconcile_ignores_mutable_candidate_as_before_state(self) -> None:
        event = self._event("add_clips", add_args())
        authorize_pre(event, self.repo, self._factory)
        self.client.timeline = added_timeline()
        after = snapshot("project", self.client.timeline)
        candidate = load_candidate(self.out)
        candidate.update({
            "fingerprint": after.fingerprint,
            "semanticFingerprint": after.semantic_fingerprint,
            "timeline": after.timeline,
        })
        save_candidate(self.out, candidate)
        result = reconcile(self.client, self.repo)
        self.assertEqual(
            result["exactMasterReference"]["status"], "disable-required")

    def test_crash_after_candidate_write_reconciles_once(self) -> None:
        event = self._event("add_clips", add_args())
        authorize_pre(event, self.repo, self._factory)
        self.client.timeline = added_timeline()
        with patch("palmier.desktop_hook.append_journal",
                   side_effect=OSError("crash after candidate write")):
            with self.assertRaisesRegex(OSError, "candidate write"):
                observe_post(event, self.repo, self._factory)
        self.assertIsNotNone(load_state(self.out)["pendingOperation"])
        result = reconcile(self.client, self.repo)
        self.assertEqual(result["operationCount"], 1)
        with self.assertRaisesRegex(PalmierError, "no safely reconcilable"):
            reconcile(self.client, self.repo)
        self.assertEqual(load_state(self.out)["operationCount"], 1)

    def test_crash_after_journal_before_state_reconciles(self) -> None:
        event = self._event("add_clips", add_args())
        authorize_pre(event, self.repo, self._factory)
        self.client.timeline = added_timeline()
        with patch("palmier.desktop_hook.save_state",
                   side_effect=OSError("crash before state")):
            with self.assertRaisesRegex(OSError, "before state"):
                observe_post(event, self.repo, self._factory)
        result = reconcile(self.client, self.repo)
        self.assertEqual(
            result["exactMasterReference"]["status"], "disable-required")

    def test_crash_before_mutation_clears_only_the_pending_reservation(self) -> None:
        event = self._event("add_clips", add_args())
        authorize_pre(event, self.repo, self._factory)
        result = reconcile(self.client, self.repo)
        self.assertIsNone(result["pendingOperation"])
        self.assertEqual(result["operationCount"], 0)

    def test_foreign_delta_during_reconcile_pauses(self) -> None:
        event = self._event("add_clips", add_args())
        authorize_pre(event, self.repo, self._factory)
        self.client.timeline = added_timeline()
        self.client.timeline["totalFrames"] = 121
        with self.assertRaisesRegex(PalmierError, "unrelated timeline state"):
            reconcile(self.client, self.repo)
        self.assertEqual(load_state(self.out)["status"], "paused")

    def test_qc_fails_before_reference_is_ready(self) -> None:
        with self.assertRaisesRegex(PalmierError, "not been placed"):
            run_qc(self.client, self.repo)
        self._place_with_hooks()
        with self.assertRaisesRegex(PalmierError, "disable step"):
            run_qc(self.client, self.repo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
