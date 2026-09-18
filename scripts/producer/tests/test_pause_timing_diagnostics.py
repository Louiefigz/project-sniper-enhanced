"""Transcript gap availability must never masquerade as acoustic silence QC."""
from __future__ import annotations

import copy
import unittest

from edit.pause_scan import propose, timing_diagnostics
from edit.study_edit_diff import Utt, Word


def utterance(starts: list[float], ends: list[float]) -> Utt:
    """Build generic synthetic speech timestamps, with no acoustic claim."""
    words = [Word(f"word{index}", start, end, f"word{index}")
             for index, (start, end) in enumerate(zip(starts, ends))]
    return Utt(0, starts[0], ends[-1], " ".join(word.text for word in words), words)


class PauseTimingDiagnosticsTests(unittest.TestCase):
    """Diagnostic warnings preserve the existing proposal and source values."""

    def test_touching_long_transcript_warns_without_inventing_pauses(self) -> None:
        row = utterance(list(range(25)), list(range(1, 26)))
        before = copy.deepcopy(row)
        report = propose([row])
        diagnostic = report["timingDiagnostics"]
        self.assertEqual(diagnostic["adjacentPairCount"], 24)
        self.assertEqual(diagnostic["touchingPairCount"], 24)
        self.assertEqual(diagnostic["touchingPairFraction"], 1.0)
        self.assertEqual(diagnostic["maxPositiveGapS"], 0.0)
        self.assertEqual(diagnostic["warnings"][0]["code"], "high_touching_boundary_rate")
        self.assertFalse(diagnostic["acousticSilenceQualified"])
        self.assertFalse(diagnostic["absenceOfPausesEstablished"])
        self.assertEqual(report["proposedTrims"], [])
        self.assertEqual(row, before)

    def test_ordinary_gaps_remain_proposals_not_audio_approval(self) -> None:
        report = propose([utterance([0, 2, 4], [0.5, 2.5, 4.5])])
        self.assertEqual(report["proposedTrimCount"], 2)
        diagnostic = report["timingDiagnostics"]
        self.assertEqual(diagnostic["maxPositiveGapS"], 1.5)
        self.assertEqual(diagnostic["warnings"], [])
        self.assertFalse(diagnostic["acousticSilenceQualified"])

    def test_short_rapid_speech_does_not_trigger_density_warning(self) -> None:
        diagnostic = timing_diagnostics([utterance([0, 1, 2], [1, 2, 3])])
        self.assertEqual(diagnostic["touchingPairCount"], 2)
        self.assertEqual(diagnostic["warnings"], [])
        self.assertFalse(diagnostic["absenceOfPausesEstablished"])

    def test_empty_or_single_word_cannot_establish_absent_pauses(self) -> None:
        for rows in ([], [utterance([0], [8])]):
            with self.subTest(rows=rows):
                diagnostic = timing_diagnostics(rows)
                self.assertEqual(diagnostic["adjacentPairCount"], 0)
                self.assertEqual(diagnostic["maxPositiveGapS"], 0.0)
                self.assertEqual(diagnostic["warnings"], [])
                self.assertFalse(diagnostic["absenceOfPausesEstablished"])

    def test_overlap_is_not_positive_gap_or_touching_pair(self) -> None:
        diagnostic = timing_diagnostics([utterance([0, 1], [2, 3])])
        self.assertEqual(diagnostic["maxPositiveGapS"], 0.0)
        self.assertEqual(diagnostic["touchingPairCount"], 0)

    def test_density_warning_never_retimes_a_long_word(self) -> None:
        row = utterance([0, *range(8, 32)], list(range(8, 33)))
        report = propose([row])
        self.assertEqual(row.words[0].end, 8)
        self.assertEqual(report["proposedTrims"], [])
        self.assertTrue(report["timingDiagnostics"]["warnings"])

    def test_nonfinite_or_nonnumeric_bounds_never_become_json_evidence(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf"), True, "0"):
            with self.subTest(value=value):
                row = utterance([0], [1])
                row.words[0].start = value
                with self.assertRaisesRegex(ValueError, "finite numeric"):
                    timing_diagnostics([row])

    def test_finite_extreme_bounds_cannot_overflow_derived_gaps(self) -> None:
        for previous_end, next_start in ((-1e308, 1e308), (1e308, -1e308)):
            row = utterance([0, next_start], [previous_end, 1])
            with self.assertRaisesRegex(ValueError, "finite derived"):
                timing_diagnostics([row])


if __name__ == "__main__":
    unittest.main()
