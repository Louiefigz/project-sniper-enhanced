#!/usr/bin/env python3
"""Focused false-positive contracts for deterministic hook timing quality."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from transcript_cut_evidence import SourceEvidence
from transcript_cut_quality import inspect_output


def _plan(words: list[dict], scope: str = "produced") -> dict:
    return {
        "target": {"mode": "longform", "scope": scope},
        "cutTrack": [{"sourceId": "raw-1", "start": words[0]["start"],
                      "end": words[-1]["end"], "speed": 1}],
    }


def _inspect(words: list[dict], scope: str = "produced") -> tuple[dict, list[str]]:
    source = SourceEvidence("raw-1", words[-1]["end"], "fixture.json", words)
    report, errors, _warnings = inspect_output(
        _plan(words, scope), {"raw-1": source}, 0.001)
    return report, errors


def _words(rows: list[tuple[str, float, float]]) -> list[dict]:
    return [{"word": word, "start": start, "end": end}
            for word, start, end in rows]


class HookTimingQualityTests(unittest.TestCase):
    def test_c0679_first_if_pause_fails_with_local_pace_evidence(self) -> None:
        words = _words([
            ("if", 11.271, 13.661), ("you", 13.661, 13.731),
            ("run", 13.731, 13.991), ("content", 14.011, 14.501),
            ("for", 14.501, 14.691), ("clients", 14.691, 15.281),
        ])
        report, errors = _inspect(words)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("first function word 'if' spans 2.390s", errors[0])
        finding = report["suspiciousWordSpans"][0]
        self.assertEqual(finding["word"], "if")
        self.assertEqual(finding["duration"], 2.39)
        self.assertGreater(finding["paceRatio"], 4.0)

    def test_excluded_c0679_if_is_a_forbidden_opening_start(self) -> None:
        words = _words([
            ("if", 11.271, 13.661), ("you", 13.661, 13.731),
            ("run", 13.731, 13.991), ("content", 14.011, 14.501),
            ("for", 14.501, 14.691), ("clients", 14.691, 15.281),
        ])
        source = SourceEvidence("raw-1", 15.281, "fixture.json", words)
        plan = _plan(words)
        plan["cutTrack"][0]["start"] = 13.661
        report, errors, _warnings = inspect_output(
            plan, {"raw-1": source}, 0.001)
        self.assertEqual(errors, [])
        self.assertEqual(report["suspiciousWordSpans"], [])
        forbidden = report["forbiddenOpeningStarts"][0]
        self.assertEqual(forbidden["word"], "if")
        self.assertEqual(forbidden["requiredStartAtOrAfter"], 13.661)
        self.assertEqual(forbidden["reason"], "probable_asr_assigned_dead_air")

    def test_first_name_or_content_word_is_not_a_function_word_defect(self) -> None:
        words = _words([
            ("Ali,", 0.0, 2.0), ("built", 2.0, 2.2),
            ("the", 2.2, 2.4), ("workflow.", 2.4, 2.8),
        ])
        report, errors = _inspect(words)
        self.assertEqual(errors, [])
        self.assertEqual(report["suspiciousWordSpans"], [])

    def test_slow_local_delivery_does_not_fail_absolute_threshold_alone(self) -> None:
        words = _words([
            ("if", 0.0, 1.6), ("you", 1.6, 2.1),
            ("move", 2.1, 2.6), ("slowly", 2.6, 3.1),
        ])
        self.assertEqual(_inspect(words)[1], [])

    def test_later_sentence_final_pause_is_not_hook_dead_air(self) -> None:
        words = _words([
            ("Start", 0.0, 0.3), ("by", 0.3, 0.5),
            ("turning", 0.5, 0.8), ("off.", 0.8, 2.36),
        ])
        self.assertEqual(_inspect(words)[1], [])

    def test_corrected_first_function_word_passes(self) -> None:
        words = _words([
            ("if", 0.0, 0.2), ("you", 0.2, 0.4),
            ("run", 0.4, 0.65), ("content", 0.65, 1.0),
        ])
        self.assertEqual(_inspect(words)[1], [])

    def test_non_produced_scope_is_not_hard_gated(self) -> None:
        words = _words([
            ("if", 0.0, 2.39), ("you", 2.39, 2.5),
            ("run", 2.5, 2.7), ("content", 2.7, 3.0),
        ])
        self.assertEqual(_inspect(words, "trim")[1], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
