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
                                           resume_live_candidate)
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


def _live_authority(tmp: str, parent: dict, candidate: dict) -> tuple[dict, dict]:
    plan_ref = _write(os.path.join(tmp, "edit_plan.json"), {
        "planVersion": 1, "target": {"mode": "longform"},
        "cutTrack": [{"sourceId": "source", "start": 0, "end": 5}]})
    journal_ref = _write(os.path.join(tmp, ".palmier-live-build.jsonl"),
                         {"event": "palmier_op_result", "status": "applied"})
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
        "plan": plan_ref, "journal": {**journal_ref, "operationCount": 1},
        "planningReviews": [_planning(tmp, digest, plan_ref["hash"])],
        "sessionId": "session-1",
    }
    input_ref = _write(os.path.join(tmp, "live-input.json"), live_input)
    envelope = {
        "schemaVersion": 1, "kind": "palmier-live-build-qc-authority",
        "requestHash": request_hash, "captureId": capture,
        "liveInput": {**input_ref, "planHash": plan_ref["hash"],
                      "journalHash": journal_ref["hash"],
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
                                     "journalHash": journal_ref["hash"]}})
    return envelope, {"scope": "produced", "planHash": plan_ref["hash"],
                      "manifestHash": "m" * 64, "pipelineDigest": "p" * 64,
                      "digest": digest}


class LiveBuildCandidateTests(unittest.TestCase):
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
