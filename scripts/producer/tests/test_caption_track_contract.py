"""CaptionTrackV1 authority, operations, and stable-word contract tests."""
from __future__ import annotations

import copy
import json
import pathlib
import unittest

from captions.caption_contract import (
    CaptionContractError,
    validate_caption_track,
    validate_correction_ledger,
)
from captions.caption_operations import (
    new_caption_track,
    new_correction_ledger,
    remove_caption_range,
    upsert_caption_correction,
    upsert_caption_range,
)
from captions.caption_words import (
    CaptionFrameRate,
    apply_correction_ledger,
    assign_stable_word_ids,
    resolve_kept_words,
)
from compile_timeline import compile_plan
from _caption_fixtures import caption_range, resolved_words


class CaptionTrackContractTests(unittest.TestCase):
    def test_schema_documents_are_strict_and_runtime_accepts_minimums(self) -> None:
        root = pathlib.Path(__file__).parents[3]
        schema_dir = root / "schemas" / "producer"
        track_schema = json.loads(
            (schema_dir / "caption-track-v1.schema.json").read_text())
        ledger_schema = json.loads(
            (schema_dir / "caption-correction-ledger-v1.schema.json").read_text())
        chapters_schema = json.loads(
            (schema_dir / "caption-chapters-v1.schema.json").read_text())
        self.assertFalse(track_schema["additionalProperties"])
        self.assertFalse(ledger_schema["additionalProperties"])
        self.assertFalse(chapters_schema["items"]["additionalProperties"])
        self.assertEqual(validate_caption_track(new_caption_track()), {
            "schemaVersion": 1,
            "source": "kept-transcript",
            "defaultPolicy": "off",
            "groups": [],
        })
        self.assertEqual(
            validate_correction_ledger(new_correction_ledger())["corrections"],
            [])

    def test_unknown_fields_and_overlapping_ranges_fail_closed(self) -> None:
        words = resolved_words(["one", "two", "three"])
        track = upsert_caption_range(
            new_caption_track(), caption_range(
                [words[0]["wordId"], words[1]["wordId"]]))
        malformed = copy.deepcopy(track)
        malformed["surprise"] = True
        with self.assertRaises(CaptionContractError):
            validate_caption_track(malformed)
        with self.assertRaises(CaptionContractError):
            upsert_caption_range(
                track, caption_range(
                    [words[1]["wordId"], words[2]["wordId"]]))

    def test_range_upsert_is_idempotent_and_exactly_removable(self) -> None:
        words = resolved_words(["use", "this", "phrase"])
        request = caption_range(
            [row["wordId"] for row in words],
            mode="karaoke-phrase", placement="center")
        once = upsert_caption_range(new_caption_track(), request)
        twice = upsert_caption_range(once, request)
        self.assertEqual(once, twice)
        self.assertEqual(
            remove_caption_range(twice, request["wordIds"]),
            new_caption_track())
        with self.assertRaises(CaptionContractError):
            remove_caption_range(twice, [words[0]["wordId"]])

    def test_word_ids_are_cut_and_speed_invariant(self) -> None:
        source = [
            {"word": "first", "start": 0.0, "end": 0.4},
            {"word": "cut", "start": 0.5, "end": 0.9},
            {"word": "third", "start": 1.0, "end": 1.4},
        ]
        identified = assign_stable_word_ids("raw-a", source)
        normal = compile_plan({"cutTrack": [{
            "sourceId": "raw-a", "start": 0.0, "end": 1.5,
        }]})
        changed = compile_plan({"cutTrack": [{
            "sourceId": "raw-a", "start": 0.95, "end": 1.5, "speed": 2.0,
        }]})
        normal_words = resolve_kept_words(
            "raw-a", source, normal, CaptionFrameRate(30, 1))
        changed_words = resolve_kept_words(
            "raw-a", source, changed, CaptionFrameRate(30, 1))
        self.assertEqual(
            [row["wordId"] for row in normal_words], [
                row["wordId"] for row in identified])
        self.assertEqual(
            [row["wordId"] for row in changed_words],
            [identified[2]["wordId"]])
        self.assertNotEqual(
            normal_words[2]["startFrame"], changed_words[0]["startFrame"])


class CorrectionLedgerTests(unittest.TestCase):
    def test_reason_uses_code_points_and_explicit_whitespace(self) -> None:
        words = resolved_words(["word"])
        request = {
            "sourceWordIds": [words[0]["wordId"]],
            "displayTokens": ["word"],
        }
        boundary = "😀" * 500
        ledger = upsert_caption_correction(
            new_correction_ledger(), {**request, "reason": boundary})
        self.assertEqual(ledger["corrections"][0]["reason"], boundary)
        for reason in ("😀" * 501, "\u0085", "\ufeff"):
            with self.subTest(reason=repr(reason)):
                with self.assertRaises(CaptionContractError):
                    upsert_caption_correction(
                        new_correction_ledger(),
                        {**request, "reason": reason})
        for token in ("\u0085", "\ufeff"):
            with self.subTest(token=repr(token)):
                with self.assertRaises(CaptionContractError):
                    upsert_caption_correction(new_correction_ledger(), {
                        **request, "displayTokens": [token],
                    })

    def test_repeated_name_correction_targets_only_selected_occurrence(self) -> None:
        words = resolved_words(["Jon", "met", "Jon"])
        ledger = upsert_caption_correction(new_correction_ledger(), {
            "sourceWordIds": [words[2]["wordId"]],
            "displayTokens": ["John"],
            "reason": "proper name",
        })
        tokens = apply_correction_ledger(words, ledger)
        self.assertEqual([row["text"] for row in tokens], ["Jon", "met", "John"])
        self.assertNotIn("correctionId", tokens[0])
        self.assertIn("correctionId", tokens[2])

    def test_one_to_many_tokens_partition_frames_without_gaps(self) -> None:
        words = resolved_words(["ProjectSniper"], duration=12)
        ledger = upsert_caption_correction(new_correction_ledger(), {
            "sourceWordIds": [words[0]["wordId"]],
            "displayTokens": ["Project", "Sniper"],
        })
        tokens = apply_correction_ledger(words, ledger)
        self.assertEqual(tokens[0]["startFrame"], words[0]["startFrame"])
        self.assertEqual(
            tokens[-1]["endFrameExclusive"], words[0]["endFrameExclusive"])
        self.assertEqual(
            tokens[0]["endFrameExclusive"], tokens[1]["startFrame"])
        self.assertTrue(all(
            row["endFrameExclusive"] > row["startFrame"] for row in tokens))

    def test_punctuation_only_correction_preserves_source_timing(self) -> None:
        words = resolved_words(["Really"], duration=9)
        ledger = upsert_caption_correction(new_correction_ledger(), {
            "sourceWordIds": [words[0]["wordId"]],
            "displayTokens": ["Really?"],
        })
        token = apply_correction_ledger(words, ledger)[0]
        self.assertEqual(token["startFrame"], words[0]["startFrame"])
        self.assertEqual(
            token["endFrameExclusive"], words[0]["endFrameExclusive"])

    def test_partial_kept_correction_fails_instead_of_guessing(self) -> None:
        words = resolved_words(["New", "York", "wins"])
        ledger = upsert_caption_correction(new_correction_ledger(), {
            "sourceWordIds": [words[0]["wordId"], words[1]["wordId"]],
            "displayTokens": ["New", "York"],
        })
        with self.assertRaisesRegex(CaptionContractError, "partly kept"):
            apply_correction_ledger(words[1:], ledger)


if __name__ == "__main__":
    unittest.main(verbosity=2)
