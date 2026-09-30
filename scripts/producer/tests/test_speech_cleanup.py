"""speech_cleanup's fold of pause_scan and retake_scan into one cutTrack (edit/speech_cleanup.py).

Moved out of test_edit.py at the P1 review-point-1 follow-up (X180 m6), with the doctrine pins it lacked:
a ``needsOperator`` retake is never auto-cut unless the operator reviewed it (``--all-retakes``), and the fold
keeps pause_scan's trims. In-process calls on TEST transcripts; no child process and no media.
"""
import unittest

from _common import *  # noqa: F401,F403
import test_edit  # its long-range spacer sentences (a module import, so its tests are not collected here)


def fold(utts: list, duration: float, all_retakes: bool) -> dict:
    """``speech_cleanup.build_cut_track`` over a TEST transcript written from ``utts``."""
    from edit import speech_cleanup
    rows = [{"start": u.start, "end": u.end, "text": u.text,
             "words": [{"word": w.text, "start": w.start, "end": w.end} for w in u.words]} for u in utts]
    with tempfile.TemporaryDirectory() as d:
        transcript = os.path.join(d, "t.json")
        with open(transcript, "w") as f:
            json.dump({"transcript": rows}, f)
        source = {"id": "raw-1", "duration": duration, "transcript": transcript}
        with contextlib.redirect_stdout(io.StringIO()):
            return speech_cleanup.build_cut_track(source, all_retakes)


def covering(track: list[dict], utt: object) -> list[dict]:
    """The kept segments that overlap ``utt``."""
    return [s for s in track if s["start"] < utt.end and s["end"] > utt.start]


@unittest.skipUnless(_HAVE_RETAKE, "rapidfuzz not installed")
class SpeechCleanupFoldTests(unittest.TestCase):
    """A valid take folds pause_scan and retake_scan into one cutTrack.

    Regression (FOLLOWUP-C6 item 1): ``build_cut_track`` passed ``retakes=`` to
    ``apply_pauses.cut_track_from_pauses``, which takes them in ``CutOptions``, so
    every valid transcript ended in the error status line instead of a cut."""

    def test_valid_take_drops_the_flubbed_opening_and_keeps_the_retake(self) -> None:
        """The confident retake's first take is cut; the later, clean take is kept whole."""
        utts = [_mk_utt(0, 0.0, "I built this in a single weekend."),
                _mk_utt(1, 3.0, "let me try that again."),
                _mk_utt(2, 6.0, "I built this whole thing in a single weekend.")]
        result = fold(utts, 10.0, False)
        track = result["cutTrack"]
        self.assertEqual(result["segments"], len(track))
        self.assertEqual(result["skippedRetakes"], 0)
        first, retake = utts[0], utts[2]
        self.assertFalse(covering(track, first), "the flubbed first take is dropped, not stitched onto the clean take")
        self.assertTrue([s for s in track if s["start"] <= retake.start and s["end"] >= retake.end],
                        "the clean later take is kept whole")

    def test_a_needs_operator_retake_is_kept_unless_the_operator_reviewed_it(self) -> None:
        """X180 m6: a long-range redelivery is flagged ``needsOperator``: kept and counted as skipped by default,
        cut only with ``all_retakes``; pause_scan's trims are folded either way."""
        first = _mk_utt(0, 0.0, "You fill out the workbook file once and paste the answers into Claude desktop.")
        spacers = test_edit.RetakeScanV2Tests("test_long_range_redelivery_found_and_flagged")._spacers(1, 8.0)
        redelivery = _mk_utt(12, 78.0, "So you fill out the workbook file once and you paste the answers into "
                                       "Claude desktop, right?")
        utts = [first, *spacers, redelivery]
        kept, reviewed = fold(utts, 90.0, False), fold(utts, 90.0, True)
        self.assertEqual((kept["skippedRetakes"], reviewed["skippedRetakes"]), (1, 0))
        self.assertTrue(covering(kept["cutTrack"], first), "a needsOperator retake is never auto-cut")
        self.assertFalse(covering(reviewed["cutTrack"], first), "the operator-reviewed retake is cut")
        gaps = [(a["end"], b["start"]) for a, b in zip(kept["cutTrack"], kept["cutTrack"][1:]) if b["start"] > a["end"]]
        self.assertTrue(gaps, "pause_scan's trims are folded into the cut")
        self.assertGreater(kept["removedS"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
