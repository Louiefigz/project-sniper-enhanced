"""Strict ordinary-token shaping, using retained JSON and synthetic edge cases.

No model, media, network or admitted-transcript writes occur in these tests.
The real fixture is recognition output, not acoustically certified word timing.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from local_whisper_token_parser import PARSER_POLICY, WhisperParseError, parse_whisper_json

FIXTURE = Path(__file__).parent / "fixtures" / "whisper_token_envelopes.json"


def _token(text: str, start: float, end: float, confidence: float = .8) -> dict:
    """Create explicitly TEST-authored token intervals, never a model response."""
    identifier = 50363 if text == "[_BEG_]" else 100
    if text.startswith("[_TT_"):
        identifier = 50363 + int(text[5:-1])
    return {"text": text, "offsets": {"from": start, "to": end}, "p": confidence, "id": identifier}


def _payload(tokens: list[dict], text: str | None = None) -> dict:
    """Make one synthetic row whose explicit bounds contain all test tokens."""
    return {"model": {"vocab": 51864}, "transcription": [{
        "text": "".join(token["text"] for token in tokens) if text is None else text,
        "offsets": {"from": min(t["offsets"]["from"] for t in tokens),
                    "to": max(t["offsets"]["to"] for t in tokens)},
        "tokens": tokens,
    }]}


def _words(payload: dict, offset: float = 0.0, speaker: int | None = None) -> list[dict]:
    """Flatten the real parser output without changing or sorting its words."""
    return [word for row in parse_whisper_json(payload, offset, speaker) for word in row["words"]]


class RetainedTokenEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(FIXTURE.read_text())

    def test_all_retained_rows_preserve_text_and_narrow_only_explicit_envelopes(self) -> None:
        rows = [row for row in self.payload["transcription"] if row["text"]]
        words = _words(self.payload)
        self.assertEqual(len(words), 73)
        self.assertEqual([w["word"] for w in words], [r["text"].strip() for r in rows])
        changed = [(r, w) for r, w in zip(rows, words) if
                   (r["offsets"]["from"] / 1000, r["offsets"]["to"] / 1000)
                   != (w["start"], w["end"])]
        self.assertEqual(len(changed), 23)
        removed = sum((r["offsets"]["to"] - r["offsets"]["from"]) / 1000
                      - (w["end"] - w["start"]) for r, w in changed)
        self.assertAlmostEqual(removed, 1.730)
        self.assertEqual(sum(a["end"] == b["start"] for a, b in zip(words, words[1:])), 48)
        self.assertTrue(all(a["end"] <= b["start"] for a, b in zip(words, words[1:])))

    def test_long_if_remains_uncertain_and_token_control_confidence_is_excluded(self) -> None:
        words = _words(self.payload)
        self.assertEqual((words[0]["start"], words[0]["end"]), (.37, 8.64))
        self.assertEqual((words[9]["start"], words[9]["end"]), (11.23, 13.6))
        single = next(word for word in words if word["word"] == "single")
        self.assertEqual(single["confidence"], .99728)
        self.assertEqual(PARSER_POLICY, "sniper-whisper-ordinary-token-envelopes-v1")

    def test_subwords_and_punctuation_retain_actual_envelope_with_offset_and_speaker(self) -> None:
        words = _words(self.payload, 10, 2)
        gpt = next(word for word in words if word["word"] == "GPT,")
        self.assertEqual((gpt["start"], gpt["end"]), (32.32, 32.65))
        self.assertEqual(sum(word["word"].lower() == "you're" for word in words), 3)
        self.assertTrue(all(word["speaker"] == 2 for word in words))

    def test_dtw_points_never_replace_token_bounds(self) -> None:
        changed = copy.deepcopy(self.payload)
        for row in changed["transcription"]:
            for token in row["tokens"]:
                token["t_dtw"] = 820
        self.assertEqual(_words(changed), _words(self.payload))

    def test_legacy_row_only_fixture_is_not_a_production_token_contract(self) -> None:
        legacy = json.loads((FIXTURE.parent / "whisper_words.json").read_text())
        with self.assertRaisesRegex(WhisperParseError, "offsets"):
            parse_whisper_json(legacy)


class TokenContractTests(unittest.TestCase):
    def assert_invalid(self, payload: object, message: str = "") -> None:
        with self.assertRaisesRegex(WhisperParseError, message):
            parse_whisper_json(payload)

    def test_multiword_row_uses_real_separate_tokens_without_uniform_fill(self) -> None:
        words = _words(_payload([_token(" two", 100, 180), _token(" words", 300, 700)]))
        self.assertEqual([(w["start"], w["end"]) for w in words], [(.1, .18), (.3, .7)])
        self.assert_invalid(_payload([_token(" two words", 100, 700)]), "multiword")

    def test_partial_missing_nonfinite_boolean_negative_and_reversed_bounds_reject(self) -> None:
        for bad in (None, {}, {"from": 0}, {"from": True, "to": 100},
                    {"from": float("nan"), "to": 100}, {"from": 0, "to": float("inf")},
                    {"from": -1, "to": 100}, {"from": 100, "to": 10},
                    {"from": 0, "to": 10 ** 500}):
            payload = _payload([_token(" word", 0, 100)])
            payload["transcription"][0]["tokens"][0]["offsets"] = bad
            self.assert_invalid(payload)

    def test_partial_text_rows_and_unknown_controls_do_not_silently_drop_words(self) -> None:
        self.assert_invalid(_payload([_token(" hello", 0, 100)], " hello world"), "reconstruct")
        self.assert_invalid(_payload([_token("[_UNKNOWN_]", 0, 0)]), "unknown control")
        self.assert_invalid(_payload([_token("[BLANK_AUDIO]", 0, 100)]), "non-speech")
        self.assert_invalid({"transcription": [None]})
        self.assert_invalid({"transcription": [{"text": " hi", "offsets": {"from": 0, "to": 1}, "tokens": []}]})
        self.assert_invalid(_payload([_token(" ", 0, 10)]), "empty")

    def test_token_escapes_row_and_backward_order_reject_before_shaping(self) -> None:
        payload = _payload([_token(" late", 100, 200), _token(" early", 0, 100)])
        self.assert_invalid(payload, "token starts move backward")
        rows = [_payload([_token(" late", 100, 200)])["transcription"][0],
                _payload([_token(" early", 0, 100)])["transcription"][0]]
        self.assert_invalid({"transcription": rows}, "row starts move backward")
        payload = _payload([_token(" word", 100, 200)])
        payload["transcription"][0]["offsets"]["to"] = 199
        self.assert_invalid(payload, "escape")

    def test_zero_duration_punctuation_retains_text_without_fabricated_duration(self) -> None:
        words = _words(_payload([_token(" word", 100, 300), _token(".", 300, 300)]))
        self.assertEqual((words[0]["word"], words[0]["start"], words[0]["end"]), ("word.", .1, .3))
        self.assert_invalid(_payload([_token(" word", 100, 100)]), "nonpositive")
        self.assert_invalid(_payload([_token(".", 100, 100)]), "no lexical")

    def test_standalone_punctuation_row_retains_explicit_span_and_empty_rows_need_controls(self) -> None:
        first = _payload([_token(" word", 100, 300)])["transcription"][0]
        second = _payload([_token(".", 300, 340)])["transcription"][0]
        word = _words({"transcription": [first, second]})[0]
        self.assertEqual((word["word"], word["start"], word["end"]), ("word.", .1, .34))
        self.assert_invalid({"transcription": [{"text": "", "offsets": {"from": 0, "to": 10}, "tokens": []}]})

    def test_whitespace_before_opening_punctuation_never_merges_lexical_words(self) -> None:
        for opening, closing in [('"', '"'), ('(', ')'), ('“', '”')]:
            words = _words(_payload([_token(" said", 0, 100), _token(" " + opening, 100, 100),
                                     _token("hello", 200, 300), _token(closing, 300, 300)]))
            self.assertEqual([word["word"] for word in words], ["said", opening + "hello" + closing])
            self.assertEqual([(w["start"], w["end"]) for w in words], [(0, .1), (.1, .3)])

    def test_utterance_does_not_erase_whitespace_before_punctuation_prefixed_word(self) -> None:
        payload = _payload([_token(" Wait", 0, 100), _token(" ...", 100, 100), _token("what", 200, 300)])
        self.assertEqual(parse_whisper_json(payload)[0]["text"], "Wait ...what")

    def test_ambiguous_whitespace_separated_punctuation_never_erases_boundary(self) -> None:
        self.assert_invalid(_payload([_token(" word", 0, 100), _token(" .", 100, 100)]), "no lexical")
        self.assert_invalid(_payload([_token(" word", 0, 100), _token(" (", 100, 100),
                                      _token(" aside", 200, 300), _token(")", 300, 300)]), "no lexical")

    def test_unicode_and_subwords_preserve_exact_characters_not_character_timings(self) -> None:
        words = _words(_payload([_token(" e\u0301", 100, 200), _token("lève", 200, 400),
                                 _token(" 你好", 600, 900), _token("。", 900, 900)]))
        self.assertEqual([w["word"] for w in words], ["e\u0301lève", "你好。"])
        self.assertEqual(words[0]["end"], .4)
        self.assert_invalid(_payload([_token(" \ud800", 0, 100)]), "Unicode")
        self.assert_invalid(_payload([_token(" \ufffd", 0, 100)]), "lossy")

    def test_controls_cannot_erase_actual_row_text_or_contribute_span(self) -> None:
        tokens = [_token(" word", 0, 100), _token("[_TT_5]", 100, 100, .01)]
        word = _words(_payload(tokens, " word"))[0]
        self.assertEqual(word["confidence"], .8)
        self.assert_invalid(_payload(tokens), "reconstruct")
        tokens[-1]["offsets"]["to"] = 110
        self.assert_invalid(_payload(tokens, " word"), "control token")

    def test_control_id_model_index_and_boundary_must_all_match(self) -> None:
        tokens = [_token(" word", 0, 100), _token("[_TT_5]", 100, 100)]
        for bad in (None, True, "50368", 100, 50369):
            payload = _payload(copy.deepcopy(tokens), " word")
            payload["transcription"][0]["tokens"][-1]["id"] = bad
            self.assert_invalid(payload, "control token|token id")
        missing = _payload(copy.deepcopy(tokens), " word")
        missing["transcription"][0]["tokens"][-1].pop("id")
        self.assert_invalid(missing, "control token")
        unknown = _payload(copy.deepcopy(tokens), " word")
        unknown["model"]["vocab"] = 42
        self.assert_invalid(unknown, "control token")
        tokens[-1] = _token("[_TT_1501]", 100, 100)
        self.assert_invalid(_payload(tokens, " word"), "control token")
        for marker in ("[_TT_0]", "[_TT_005]", "[_TT_99999999999999999999]"):
            tokens[-1] = _token(marker, 100, 100)
            self.assert_invalid(_payload(tokens, " word"), "unknown control")
        self.assert_invalid(_payload([_token(" [_UNKNOWN_]", 0, 100)]), "unknown control")

    def test_control_points_cannot_escape_or_move_inside_their_row(self) -> None:
        payload = _payload([_token("[_BEG_]", 0, 0), _token(" word", 100, 200)], " word")
        payload["transcription"][0]["tokens"][0]["offsets"] = {"from": 999999, "to": 999999}
        self.assert_invalid(payload, "escape")
        payload["transcription"][0]["tokens"][0]["offsets"] = {"from": 50, "to": 50}
        self.assert_invalid(payload, "boundary")

    def test_invalid_confidence_rejects_and_missing_confidence_stays_unknown(self) -> None:
        for value in (True, float("nan"), -1, 1.1):
            self.assert_invalid(_payload([_token(" word", 0, 100, value)]), "confidence")
        token = _token(" word", 0, 100)
        token.pop("p")
        self.assertNotIn("confidence", _words(_payload([token]))[0])

    def test_invalid_offset_or_speaker_is_not_coerced(self) -> None:
        payload = _payload([_token(" word", 100, 200)])
        for offset in (True, float("nan"), 10 ** 200):
            with self.assertRaises(WhisperParseError):
                _words(payload, offset)
        with self.assertRaises(WhisperParseError):
            _words(payload, speaker=True)

    def test_signed_source_pts_offset_is_preserved_without_clamping(self) -> None:
        word = _words(_payload([_token(" word", 100, 200)]), -1)[0]
        self.assertEqual((word["start"], word["end"]), (-.9, -.8))

    def test_multiword_token_is_an_experimental_parser_error(self) -> None:
        self.assert_invalid(_payload([_token(" two words", 0, 100)]), "multiword")


if __name__ == "__main__":
    unittest.main()
