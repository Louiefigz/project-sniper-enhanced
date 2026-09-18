"""Live P2 context is derived from current authority, never request hashes."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest

from edit.cut_repair_context_materialize import (
    ContextMaterializationError,
    materialize,
)
from edit.cut_repair_route import run
from fingerprints import plan_content_hash


def _bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode()


def _write_json(path: str, value: object) -> str:
    payload = _bytes(value)
    with open(path, "wb") as stream:
        stream.write(payload)
    return hashlib.sha256(payload).hexdigest()


def _write_pretty_json(path: str, value: object) -> str:
    payload = (json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with open(path, "wb") as stream:
        stream.write(payload)
    return hashlib.sha256(payload).hexdigest()


def _write_media(path: str, payload: bytes) -> str:
    with open(path, "wb") as stream:
        stream.write(payload)
    return hashlib.sha256(payload).hexdigest()


def _evidence_core(fixture: "_Fixture") -> dict:
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-acoustic-evidence",
        "parentRevisionHash": fixture.head,
        "planSha256": fixture.plan_hash,
        "manifestSha256": fixture.manifest_hash,
        "sourceId": "raw",
        "alignment": {
            "status": "pinned-bounded-evidence",
            "receiptSha256": "1" * 64,
            "runtimeSha256": "2" * 64,
            "modelSha256": "3" * 64,
            "cacheSha256": "4" * 64,
        },
        "vad": {
            "status": "pinned-bounded-evidence",
            "receiptSha256": "5" * 64,
        },
        "audition": {
            "status": "operator-reported-damage",
            "receiptSha256": "6" * 64,
        },
        "audioIsolation": {
            "status": "dialogue-only-bounded-evidence",
            "receiptSha256": "9" * 64,
            "runtimeSha256": "a" * 64,
            "musicSfxOverlapCount": 0,
        },
        "silences": [],
        "coveredPicture": [{"startFrame": 32, "endFrameExclusive": 34}],
        "replaceableAudio": [
            {"startSample": 51_200, "endSampleExclusive": 53_600}],
        "replaceableAudioEvidenceHash": "5" * 64,
        "dependents": [],
        "parentMedia": {
            "path": fixture.parent_path,
            "sha256": fixture.parent_hash,
        },
        "maxDirtyFrames": 120,
        "maxAudioOverlapFrames": 15,
    }


class _Fixture:
    def __init__(self, audio_lead: bool = False) -> None:
        self.audio_lead = audio_lead
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.producer = os.path.join(self.root, "producer")
        self.source_dir = os.path.join(self.root, "source")
        os.makedirs(self.producer)
        os.makedirs(self.source_dir)
        self.source_path = os.path.join(self.source_dir, "raw.mov")
        self.parent_path = os.path.join(self.producer, "parent.mov")
        self.source_hash = _write_media(self.source_path, b"source")
        self.parent_hash = _write_media(self.parent_path, b"parent")
        self.directive_path = os.path.join(self.root, "directive.json")
        _write_json(self.directive_path, {
            "schemaVersion": 1, "operation": "cut.restoreSpeech",
            "mode": "analyze", "target": {"phrase": "automation"},
        })
        self._write_transcript()
        self.plan_hash = self._write_plan()
        self.manifest_path = os.path.join(self.source_dir, "manifest.json")
        self.manifest_hash = self._write_manifest()
        self.head = self._write_revision()
        self._write_evidence()

    def _write_transcript(self) -> None:
        _write_json(os.path.join(
            self.source_dir, "raw.transcript.json"), {
                "transcript": [{
                    "speaker": "host",
                    "words": [
                        {"word": "use", "start": 0.8, "end": 0.95},
                        {"word": "automation", "start": 1.0, "end": 1.1},
                    ],
                }],
            })

    def _write_plan(self) -> str:
        self.plan = {
            "planVersion": 1,
            "target": {"mode": "longform", "fps": 30},
            "cutTrack": [
                {"id": "seg-a", "sourceId": "raw",
                 "start": 0, "end": 1.05, "speed": 1},
                {"id": "seg-b", "sourceId": "raw",
                 "start": 2, "end": 5, "speed": 1,
                 **({"audioLeadMs": 50} if self.audio_lead else {})},
            ],
        }
        self.plan_content_hash = plan_content_hash(self.plan)
        return _write_pretty_json(
            os.path.join(self.producer, "edit_plan.json"), self.plan)

    def _write_manifest(self) -> str:
        return _write_json(self.manifest_path, {
            "sources": [{
                "id": "raw", "path": self.source_path,
                "contentHash": self.source_hash,
                "transcriptPath": "raw.transcript.json",
                "fps": 30, "vfr": False,
                "audio": {"sampleRate": 48_000},
            }],
        })

    def _write_revision(self) -> str:
        revision = {
            "schemaVersion": 1, "workflowState": "PICTURE_LOCKED",
            "pictureLockHash": "7" * 64, "timelineMapHash": "8" * 64,
            "planContentHash": self.plan_content_hash,
            "manifestHash": self.manifest_hash,
        }
        head = hashlib.sha256(_bytes(revision)).hexdigest()
        authority = os.path.join(
            self.producer, ".sniper-authority-v1")
        revisions = os.path.join(authority, "objects", "revisions")
        os.makedirs(revisions)
        _write_json(os.path.join(revisions, f"{head}.json"), revision)
        with open(os.path.join(authority, "ACTIVE_HEAD"),
                  "w", encoding="ascii") as stream:
            stream.write(head + "\n")
        return head

    def upgrade_revision_v2(self, content_hash: str | None = None) -> None:
        authority = os.path.join(
            self.producer, ".sniper-authority-v1")
        with open(os.path.join(self.producer, "edit_plan.json"),
                  encoding="utf-8") as stream:
            plan = json.load(stream)
        plans = os.path.join(authority, "objects", "plans")
        os.makedirs(plans)
        object_hash = hashlib.sha256(_bytes(plan)).hexdigest()
        _write_json(os.path.join(plans, f"{object_hash}.json"), plan)
        revision = {
            "schemaVersion": 2, "workflowState": "PICTURE_LOCKED",
            "pictureLockHash": "7" * 64, "timelineMapHash": "8" * 64,
            "planContentHash": content_hash or self.plan_content_hash,
            "planObjectHash": object_hash,
            "manifestHash": self.manifest_hash,
        }
        self.head = hashlib.sha256(_bytes(revision)).hexdigest()
        revisions = os.path.join(authority, "objects", "revisions")
        _write_json(os.path.join(
            revisions, f"{self.head}.json"), revision)
        with open(os.path.join(authority, "ACTIVE_HEAD"),
                  "w", encoding="ascii") as stream:
            stream.write(self.head + "\n")
        self._write_evidence()

    def _write_evidence(self, **overrides: object) -> None:
        core = {**_evidence_core(self), **overrides}
        document = {
            **core,
            "authorityHash": hashlib.sha256(_bytes(core)).hexdigest(),
        }
        _write_json(os.path.join(
            self.producer, "cut_repair_acoustic_evidence_v1.json"), document)

    def clean(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class CutRepairContextMaterializeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = _Fixture()

    def tearDown(self) -> None:
        self.fixture.clean()

    def test_pretty_v1_live_plan_materializes_eligible_analysis(self) -> None:
        self.assertNotEqual(self.fixture.plan_hash, self.fixture.plan_content_hash)
        value = materialize(
            self.fixture.producer, self.fixture.manifest_path,
            self.fixture.directive_path)
        context_path = os.path.join(
            self.fixture.producer, "cut_repair_context_v1.json")
        _write_json(context_path, value)
        result = run(self.fixture.producer, self.fixture.directive_path)
        self.assertEqual(result["status"], "eligible")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(
            result["candidates"][0]["operation"]["method"],
            "audio-lj-overlap")
        self.assertEqual(
            value["sourceMedia"]["sha256"], self.fixture.source_hash)

    def test_existing_jcut_is_materialized_as_exact_sample_ownership(
            self) -> None:
        self.fixture.clean()
        self.fixture = _Fixture(audio_lead=True)
        value = materialize(
            self.fixture.producer, self.fixture.manifest_path,
            self.fixture.directive_path)
        self.assertEqual(value["existingAudioLeadSampleRanges"], [{
            "segmentId": "seg-b",
            "outputSampleRange": {
                "startSample": 48_800,
                "endSampleExclusive": 51_200,
            },
        }])

    def test_missing_acoustic_evidence_fails_closed(self) -> None:
        os.unlink(os.path.join(
            self.fixture.producer,
            "cut_repair_acoustic_evidence_v1.json"))
        with self.assertRaises(FileNotFoundError):
            materialize(
                self.fixture.producer, self.fixture.manifest_path,
                self.fixture.directive_path)

    def test_v2_requires_semantic_and_exact_plan_authority(self) -> None:
        self.fixture.upgrade_revision_v2()
        value = materialize(
            self.fixture.producer, self.fixture.manifest_path,
            self.fixture.directive_path)
        self.assertEqual(value["parentRevisionHash"], self.fixture.head)
        self.fixture.plan["planVersion"] = True
        self.fixture.plan_hash = _write_pretty_json(
            os.path.join(self.fixture.producer, "edit_plan.json"),
            self.fixture.plan)
        self.fixture._write_evidence()
        with self.assertRaisesRegex(ContextMaterializationError, "exact"):
            materialize(
                self.fixture.producer, self.fixture.manifest_path,
                self.fixture.directive_path)

    def test_v2_rejects_stale_semantic_plan_hash(self) -> None:
        self.fixture.upgrade_revision_v2("f" * 64)
        with self.assertRaisesRegex(
                ContextMaterializationError, "semantic authority"):
            materialize(
                self.fixture.producer, self.fixture.manifest_path,
                self.fixture.directive_path)

    def test_stale_acoustic_head_fails_closed(self) -> None:
        self.fixture._write_evidence(parentRevisionHash="9" * 64)
        with self.assertRaisesRegex(
                ContextMaterializationError, "stale or unsealed"):
            materialize(
                self.fixture.producer, self.fixture.manifest_path,
                self.fixture.directive_path)

    def test_changed_source_media_fails_closed(self) -> None:
        with open(self.fixture.source_path, "ab") as stream:
            stream.write(b"-changed")
        with self.assertRaisesRegex(
                ContextMaterializationError, "snapshot authority"):
            materialize(
                self.fixture.producer, self.fixture.manifest_path,
                self.fixture.directive_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
