"""Explicit row compatibility is not hidden strict fallback or token alignment."""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest import mock

import local_whisper_parser as production
import local_whisper_token_parser as experimental
from local_whisper_timing import TimingContext, WhisperTimingError, accept_or_retry
from test_local_whisper_tokens import _payload, _token

FIXTURES = Path(__file__).parent / "fixtures"


class RowCompatibilityTests(unittest.TestCase):
    def test_retained_whole_word_points_keep_explicit_row_spans_only_in_production(self) -> None:
        fixture = json.loads((FIXTURES / "whisper_zero_lexical_words.json").read_text())
        payload = {"model": fixture["model"], "transcription": [item["row"] for item in fixture["rows"]]}
        rows = production.parse_whisper_json(payload)
        words = [word for row in rows for word in row["words"]]
        self.assertEqual([(w["word"], w["start"], w["end"]) for w in words],
                         [("of", 122.82, 122.87), ("a", 231.23, 231.25), ("I", 801.79, 801.85)])
        with self.assertRaisesRegex(experimental.WhisperParseError, "nonpositive lexical"):
            experimental.parse_whisper_json(payload)

    def test_production_never_invokes_strict_parser_then_falls_back(self) -> None:
        payload = json.loads((FIXTURES / "whisper_words.json").read_text())
        with mock.patch.object(experimental, "parse_whisper_json", side_effect=AssertionError("not selected")), \
                mock.patch.object(experimental, "token_words", side_effect=AssertionError("not selected")):
            rows = production.parse_whisper_json(payload)
            accepted = accept_or_retry(payload, True, TimingContext(0, None, None),
                                       lambda: self.fail("no retry expected"))
        self.assertEqual(accepted[1], rows)
        self.assertEqual(production.PARSER_POLICY, "sniper-whisper-row-uniform-compatibility-v1")
        self.assertNotEqual(production.PARSER_POLICY, experimental.PARSER_POLICY)

    def test_uniform_subdivision_is_explicitly_legacy_not_actual_token_bounds(self) -> None:
        payload = _payload([_token(" two", 100, 180), _token(" words", 300, 700)])
        words = production.parse_whisper_json(payload)[0]["words"]
        self.assertEqual([(w["start"], w["end"]) for w in words], [(.1, .4), (.4, .7)])
        strict = experimental.parse_whisper_json(payload)[0]["words"]
        self.assertEqual([(w["start"], w["end"]) for w in strict], [(.1, .18), (.3, .7)])

    def test_legacy_floor_still_faces_existing_collapsed_run_quality_gate(self) -> None:
        payload = {"transcription": [
            {"text": " a", "offsets": {"from": 100, "to": 100}, "tokens": []},
            {"text": " b", "offsets": {"from": 110, "to": 110}, "tokens": []},
        ]}
        self.assertEqual(production.parse_whisper_json(payload)[0]["words"][0]["end"], .11)
        with self.assertRaisesRegex(WhisperTimingError, "collapsed_run"):
            accept_or_retry(payload, True, TimingContext(0, None, None),
                            lambda: self.fail("CPU quality failure must remain terminal"))


if __name__ == "__main__":
    unittest.main()
