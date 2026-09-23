"""compile_timeline tests (split from selftest.py)."""
import unittest

from _common import *  # noqa: F401,F403
from edit.cut_repair_context_timeline import segments as exact_segments


class CompileTimelineTests(unittest.TestCase):
    """The source↔output map — the render pipeline's correctness keystone."""

    def setUp(self) -> None:
        # raw-2 first, then raw-1: exercises multi-source ordering + speed.
        self.plan = {"cutTrack": [
            {"sourceId": "raw-1", "start": 0.0, "end": 10.0, "speed": 1.0},
            {"sourceId": "raw-2", "start": 5.0, "end": 15.0, "speed": 2.0},
        ]}
        self.tmap = ct.compile_plan(self.plan)

    def test_multi_source_ordering(self) -> None:
        segs = self.tmap.segments
        self.assertEqual([s.source_id for s in segs], ["raw-1", "raw-2"])
        self.assertEqual(segs[0].out_start, 0.0)
        self.assertAlmostEqual(segs[0].out_end, 10.0)
        self.assertAlmostEqual(segs[1].out_start, 10.0)   # contiguous, no gap
        self.assertAlmostEqual(segs[1].out_end, 15.0)     # 10s / 2.0 = 5s

    def test_speed_math_matches_predicted_duration(self) -> None:
        expected = sum((r["end"] - r["start"]) / r["speed"] for r in self.plan["cutTrack"])
        self.assertAlmostEqual(ct.predicted_duration_s(self.plan), expected, delta=HALF_FRAME_S)
        self.assertAlmostEqual(self.tmap.output_duration, 15.0, delta=HALF_FRAME_S)

    def test_cut_material_maps_to_none(self) -> None:
        # raw-2 source time 2.0 is before its kept range [5,15] — cut out.
        self.assertIsNone(self.tmap.to_output("raw-2", 2.0))
        # raw-1 past the end of its kept range.
        self.assertIsNone(self.tmap.to_output("raw-1", 10.5))

    def test_output_to_source_feedback_mapping(self) -> None:
        # "at 12.5s" of output → raw-2 source time 10.0 (round trips).
        self.assertAlmostEqual(self.tmap.to_output("raw-2", 10.0), 12.5)
        src = self.tmap.to_source(12.5)
        self.assertEqual(src[0], "raw-2")
        self.assertAlmostEqual(src[1], 10.0)
        self.assertIsNone(self.tmap.to_source(999.0))     # past end of video

    def test_remap_words_clamps_and_drops(self) -> None:
        words = [
            {"word": "a", "start": 1.0, "end": 1.5},     # fully inside raw-1
            {"word": "b", "start": 9.5, "end": 10.5},    # end crosses cut → clamp
            {"word": "c", "start": 10.5, "end": 11.0},   # outside kept range → drop
        ]
        out = ct.remap_words(words, "raw-1", self.tmap)
        self.assertEqual([w["word"] for w in out], ["a", "b"])
        self.assertAlmostEqual(out[1]["end"], 10.0)      # clamped to segment end

    def test_word_cut_exactly_at_its_boundaries_is_dropped(self) -> None:
        # The strike-to-cut seam ghost: cutting a word's EXACT [start,end] span
        # splits the track at its edges; edge-inclusive contains_src still finds
        # the word's start on the seam, so without the zero-audible-span check
        # it survives as a zero-length caption word.
        tmap = ct.compile_plan({"cutTrack": [
            {"sourceId": "raw-1", "start": 0.0, "end": 4.0, "speed": 1.0},
            {"sourceId": "raw-1", "start": 4.8, "end": 10.0, "speed": 1.0},
        ]})
        words = [
            {"word": "keep", "start": 3.0, "end": 3.6},
            {"word": "struck", "start": 4.0, "end": 4.8},   # exactly the cut span
            {"word": "after", "start": 4.8, "end": 5.3},
        ]
        out = ct.remap_words(words, "raw-1", tmap)
        self.assertEqual([w["word"] for w in out], ["keep", "after"])
        self.assertAlmostEqual(out[1]["start"], 4.0)     # lands right at the seam

    def test_dict_round_trip(self) -> None:
        restored = ct.TimelineMap.from_dict(self.tmap.to_dict())
        self.assertEqual(restored.segments, self.tmap.segments)

    def test_lf14_frame_duration_survives_canonical_sidecar_precision(self) -> None:
        plan = {"cutTrack": [
            {
                "sourceId": "raw-1", "start": 70.07,
                "end": 733.2325, "speed": 1.0,
            },
            {
                "sourceId": "raw-1", "start": 736.5691666666667,
                "end": 913.3707916666667, "speed": 1.0,
            },
        ]}
        timeline = ct.compile_plan(plan)
        document = timeline.to_dict()
        self.assertEqual(timeline.output_duration, 839.964125)
        self.assertEqual(document["outputDuration"], 839.964125)
        self.assertEqual(document["segments"][-1]["out_end"], 839.964125)
        self.assertEqual(
            ct.TimelineMap.from_dict(document).output_duration,
            839.964125,
        )

    def test_lf14_precision_reaches_exact_repair_frame_projection(self) -> None:
        plan = {"cutTrack": [
            {
                "sourceId": "raw-1", "start": 70.07,
                "end": 733.2325, "speed": 1.0,
            },
            {
                "sourceId": "raw-1", "start": 736.5691666666667,
                "end": 913.3707916666667, "speed": 1.0,
            },
        ]}
        sources = {"raw-1": {
            "fps": 23.976, "vfr": False,
            "audio": {"sampleRate": 48_000},
        }}
        rows, total = exact_segments(plan, sources, (24_000, 1_001))
        self.assertEqual(total, 20_139)
        self.assertEqual(rows[0]["outputFrames"], {
            "startFrame": 0, "endFrameExclusive": 15_900,
        })
        self.assertEqual(rows[1]["outputFrames"], {
            "startFrame": 15_900, "endFrameExclusive": 20_139,
        })


class DisplayDimsTests(unittest.TestCase):
    """Edge I9: rotation flags must swap the profile canvas (phone footage)."""

    def test_portrait_rotation_swaps(self) -> None:
        s = {"width": 3840, "height": 2160,
             "side_data_list": [{"rotation": -90}]}
        self.assertEqual(ct_display_dims(s), (2160, 3840))

    def test_no_rotation_keeps(self) -> None:
        self.assertEqual(ct_display_dims({"width": 1920, "height": 1080}), (1920, 1080))

    def test_180_keeps_dims(self) -> None:
        s = {"width": 1920, "height": 1080,
             "side_data_list": [{"rotation": 180}]}
        self.assertEqual(ct_display_dims(s), (1920, 1080))


class SourceTimeBoundaryTests(unittest.TestCase):
    """MG-4.1: topic boundaries detected on SOURCE time, mapped forward.

    The inter-topic PAUSE is a boundary's strongest signal, but compile_timeline's
    cuts trim it — so boundaries are detected on source words (pauses intact) and
    mapped through the TimelineMap. A boundary whose anchor fell in cut material
    maps to None and is dropped; the survivors REPLACE the output-time hits.
    """

    def _tmap(self):
        # Keep source [0,10] and [30,40]; the 10s..30s pause between is cut out.
        return ct.compile_plan({"cutTrack": [
            {"sourceId": "raw-1", "start": 0.0, "end": 10.0, "speed": 1.0},
            {"sourceId": "raw-1", "start": 30.0, "end": 40.0, "speed": 1.0}]})

    def test_boundary_in_cut_material_is_dropped(self) -> None:
        # Two 'okay so' markers after long pauses: one at src 15s (inside the cut
        # gap) and one at src 31s (kept). Only the kept one maps forward.
        words = _mid_sentence(
            ("Intro.", 0.0, 0.5),
            ("okay", 15.0, 15.3), ("so", 15.3, 15.6), ("cut.", 15.6, 16.0),
            ("okay", 31.0, 31.3), ("so", 31.3, 31.6), ("kept.", 31.6, 32.0))
        mapped = gpb.map_source_words(words, "raw-1", self._tmap(), 1.5)
        self.assertEqual(len(mapped), 1)                     # the cut one dropped
        self.assertEqual(mapped[0]["trigger"], "topic-boundary")
        self.assertAlmostEqual(mapped[0]["outSpan"][0], 11.0, places=2)  # 30->10, +1

    def test_source_boundaries_do_not_automatically_select_retired_section_marker(self) -> None:
        # The output words carry an 'Okay. So' that WOULD fire a boundary; when
        # source boundaries are supplied it is discarded for the mapped one, so
        # the topic boundary lands at 5.0s (source-mapped), not 0.0s (output hit).
        words = _mid_sentence(("Okay.", 0.0, 0.3), ("So", 0.3, 0.6),
                              ("we", 0.6, 0.8), ("begin.", 0.8, 1.1))
        src_b = [{"trigger": "topic-boundary", "wordIndices": [0, 1],
                  "text": "Alright", "confidence": "high", "outSpan": [5.0, 5.4]}]
        cands, _ = gp.assemble(words, "longform", 10.0, {},
                               lambda t: (None, None), 1.5, src_b)
        tb = [c for c in cands if c["trigger"] == "topic-boundary"]
        self.assertEqual(tb, [])  # Planning hints cannot select a retired visual.

if __name__ == "__main__":
    unittest.main(verbosity=2)
