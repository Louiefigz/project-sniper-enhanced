"""apply_pauses — fold pause_scan trims into a silence-cut cutTrack.

The applier is the missing wire between the edit brain (pause_scan PROPOSES which
gaps to tighten) and the renderer (cut_speed EXECUTES a cutTrack). These pin the
fold: each trimmed gap keeps its breath and drops the rest; protected pauses pass
through whole; the window bounds are the first/last edges.
"""
import unittest

from _common import *  # noqa: F401,F403
from edit import apply_pauses as ap


def _proposal(*trims, protected=()):
    return {"proposedTrims": list(trims), "protectedPauses": list(protected)}


def _trim(at_s, gap_s, residual_s=0.35, protected=False):
    return {"at_s": at_s, "gap_s": gap_s, "residual_s": residual_s,
            "protected": protected}


class ApplyPausesTests(unittest.TestCase):
    def test_one_gap_splits_into_two_segments_dropping_the_silence(self) -> None:
        # a 5s gap at 3.0s, keep 0.35 breath → seg1 [0,3.35], seg2 [8.0,20]
        track = ap.cut_track_from_pauses(
            _proposal(_trim(3.0, 5.0)), "raw-1", (0.0, 20.0))
        self.assertEqual(len(track), 2)
        self.assertAlmostEqual(track[0]["end"], 3.35, places=3)
        self.assertAlmostEqual(track[1]["start"], 8.0, places=3)
        self.assertEqual(track[-1]["end"], 20.0)

    def test_removed_silence_equals_window_minus_kept(self) -> None:
        track = ap.cut_track_from_pauses(
            _proposal(_trim(3.0, 5.0)), "raw-1", (0.0, 20.0))
        # 5.0 gap minus 0.35 breath kept = 4.65 removed
        self.assertAlmostEqual(ap.removed_seconds(track, (0.0, 20.0)), 4.65, places=3)

    def test_protected_pause_is_never_trimmed(self) -> None:
        track = ap.cut_track_from_pauses(
            _proposal(_trim(3.0, 5.0, protected=True)), "raw-1", (0.0, 20.0))
        self.assertEqual(len(track), 1)                       # one uncut span
        self.assertEqual(track[0]["start"], 0.0)
        self.assertEqual(track[0]["end"], 20.0)

    def test_gaps_outside_the_window_are_ignored(self) -> None:
        track = ap.cut_track_from_pauses(
            _proposal(_trim(1.0, 3.0), _trim(50.0, 4.0)), "raw-1", (10.0, 40.0))
        self.assertEqual(len(track), 1)                       # neither trim is inside
        self.assertEqual((track[0]["start"], track[0]["end"]), (10.0, 40.0))

    def test_speed_and_source_ride_onto_every_segment(self) -> None:
        track = ap.cut_track_from_pauses(
            _proposal(_trim(3.0, 5.0)), "raw-9", (0.0, 20.0), ap.CutOptions(speed=1.1))
        self.assertTrue(all(s["sourceId"] == "raw-9" for s in track))
        self.assertTrue(all(s["speed"] == 1.1 for s in track))

    def test_adjacent_gaps_do_not_produce_slivers(self) -> None:
        # two gaps closer than a breath apart must not emit a < MIN_SEG_S segment
        track = ap.cut_track_from_pauses(
            _proposal(_trim(3.0, 2.0), _trim(5.0, 2.0)), "raw-1", (0.0, 20.0))
        self.assertTrue(all(s["end"] - s["start"] > ap.MIN_SEG_S for s in track))


class ApplyRetakesTests(unittest.TestCase):
    def test_retake_span_is_dropped(self) -> None:
        # a re-take of [5,10] is removed; content resumes at the clean take
        track = ap.cut_track_from_pauses(
            _proposal(), "raw-1", (0.0, 20.0),
            ap.CutOptions(retakes=[{"cutStartS": 5.0, "cutEndS": 10.0}]))
        self.assertEqual([(s["start"], s["end"]) for s in track],
                         [(0.0, 5.0), (10.0, 20.0)])

    def test_pause_and_retake_drops_merge(self) -> None:
        # a pause-trim gap overlapping a retake span collapses to one drop
        track = ap.cut_track_from_pauses(
            _proposal(_trim(4.0, 3.0)), "raw-1", (0.0, 20.0),
            ap.CutOptions(retakes=[{"cutStartS": 5.0, "cutEndS": 11.0}]))
        # keep [0,4.35] (breath), drop 4.35..11, keep [11,20]
        self.assertEqual(len(track), 2)
        self.assertAlmostEqual(track[0]["end"], 4.35, places=2)
        self.assertAlmostEqual(track[1]["start"], 11.0, places=2)

    def test_abandoned_cold_open_fragment_dropped(self) -> None:
        # a ~1.35s lead ("If") orphaned before a 5s settle + retake → dropped
        track = ap.cut_track_from_pauses(
            _proposal(_trim(1.0, 5.0)), "raw-1", (0.0, 40.0),
            ap.CutOptions(speed=1.1, retakes=[{"cutStartS": 6.0, "cutEndS": 12.0}]))
        self.assertEqual(track[0]["start"], 12.0)          # cold-open dropped

    def test_short_cold_open_kept_when_no_big_drop(self) -> None:
        # a short lead that flows straight in (tiny gap) is NOT dropped
        track = ap.cut_track_from_pauses(
            _proposal(_trim(1.4, 0.5)), "raw-1", (0.0, 20.0))
        self.assertEqual(track[0]["start"], 0.0)           # kept — deliberate


class PauseCutsStayInsideMeasuredSilence(unittest.TestCase):
    """A transcript gap can hold the first moment of the next word (whisper starts
    words late). With measured silence, a pause cut can only remove silence."""

    def test_a_cut_stops_where_speech_was_measured_again(self) -> None:
        # gap 3.0-8.0 by the transcript, but the audio is only silent 3.0-7.0:
        # speech resumes at 7.0, so nothing after 7.0 may be cut.
        track = ap.cut_track_from_pauses(
            _proposal(_trim(3.0, 5.0)), "raw-1", (0.0, 20.0),
            ap.CutOptions(silence=[(3.0, 7.0)]))
        self.assertAlmostEqual(track[0]["end"], 3.35, places=3)
        self.assertAlmostEqual(track[1]["start"], 7.0, places=3,
                               msg="the cut stopped where speech was measured again")

    def test_the_whole_measured_pause_goes_even_when_the_gap_understates_it(self) -> None:
        """whisper pads a word's end, so the transcript gap can start late: the
        measured silence (2.5-9.0) is what gets removed, less the breath."""
        track = ap.cut_track_from_pauses(
            _proposal(_trim(3.0, 5.0)), "raw-1", (0.0, 20.0),
            ap.CutOptions(silence=[(2.5, 9.0)]))
        self.assertAlmostEqual(track[0]["end"], 2.85, places=3, msg="breath kept from 2.5")
        self.assertAlmostEqual(track[1]["start"], 9.0, places=3, msg="all measured silence gone")

    def test_a_gap_with_no_measured_silence_is_not_cut_at_all(self) -> None:
        track = ap.cut_track_from_pauses(
            _proposal(_trim(3.0, 5.0)), "raw-1", (0.0, 20.0), ap.CutOptions(silence=[]))
        self.assertEqual(len(track), 1, "no measured silence means nothing to remove")
        self.assertEqual(ap.removed_seconds(track, (0.0, 20.0)), 0.0)

    def test_without_measured_silence_the_old_behaviour_is_unchanged(self) -> None:
        track = ap.cut_track_from_pauses(_proposal(_trim(3.0, 5.0)), "raw-1", (0.0, 20.0))
        self.assertAlmostEqual(track[1]["start"], 8.0, places=3)

    def test_a_cut_never_crosses_a_word_the_transcript_claims(self) -> None:
        """A mis-timed word can sit inside measured silence; the cut goes around it, so the
        cut gate's mid-word rule holds without weakening it."""
        track = ap.cut_track_from_pauses(
            _proposal(_trim(3.0, 5.0)), "raw-1", (0.0, 20.0),
            ap.CutOptions(silence=[(3.0, 8.0)], words=[(4.0, 4.4)]))
        starts = [round(s["start"], 3) for s in track]
        ends = [round(s["end"], 3) for s in track]
        self.assertIn(4.0, starts, "the claimed word's time is kept as its own segment")
        self.assertIn(4.4, ends, "up to where the transcript says it ends")
        self.assertIn(8.0, starts, "the rest of the measured silence still goes")

    def test_retake_drops_are_content_decisions_and_are_not_clamped(self) -> None:
        track = ap.cut_track_from_pauses(
            _proposal(), "raw-1", (0.0, 20.0),
            ap.CutOptions(retakes=[{"cutStartS": 5.0, "cutEndS": 10.0}], silence=[]))
        self.assertAlmostEqual(track[0]["end"], 5.0, places=3)
        self.assertAlmostEqual(track[1]["start"], 10.0, places=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
