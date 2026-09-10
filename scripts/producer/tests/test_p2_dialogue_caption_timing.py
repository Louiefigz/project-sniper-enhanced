"""Exact dialogue-map-aware caption/karaoke resolution and compilation tests."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from _caption_fixtures import DESTINATION, RATE, STYLES
from captions.caption_context import CaptionCompileContext
from captions.caption_operations import (
    new_caption_track,
    new_correction_ledger,
    upsert_caption_correction,
)
from captions.dialogue_caption_compile import (
    DialogueCaptionCompileContext,
    compile_dialogue_caption_track,
)
from captions.dialogue_caption_timing import (
    DialogueCaptionTimingError,
    occurrence_word_id,
    resolve_dialogue_caption_words,
)
from contracts.schema_validator import validate_document
from edit.dialogue_authority import (
    compile_dialogue_map,
    dialogue_map_hash,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "dialogue-authority-v1.json"


def _word(source_word_id: str, start: int, end: int,
          **options: object) -> dict:
    return {
        "sourceWordId": source_word_id,
        "occurrence": options.get("occurrence", 1),
        "text": options.get("text", "word"),
        "sourceId": "source-b",
        **({"ownerCutSegmentId": options["owner"]}
           if "owner" in options else {}),
        "sourceSampleRate": 44_100,
        "sourceSampleRange": {
            "startSample": start, "endSampleExclusive": end},
        "transcriptTimingHash": "c" * 64,
        **({"speaker": options["speaker"]} if "speaker" in options else {}),
    }


def _repeated_map(track: dict) -> dict:
    value = copy.deepcopy(track)
    value["totalOutputFrames"] = 210
    value["totalOutputSamples"] = 336_000
    value["segments"].append({
        "dialogueSegmentId": "dialogue-d-primary",
        "cutSegmentId": "cut-d",
        "elementVersion": 1,
        "sourceId": "source-b",
        "sourceSampleRate": 44_100,
        "sourceSampleRange": {
            "startSample": 4_000, "endSampleExclusive": 5_000},
        "outputSampleRange": {
            "startSample": 288_000, "endSampleExclusive": 289_089},
        "speed": {"numerator": "1", "denominator": "1"},
        "role": "primary",
    })
    return compile_dialogue_map(value)


def _caption_context(dialogue_map: dict, source_words: list[dict],
                     ledger: dict | None = None) -> DialogueCaptionCompileContext:
    caption = CaptionCompileContext(
        track=new_caption_track("karaoke"),
        ledger=ledger or new_correction_ledger(),
        words=[],
        rate=RATE,
        timeline_map_hash=dialogue_map["pictureTimelineMapHash"],
        style_inputs=STYLES,
        destination=DESTINATION,
        sample_rate=dialogue_map["projectSampleRate"],
        max_shard_frames=120,
        toolchain={"chromium": "fixture-1"},
    )
    return DialogueCaptionCompileContext(
        caption, source_words, dialogue_map, dialogue_map_hash(dialogue_map))


class DialogueCaptionResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        cls.track = fixture["track"]
        cls.dialogue_map = fixture["map"]

    def test_shared_python_typescript_golden_and_schema_are_exact(self) -> None:
        golden = json.loads((
            _FIXTURE.parent / "dialogue-caption-timing-v1.json"
        ).read_text(encoding="utf-8"))
        timing = resolve_dialogue_caption_words(
            golden["sourceWords"], self.dialogue_map)
        self.assertEqual(timing, golden["timing"])
        self.assertEqual(validate_document(
            "dialogue-caption-timing-v1.schema.json", timing), timing)

    def test_j_preroll_and_l_tail_map_through_compatible_split_spans(self) -> None:
        words = [
            _word("w-" + "1" * 16, 4_000, 5_000, owner="cut-b"),
            _word("w-" + "2" * 16, 92_000, 93_200, owner="cut-b"),
        ]
        timing = resolve_dialogue_caption_words(words, self.dialogue_map)
        first, last = timing["words"]
        self.assertEqual(first["dialogueRoles"], [
            "j-cut-handle", "primary"])
        self.assertEqual(first["coveringCutSegmentIds"], ["cut-a", "cut-b"])
        self.assertLess(first["startSample"], 144_000)
        self.assertGreater(first["endSampleExclusive"], 144_000)
        self.assertEqual(last["dialogueRoles"], [
            "primary", "l-cut-handle"])
        self.assertEqual(last["coveringCutSegmentIds"], ["cut-b", "cut-c"])
        self.assertLess(last["startSample"], 240_000)
        self.assertGreater(last["endSampleExclusive"], 240_000)

    def test_repeat_occurrences_require_explicit_unique_ownership(self) -> None:
        dialogue_map = _repeated_map(self.track)
        ambiguous = _word("w-" + "3" * 16, 4_000, 5_000)
        with self.assertRaisesRegex(
                DialogueCaptionTimingError, "ambiguous/double"):
            resolve_dialogue_caption_words([ambiguous], dialogue_map)
        repeated = [
            _word("w-" + "3" * 16, 4_000, 5_000,
                  owner="cut-b", occurrence=1),
            _word("w-" + "3" * 16, 4_000, 5_000,
                  owner="cut-d", occurrence=2),
        ]
        resolved = resolve_dialogue_caption_words(
            repeated, dialogue_map)["words"]
        self.assertEqual(
            [row["ownerCutSegmentId"] for row in resolved],
            ["cut-b", "cut-d"])
        self.assertEqual(
            [row["occurrence"] for row in resolved], [1, 2])
        self.assertEqual(len({row["wordId"] for row in resolved}), 2)
        self.assertEqual(
            resolved[0]["wordId"],
            occurrence_word_id("w-" + "3" * 16, 1))

    def test_bad_occurrence_order_duplicate_or_split_fails_closed(self) -> None:
        dialogue_map = _repeated_map(self.track)
        reversed_occurrences = [
            _word("w-" + "4" * 16, 4_000, 5_000,
                  owner="cut-d", occurrence=1),
            _word("w-" + "4" * 16, 4_000, 5_000,
                  owner="cut-b", occurrence=2),
        ]
        with self.assertRaisesRegex(
                DialogueCaptionTimingError, "output order"):
            resolve_dialogue_caption_words(
                reversed_occurrences, dialogue_map)
        duplicated = [
            _word("w-" + "5" * 16, 4_000, 5_000,
                  owner="cut-b", occurrence=1),
            _word("w-" + "5" * 16, 4_000, 5_000,
                  owner="cut-d", occurrence=1),
        ]
        with self.assertRaisesRegex(
                DialogueCaptionTimingError, "duplicated"):
            resolve_dialogue_caption_words(duplicated, dialogue_map)
        drifted = copy.deepcopy(reversed_occurrences)
        drifted[0]["occurrence"], drifted[1]["occurrence"] = 2, 1
        drifted[1]["text"] = "changed identity"
        with self.assertRaisesRegex(
                DialogueCaptionTimingError, "identity changed"):
            resolve_dialogue_caption_words(drifted, dialogue_map)
        with self.assertRaisesRegex(
                DialogueCaptionTimingError, "complete source word"):
            resolve_dialogue_caption_words([
                _word("w-" + "6" * 16, 4_000, 98_000, owner="cut-b"),
            ], self.dialogue_map)


class DialogueCaptionCompilationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        cls.dialogue_map = fixture["map"]

    def _words(self) -> list[dict]:
        return [
            _word("w-" + "7" * 16, 4_000, 5_000,
                  owner="cut-b", text="early"),
            _word("w-" + "8" * 16, 10_000, 15_000,
                  owner="cut-b", text="middle"),
            _word("w-" + "9" * 16, 92_000, 93_200,
                  owner="cut-b", text="tail"),
        ]

    def test_explicit_entry_compiles_exact_samples_into_karaoke_cues(self) -> None:
        value = compile_dialogue_caption_track(
            _caption_context(self.dialogue_map, self._words()))
        cue = value["cues"][0]
        bindings = value["wordOccurrenceBindings"]
        self.assertEqual(cue["startSample"], bindings[0]["startSample"])
        self.assertEqual(
            cue["endSampleExclusive"], bindings[-1]["endSampleExclusive"])
        self.assertNotEqual(
            cue["startSample"], cue["startFrame"] * 1_600)
        self.assertNotEqual(
            cue["endSampleExclusive"],
            cue["endFrameExclusive"] * 1_600)
        self.assertEqual(
            cue["tokens"][0]["sourceWordOccurrences"],
            [{"sourceWordId": "w-" + "7" * 16, "occurrence": 1}])
        self.assertEqual(
            value["dialogueTimingAuthority"]["dialogueMapHash"],
            dialogue_map_hash(self.dialogue_map))

    def test_correction_tokens_partition_the_exact_sample_envelope(self) -> None:
        words = self._words()
        occurrence_id = occurrence_word_id("w-" + "7" * 16, 1)
        ledger = upsert_caption_correction(new_correction_ledger(), {
            "sourceWordIds": [occurrence_id],
            "displayTokens": ["ear", "ly"],
        })
        value = compile_dialogue_caption_track(
            _caption_context(self.dialogue_map, words, ledger))
        first, second = value["cues"][0]["tokens"][:2]
        binding = value["wordOccurrenceBindings"][0]
        self.assertEqual(first["startSample"], binding["startSample"])
        self.assertEqual(
            second["endSampleExclusive"], binding["endSampleExclusive"])
        self.assertEqual(
            first["endSampleExclusive"], second["startSample"])

    def test_stale_map_and_clock_mismatch_fail_before_compilation(self) -> None:
        context = _caption_context(self.dialogue_map, self._words())
        stale = DialogueCaptionCompileContext(
            context.caption, context.source_words,
            context.dialogue_map, "d" * 64)
        with self.assertRaisesRegex(
                Exception, "stale DialogueMapV1"):
            compile_dialogue_caption_track(stale)
        wrong_rate = copy.deepcopy(context.caption)
        object.__setattr__(wrong_rate, "sample_rate", 44_100)
        with self.assertRaisesRegex(Exception, "sample rate"):
            compile_dialogue_caption_track(DialogueCaptionCompileContext(
                wrong_rate, context.source_words,
                context.dialogue_map, context.dialogue_map_hash))


if __name__ == "__main__":
    unittest.main(verbosity=2)
