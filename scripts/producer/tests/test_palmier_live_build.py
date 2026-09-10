"""Offline lifecycle and authority tests for skilled-agent Palmier builds."""
import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from palmier.candidate_receipt import load_candidate
from palmier.live_build_candidate import (checkpoint_live_candidate,
                                           fork_live_candidate,
                                           observe_live_candidate,
                                           resume_live_candidate)
from palmier.live_build_journal_contract import (close_live_build_journal,
                                                  read_live_build_journal)
from palmier.live_build_qc_contract import authority_from_value
from palmier.timeline_authority import load_authority
from test_palmier_native_delta import NativeClient, _record


def _write(path: str, value: object) -> dict:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle)
    return {"path": path, "hash": file_sha256(path)}


def _planning(tmp: str, digest: str, plan_hash: str) -> dict:
    packet = _write(os.path.join(tmp, "packet.json"), {
        "stage": "plan", "round": 1, "inputAuthority": {"digest": digest}})
    gates = _write(os.path.join(tmp, "gates.json"), {
        "stage": "plan-gates", "round": 1,
        "inputAuthority": {"digest": digest}, "gates": {"ok": True}})
    review = _write(os.path.join(tmp, "review.json"), {
        "stage": "plan", "round": 1,
        "inputAuthority": {"digest": digest}, "review": {"verdict": "pass"}})
    return {"round": 1, "authorityDigest": digest,
            "planHash": plan_hash, "packet": packet,
            "gates": gates, "review": review}


def _closed_journal(tmp: str, fingerprint: str) -> dict:
    path = os.path.join(tmp, ".palmier-live-build.jsonl")
    rows = [
        {"at": "2026-07-30T00:00:00Z", "event": "live_build_head",
         "fingerprint": "e" * 64, "verifiedOperationIds": []},
        {"at": "2026-07-30T00:00:01Z", "event": "palmier_op",
         "operationId": "op-1", "tool": "remove_words",
         "input": {"words": ["um"]}, "status": "applying", "elapsedMs": 1},
        {"at": "2026-07-30T00:00:02Z", "event": "palmier_op_result",
         "operationId": "op-1", "status": "applied", "elapsedMs": 2},
        {"at": "2026-07-30T00:00:03Z", "event": "live_build_head",
         "fingerprint": fingerprint, "verifiedOperationIds": ["op-1"]},
    ]
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return close_live_build_journal(path, fingerprint)


def _live_authority(tmp: str, parent: dict, candidate: dict) -> tuple[dict, dict]:
    plan_ref = _write(os.path.join(tmp, "edit_plan.json"), {
        "planVersion": 1, "target": {"mode": "longform"},
        "cutTrack": [{"sourceId": "source", "start": 0, "end": 5}]})
    journal_ref = _closed_journal(tmp, candidate["fingerprint"])
    request = f"Execute approved Producer plan {plan_ref['hash']} exactly."
    request_hash = hashlib.sha256(request.encode()).hexdigest()
    digest = "a" * 64
    capture = "live-capture"
    live_input = {
        "schemaVersion": 1, "kind": "palmier-live-build-input",
        "captureId": capture,
        "request": {"text": request, "hash": request_hash},
        "controller": {"lanes": ["cuts", "graphics"]},
        "parent": {key: parent[key] for key in
                   ("projectId", "timelineId", "fingerprint")},
        "plan": plan_ref, "journal": journal_ref,
        "planningReviews": [_planning(tmp, digest, plan_ref["hash"])],
        "sessionId": "session-1",
    }
    input_ref = _write(os.path.join(tmp, "live-input.json"), live_input)
    envelope = {
        "schemaVersion": 1, "kind": "palmier-live-build-qc-authority",
        "requestHash": request_hash, "captureId": capture,
        "liveInput": {**input_ref, "planHash": plan_ref["hash"],
                      "journalHash": journal_ref["hash"],
                      "journalLifecycleDigest":
                      journal_ref["lifecycleDigest"],
                      "headFingerprint": journal_ref["headFingerprint"],
                      "lanes": ["cuts", "graphics"],
                      "parent": live_input["parent"], "operationCount": 1,
                      "sessionId": "session-1"},
        "ctx": {"dir": tmp, "scope": "produced", "planPath": plan_ref["path"],
                "manifestPath": os.path.join(tmp, "manifest.json"),
                "transcriptsDir": tmp,
                "doctrine": {"runId": "plan-run", "doctrineHash": "d" * 64},
                "pipeline": {"runId": "plan-run"}},
    }
    candidate.update({"requestHash": request_hash,
                      "lanes": ["cuts", "graphics"],
                      "operations": {"count": 1,
                                     "journalHash": journal_ref["hash"],
                                     "lifecycleDigest":
                                     journal_ref["lifecycleDigest"],
                                     "headFingerprint":
                                     journal_ref["headFingerprint"]}})
    return envelope, {"scope": "produced", "planHash": plan_ref["hash"],
                      "manifestHash": "m" * 64, "pipelineDigest": "p" * 64,
                      "digest": digest}


class LiveBuildJournalTests(unittest.TestCase):
    def test_applied_no_delta_is_not_a_controller_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".palmier-live-build.jsonl")
            rows = [
                {"at": "t0", "event": "live_build_head",
                 "fingerprint": "a" * 64, "verifiedOperationIds": []},
                {"at": "t1", "event": "palmier_op", "operationId": "op",
                 "tool": "remove_words", "input": {"words": ["um"]},
                 "status": "applying"},
                {"at": "t2", "event": "palmier_op_result",
                 "operationId": "op", "status": "applied"},
                {"at": "t3", "event": "live_build_head",
                 "fingerprint": "a" * 64,
                 "verifiedOperationIds": ["op"]},
            ]
            with open(path, "w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            with self.assertRaisesRegex(Exception, "no candidate delta"):
                close_live_build_journal(path, "a" * 64)

    def test_oversized_row_and_ambiguous_retry_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".palmier-live-build.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "at": "t", "event": "palmier_op", "operationId": "large",
                    "tool": "remove_words", "status": "applying",
                    "input": {"entries": ["x" * 20_000]},
                }) + "\n")
            with self.assertRaisesRegex(Exception, "durable limit"):
                read_live_build_journal(path)
            rows = [
                {"at": "t0", "event": "palmier_op", "operationId": "one",
                 "tool": "remove_words", "status": "applying",
                 "input": {"words": ["um"]}},
                {"at": "t1", "event": "palmier_op_result",
                 "operationId": "one", "status": "failed"},
                {"at": "t2", "event": "palmier_op", "operationId": "two",
                 "tool": "remove_words", "status": "applying",
                 "input": {"words": ["um"]}},
            ]
            with open(path, "w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            with self.assertRaisesRegex(Exception, "replay fence"):
                read_live_build_journal(path)


class LiveBuildCandidateTests(unittest.TestCase):
    def test_observe_is_read_only_and_resume_uses_fingerprint_cas(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            _record(tmp, client)
            saved = fork_live_candidate(client, tmp, "Live candidate")
            client.timelines["candidate"]["tracks"][0]["clips"][0]["opacity"] = 0.4
            observed = observe_live_candidate(client, tmp)
            self.assertNotEqual(observed["fingerprint"], saved["fingerprint"])
            self.assertEqual(
                load_candidate(tmp)["fingerprint"], saved["fingerprint"])
            with self.assertRaisesRegex(Exception, "resume reconciliation"):
                resume_live_candidate(client, tmp, "0" * 64)
            self.assertEqual(
                load_candidate(tmp)["fingerprint"], saved["fingerprint"])
            resumed = resume_live_candidate(
                client, tmp, observed["fingerprint"])
            self.assertEqual(
                resumed["fingerprint"], observed["fingerprint"])

    def test_fork_partial_resume_and_checkpoint_preserve_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent = _record(tmp, client)
            forked = fork_live_candidate(client, tmp, "Live candidate")
            self.assertEqual((client.active, forked["status"]),
                             ("candidate", "staged"))
            client.timelines["candidate"]["tracks"][0]["clips"][0]["opacity"] = 0.6
            resumed = resume_live_candidate(client, tmp)
            self.assertEqual(resumed["status"], "edited")
            envelope, _snapshot = _live_authority(tmp, parent, resumed)
            authority_path = os.path.join(tmp, "authority.json")
            _write(authority_path, envelope)
            completed = checkpoint_live_candidate(client, tmp, authority_path)
            self.assertEqual(completed["status"], "edited")
            self.assertEqual(completed["builder"]["kind"], "skilled-live-build")
            self.assertEqual(client.active, "candidate")
            self.assertEqual(load_authority(tmp), parent)
            self.assertEqual(load_candidate(tmp)["liveBuildAuthority"], envelope)

    def test_checkpoint_fingerprint_cas_preserves_candidate_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent = _record(tmp, client)
            candidate = fork_live_candidate(client, tmp, "Live candidate")
            client.timelines["candidate"]["tracks"][0]["clips"][0]["opacity"] = 0.5
            candidate = resume_live_candidate(client, tmp)
            envelope, _snapshot = _live_authority(tmp, parent, candidate)
            authority_path = os.path.join(tmp, "authority.json")
            _write(authority_path, envelope)
            saved = load_candidate(tmp)
            with self.assertRaisesRegex(Exception, "journal closure"):
                checkpoint_live_candidate(
                    client, tmp, authority_path, "0" * 64)
            self.assertEqual(load_candidate(tmp), saved)

    def test_unmodified_semantic_copy_cannot_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = NativeClient()
            parent = _record(tmp, client)
            candidate = fork_live_candidate(client, tmp, "Live candidate")
            envelope, _snapshot = _live_authority(tmp, parent, candidate)
            authority_path = os.path.join(tmp, "authority.json")
            _write(authority_path, envelope)
            with self.assertRaisesRegex(Exception, "no observable"):
                checkpoint_live_candidate(client, tmp, authority_path)


class LiveBuildAuthorityTests(unittest.TestCase):
    def test_plan_journal_planning_and_candidate_are_one_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = {"projectId": "project-1", "timelineId": "head",
                      "fingerprint": "h" * 64}
            candidate = {"projectId": "project-1", "timelineId": "candidate",
                         "fingerprint": "c" * 64}
            envelope, snapshot = _live_authority(tmp, parent, candidate)
            with patch("palmier.live_build_qc_contract.authority_snapshot",
                       return_value=snapshot), \
                    patch("palmier.live_build_qc_contract.request_key",
                          return_value="k" * 64):
                found = authority_from_value(envelope, tmp, {
                    "candidate": candidate, "parent": parent})
            self.assertEqual(found["kind"], "live-build")
            self.assertEqual(found["editPlan"]["planVersion"], 1)
            self.assertEqual(found["lanes"], ["cuts", "graphics"])
            with open(envelope["liveInput"]["path"], "a", encoding="utf-8") as handle:
                handle.write(" ")
            with self.assertRaisesRegex(Exception, "changed"):
                authority_from_value(envelope, tmp, {
                    "candidate": candidate, "parent": parent})


if __name__ == "__main__":
    unittest.main()
