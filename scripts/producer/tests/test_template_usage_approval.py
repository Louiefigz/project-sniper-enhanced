"""Delivery-bound template-history approval tests."""
import json
import contextlib
import io
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from assemble import delivery_authority_dir
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

    def test_other_delivery_entrypoints_call_shared_verifier(self):
        paths = [os.path.join(PRODUCER_DIR, "render.py"),
                 os.path.join(PRODUCER_DIR, "palmier", "push.py")]
        for path in paths:
            with open(path, encoding="utf-8") as handle:
                self.assertIn("require_template_usage_approval(", handle.read(), path)

    def _assemble_args(self) -> SimpleNamespace:
        """Keep the ordinary CLI form while isolating actual media work."""
        return SimpleNamespace(plan_path=self.plan, manifest=self.manifest,
            base=os.path.join(self.producer, "TEST-base.mp4"),
            out=os.path.join(self.producer, "TEST-out.mp4"), fingerprint=None,
            allow_legacy_unadmitted=False, auto_base=False, cache_dir=None,
            audio_clock_policy="legacy-v1", source_bus_receipt_hash=None)

    def test_assembler_calls_real_shared_verifier_through_document_loader(self) -> None:
        """A delegated call must still use the canonical project, not output dir."""
        from assemble import main
        with patch("assemble_arguments.parse_arguments", return_value=self._assemble_args()), \
                patch("assemble.acquire_lock", return_value=True), patch("assemble.emit"), \
                patch("render_readiness.require_readiness"), \
                patch("assemble.validate_render_documents"), patch("assemble.verify_execution_media_authority"), \
                patch("assemble.require_template_usage_approval", wraps=require_current) as approval, \
                patch("assemble.assemble", return_value={"TEST": True}) as media:
            main()
        approval.assert_called_once_with(self.plan, self.manifest, self.producer, self.source)
        media.assert_called_once()

    def test_missing_template_approval_stops_actual_assembler_entry_before_media(self) -> None:
        """Guard behavior, not a literal spelling in an old source location."""
        from assemble import main
        os.remove(os.path.join(self.producer, APPROVAL_FILE))
        with patch("assemble_arguments.parse_arguments", return_value=self._assemble_args()), \
                patch("assemble.acquire_lock", return_value=True), patch("assemble.emit"), \
                patch("render_readiness.require_readiness"), \
                patch("assemble.validate_render_documents"), patch("assemble.verify_execution_media_authority"), \
                patch("assemble.assemble") as media, contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as stopped:
            main()
        self.assertEqual(stopped.exception.code, 1)
        media.assert_not_called()

    def test_private_output_directory_cannot_rebind_delivery_authority(self):
        candidate = os.path.join(
            self.producer, ".sniper-qc", "run", "round-1", "final.mp4")
        self.assertEqual(
            delivery_authority_dir(self.plan), self.producer)
        self.assertNotEqual(
            delivery_authority_dir(self.plan), os.path.dirname(candidate))


if __name__ == "__main__":
    unittest.main()
