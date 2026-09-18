"""Sequential disjoint J-cuts preserve prior dialogue/caption authority."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest

from captions.caption_words import stable_word_id
from edit.compatibility_projection import build_projection
from edit.cut_repair_context_sources import digest
from edit.cut_repair_context_timeline import segments as exact_segments
from edit.cut_repair_existing_leads import assert_new_repair_disjoint
from edit.cut_repair_prepare_media import PreparationError, _review_plan
from edit.exact_timing import PositiveRational, ProjectClock

CLOCK = ProjectClock(PositiveRational(30_000, 1_001), 48_000)
WORD_OUTSIDE = stable_word_id("source-a", 0)
WORD_FIRST = stable_word_id("source-b", 0)
WORD_SECOND = stable_word_id("source-a", 1)


def _group(number: int, word_id: str) -> dict:
    return {
        "groupId": f"cg-{number:016x}",
        "anchor": {"kind": "word-range", "wordIds": [word_id]},
        "styleId": "karaoke", "mode": "karaoke-word",
        "placement": "bottom-center",
    }


def _plan() -> dict:
    return {
        "planVersion": 1,
        "target": {"mode": "longform", "fps": 29.97},
        "cutTrack": [
            {"id": "seg-a", "sourceId": "source-a",
             "start": 0, "end": 3.003, "speed": 1},
            {"id": "seg-b", "sourceId": "source-b",
             "start": 0.1, "end": 2.102, "speed": 1},
            {"id": "seg-c", "sourceId": "source-a",
             "start": 4, "end": 5.001, "speed": 1},
        ],
        "cutDecisions": {"schemaVersion": 1, "removals": []},
        "captionsTrack": {
            "schemaVersion": 1, "source": "kept-transcript",
            "defaultPolicy": "off",
            "groups": [
                _group(1, WORD_OUTSIDE),
                _group(2, WORD_FIRST),
                _group(3, WORD_SECOND),
            ],
        },
        "captionChapters": [{
            "chapterId": "outside", "title": "Outside",
            "wordId": WORD_OUTSIDE,
        }],
    }


def _sources() -> list[dict]:
    return [{
        "sourceId": "source-a", "sourceSampleRate": 48_000,
        "sourceMediaSha256": "1" * 64,
        "transcriptTimingHash": "2" * 64,
        "words": [{
            "sourceWordId": WORD_OUTSIDE, "text": "outside",
            "sourceSampleRange": {
                "startSample": 9_600, "endSampleExclusive": 12_000},
        }, {
            "sourceWordId": WORD_SECOND, "text": "second",
            "sourceSampleRange": {
                "startSample": 189_600, "endSampleExclusive": 194_400},
        }],
    }, {
        "sourceId": "source-b", "sourceSampleRate": 48_000,
        "sourceMediaSha256": "3" * 64,
        "transcriptTimingHash": "4" * 64,
        "words": [{
            "sourceWordId": WORD_FIRST, "text": "first",
            "sourceSampleRange": {
                "startSample": 2_400, "endSampleExclusive": 7_200},
        }],
    }]


def _context() -> dict:
    sources = _sources()
    snapshots = [{
        "sourceId": row["sourceId"],
        "sourceMediaSha256": row["sourceMediaSha256"],
        "transcriptTimingHash": row["transcriptTimingHash"],
    } for row in sources]
    values = (
        ("seg-a", "source-a", 0, 144_144, 0, 90),
        ("seg-b", "source-b", 4_800, 100_896, 90, 150),
        ("seg-c", "source-a", 192_000, 240_048, 150, 180),
    )
    return {
        "segments": [{
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
            frame_start, frame_end in values],
        "totalFrames": 180,
        "sourceSnapshotSetHash": digest(snapshots),
        "dialogueSources": sources,
    }


def _operation_terms(segment: str) -> dict:
    second = segment == "seg-c"
    return {
        "source_id": "source-a" if second else "source-b",
        "word_id": WORD_SECOND if second else WORD_FIRST,
        "timing_hash": "2" * 64 if second else "4" * 64,
        "source_start": 189_600 if second else 2_400,
        "source_end": 192_000 if second else 4_800,
        "word_end": 194_400 if second else 7_200,
        "seam_frame": 150 if second else 90,
    }


def _operation(segment: str, parent_map: str) -> dict:
    terms = _operation_terms(segment)
    source_start = terms["source_start"]
    seam_frame = terms["seam_frame"]
    seam_sample = CLOCK.sample_at_frame(seam_frame)
    return {
        "schemaVersion": 1, "operation": "cut.restoreSpeech",
        "target": {
            "kind": "word-range", "sourceId": terms["source_id"],
            "wordIds": [terms["word_id"]], "occurrence": 1,
            "sourceSampleRange": {
                "startSample": source_start,
                "endSampleExclusive": terms["word_end"],
            },
            "transcriptTimingHash": terms["timing_hash"],
        },
        "parentPictureLockHash": "9" * 64,
        "parentTimelineMapHash": parent_map,
        "segment": {
            "segmentId": segment, "elementVersion": 1, "edge": "start"},
        "sourceExtension": {
            "startSample": source_start,
            "endSampleExclusive": terms["source_end"],
        },
        "sourceSampleRate": 48_000,
        "speed": {"numerator": "1", "denominator": "1"},
        "extensionFrames": 2, "preserveUnrelated": True,
        "totalOutputFramesBefore": 180,
        "totalOutputFramesAfter": 180,
        "method": "audio-lj-overlap",
        "pictureDirtyWindows": [],
        "audioDirtyWindows": [{
            "startFrame": seam_frame - 2,
            "endFrameExclusive": seam_frame,
        }],
        "audioDirtySampleRanges": [{
            "startSample": seam_sample - 2_400,
            "endSampleExclusive": seam_sample,
        }],
        "replacedAudioSampleRanges": [{
            "startSample": seam_sample - 2_400,
            "endSampleExclusive": seam_sample,
        }],
        "replaceableAudioEvidenceHash": "8" * 64,
        "extensionOutputSamples": 2_400,
        "unchangedPictureMappingRanges": [{
            "startFrame": 0, "endFrameExclusive": 180}],
        "revalidatedDependentIds": [],
        "unchangedDependentIds": [],
    }


def _write_plan(root: str, plan: dict) -> str:
    payload = json.dumps(
        plan, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()
    with open(os.path.join(root, "edit_plan.json"), "wb") as stream:
        stream.write(payload)
    return hashlib.sha256(payload).hexdigest()


def _parent_context(root: str, plan: dict, context: dict) -> dict:
    plan_hash = _write_plan(root, plan)
    result = copy.deepcopy(context)
    result["parentTimelineMapHash"] = build_projection(
        plan, plan_hash)["timelineMapHash"]
    return result


class SequentialJcutCaptionTests(unittest.TestCase):
    def test_two_disjoint_repairs_preserve_first_handle_and_outside_cues(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            root = os.path.realpath(root)
            initial = _plan()
            first_context = _parent_context(root, initial, _context())
            first, first_projection = _review_plan(
                root, first_context,
                _operation("seg-b", first_context["parentTimelineMapHash"]),
                CLOCK)
            second_context = _parent_context(root, first, _context())
            self.assertEqual(
                second_context["parentTimelineMapHash"],
                first_projection["timelineMapHash"])
            second, _ = _review_plan(
                root, second_context,
                _operation("seg-c", second_context["parentTimelineMapHash"]),
                CLOCK)
        self.assertEqual(
            [row.get("audioLeadMs") for row in second["cutTrack"]],
            [None, 50, 50])
        first_authority = first["dialogueCaptionAuthority"]
        second_authority = second["dialogueCaptionAuthority"]
        self.assertEqual(
            second_authority["parentDialogueTrackHash"],
            first_authority["childDialogueTrackHash"])
        first_handle = next(
            row for row in first_authority["childDialogueTrack"]["segments"]
            if row["role"] == "j-cut-handle")
        preserved = next(
            row for row in second_authority["parentDialogueTrack"]["segments"]
            if row["role"] == "j-cut-handle")
        self.assertEqual(preserved, first_handle)
        self.assertEqual(
            len([row for row in
                 second_authority["childDialogueTrack"]["segments"]
                 if row["role"] == "j-cut-handle"]),
            2)
        self.assertEqual(
            second_authority["captionRevalidation"]["chapters"]
            ["changedChapterIds"],
            [])

    def test_same_target_and_overlapping_lead_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root = os.path.realpath(root)
            initial = _plan()
            context = _parent_context(root, initial, _context())
            first, _ = _review_plan(
                root, context,
                _operation("seg-b", context["parentTimelineMapHash"]),
                CLOCK)
            next_context = _parent_context(root, first, _context())
            with self.assertRaisesRegex(
                    PreparationError, "already has an audio lead"):
                _review_plan(
                    root, next_context,
                    _operation(
                        "seg-b", next_context["parentTimelineMapHash"]),
                    CLOCK)
            overlap = _operation(
                "seg-c", next_context["parentTimelineMapHash"])
            overlap["replacedAudioSampleRanges"] = [{
                "startSample": 142_000,
                "endSampleExclusive": 143_000,
            }]
            overlap["audioDirtySampleRanges"] = copy.deepcopy(
                overlap["replacedAudioSampleRanges"])
            with self.assertRaisesRegex(
                    ValueError, "CUT_REPAIR_OVERLAPS_EXISTING_AUDIO_LEAD"):
                assert_new_repair_disjoint(
                    first, next_context, overlap, CLOCK)

    def test_rational_context_accepts_governed_existing_jcut(self) -> None:
        plan = _plan()
        plan["cutTrack"][1]["audioLeadMs"] = 50
        sources = {
            "source-a": {
                "fps": 29.97, "vfr": False,
                "audio": {"sampleRate": 48_000},
            },
            "source-b": {
                "fps": 29.97, "vfr": False,
                "audio": {"sampleRate": 48_000},
            },
        }
        rows, total = exact_segments(plan, sources, (30_000, 1_001))
        self.assertEqual(total, 180)
        self.assertEqual(rows[1]["outputFrames"], {
            "startFrame": 90, "endFrameExclusive": 150})


if __name__ == "__main__":
    unittest.main(verbosity=2)
