"""Delivery-bound template-history approval tests."""
import json
import os
import tempfile
import unittest

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from palmier.quality_hash import stable_hash
from template_usage_approval import APPROVAL_FILE, require_current

PRODUCER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _write(path: str, value: object) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)


class TemplateUsageApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = self.temp.name
        self.producer = os.path.join(self.project, "producer")
        self.source = os.path.join(self.project, "source")
        self.plan = os.path.join(self.producer, "edit_plan.json")
        self.manifest = os.path.join(self.source, "asset_manifest.json")
        self.transcript = os.path.join(self.source, "raw.transcript.json")
        self.history = os.path.join(
            self.producer, ".sniper-learning", "runs", "r1", "template-usage.json")
        self.intent = {"mode": "longform", "scope": "produced", "lanes": {}}
        _write(os.path.join(self.project, "project.json"), {
            "origin": "raw", "history": [], "resolvedIntent": self.intent})
        _write(self.plan, {"target": {"mode": "longform", "scope": "produced"},
                           "cutTrack": [], "graphicsDecisions": []})
        _write(self.transcript, {"words": []})
        _write(self.manifest, {"sources": [
            {"id": "raw", "transcriptPath": "raw.transcript.json"}]})
        history = {"schemaVersion": 1, "kind": "producer-template-usage-history",
                   "mode": "longform", "windowProjects": 8, "projectCount": 0,
                   "projects": [], "counts": {}, "overusedKinds": [],
                   "policy": {"minProjects": 3, "minProjectShare": 0.5}}
        _write(self.history, {**history, "digest": stable_hash(history)})
        self._approve()

    def tearDown(self):
        self.temp.cleanup()

    def _approve(self):
        with open(self.plan, encoding="utf-8") as handle:
            plan_value = json.load(handle)
        with open(self.history, encoding="utf-8") as handle:
            history_value = json.load(handle)
        transcript_rows = [["raw", "raw.transcript.json", file_sha256(self.transcript)]]
        contract = os.path.join(PRODUCER_DIR, "template_usage_contract.py")
        core = {"schemaVersion": 1, "kind": "producer-template-usage-approval",
                "planHash": file_sha256(self.plan),
                "planContentHash": stable_hash(plan_value),
                "manifestHash": file_sha256(self.manifest),
                "transcriptDigest": stable_hash(transcript_rows),
                "contractHash": file_sha256(contract),
                "operatorIntentDigest": stable_hash(
                    {key: value for key, value in self.intent.items() if key != "preset"}),
                "operatorIntentContractHash": file_sha256(
                    os.path.join(PRODUCER_DIR, "operator_intent_contract.py")),
                "historyPath": self.history,
                "historyDigest": history_value["digest"],
                "approvedAt": "2026-07-13T12:00:00.000Z"}
        _write(os.path.join(self.producer, APPROVAL_FILE),
               {**core, "digest": stable_hash(core)})

    def test_current_receipt_passes_and_plan_change_fails(self):
        require_current(self.plan, self.manifest, self.producer, self.source)
        _write(self.plan, {"target": {"mode": "longform", "scope": "produced"},
                           "cutTrack": [{"sourceId": "raw", "start": 0, "end": 1}]})
        with self.assertRaisesRegex(ValueError, "stale"):
            require_current(self.plan, self.manifest, self.producer, self.source)

    def test_missing_receipt_fails_produced_but_not_light(self):
        os.remove(os.path.join(self.producer, APPROVAL_FILE))
        with self.assertRaisesRegex(ValueError, "review the saved plan first"):
            require_current(self.plan, self.manifest, self.producer, self.source)
        self.intent = {"mode": "longform", "scope": "light", "lanes": {}}
        _write(os.path.join(self.project, "project.json"), {
            "origin": "raw", "history": [], "resolvedIntent": self.intent})
        _write(self.plan, {"target": {"mode": "longform", "scope": "light"}})
        require_current(self.plan, self.manifest, self.producer, self.source)

    def test_plan_lane_flip_cannot_waive_stored_graphics_authority(self):
        os.remove(os.path.join(self.producer, APPROVAL_FILE))
        _write(self.plan, {"target": {"mode": "longform", "scope": "produced",
                                      "lanes": {"graphics": "off"}}})
        with self.assertRaisesRegex(ValueError, "review the saved plan first"):
            require_current(self.plan, self.manifest, self.producer, self.source)

    def test_delivery_entrypoints_call_shared_verifier(self):
        paths = [os.path.join(PRODUCER_DIR, "render.py"),
                 os.path.join(PRODUCER_DIR, "assemble.py"),
                 os.path.join(PRODUCER_DIR, "palmier", "push.py")]
        for path in paths:
            with open(path, encoding="utf-8") as handle:
                self.assertIn("require_template_usage_approval(", handle.read(), path)


if __name__ == "__main__":
    unittest.main()
