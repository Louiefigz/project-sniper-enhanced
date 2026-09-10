"""Pure TEST-only worker-transport failures; no ASR, subprocess, or media work."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import transcribe_output as output

PAYLOAD = {"status": "done", "transcript": [], "duration": 1,
           "model": "TEST-only", "provenance": {"scope": "TEST transport only"}}
DONE = json.dumps(PAYLOAD)


class TranscriptionOutputTests(unittest.TestCase):
    """A bounded stream has one unambiguous final result or rejects entirely."""

    def test_current_progress_and_result_are_preserved(self) -> None:
        """All current local/paid progress statuses remain transport-compatible."""
        rows = [json.dumps({"status": status, "detail": "TEST"})
                for status in sorted(output._PROGRESS)]
        actual = output.parse_transcription_output("\n" + "\n".join(rows + [DONE]) + "\n \n")
        self.assertEqual(actual, PAYLOAD)

    def test_malformed_or_nonobject_rows_are_never_skipped(self) -> None:
        """Reject corruption even when a plausible completion follows it."""
        for raw in ("noise", "null", "[]", '"text"', "1", "true", "{", "{}"):
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                output.parse_transcription_output(raw + "\n" + DONE)

    def test_any_error_or_postcompletion_record_rejects(self) -> None:
        """Neither last-result-wins nor reverse scanning can hide an error."""
        cases = ['{"error":"TEST failure"}\n' + DONE,
                 '{"status":"extracting_audio","error":null}\n' + DONE,
                 DONE + '\n{"error":"TEST late failure"}', DONE + "\n" + DONE,
                 DONE + "\nnoise", DONE + '\n{"status":"audio_extracted"}']
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                output.parse_transcription_output(raw)

    def test_missing_unknown_and_partial_completion_rejects(self) -> None:
        """A transcript field alone is not completion authority."""
        cases = ["", " \n", '{"status":"extracting_audio"}',
                 '{"status":"unknown"}', '{"transcript":[]}',
                 '{"status":"done"}', '{"status":"done","transcript":{}}',
                 '{"status":[],"transcript":[]}',
                 '{"status":"audio_extracted","transcript":[]}\n' + DONE]
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                output.parse_transcription_output(raw)

    def test_duplicate_keys_and_nonfinite_values_reject_at_any_depth(self) -> None:
        """Reject JSON ambiguity and numeric overflow, including nested metadata."""
        values = ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}',
                  '{"x":-Infinity}', '{"x":1e400}']
        for value in values:
            raw = '{"status":"done","transcript":[],"metadata":' + value + "}"
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                output.parse_transcription_output(raw)
        with self.assertRaises(RuntimeError):
            output.parse_transcription_output('{"status":"done","status":"done","transcript":[]}')

    def test_byte_limit_is_utf8_exact_and_checked_before_parsing(self) -> None:
        """The transport limit is bytes, not Python character count."""
        raw = json.dumps({**PAYLOAD, "text": "é"}, ensure_ascii=False)
        size = len(raw.encode("utf-8"))
        with mock.patch.object(output, "MAX_OUTPUT_BYTES", size):
            self.assertEqual(output.parse_transcription_output(raw)["text"], "é")
        with mock.patch.object(output, "MAX_OUTPUT_BYTES", size - 1), \
                mock.patch.object(output, "_row") as parse, self.assertRaises(RuntimeError):
            output.parse_transcription_output(raw)
        parse.assert_not_called()

    def test_nontext_invalid_unicode_and_extreme_nesting_are_catchable(self) -> None:
        """Malformed input errors stay within callers' RuntimeError handling."""
        values = [None, b"bytes", "\ud800", '[' * 2000 + ']' * 2000]
        for raw in values:
            with self.subTest(kind=type(raw).__name__), self.assertRaises(RuntimeError):
                output.parse_transcription_output(raw)

    def test_original_guard_checks_before_and_after_parse(self) -> None:
        """Late JSON parsing cannot publish a completion after the caller expires."""
        expired = [False]
        original = output.json.loads

        def guard() -> None:
            """Represent a caller-held clock, never a parser-created timeout."""
            if expired[0]:
                raise RuntimeError("TEST original clock expired")

        def parse_then_expire(*args: object, **kwargs: object) -> object:
            """Complete a real JSON parse before simulating clock exhaustion."""
            result = original(*args, **kwargs)
            expired[0] = True
            return result

        with mock.patch.object(output.json, "loads", side_effect=parse_then_expire), \
                self.assertRaisesRegex(RuntimeError, "original clock"):
            output.parse_transcription_output(DONE, guard)
        with mock.patch.object(output, "_row") as parse, \
                self.assertRaisesRegex(RuntimeError, "original clock"):
            output.parse_transcription_output(DONE, guard)
        parse.assert_not_called()


if __name__ == "__main__":
    unittest.main()
