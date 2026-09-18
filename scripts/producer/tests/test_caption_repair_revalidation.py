"""Caption/chapter recompilation at the P2 non-ripple repair boundary."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from captions.caption_operations import (
    new_caption_track,
    upsert_caption_range,
)
from captions.caption_plan_pipeline import PlanCaptionContext
from captions.caption_repair_revalidation import (
    CaptionRepairContexts,
    revalidate_caption_repair,
)
from captions.caption_words import CaptionFrameRate, stable_word_id
from compile_timeline import compile_plan
from edit.picture_lock_common import PictureLockError


def _track() -> dict:
    ids = [stable_word_id("raw-a", index) for index in range(3)]
    track = new_caption_track("off")
    for word_id in (ids[0], ids[2]):
        track = upsert_caption_range(track, {
            "wordIds": [word_id], "styleId": "karaoke",
            "mode": "karaoke-word", "placement": "bottom-center",
        })
    return track


def _plan(speed: float = 1.0) -> dict:
    return {
        "target": {"mode": "longform"},
        "cutTrack": [{
            "sourceId": "raw-a", "start": 0.0, "end": 4.0,
            "speed": speed,
        }],
        "captions": {"burn": False},
        "captionsTrack": _track(),
        "captionChapters": [{
            "chapterId": "proof", "title": "Proof",
            "wordId": stable_word_id("raw-a", 2),
        }],
    }


def _same_duration_shifted_plan() -> dict:
    plan = _plan()
    plan["cutTrack"] = [
        {
            "sourceId": "raw-a", "start": 0.0, "end": 1.0,
            "speed": 2.0,
        },
        {
            "sourceId": "raw-a", "start": 1.0, "end": 4.0,
            "speed": 6 / 7,
        },
    ]
    return plan


def _write_transcript(path: str, first_end: float = 0.4) -> None:
    words = [
        {"word": "Intro", "start": 0.1, "end": first_end},
        {"word": "middle", "start": 1.0, "end": 1.3},
        {"word": "proof", "start": 2.0, "end": 2.3},
    ]
    Path(path).write_text(json.dumps({
        "transcript": [{"start": 0, "end": 4, "words": words}],
    }))


def _context(root: str, name: str, plan: dict,
             first_end: float = 0.4) -> PlanCaptionContext:
    transcript = os.path.join(root, f"{name}.json")
    _write_transcript(transcript, first_end)
    manifest = {"sources": [{
        "id": "raw-a", "transcriptPath": transcript,
    }]}
    return PlanCaptionContext(
        plan, manifest, compile_plan(plan), CaptionFrameRate(30, 1), root)


def _operation() -> dict:
    return {
        "schemaVersion": 1, "operation": "cut.restoreSpeech",
        "totalOutputFramesBefore": 120, "totalOutputFramesAfter": 120,
        "audioDirtyWindows": [{
            "startFrame": 0, "endFrameExclusive": 20,
        }],
    }


class CaptionRepairRevalidationTests(unittest.TestCase):
    def test_local_timing_rebuilds_one_cue_and_preserves_chapter(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            plan = _plan()
            before = _context(root, "before", plan)
            after = _context(root, "after", plan, first_end=0.5)
            receipt = revalidate_caption_repair(
                CaptionRepairContexts(before, after), _operation())
        self.assertEqual(receipt["status"], "revalidated")
        self.assertEqual(len(receipt["cues"]["changedCueIds"]), 1)
        self.assertEqual(len(receipt["cues"]["unchangedCueIds"]), 1)
        self.assertEqual(receipt["chapters"]["changedChapterIds"], [])
        self.assertEqual(
            receipt["chapters"]["beforeHash"],
            receipt["chapters"]["afterHash"])
        self.assertEqual(
            receipt["beforeCoverage"]["renderedWordIds"],
            receipt["afterCoverage"]["renderedWordIds"])

    def test_shifted_downstream_cue_outside_dirty_window_fails(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            before = _context(root, "before", _plan())
            after = _context(root, "after", _same_duration_shifted_plan())
            with self.assertRaisesRegex(
                    PictureLockError, "outside its dirty windows"):
                revalidate_caption_repair(
                    CaptionRepairContexts(before, after), _operation())

    def test_context_duration_must_match_declared_repair_clock(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            before = _context(root, "before", _plan())
            after = _context(root, "after", _plan(speed=1.1))
            with self.assertRaisesRegex(
                    PictureLockError, "do not match repair frame totals"):
                revalidate_caption_repair(
                    CaptionRepairContexts(before, after), _operation())

    def test_actual_no_caption_contexts_emit_not_present(self) -> None:
        plan = {"cutTrack": [{
            "sourceId": "raw-a", "start": 0.0, "end": 4.0,
        }]}
        with tempfile.TemporaryDirectory() as root:
            context = PlanCaptionContext(
                plan, {"sources": []}, compile_plan(plan),
                CaptionFrameRate(30, 1), root)
            receipt = revalidate_caption_repair(
                CaptionRepairContexts(context, context), _operation())
        self.assertEqual(receipt["status"], "not-present")
        self.assertRegex(receipt["revalidationHash"], r"^[0-9a-f]{64}$")

    def test_emitted_receipts_match_closed_schema_branches(self) -> None:
        root = Path(__file__).resolve().parents[3]
        schema = json.loads((root / "schemas" / "producer" /
                             "caption-repair-revalidation-v1.schema.json")
                            .read_text())
        self.assertFalse(schema["unevaluatedProperties"])
        with tempfile.TemporaryDirectory() as work:
            plan = _plan()
            contexts = CaptionRepairContexts(
                _context(work, "before", plan),
                _context(work, "after", plan, first_end=0.5))
            receipt = revalidate_caption_repair(contexts, _operation())
        branch = schema["$defs"]["revalidated"]
        self.assertEqual(set(receipt), set(branch["required"]))
        self.assertTrue(set(receipt).issubset(branch["properties"]))
        for key in ("cues", "beforeCoverage", "afterCoverage"):
            nested = schema["$defs"][key if key == "cues" else "coverage"]
            self.assertEqual(set(receipt[key]), set(nested["required"]))
            self.assertTrue(set(receipt[key]).issubset(nested["properties"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
