"""Offline lock/deadline/session/mutation controls for connected acceptance."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from _common import *  # noqa: F401,F403
from palmier.live_acceptance_runtime import (
    AcceptanceClient, AppliedResponseLost, Deadline, MutationInventory)
from palmier.mcp_client import PalmierClient, PalmierError
from palmier.sync_lock import SyncLockState
import live_p5_connected_palmier_acceptance as harness


class FakeSession:
    def __init__(self, ident: str):
        self.session_id = ident
        self.timeout_s = 100
        self.closed = False

    def handshake(self):
        return None

    def call(self, tool, _args):
        if tool == "get_projects":
            return json.dumps({"projects": []})
        return json.dumps({"ok": True})

    def close(self):
        self.closed = True
        self.session_id = None


class RuntimeTests(unittest.TestCase):
    def test_every_mutation_uses_and_terminates_a_unique_session(self):
        sessions = []

        def factory(_timeout):
            session = FakeSession(f"session-{len(sessions) + 1}")
            sessions.append(session)
            return session

        inventory = MutationInventory()
        client = AcceptanceClient(Deadline(30), inventory, factory)
        client.call_json("get_projects", {})
        with client.phase("project-lifecycle"):
            client.call_json("new_project", {"name": "disposable"})
            client.call_json("close_project", {"path": "/tmp/disposable"})
        client.close()
        self.assertEqual(len(inventory.rows), 2)
        self.assertEqual(len({
            row["sessionId"] for row in inventory.rows}), 2)
        self.assertTrue(all(session.closed for session in sessions))
        self.assertTrue(all(row["outcome"] == "succeeded"
                            for row in inventory.rows))

    def test_unclassified_mutation_fails_before_it_can_be_explained_away(self):
        client = AcceptanceClient(
            Deadline(30), MutationInventory(),
            lambda _timeout: FakeSession("session-1"))
        with self.assertRaisesRegex(PalmierError, "unclassified"):
            client.call_json("new_project", {"name": "unsafe"})

    def test_governed_inventory_must_exactly_equal_terminal_journal(self):
        rows = [{
            "sequence": 1, "tool": "add_clips",
            "argsHash": "a" * 64, "sessionId": "session-1",
            "disposition": "desktop-journal", "outcome": "succeeded",
        }]
        inventory = MutationInventory(rows)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "journal.jsonl")
            path.write_text(json.dumps({
                "event": "operation_verified", "tool": "add_clips",
                "argsHash": "a" * 64}) + "\n")
            inventory.bind_desktop_journal(str(path))
            self.assertTrue(inventory.rows[0]["journalBound"])
            path.write_text(json.dumps({
                "event": "operation_verified", "tool": "remove_clips",
                "argsHash": "a" * 64}) + "\n")
            with self.assertRaisesRegex(PalmierError, "differs"):
                inventory.bind_desktop_journal(str(path))

    def test_applied_response_loss_is_reconciled_and_proof_bound(self):
        inventory = MutationInventory()
        client = AcceptanceClient(
            Deadline(30), inventory,
            lambda _timeout: FakeSession("response-loss-session"))
        with client.phase("desktop-journal"):
            client.arm_response_loss()
            with self.assertRaises(AppliedResponseLost):
                client.call_json("add_clips", {"entries": [{"id": "one"}]})
        self.assertEqual(
            inventory.rows[0]["outcome"], "response-lost-after-apply")
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp, "journal.jsonl")
            journal.write_text(json.dumps({
                "event": "operation_reconciled", "tool": "add_clips",
                "argsHash": inventory.rows[0]["argsHash"],
            }) + "\n")
            inventory.bind_desktop_journal(str(journal))
        inventory.bind_proof(
            "desktop-journal", {"kind": "reconciled-timeline-readback"})
        inventory.assert_complete({"desktop-journal"})
        self.assertEqual(
            inventory.rows[0]["journalEvent"], "operation_reconciled")

    def test_boundary_fault_mode_withholds_and_reconciles_nonjournal_call(self):
        inventory = MutationInventory()
        sessions = []

        def factory(_timeout):
            session = FakeSession(f"boundary-{len(sessions) + 1}")
            sessions.append(session)
            return session

        client = AcceptanceClient(Deadline(30), inventory, factory)
        proof = {"kind": "new-project-readback", "projectId": "project"}
        with patch(
                "palmier.live_response_reconciliation."
                "reconcile_response_loss",
                return_value=(json.dumps({"id": "project"}), proof)):
            client.enable_boundary_faults()
            with client.phase("project-lifecycle"):
                result = client.call_json(
                    "new_project", {"name": "disposable"})
        client.bind_proof(
            "project-lifecycle", {"kind": "created-project-readback"})
        inventory.assert_response_loss_receipts(
            client.response_loss_receipts)
        inventory.assert_complete({"project-lifecycle"})
        self.assertEqual(result["id"], "project")
        self.assertEqual(
            inventory.rows[0]["outcome"], "response-lost-after-apply")
        self.assertTrue(inventory.rows[0]["reconciliationBound"])
        self.assertTrue(sessions[0].closed)
        tampered = copy.deepcopy(client.response_loss_receipts)
        tampered[0]["proof"]["projectId"] = "foreign"
        with self.assertRaisesRegex(PalmierError, "differs"):
            inventory.assert_response_loss_receipts(tampered)

    def test_required_fault_cohort_rejects_one_ordinary_success(self):
        inventory = MutationInventory([{
            "sequence": 1, "tool": "new_project",
            "argsHash": "a" * 64, "sessionId": "session-1",
            "disposition": "project-lifecycle", "outcome": "succeeded",
        }])
        inventory.bind_proof(
            "project-lifecycle", {"kind": "created-project-readback"})
        inventory.assert_complete({"project-lifecycle"})
        with self.assertRaisesRegex(PalmierError, "ordinary mutation"):
            inventory.assert_complete(
                {"project-lifecycle"}, require_response_loss=True)

    def test_palmier_http_timeout_is_refreshed_before_each_request(self):
        class Response:
            status = 200

            def __init__(self, session=None):
                self.headers = {"Mcp-Session-Id": session} if session else {}

            def read(self):
                return b'data: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{}}\n'

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        provider = Mock(side_effect=[9.0, 8.0, 7.0, 6.0])
        responses = [
            Response("fresh-session"), Response(), Response(), Response()]
        client = PalmierClient(timeout_s=100)
        client.set_timeout_provider(provider)
        with patch(
                "palmier.mcp_client.urllib.request.urlopen",
                side_effect=responses) as urlopen:
            client.handshake()
            client.call("get_projects", {})
            client.close()
        self.assertEqual(
            [call.kwargs["timeout"] for call in urlopen.call_args_list],
            [9.0, 8.0, 7.0, 6.0])

    def test_monotonic_deadline_fails_after_total_budget(self):
        with patch(
                "palmier.live_acceptance_runtime.time.monotonic",
                side_effect=[10.0, 10.5, 11.1]):
            deadline = Deadline(1.0)
            self.assertAlmostEqual(deadline.remaining(), 0.5)
            with self.assertRaisesRegex(PalmierError, "wall-clock"):
                deadline.check()

    def test_busy_global_lock_prevents_any_mcp_client_or_handshake(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp, "plan.json")
            plan.write_text("{}")
            config = SimpleNamespace(
                timeout_s=30, out_dir=tmp, plan_path=str(plan))
            waiting = SimpleNamespace(
                state=SyncLockState.WAITING, lease=None, plan_hash="hash")
            with patch.object(
                    harness, "validate_config", return_value={}), patch.object(
                        harness.SyncLock, "acquire",
                        return_value=waiting), patch.object(
                            harness, "AcceptanceClient") as client:
                with self.assertRaisesRegex(PalmierError, "SyncLock"):
                    harness.run(config)
            client.assert_not_called()

    def test_late_failure_recovers_exact_cleanup_handles_from_evidence(self):
        prior = {
            "project": {"id": "user-project", "path": "/user.palmier"},
            "timelineId": "user-timeline", "fingerprint": "user-fingerprint",
        }
        disposable = {
            "id": "probe-project", "path": "/probe.palmier",
            "name": "Sniper Probe",
        }
        evidence = SimpleNamespace(
            value={"phases": {"prior": prior, "project": disposable}},
            fail=Mock())
        context = SimpleNamespace(
            config=SimpleNamespace(mode="build"), evidence=evidence,
            client=Mock(), deadline=Mock())
        with patch.object(
                harness, "build_cohort",
                side_effect=PalmierError("late failure after new_project")):
            failure, recovered_prior, recovered_project = harness._attempt(
                context)
        self.assertIsInstance(failure, PalmierError)
        self.assertEqual(recovered_prior, prior)
        self.assertEqual(recovered_project, disposable)
        self.assertEqual(recovered_prior["timelineId"], "user-timeline")
        self.assertEqual(
            recovered_prior["fingerprint"], "user-fingerprint")

    def test_late_resume_failure_prefers_resume_prior_checkpoint(self):
        resume_prior = {
            "project": {"id": "reviewer", "path": "/reviewer.palmier"},
            "timelineId": "reviewer-timeline", "fingerprint": "exact",
        }
        evidence = SimpleNamespace(
            value={"phases": {
                "prior": {"project": {"id": "old"}},
                "resumePrior": resume_prior,
                "project": {"id": "retained", "path": "/retained.palmier"},
            }}, fail=Mock())
        context = SimpleNamespace(
            config=SimpleNamespace(mode="resume"), evidence=evidence,
            client=Mock(), deadline=Mock())
        with patch.object(
                harness, "resume_cohort",
                side_effect=PalmierError("late retained failure")):
            _failure, recovered_prior, _project = harness._attempt(context)
        self.assertEqual(recovered_prior, resume_prior)


if __name__ == "__main__":
    unittest.main()
