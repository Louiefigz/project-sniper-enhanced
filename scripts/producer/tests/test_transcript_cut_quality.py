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


class AdjacentDuplicateTests(unittest.TestCase):
    """Stutters compare whole spoken words; a contraction after its stem is not a repeat."""

    def test_contraction_after_its_stem_is_not_a_stutter(self) -> None:
        # C0679 at 239.56 s: "...do it. It's the first link" was flagged as 'it it'
        # because every word was expanded to its first normalized token.
        words = _words([("do", 239.0, 239.2), ("it.", 239.56, 240.12), ("It's", 240.12, 240.3),
                        ("the", 240.3, 240.44), ("first", 240.44, 240.67), ("link", 240.67, 240.85)])
        report, errors = _inspect(words)
        self.assertEqual(errors, [])
        self.assertEqual(report["adjacentDuplicates"], [])

    def test_real_repeated_function_word_is_still_a_hard_stutter(self) -> None:
        words = _words([("or", 16.5, 16.62), ("maybe,", 16.62, 17.04), ("maybe", 17.04, 17.33),
                        ("you're", 17.33, 17.7), ("just", 17.7, 17.94)])
        report, errors = _inspect(words)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("adjacent duplicate word 'maybe'", errors[0])
        self.assertEqual(report["adjacentDuplicates"][0]["severity"], "error")


class HookTimingQualityTests(unittest.TestCase):
    def test_c0679_first_if_pause_fails_with_local_pace_evidence(self) -> None:
        words = _words([
            ("if", 11.271, 13.661), ("you", 13.661, 13.731),
            ("run", 13.731, 13.991), ("content", 14.011, 14.501),
            ("for", 14.501, 14.691), ("clients", 14.691, 15.281),
        ])
        report, errors = _inspect(words)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("kept_opening function word 'if' spans 2.390s", errors[0])
        self.assertIn("review is required", errors[0])
        finding = report["suspiciousWordSpans"][0]
        self.assertEqual(finding["word"], "if")
        self.assertEqual(finding["duration"], 2.39)
        self.assertGreater(finding["paceRatio"], 4.0)
        self.assertEqual(finding["reason"], "unresolved_opening_word_timing")
        self.assertTrue(finding["reviewRequired"])
        self.assertNotIn("must be removed", errors[0])

    def test_excluded_c0679_if_requires_review_not_a_forbidden_start(self) -> None:
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
        self.assertEqual(len(errors), 1)
        self.assertIn("excluded_before_opening", errors[0])
        self.assertEqual(report["forbiddenOpeningStarts"], [])
        finding = report["suspiciousWordSpans"][0]
        self.assertEqual(finding["word"], "if")
        self.assertEqual(finding["sourceId"], "raw-1")
        self.assertNotIn("requiredStartAtOrAfter", finding)
        self.assertEqual(finding["reason"], "unresolved_opening_word_timing")

    def test_nearest_excluded_word_is_not_hidden_by_a_small_gap(self) -> None:
        words = _words([
            ("If", 11.54, 13.62), ("you", 13.68, 13.85),
            ("run", 13.85, 14.10), ("content", 14.10, 14.50),
            ("for", 14.50, 14.69), ("clients", 14.69, 15.28),
        ])
        source = SourceEvidence("raw-1", 15.28, "fixture.json", words)
        plan = _plan(words)
        plan["cutTrack"][0]["start"] = 13.65
        report, errors, _warnings = inspect_output(plan, {"raw-1": source}, 0.015)
        self.assertEqual(len(errors), 1)
        self.assertEqual(report["suspiciousWordSpans"][0]["start"], 11.54)

    def test_pace_uses_source_even_when_following_output_is_shortened(self) -> None:
        words = _words([
            ("If", 11.54, 13.62), ("you", 13.62, 13.85),
            ("run", 13.85, 14.10), ("content", 14.10, 14.50),
        ])
        source = SourceEvidence("raw-1", 14.50, "fixture.json", words)
        plan = _plan(words)
        plan["cutTrack"][0]["end"] = 13.85
        report, errors, _warnings = inspect_output(plan, {"raw-1": source}, 0.015)
        self.assertEqual(len(errors), 1)
        self.assertEqual(report["suspiciousWordSpans"][0]["localMedianS"], 0.25)

    def test_confidence_is_evidence_not_a_silence_or_deletion_rule(self) -> None:
        words = _words([
            ("If", 0.37, 8.64), ("you", 8.64, 8.85),
            ("run", 8.85, 9.10), ("content", 9.10, 9.50),
        ])
        words[0]["confidence"] = 0.3575
        report, errors = _inspect(words)
        self.assertEqual(report["suspiciousWordSpans"][0]["confidence"], 0.3575)
        self.assertIn("do not prove silence", errors[0])
        words[0]["start"] = 8.44  # TEST-only ordinary timing, not repaired source.
        self.assertEqual(_inspect(words)[1], [])

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
