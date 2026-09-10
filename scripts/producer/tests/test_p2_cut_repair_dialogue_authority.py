"""P2 plan-carried dialogue/caption authority and locality tests."""
from __future__ import annotations

import copy
import unittest

from captions.caption_words import CaptionFrameRate, stable_word_id
from captions.caption_repair_revalidation import caption_compilation_hash
from captions.cut_repair_dialogue_authority import (
    PLAN_FIELD,
    CutRepairCaptionAuthorityInput,
    build_cut_repair_caption_authority,
    compile_plan_cut_repair_captions,
    parse_cut_repair_caption_authority,
)
from captions.dialogue_caption_timing import (
    occurrence_word_id,
    resolve_dialogue_caption_words,
)
from contracts.schema_validator import validate_document
from edit.cut_repair_context_sources import digest
from edit.cut_repair_promotion_proof import PromotionProofInput, _caption
from edit.exact_timing import PositiveRational, ProjectClock

RATE = CaptionFrameRate(30_000, 1_001)
CLOCK = ProjectClock(PositiveRational(30_000, 1_001), 48_000)
TARGET_ID = stable_word_id("source-b", 0)
OUTSIDE_ID = stable_word_id("source-b", 1)
REPEAT_ID = stable_word_id("source-a", 0)


def _group(number: int, word_id: str) -> dict:
    return {
        "groupId": f"cg-{number:016x}",
        "anchor": {"kind": "word-range", "wordIds": [word_id]},
        "styleId": "karaoke",
        "mode": "karaoke-word",
        "placement": "bottom-center",
    }


def _plan() -> dict:
    repeated = [
        occurrence_word_id(REPEAT_ID, occurrence)
        for occurrence in (1, 2)
    ]
    return {
        "planVersion": 1,
        "target": {"mode": "longform", "fps": 29.97},
        "cutTrack": [
            {"id": "seg-a", "sourceId": "source-a",
             "start": 0, "end": 3.003, "speed": 1},
            {"id": "seg-b", "sourceId": "source-b",
             "start": 0.1, "end": 2.102, "speed": 1},
            {"id": "seg-c", "sourceId": "source-a",
             "start": 0, "end": 1.001, "speed": 1},
        ],
        "cutDecisions": {"schemaVersion": 1, "removals": []},
        "captionsTrack": {
            "schemaVersion": 1,
            "source": "kept-transcript",
            "defaultPolicy": "off",
            "groups": [
                _group(1, TARGET_ID), _group(2, OUTSIDE_ID),
                _group(3, repeated[0]), _group(4, repeated[1]),
            ],
        },
        "captionChapters": [{
            "chapterId": "outside",
            "title": "Outside",
            "wordId": OUTSIDE_ID,
        }],
    }


def _segments() -> list[dict]:
    values = (
        ("seg-a", "source-a", 0, 144_144, 0, 90),
        ("seg-b", "source-b", 4_800, 100_896, 90, 150),
        ("seg-c", "source-a", 0, 48_048, 150, 180),
    )
    return [{
        "segmentId": ident, "elementVersion": 1, "sourceId": source,
        "sourceRate": 48_000,
        "sourceSamples": {
            "startSample": source_start,
            "endSampleExclusive": source_end,
        },
        "outputFrames": {
            "startFrame": frame_start,
            "endFrameExclusive": frame_end,
        },
        "speed": {"numerator": "1", "denominator": "1"},
    } for ident, source, source_start, source_end,
        frame_start, frame_end in values]


def _sources() -> list[dict]:
    return [{
        "sourceId": "source-a", "sourceSampleRate": 48_000,
        "sourceMediaSha256": "1" * 64,
        "transcriptTimingHash": "2" * 64,
        "words": [{
            "sourceWordId": REPEAT_ID, "text": "repeat",
            "sourceSampleRange": {
                "startSample": 9_600, "endSampleExclusive": 12_000},
        }],
    }, {
        "sourceId": "source-b", "sourceSampleRate": 48_000,
        "sourceMediaSha256": "3" * 64,
        "transcriptTimingHash": "4" * 64,
        "words": [{
            "sourceWordId": TARGET_ID, "text": "target",
            "sourceSampleRange": {
                "startSample": 2_400, "endSampleExclusive": 7_200},
        }, {
            "sourceWordId": OUTSIDE_ID, "text": "outside",
            "sourceSampleRange": {
                "startSample": 20_000, "endSampleExclusive": 24_000},
        }],
    }]


def _context() -> dict:
    sources = _sources()
    snapshots = [{
        "sourceId": row["sourceId"],
        "sourceMediaSha256": row["sourceMediaSha256"],
        "transcriptTimingHash": row["transcriptTimingHash"],
    } for row in sources]
    return {
        "segments": _segments(),
        "totalFrames": 180,
        "parentTimelineMapHash": "a" * 64,
        "sourceSnapshotSetHash": digest(snapshots),
        "dialogueSources": sources,
    }


def _operation() -> dict:
    return {
        "schemaVersion": 1, "operation": "cut.restoreSpeech",
        "target": {
            "kind": "word-range", "sourceId": "source-b",
            "wordIds": [TARGET_ID], "occurrence": 1,
            "sourceSampleRange": {
                "startSample": 2_400, "endSampleExclusive": 7_200},
            "transcriptTimingHash": "4" * 64,
        },
        "parentPictureLockHash": "9" * 64,
        "parentTimelineMapHash": "a" * 64,
        "segment": {
            "segmentId": "seg-b", "elementVersion": 1, "edge": "start"},
        "sourceExtension": {
            "startSample": 2_400, "endSampleExclusive": 4_800},
        "sourceSampleRate": 48_000,
        "speed": {"numerator": "1", "denominator": "1"},
        "extensionFrames": 2,
        "preserveUnrelated": True,
        "extensionOutputSamples": 2_400,
        "totalOutputFramesBefore": 180,
        "totalOutputFramesAfter": 180,
        "method": "audio-lj-overlap",
        "pictureDirtyWindows": [],
        "audioDirtyWindows": [{
            "startFrame": 88, "endFrameExclusive": 92}],
        "audioDirtySampleRanges": [{
            "startSample": 141_744, "endSampleExclusive": 144_144}],
        "replacedAudioSampleRanges": [{
            "startSample": 141_744, "endSampleExclusive": 144_144}],
        "replaceableAudioEvidenceHash": "8" * 64,
        "unchangedPictureMappingRanges": [{
            "startFrame": 0, "endFrameExclusive": 180}],
        "revalidatedDependentIds": [],
        "unchangedDependentIds": [],
    }


def _authority(plan: dict | None = None, context: dict | None = None) -> dict:
    parent = plan or _plan()
    child = copy.deepcopy(parent)
    child["cutTrack"][1]["audioLeadMs"] = 50
    return build_cut_repair_caption_authority(
        CutRepairCaptionAuthorityInput(
            parent, child, context or _context(), _operation(),
            "b" * 64, CLOCK))


class CutRepairDialogueAuthorityTests(unittest.TestCase):
    def test_rational_multi_source_jcut_is_local_and_runtime_exact(self) -> None:
        authority = _authority()
        self.assertEqual(
            validate_document(
                "cut-repair-dialogue-caption-authority-v1.schema.json",
                authority),
            authority)
        receipt = authority["captionRevalidation"]
        self.assertEqual(receipt["status"], "revalidated")
        self.assertEqual(len(receipt["cues"]["changedCueIds"]), 1)
        self.assertEqual(len(receipt["cues"]["unchangedCueIds"]), 3)
        self.assertEqual(receipt["chapters"]["changedChapterIds"], [])
        self.assertEqual(
            receipt["chapters"]["beforeHash"],
            receipt["chapters"]["afterHash"])
        self.assertEqual(
            authority["childDialogueTrack"]["totalOutputSamples"],
            CLOCK.sample_at_frame(180))
        child = copy.deepcopy(_plan())
        child["cutTrack"][1]["audioLeadMs"] = 50
        child[PLAN_FIELD] = authority
        compiled = compile_plan_cut_repair_captions(child, RATE)
        self.assertEqual(
            receipt["afterCompilationHash"],
            caption_compilation_hash(compiled))

    def test_target_word_crosses_handle_and_primary(self) -> None:
        authority = _authority()
        timing = resolve_dialogue_caption_words(
            authority["childSourceWords"], authority["childDialogueMap"])
        target = next(row for row in timing["words"]
                      if row["sourceWordId"] == TARGET_ID)
        self.assertEqual(
            target["dialogueRoles"], ["j-cut-handle", "primary"])
        self.assertEqual(
            target["coveringCutSegmentIds"], ["seg-a", "seg-b"])

    def test_repeated_source_word_requires_occurrence_binding(self) -> None:
        plan = _plan()
        plan["captionsTrack"]["groups"][2]["anchor"]["wordIds"] = [REPEAT_ID]
        with self.assertRaisesRegex(
                ValueError, "CAPTION_OCCURRENCE_BINDING_REQUIRED"):
            _authority(plan)

    def test_missing_source_timing_and_bad_handle_fail_closed(self) -> None:
        context = _context()
        context.pop("dialogueSources")
        with self.assertRaisesRegex(
                ValueError, "CAPTION_DIALOGUE_SOURCE_TIMING_REQUIRED"):
            _authority(context=context)
        stale = _context()
        stale["sourceSnapshotSetHash"] = "0" * 64
        with self.assertRaisesRegex(
                ValueError, "CAPTION_DIALOGUE_SOURCE_SNAPSHOT_STALE"):
            _authority(context=stale)
        operation = _operation()
        operation["sourceExtension"]["endSampleExclusive"] = 4_799
        parent = _plan()
        child = copy.deepcopy(parent)
        child["cutTrack"][1]["audioLeadMs"] = 50
        with self.assertRaisesRegex(
                ValueError, "CAPTION_DIALOGUE_JCUT_AUTHORITY_REQUIRED"):
            build_cut_repair_caption_authority(
                CutRepairCaptionAuthorityInput(
                    parent, child, _context(), operation, "b" * 64, CLOCK))

    def test_nested_tampering_is_rejected_by_authority_hash(self) -> None:
        changed = copy.deepcopy(_authority())
        changed["childSourceWords"][0]["text"] = "substituted"
        with self.assertRaisesRegex(ValueError, "authority is stale"):
            parse_cut_repair_caption_authority(changed)

    def test_promotion_consumes_the_exact_plan_carried_receipt(self) -> None:
        authority = _authority()
        item = PromotionProofInput(
            {"captionDialogueAuthority": authority}, _operation(),
            authority["operationHash"], {}, "5" * 64)
        self.assertEqual(
            _caption(item), authority["captionRevalidation"])
        changed = PromotionProofInput(
            item.value, item.operation, "0" * 64, item.revision,
            item.revision_hash)
        with self.assertRaisesRegex(ValueError, "another repair operation"):
            _caption(changed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
