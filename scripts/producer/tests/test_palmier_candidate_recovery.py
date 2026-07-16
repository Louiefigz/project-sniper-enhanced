"""Failed and pending Palmier candidates never become truth accidentally."""
import contextlib
import io
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
from palmier.native_candidate_lifecycle import (
    assert_candidate_slot_available, discard_candidate)
import palmier.native_delta_cli as native_cli
from palmier.sync_lock import SyncLockState
from palmier.timeline_authority import TimelineConflict, load_authority
from palmier.timeline_guard import reconcile_working_authority
from test_palmier_native_delta import NativeClient, _plan, _record


class CandidateRecoveryTests(unittest.TestCase):
    def test_restore_failure_stays_quarantined_and_cannot_be_adopted(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            client.destructive = True
            client.restore_failure = True
            authority = _record(tmp, client)
            request = NativeRequest({"projectId": "project-1"}, _plan(authority))
            with self.assertRaisesRegex(PalmierError, "recovery was incomplete"):
                execute_native_candidate(client, tmp, request)
            self.assertEqual(client.active, "candidate")
            self.assertEqual(load_candidate(tmp)["status"], "quarantined")
            with self.assertRaisesRegex(PalmierError, "archive the failure"):
                assert_candidate_slot_available(tmp)
            self.assertEqual(load_authority(tmp), authority)
            client.restore_failure = False
            lease = SimpleNamespace(release=lambda: None)
            acquired = SimpleNamespace(
                state=SyncLockState.ACQUIRED, lease=lease)
            output = io.StringIO()
            with patch.object(native_cli, "PalmierClient", return_value=client), \
                    patch.object(native_cli.SyncLock, "acquire",
                                 return_value=acquired), \
                    contextlib.redirect_stdout(output):
                code = native_cli.main([tmp, "--recover-parent"])
            recovered = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(recovered["status"], "parent-restored")
            self.assertEqual(client.active, "head")
            receipt = load_candidate(tmp)
            self.assertEqual(receipt["status"], "quarantined")
            self.assertEqual(receipt["recovery"]["status"], "restored")
            with self.assertRaisesRegex(PalmierError, "archive the failure"):
                assert_candidate_slot_available(tmp)
            discarded = discard_candidate(client, tmp)
            self.assertEqual(discarded["status"], "discarded")
            self.assertTrue(os.path.isfile(os.path.join(
                discarded["archivePath"], "archive.json")))
            assert_candidate_slot_available(tmp)

    def test_pending_candidate_is_review_only_until_a_human_changes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            authority = _record(tmp, client)
            execute_native_candidate(
                client, tmp, NativeRequest({"projectId": "project-1"},
                                           _plan(authority)))
            client.active = "candidate"
            with self.assertRaisesRegex(TimelineConflict, "review-only"):
                reconcile_working_authority(
                    client, tmp, {"projectId": "project-1"})
            self.assertEqual(load_authority(tmp), authority)
            client.timelines["candidate"]["tracks"][0]["clips"][0]["opacity"] = 0.3
            found, change = reconcile_working_authority(
                client, tmp, {"projectId": "project-1"})
            self.assertEqual(change, "candidate-manual")
            self.assertEqual(found["origin"], "palmier-manual")
            self.assertEqual(load_candidate(tmp)["status"], "superseded-manual")
            with open(f"{tmp}/palmier.sync.json") as handle:
                state = json.load(handle)
            self.assertNotIn("verification", state)

    def test_cancellation_after_fork_restores_and_quarantines(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            authority = _record(tmp, client)
            request = NativeRequest({"projectId": "project-1"}, _plan(authority))
            with patch("palmier.native_delta._apply_operation",
                       side_effect=PalmierError("cancelled")), \
                    self.assertRaisesRegex(PalmierError, "cancelled"):
                execute_native_candidate(client, tmp, request)
            self.assertEqual(client.active, "head")
            self.assertEqual(load_candidate(tmp)["status"], "quarantined")

    def test_candidate_is_not_bootstrapped_when_parent_authority_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            client.destructive = True
            authority = _record(tmp, client)
            request = NativeRequest({"projectId": "project-1"}, _plan(authority))
            with self.assertRaises(PalmierError):
                execute_native_candidate(client, tmp, request)
            client.active = "candidate"
            os.remove(f"{tmp}/palmier.timeline-authority.json")
            with self.assertRaisesRegex(TimelineConflict, "authority is missing"):
                reconcile_working_authority(
                    client, tmp, {"projectId": "project-1"})


if __name__ == "__main__":
    unittest.main()
