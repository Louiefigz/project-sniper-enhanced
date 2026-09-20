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

from transcript_cut_contract import _boundary_receipt, _validate_decision  # noqa: E402
from transcript_cut_evidence import SourceEvidence  # noqa: E402

WORDS = [{"word": "be", "start": 9.00, "end": 9.20},
         {"word": "asking", "start": 9.29, "end": 9.47},
         {"word": "what", "start": 9.72, "end": 9.90}]


def _source(silence=()):
    return SourceEvidence("raw-1", 22.33, "t.json", WORDS, silence,
                          -55.0 if silence else None)


class BoundaryInsideAWord(unittest.TestCase):
    def test_without_audio_a_boundary_inside_a_word_is_still_refused(self):
        errors = []
        _boundary_receipt("cutTrack[1]", 9.40, "end", _source(), errors)
        self.assertTrue(any("cuts through word 'asking'" in e for e in errors), errors)

    def test_measured_silence_admits_the_boundary_and_says_so(self):
        errors = []
        receipt = _boundary_receipt("cutTrack[1]", 9.40, "end",
                                    _source(((9.28, 9.72),)), errors)   # silence AFTER it
        self.assertEqual(errors, [], "the audio was silent there")
        self.assertTrue(receipt["admittedByMeasuredSilence"])
        self.assertEqual(receipt["insideWord"]["word"], "asking", "still recorded, not hidden")

    def test_audible_speech_is_refused_even_with_audio_measured(self):
        errors = []
        _boundary_receipt("cutTrack[1]", 9.40, "end",
                          _source(((3.0, 3.4), (10.5, 11.0))), errors)
        self.assertTrue(any("cuts through word 'asking'" in e for e in errors), errors)

    def test_only_the_removed_side_counts(self):
        """A kept range ENDS where silence begins: silence before an `end` boundary is the
        kept side and proves nothing about what the cut swallows."""
        errors = []
        _boundary_receipt("cutTrack[1]", 9.40, "end", _source(((9.00, 9.40),)), errors)
        self.assertTrue(any("cuts through word 'asking'" in e for e in errors), errors)
        ok = []
        receipt = _boundary_receipt("cutTrack[2]", 9.40, "start", _source(((9.00, 9.40),)), ok)
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
        source = _source(((9.28, 9.72),))
        claimed = WORDS[1:2]
        gap_words = [w for w in claimed if not source.measured_silent(w["start"], w["end"])]
        self.assertEqual(gap_words, [], "the mis-timed word is not counted as removed speech")
        errors = []
        _validate_decision("removals[0]", self._decision(), gap_words, None, None, errors)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
