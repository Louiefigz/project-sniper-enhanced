"""The cut gate weighs the audio, not only whisper's word bounds.

Its rule is that a cut never lands inside a word. Its evidence for where words are is a
transcript whose bounds whisper pads and starts late, so a cut into MEASURED silence was
refused as "cuts through word X" while a genuinely mis-timed word sat there. Measured
silence now admits such a boundary — and nothing else: a cut into audible speech is still
refused, with the same message.
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transcript_cut_contract import (  # noqa: E402
    Boundary, _boundary_receipt, _straddling_words, _validate_decision)
from transcript_cut_evidence import PEAK_HEADROOM_DB, SourceEvidence  # noqa: E402

WORDS = [{"word": "be", "start": 9.00, "end": 9.20},
         {"word": "asking", "start": 9.29, "end": 9.47},
         {"word": "what", "start": 9.72, "end": 9.90}]


def _source(silence=(), levels=None, gate=-55.0):
    """Evidence with optional per-frame levels; default levels are far below the gate."""
    frames = levels if levels is not None else tuple([-70.0] * 1200)
    return SourceEvidence("raw-1", 22.33, "t.json", WORDS, silence,
                          gate if silence else None, frames)


class BoundaryInsideAWord(unittest.TestCase):
    def test_without_audio_a_boundary_inside_a_word_is_still_refused(self):
        errors = []
        _boundary_receipt(Boundary("cutTrack[1]", 9.40, "end"), _source(), errors)
        self.assertTrue(any("cuts through word 'asking'" in e for e in errors), errors)

    def test_measured_silence_admits_the_boundary_and_says_so(self):
        errors = []
        receipt = _boundary_receipt(Boundary("cutTrack[1]", 9.40, "end"),
                                    _source(((9.28, 9.72),)), errors)   # silence AFTER it
        self.assertEqual(errors, [], "the audio was silent there")
        self.assertTrue(receipt["admittedByMeasuredSilence"])
        self.assertEqual(receipt["insideWord"]["word"], "asking", "still recorded, not hidden")

    def test_audible_speech_is_refused_even_with_audio_measured(self):
        errors = []
        _boundary_receipt(Boundary("cutTrack[1]", 9.40, "end"),
                          _source(((3.0, 3.4), (10.5, 11.0))), errors)
        self.assertTrue(any("cuts through word 'asking'" in e for e in errors), errors)

    def test_only_the_removed_side_counts(self):
        """A kept range ENDS where silence begins: silence before an `end` boundary is the
        kept side and proves nothing about what the cut swallows."""
        errors = []
        _boundary_receipt(Boundary("cutTrack[1]", 9.40, "end"), _source(((9.00, 9.40),)), errors)
        self.assertTrue(any("cuts through word 'asking'" in e for e in errors), errors)
        ok = []
        receipt = _boundary_receipt(Boundary("cutTrack[2]", 9.40, "start"), _source(((9.00, 9.40),)), ok)
        self.assertEqual(ok, [], "for a `start`, the silence before it is what was removed")
        self.assertTrue(receipt["admittedByMeasuredSilence"])


class RemovalOverAMistimedWord(unittest.TestCase):
    """dead_air 'cannot hide removed words' — unless the audio says the word is not there."""

    def _decision(self):
        return {"kind": "dead_air", "rationale": "Measured silence, tightened to a breath.",
                "evidence": {"beforeWord": "asking", "afterWord": "what", "removedText": ""}}

    def test_a_word_measured_as_audible_still_blocks_dead_air(self):
        errors = []
        _validate_decision("removals[0]", self._decision(), WORDS[1:2], None, None, errors)
        self.assertTrue(any("dead_air cannot hide" in e for e in errors), errors)

    def test_a_word_the_audio_measures_as_silent_is_not_a_removed_word(self):
        source = _source(((9.20, 9.80),))   # a mis-timed word sits well inside the silence
        claimed = WORDS[1:2]
        gap_words = [w for w in claimed if not source.measured_silent(w["start"], w["end"])]
        self.assertEqual(gap_words, [], "the mis-timed word is not counted as removed speech")
        errors = []
        _validate_decision("removals[0]", self._decision(), gap_words, None, None, errors)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()


class PartlyRemovedWords(unittest.TestCase):
    """A word half inside a removal belonged to neither check: `claimed` requires
    containment, and the boundary rule suppresses its own error once admitted."""

    def test_a_word_is_found_when_it_only_overlaps_the_gap(self):
        found = _straddling_words(_source(), 9.40, 9.80)
        self.assertEqual([w["word"] for w in found], ["asking", "what"])

    def test_a_word_fully_inside_the_gap_is_not_straddling(self):
        found = _straddling_words(_source(), 9.00, 10.00)
        self.assertEqual(found, [], "those are `claimed` words, counted elsewhere")


class MeasuredSilentNeedsMarginAndLevel(unittest.TestCase):
    """Containment in a silence run is not proof a word was never spoken there."""

    def test_a_window_that_merely_dips_under_the_gate_is_not_silent(self):
        loud = tuple([-55.0 + PEAK_HEADROOM_DB] * 1200)     # right at the gate
        source = _source(((9.20, 9.80),), levels=loud)
        self.assertFalse(source.measured_silent(9.29, 9.47),
                         "a window peaking at the gate is not measured silence")

    def test_a_window_well_under_the_gate_is_silent(self):
        source = _source(((9.20, 9.80),), levels=tuple([-70.0] * 1200))
        self.assertTrue(source.measured_silent(9.29, 9.47))

    def test_an_exact_touch_does_not_count(self):
        source = _source(((9.29, 9.47),))
        self.assertFalse(source.measured_silent(9.29, 9.47),
                         "the span must extend past the window, not just meet it")
