"""Repeated source-slice caption identity on rational delivery clocks."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from captions.caption_occurrences import occurrence_word_id
from captions.caption_plan_pipeline import (
    PlanCaptionContext,
    compile_plan_caption_track,
)
from captions.caption_words import (
    CaptionFrameRate,
    CaptionWordClock,
    resolve_kept_word_occurrences,
    stable_word_id,
)
from compile_timeline import compile_plan

RATE = CaptionFrameRate(30_000, 1_001)
CLOCK = CaptionWordClock(RATE, 48_000)


def _words() -> list[dict]:
    return [
        {"word": "Project", "start": 0, "end": 0.3},
        {"word": "Sniper", "start": 0.31, "end": 0.7},
        {"word": "works", "start": 0.71, "end": 1},
    ]


def _plan(repeated: bool = True) -> dict:
    track = [{
        "id": "first-use", "sourceId": "raw", "start": 0, "end": 1,
    }]
    if repeated:
        track.append({
            "id": "second-use", "sourceId": "raw", "start": 0, "end": 1,
        })
    source_ids = [stable_word_id("raw", index) for index in range(3)]
    second = [occurrence_word_id(ident, 2) for ident in source_ids]
    return {
        "planVersion": 1,
        "target": {"mode": "short", "fps": 29.97},
        "cutTrack": track,
        "captionsTrack": {
            "schemaVersion": 1,
            "source": "kept-transcript",
            "defaultPolicy": "off",
            "groups": [{
                "groupId": "cg-0000000000000001",
                "anchor": {"kind": "word-range", "wordIds": second},
                "styleId": "karaoke",
                "mode": "karaoke-word",
                "placement": "bottom-center",
            }],
        },
    }


class CaptionOccurrenceTests(unittest.TestCase):
    def test_unique_plan_retains_legacy_word_identity(self) -> None:
        word = resolve_kept_word_occurrences(
            "raw", _words()[:1], compile_plan(_plan(False)), CLOCK)[0]
        self.assertEqual(word["wordId"], stable_word_id("raw", 0))
        self.assertNotIn("sourceWordId", word)
        self.assertNotIn("occurrence", word)

    def test_repeated_slice_mints_output_order_occurrences_at_rational_fps(
        self,
    ) -> None:
        rows = resolve_kept_word_occurrences(
            "raw", _words()[:1], compile_plan(_plan()), CLOCK)
        self.assertEqual(
            [row["wordId"] for row in rows],
            ["w-03edcd5234f6a826", "w-8a21a9391090d9d8"])
        self.assertEqual(
            [row["sourceWordId"] for row in rows],
            [stable_word_id("raw", 0)] * 2)
        self.assertEqual([row["occurrence"] for row in rows], [1, 2])
        self.assertEqual([row["cutSegmentIndex"] for row in rows], [0, 1])
        self.assertEqual(
            [(row["startFrame"], row["endFrameExclusive"]) for row in rows],
            [(0, 9), (29, 39)])
        self.assertEqual(
            [(row["startSample"], row["endSampleExclusive"]) for row in rows],
            [(0, 14_400), (48_000, 62_400)])

    def test_plan_compiler_targets_only_the_selected_repeated_occurrence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            transcript = os.path.join(root, "transcript.json")
            with open(transcript, "w", encoding="utf-8") as stream:
                json.dump({"transcript": [{"words": _words()}]}, stream)
            plan = _plan()
            context = PlanCaptionContext(
                plan,
                {"sources": [{
                    "id": "raw", "transcriptPath": transcript,
                }]},
                compile_plan(plan),
                RATE,
                root,
            )
            compilation = compile_plan_caption_track(context)
        self.assertEqual(len(compilation["cues"]), 1)
        cue = compilation["cues"][0]
        self.assertEqual(
            cue["sourceWordIds"],
            [occurrence_word_id(stable_word_id("raw", index), 2)
             for index in range(3)])
        self.assertEqual(
            (cue["startFrame"], cue["endFrameExclusive"]), (29, 60))
        self.assertEqual(
            (cue["startSample"], cue["endSampleExclusive"]),
            (48_000, 96_000))


if __name__ == "__main__":
    unittest.main(verbosity=2)
