"""Structured Ask Editor phrase route reads only controller-owned evidence."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest

from edit.cut_repair_context_sources import digest as materialized_digest
from edit.cut_repair_route import RouteContractError, _canonical_hash, run
from edit.cut_repair_selection import select_restore_candidate
from edit.picture_lock_common import PictureLockError

HASH = "a" * 64


def _digest(value: object) -> str:
    return materialized_digest(value)


def _evidence() -> dict:
    return {
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
            "receiptSha256": "7" * 64,
            "runtimeSha256": "8" * 64,
            "musicSfxOverlapCount": 0,
        },
    }


def _source_timing() -> dict:
    return {
        "transcript": {
            "sourceId": "raw",
            "timingHash": HASH,
            "words": [
                {
                    "word": "use", "startSample": 40_000,
                    "endSampleExclusive": 47_000, "speaker": "host",
                },
                {
                    "word": "automation", "startSample": 48_000,
                    "endSampleExclusive": 52_800, "speaker": "host",
                },
            ],
        },
        "segments": [{
            "segmentId": "seg-180",
            "elementVersion": 1,
            "sourceId": "raw",
            "sourceRate": 48_000,
            "sourceSamples": {
                "startSample": 20_000, "endSampleExclusive": 50_400,
            },
            "outputFrames": {
                "startFrame": 150, "endFrameExclusive": 180,
            },
            "speed": {"numerator": "1", "denominator": "1"},
            "sourceFps": {"numerator": "30", "denominator": "1"},
        }],
        "silences": [{
            "silenceId": "sil-180",
            "segmentId": "seg-180",
            "sourceId": "raw",
            "sourceSamples": {
                "startSample": 30_000, "endSampleExclusive": 33_200,
            },
            "outputFrames": {
                "startFrame": 155, "endFrameExclusive": 157,
            },
        }],
    }


def _repair_evidence() -> dict:
    return {
        "coveredPicture": [{
            "startFrame": 180, "endFrameExclusive": 182,
        }],
        "replaceableAudio": [{
            "startSample": 288_000, "endSampleExclusive": 291_200,
        }],
        "replaceableAudioEvidenceHash": "8" * 64,
        "dependents": [{
            "stableId": "caption-1",
            "elementKind": "caption",
            "frames": {"startFrame": 185, "endFrameExclusive": 190},
            "anchorType": "content",
        }],
        "clock": {
            "fps": {"numerator": "30", "denominator": "1"},
            "sampleRate": 48_000,
        },
        "totalFrames": 360,
        "parentTimelineMapHash": "9" * 64,
        "parentPictureLockHash": "b" * 64,
        "maxDirtyFrames": 120,
        "maxAudioOverlapFrames": 15,
        "evidence": _evidence(),
    }


def _core(root: str) -> dict:
    source_path = os.path.join(root, "source.mov")
    parent_path = os.path.join(root, "parent.mov")
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-analysis-context",
        "parentRevisionHash": "7" * 64,
        **_source_timing(),
        **_repair_evidence(),
        "sourceMedia": {
            "sourceId": "raw", "path": source_path,
            "sha256": hashlib.sha256(b"source-media").hexdigest(),
        },
        "parentMedia": {
            "path": parent_path,
            "sha256": hashlib.sha256(b"parent-media").hexdigest(),
        },
    }


def _write_json(path: str, value: object) -> None:
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)


class CutRepairRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = os.path.realpath(tempfile.mkdtemp())
        os.makedirs(os.path.join(self.root, ".sniper-authority-v1"))
        with open(os.path.join(
                self.root, ".sniper-authority-v1", "ACTIVE_HEAD"),
                "w", encoding="ascii") as stream:
            stream.write("7" * 64 + "\n")
        with open(os.path.join(self.root, "source.mov"), "wb") as stream:
            stream.write(b"source-media")
        with open(os.path.join(self.root, "parent.mov"), "wb") as stream:
            stream.write(b"parent-media")
        core = _core(self.root)
        self.context = {**core, "authorityHash": _digest(core)}
        _write_json(
            os.path.join(self.root, "cut_repair_context_v1.json"),
            self.context)
        self.directive_path = os.path.join(self.root, "directive.json")
        _write_json(self.directive_path, {
            "schemaVersion": 1,
            "operation": "cut.restoreSpeech",
            "mode": "analyze",
            "target": {"phrase": "automation", "occurrence": 1},
        })

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_structured_phrase_resolves_and_enumerates(self) -> None:
        result = run(self.root, self.directive_path)
        self.assertEqual(result["status"], "eligible")
        self.assertEqual(result["routeStatus"], "analysis-only-no-mutation")
        self.assertEqual(result["contextAuthorityHash"],
                         self.context["authorityHash"])
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(
            result["recommendedCandidate"]["operation"]["method"],
            "audio-lj-overlap")
        self.assertEqual(
            result["resolvedTarget"]["wordIds"],
            ["w-" + hashlib.sha256(
                ("sniper-caption-word-v1\0raw\0" + "1").encode()
            ).hexdigest()[:16]])

    def test_candidate_selection_is_order_independent(self) -> None:
        result = run(self.root, self.directive_path)
        selected = select_restore_candidate(
            list(reversed(result["candidates"])))
        self.assertEqual(
            selected["operationHash"],
            result["recommendedCandidate"]["operationHash"])

    def test_materializer_and_analyzer_share_edge_hash(self) -> None:
        payload = {
            "seconds": [1e-6, 1e-7],
            "decisions": {"2": "keep", "10": "remove"},
        }
        self.assertEqual(materialized_digest(payload), _canonical_hash(payload))

    def test_candidate_selection_rejects_hash_tampering(self) -> None:
        result = run(self.root, self.directive_path)
        candidates = list(result["candidates"])
        candidates[0] = {**candidates[0], "operationHash": "f" * 64}
        with self.assertRaisesRegex(PictureLockError, "hash is stale"):
            select_restore_candidate(candidates)

    def test_existing_jcut_filters_overlapping_audio_candidate(self) -> None:
        core = _core(self.root)
        core["existingAudioLeadSampleRanges"] = [{
            "segmentId": "seg-prior",
            "outputSampleRange": {
                "startSample": 288_000,
                "endSampleExclusive": 290_400,
            },
        }]
        _write_json(
            os.path.join(self.root, "cut_repair_context_v1.json"),
            {**core, "authorityHash": _digest(core)})
        result = run(self.root, self.directive_path)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(
            result["recommendedCandidate"]["operation"]["method"],
            "extend-and-reclaim-silence")

    def test_missing_alignment_provenance_fails_closed(self) -> None:
        core = _core(self.root)
        del core["evidence"]["alignment"]["modelSha256"]
        _write_json(
            os.path.join(self.root, "cut_repair_context_v1.json"),
            {**core, "authorityHash": _digest(core)})
        with self.assertRaisesRegex(RouteContractError, "alignment"):
            run(self.root, self.directive_path)

    def test_stale_parent_head_fails_closed(self) -> None:
        with open(os.path.join(
                self.root, ".sniper-authority-v1", "ACTIVE_HEAD"),
                "w", encoding="ascii") as stream:
            stream.write("c" * 64 + "\n")
        with self.assertRaisesRegex(RouteContractError, "ACTIVE_HEAD"):
            run(self.root, self.directive_path)

    def test_directive_cannot_supply_evidence_or_hashes(self) -> None:
        _write_json(self.directive_path, {
            "schemaVersion": 1,
            "operation": "cut.restoreSpeech",
            "mode": "analyze",
            "target": {"phrase": "automation"},
            "alignmentHash": "f" * 64,
        })
        with self.assertRaisesRegex(RouteContractError, "fields"):
            run(self.root, self.directive_path)

    def test_directive_disambiguators_are_strictly_typed(self) -> None:
        _write_json(self.directive_path, {
            "schemaVersion": 1,
            "operation": "cut.restoreSpeech",
            "mode": "analyze",
            "target": {
                "phrase": "automation",
                "occurrence": True,
            },
        })
        with self.assertRaisesRegex(ValueError, "occurrence"):
            run(self.root, self.directive_path)

    def test_approximate_sample_requires_tolerance(self) -> None:
        _write_json(self.directive_path, {
            "schemaVersion": 1,
            "operation": "cut.restoreSpeech",
            "mode": "analyze",
            "target": {
                "phrase": "automation",
                "approximateSourceSample": 50_000,
            },
        })
        with self.assertRaisesRegex(ValueError, "must be paired"):
            run(self.root, self.directive_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
