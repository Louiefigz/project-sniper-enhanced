"""TEST token points may join proven word envelopes, never manufacture timing."""
from __future__ import annotations

import unittest
import json
from pathlib import Path

from local_whisper_token_parser import WhisperParseError, parse_whisper_json
from test_local_whisper_tokens import _payload, _token, _words


class ZeroDurationPieceTests(unittest.TestCase):
    def assert_invalid(self, tokens: list[dict], message: str) -> None:
        """Require the actual production parser to reject an ambiguous word."""
        with self.assertRaisesRegex(WhisperParseError, message):
            parse_whisper_json(_payload(tokens))

    def test_leading_lexical_point_can_join_same_start_positive_piece(self) -> None:
        words = _words(_payload([_token(" G", 100, 100), _token("PT", 100, 300)]))
        self.assertEqual(words, [{"word": "GPT", "start": .1, "end": .3, "confidence": .8}])

    def test_trailing_point_preserves_contraction_without_extending_end(self) -> None:
        words = _words(_payload([_token(" can", 100, 300), _token("'t", 300, 300),
                                 _token(".", 300, 300)]))
        self.assertEqual(words[0], {"word": "can't.", "start": .1, "end": .3, "confidence": .8})

    def test_internal_lexical_points_preserve_all_text_and_explicit_bounds(self) -> None:
        words = _words(_payload([_token(" re", 100, 200), _token("organ", 200, 200),
                                 _token("ization", 200, 400)]))
        self.assertEqual((words[0]["word"], words[0]["start"], words[0]["end"]),
                         ("reorganization", .1, .4))

    def test_zero_point_outside_positive_lexical_envelope_cannot_extend_it(self) -> None:
        self.assert_invalid([_token(" G", 90, 90), _token("PT", 100, 300)], "outside positive lexical")
        self.assert_invalid([_token(" can", 100, 300), _token("'t", 310, 310)], "outside positive lexical")

    def test_all_zero_lexical_pieces_cannot_manufacture_a_positive_word(self) -> None:
        self.assert_invalid([_token(" word", 100, 100)], "nonpositive lexical")
        self.assert_invalid([_token(" G", 100, 100), _token("PT", 300, 300)], "nonpositive lexical")
        self.assert_invalid([_token(" word", 100, 100), _token(".", 100, 300)], "nonpositive lexical")

    def test_separate_word_cannot_borrow_neighbor_or_punctuation_duration(self) -> None:
        self.assert_invalid([_token(" first", 100, 300), _token(" second", 300, 300)], "nonpositive lexical")
        self.assert_invalid([_token(" \"", 100, 200), _token("word", 200, 200),
                             _token("\"", 200, 300)], "nonpositive lexical")

    def test_cross_row_piece_keeps_source_offset_and_speaker_without_inference(self) -> None:
        first = _payload([_token(" Good", 100, 300)])["transcription"][0]
        second = _payload([_token("bye", 300, 300)])["transcription"][0]
        word = _words({"transcription": [first, second]}, 10, 2)[0]
        self.assertEqual(word, {"word": "Goodbye", "start": 10.1, "end": 10.3,
                                "confidence": .8, "speaker": 2})

    def test_zero_piece_does_not_waive_exact_text_row_bounds_or_order(self) -> None:
        payload = _payload([_token(" can", 100, 300), _token("'t", 300, 300)], " cannot")
        with self.assertRaisesRegex(WhisperParseError, "reconstruct"):
            parse_whisper_json(payload)
        self.assert_invalid([_token(" can", 100, 300), _token("'t", 90, 90)], "starts move backward")
        payload = _payload([_token(" can", 100, 300), _token("'t", 300, 300)])
        payload["transcription"][0]["offsets"]["to"] = 299
        with self.assertRaisesRegex(WhisperParseError, "escape"):
            parse_whisper_json(payload)

    def test_retained_full_source_whole_words_remain_unqualified(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "whisper_zero_lexical_words.json"
        retained = json.loads(fixture.read_text())
        self.assertEqual(retained["source"]["sha256"],
                         "d3db91e5d1683432f8e8be74eab1c6ea13716c967a39c146e2951090a67db12f")
        self.assertEqual([item["index"] for item in retained["rows"]], [322, 639, 2180])
        self.assertEqual([item["row"]["text"] for item in retained["rows"]], [" of", " a", " I"])
        for item in retained["rows"]:
            with self.assertRaisesRegex(WhisperParseError, "nonpositive lexical"):
                parse_whisper_json({"model": retained["model"], "transcription": [item["row"]]})


if __name__ == "__main__":
    unittest.main()
