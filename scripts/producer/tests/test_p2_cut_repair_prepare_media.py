"""P2 preparation renders real media but cannot promote diagnostic bytes."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest

from edit.compatibility_projection import build_projection
from edit.cut_repair_context_materialize import materialize
from edit.cut_repair_prepare_media import (
    PreparationError,
    _lead_ms,
    _review_plan,
    _selection,
    prepare,
)
from edit.exact_timing import PositiveRational, ProjectClock
from edit.picture_lock_common import content_hash
from fingerprints import file_sha256, plan_content_hash
from tests._p2_repair_media_fixture import FFMPEG, FFPROBE, media


def _bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()


def _write_json(path: str, value: object) -> str:
    payload = _bytes(value)
    with open(path, "wb") as stream:
        stream.write(payload)
    return hashlib.sha256(payload).hexdigest()


class _Fixture:
    def __init__(self) -> None:
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.producer = os.path.join(self.root, "producer")
        self.source_dir = os.path.join(self.root, "source")
        os.makedirs(self.producer)
        os.makedirs(self.source_dir)
        self.source_path = os.path.join(self.source_dir, "raw.mov")
        self.parent_path = os.path.join(self.producer, "parent.mov")
        media(self.source_path, "30/1", True, False)
        media(self.parent_path, "30/1", False)
        self.directive_path = self._directive()
        self.plan, self.plan_hash = self._plan()
        self.manifest_path, self.manifest_hash = self._manifest()
        self.head = self._revision()
        self._evidence()
        self.context_path = os.path.join(self.root, "context.json")
        _write_json(self.context_path, materialize(
            self.producer, self.manifest_path, self.directive_path))
        self.staging = os.path.join(
            self.producer, ".sniper-cut-repair-staging", "case")
        os.makedirs(self.staging)

    def _directive(self) -> str:
        path = os.path.join(self.root, "directive.json")
        _write_json(path, {
            "schemaVersion": 1, "operation": "cut.restoreSpeech",
            "mode": "analyze", "target": {"phrase": "automation"},
        })
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
        return path

    def _plan(self) -> tuple[dict, str]:
        value = {
            "planVersion": 1,
            "target": {"mode": "longform", "fps": 30},
            "cutTrack": [
                {"id": "seg-a", "sourceId": "raw",
                 "start": 3, "end": 4.05, "speed": 1},
                {"id": "seg-b", "sourceId": "raw",
                 "start": 1.05, "end": 5, "speed": 1},
            ],
            "cutDecisions": {"schemaVersion": 1, "removals": []},
            "captionsTrack": {
                "schemaVersion": 1,
                "source": "kept-transcript",
                "defaultPolicy": "karaoke",
                "groups": [],
            },
        }
        return value, _write_json(
            os.path.join(self.producer, "edit_plan.json"), value)

    def _manifest(self) -> tuple[str, str]:
        path = os.path.join(self.source_dir, "manifest.json")
        value = {"sources": [{
            "id": "raw", "path": self.source_path,
            "contentHash": file_sha256(self.source_path),
            "transcriptPath": "raw.transcript.json",
            "fps": 30, "vfr": False,
            "audio": {"sampleRate": 48_000},
        }]}
        return path, _write_json(path, value)

    def _revision(self) -> str:
        timeline_hash = build_projection(
            self.plan, self.plan_hash)["timelineMapHash"]
        revision = {
            "schemaVersion": 1, "workflowState": "PICTURE_LOCKED",
            "pictureLockHash": "7" * 64,
            "timelineMapHash": timeline_hash,
            "planContentHash": plan_content_hash(self.plan),
            "manifestHash": self.manifest_hash,
        }
        head = hashlib.sha256(_bytes(revision)).hexdigest()
        root = os.path.join(self.producer, ".sniper-authority-v1")
        revisions = os.path.join(root, "objects", "revisions")
        os.makedirs(revisions)
        _write_json(os.path.join(revisions, f"{head}.json"), revision)
        with open(os.path.join(root, "ACTIVE_HEAD"),
                  "w", encoding="ascii") as stream:
            stream.write(head + "\n")
        return head

    def _evidence(self) -> None:
        core = {
            "schemaVersion": 1,
            "kind": "cut-repair-acoustic-evidence",
            "parentRevisionHash": self.head,
            "planSha256": self.plan_hash,
            "manifestSha256": self.manifest_hash,
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
            "coveredPicture": [{
                "startFrame": 30, "endFrameExclusive": 32,
            }],
            "replaceableAudio": [{
                "startSample": 48_800, "endSampleExclusive": 51_200,
            }],
            "replaceableAudioEvidenceHash": "b" * 64,
            "dependents": [],
            "parentMedia": {
                "path": self.parent_path,
                "sha256": file_sha256(self.parent_path),
            },
            "maxDirtyFrames": 120,
            "maxAudioOverlapFrames": 15,
        }
        _write_json(os.path.join(
            self.producer, "cut_repair_acoustic_evidence_v1.json"), {
                **core,
                "authorityHash": hashlib.sha256(_bytes(core)).hexdigest(),
            })

    def clean(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg and ffprobe required")
class CutRepairPrepareMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = _Fixture()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.clean()

    def test_start_edge_preparation_renders_real_diagnostic_media(self) -> None:
        value = prepare(
            self.fixture.producer, self.fixture.directive_path,
            self.fixture.context_path, self.fixture.staging)
        operation = value["operation"]
        self.assertEqual(operation["method"], "audio-lj-overlap")
        self.assertEqual(operation["segment"]["edge"], "start")
        self.assertEqual(value["reviewPlan"]["cutTrack"][1]["audioLeadMs"], 50)
        self.assertNotEqual(
            value["reviewTimelineMapHash"],
            operation["parentTimelineMapHash"])
        authority = value["reviewPlan"]["dialogueCaptionAuthority"]
        self.assertEqual(
            authority["captionRevalidation"]["status"], "revalidated")
        self.assertEqual(
            authority["operationHash"], value["operationHash"])
        for name, receipt in (
                ("fragment.mov", value["fragmentReceipt"]),
                ("candidate.mov", value["compositeReceipt"])):
            path = os.path.join(self.fixture.staging, name)
            self.assertTrue(os.path.isfile(path))
            self.assertEqual(receipt["output"]["sha256"], file_sha256(path))
        self.assertEqual(
            value["compositeReceipt"]["output"]["videoFrames"], 150)


class CutRepairPreparationBoundaryTests(unittest.TestCase):
    def test_end_edge_l_cut_is_not_in_released_plan_vocabulary(self) -> None:
        operation = {
            "method": "audio-lj-overlap",
            "segment": {"edge": "end"},
        }
        policy = {"kind": "test-policy"}
        result = {
            "status": "eligible",
            "recommendedCandidate": {
                "operation": operation,
                "operationHash": content_hash(operation),
                "selectionPolicy": policy,
                "selectionPolicyHash": content_hash(policy),
            },
        }
        with self.assertRaisesRegex(
                PreparationError, "PLAN_VOCABULARY_LCUT_UNAVAILABLE"):
            _selection(result)

    def test_sub_millisecond_lead_is_not_plan_exact(self) -> None:
        operation = {
            "extensionOutputSamples": 2_401,
            "sourceExtension": {
                "startSample": 48_000,
                "endSampleExclusive": 50_401,
            },
            "sourceSampleRate": 48_000,
            "speed": {"numerator": "1", "denominator": "1"},
        }
        with self.assertRaisesRegex(
                PreparationError,
                "PLAN_VOCABULARY_SAMPLE_EXACT_JCUT_UNAVAILABLE"):
            _lead_ms(operation, 48_000)

    def test_caption_plan_without_segment_authority_fails_closed(self) -> None:
        root = os.path.realpath(tempfile.mkdtemp())
        try:
            _write_json(os.path.join(root, "edit_plan.json"), {
                "captionsTrack": {},
            })
            with self.assertRaisesRegex(
                    PreparationError,
                    "cut repair segment authority is malformed"):
                _review_plan(
                    root, {}, {},
                    ProjectClock(PositiveRational(30, 1), 48_000))
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
