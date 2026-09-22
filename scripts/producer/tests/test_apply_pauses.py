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

    def test_a_cut_never_exceeds_the_approved_gap(self) -> None:
        """Superseded behaviour: the cut used to swallow the whole measured span, so one
        span covering two gaps removed both — a 0.25s approved trim became 4.38s and took a
        protected beat with it. The proposal bounds WHAT may go; measurement only narrows it.
        """
        track = ap.cut_track_from_pauses(
            _proposal(_trim(3.0, 5.0)), "raw-1", (0.0, 20.0),
            ap.CutOptions(silence=[(2.5, 9.0)]))
        self.assertAlmostEqual(track[0]["end"], 3.35, places=3, msg="breath kept from the gap")
        self.assertAlmostEqual(track[1]["start"], 8.0, places=3, msg="never past the gap end")

    def test_a_protected_beat_is_never_cut_even_inside_measured_silence(self) -> None:
        proposal = _proposal(_trim(10.4, 0.40, residual_s=0.15))
        proposal["protectedPauses"] = [_trim(12.0, 2.60, protected=True)]
        track = ap.cut_track_from_pauses(
            proposal, "raw-1", (0.0, 20.0), ap.CutOptions(silence=[(10.15, 14.68)]))
        kept = sum(s["end"] - s["start"] for s in track)
        self.assertAlmostEqual(20.0 - kept, 0.25, places=3, msg="only the approved trim")
        self.assertTrue(any(s["start"] <= 12.0 and s["end"] >= 14.6 for s in track),
                        "the protected beat survived")

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

    def test_a_sliver_of_silence_is_not_worth_a_cut(self) -> None:
        """Going around a claimed word can leave 10-40ms scraps; they are not cuts."""
        track = ap.cut_track_from_pauses(
            _proposal(_trim(3.0, 5.0)), "raw-1", (0.0, 20.0),
            ap.CutOptions(silence=[(3.0, 8.0)], words=[(3.4, 7.99)]))
        self.assertEqual(len(track), 1, "the 10ms scrap left over is not removed")

    def test_retake_drops_are_content_decisions_and_are_not_clamped(self) -> None:
        track = ap.cut_track_from_pauses(
            _proposal(), "raw-1", (0.0, 20.0),
            ap.CutOptions(retakes=[{"cutStartS": 5.0, "cutEndS": 10.0}], silence=[]))
        self.assertAlmostEqual(track[0]["end"], 5.0, places=3)
        self.assertAlmostEqual(track[1]["start"], 10.0, places=3)


class MeasuredMediaBindingTests(unittest.TestCase):
    """A pause measurement must belong to the source this invocation cuts."""

    def test_media_without_manifest_is_refused_before_measurement(self) -> None:
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            proposal = os.path.join(directory, "pauses.json")
            with open(proposal, "w") as handle:
                json.dump(_proposal(), handle)
            args = ["apply_pauses", proposal, "--source", "raw-1", "--window",
                    "0", "10", "--media", "/unrelated.mov"]
            with patch.object(sys, "argv", args), patch.object(ap, "_measurement") as measure:
                with self.assertRaisesRegex(SystemExit, "requires --manifest"):
                    ap.main()
                measure.assert_not_called()

    def test_relative_manifest_path_is_bound_to_manifest_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = os.path.join(directory, "asset_manifest.json")
            with open(manifest, "w") as handle:
                json.dump({"sources": [{"id": "raw-1", "path": "source.mov"}]}, handle)
            ap._require_declared_media(os.path.join(directory, "source.mov"), manifest, "raw-1")
            with self.assertRaisesRegex(SystemExit, "not the media"):
                ap._require_declared_media("/unrelated.mov", manifest, "raw-1")

    def test_duplicate_source_id_is_not_an_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = os.path.join(directory, "asset_manifest.json")
            with open(manifest, "w") as handle:
                json.dump({"sources": [{"id": "raw-1", "path": "/a.mov"},
                                       {"id": "raw-1", "path": "/b.mov"}]}, handle)
            with self.assertRaisesRegex(SystemExit, "uniquely identify"):
                ap._require_declared_media("/a.mov", manifest, "raw-1")

    def test_measurement_is_not_reused_for_another_recording(self) -> None:
        from unittest.mock import patch
        # _measurement adds scripts/ to sys.path for its ordinary run-by-path import.
        sys.path.insert(0, str(Path(ap.__file__).resolve().parents[2]))
        with patch("local_whisper_speech_edges.measure", side_effect=["a", "b"]) as measure:
            self.assertEqual(ap._measurement("a.mov"), "a")
            self.assertEqual(ap._measurement("b.mov"), "b")
            self.assertEqual(measure.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
