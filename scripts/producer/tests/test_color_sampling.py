"""Conservative source metadata, retained-time sampling and review-only rules."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from color.metadata import context_warnings, source_metadata
from color.model import context
from color.sample_plan import build_sample_plan
from color.statistics import review_suggestion, summarize, validate_sample


def declared(intent: str = "neutral") -> dict:
    """Explicit test context; never an actual camera-profile verification."""
    return {"sourceId": "raw-1", "sourceProfile": "bt709-sdr", "cameraProfile": None,
            "historyState": "known", "transformHistory": [], "lightingGroups": [
                {"id": "room", "start": 0, "end": 600, "intent": intent, "description": "synthetic"}]}


def probe(**changes) -> dict:
    """Positive class facts without coercing absent/unknown color fields."""
    return {"streams": [{"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p",
                         "color_range": "tv", "color_space": "bt709", "color_transfer": "bt709",
                         "color_primaries": "bt709", "width": 160, "height": 90,
                         "duration": "600", "start_time": "0", **changes}], "format": {}}


def sample_statistics(y: float = 48, u: float = 128) -> dict:
    return {"yMin": y, "yP10": y, "yMedian": y, "yMean": y, "yP90": y, "yMax": y,
            "uMean": u, "vMean": 128, "nominalBlackFraction": 0, "nominalWhiteFraction": 0}


class ColorSamplingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sources = [{"id": "raw-1", "duration": 600, "fps": 30}]
        self.plan = {"cutTrack": [{"sourceId": "raw-1", "start": 0, "end": 600, "speed": 1}]}

    def test_full_timeline_not_first_fifty_seconds(self) -> None:
        result = build_sample_plan(self.plan, self.sources, [declared()], 32)
        times = [row["sourceTime"] for row in result["groups"][0]["samples"]]
        self.assertEqual(len(times), 21)
        self.assertLess(times[0], 1)
        self.assertGreater(times[-1], 599)
        self.assertIn(300, times)

    def test_cut_gaps_speed_and_late_groups_use_output_map(self) -> None:
        self.plan["cutTrack"] = [{"sourceId": "raw-1", "start": 10, "end": 20, "speed": 2},
                                 {"sourceId": "raw-1", "start": 500, "end": 600, "speed": 1}]
        result = build_sample_plan(self.plan, self.sources, [declared()], 10)
        samples = result["groups"][0]["samples"]
        self.assertTrue(all(10 <= row["sourceTime"] < 20 or 500 <= row["sourceTime"] < 600 for row in samples))
        self.assertAlmostEqual(samples[0]["outputTime"], (samples[0]["sourceTime"] - 10) / 2)
        self.assertGreater(samples[-1]["sourceTime"], 599)

    def test_unclassified_and_unsampled_intervals_are_explicit(self) -> None:
        self.plan["cutTrack"] = [{"sourceId": "raw-1", "start": i * 3, "end": i * 3 + 1}
                                 for i in range(20)]
        result = build_sample_plan(self.plan, self.sources, [], 5)
        group = result["groups"][0]
        self.assertEqual(group["intent"], "unknown")
        self.assertEqual(len(group["unsampledIntervalIndices"]), 15)
        self.assertGreater(group["samples"][-1]["sourceTime"], 57)

    def test_group_budget_and_overlap_fail_loudly(self) -> None:
        ctx = declared()
        ctx["lightingGroups"].append({"id": "other", "start": 50, "end": 70,
                                      "intent": "colored", "description": "overlap"})
        with self.assertRaisesRegex(ValueError, "overlap"):
            context(ctx, self.sources[0])
        ctx["lightingGroups"][0]["end"] = 50
        with self.assertRaisesRegex(ValueError, "budget"):
            build_sample_plan(self.plan, self.sources, [ctx], 5)

    def test_declared_group_cannot_absorb_unclassified_gaps(self) -> None:
        ctx = declared()
        ctx["lightingGroups"][0].update(id="unclassified", end=50)
        with self.assertRaisesRegex(ValueError, "id"):
            context(ctx, self.sources[0])

    def test_metadata_requires_all_positive_fields_and_preserves_hdr(self) -> None:
        self.assertEqual(source_metadata(probe())["supportedSamplingClass"], "limited-8bit-bt709")
        for key in ("color_range", "color_space", "color_transfer", "color_primaries", "pix_fmt"):
            self.assertIsNone(source_metadata(probe(**{key: None}))["supportedSamplingClass"])
        for change in ({"color_transfer": "smpte2084"}, {"color_transfer": "arib-std-b67"},
                       {"pix_fmt": "yuv420p10le"}, {"color_range": "pc"},
                       {"side_data_list": [{"side_data_type": "Mastering display metadata"}]}):
            self.assertIsNone(source_metadata(probe(**change))["supportedSamplingClass"])
        self.assertTrue(source_metadata(probe(color_transfer="smpte2084"))["hdrSignaled"])

    def test_context_warnings_are_never_lost(self) -> None:
        ctx = declared()
        ctx.update(sourceProfile="log", cameraProfile="S-Log3", historyState="unknown")
        warnings = context_warnings(source_metadata(probe()), ctx)
        self.assertTrue(any("Log" in row for row in warnings))
        self.assertTrue(any("history" in row for row in warnings))

    def _group_and_summary(self, intent: str = "neutral") -> tuple[dict, dict]:
        group = build_sample_plan(self.plan, self.sources, [declared(intent)], 5)["groups"][0]
        rows = [{"status": "sampled", "statistics": sample_statistics()} for _ in group["samples"]]
        return group, summarize(rows)

    def test_only_bounded_read_only_neutral_brightness_candidate(self) -> None:
        group, summary = self._group_and_summary()
        suggestions, warnings = review_suggestion(group, source_metadata(probe()), summary)
        self.assertEqual(len(suggestions), 1)
        self.assertLessEqual(abs(suggestions[0]["value"]), 0.04)
        self.assertFalse(suggestions[0]["applicableToPlan"])
        self.assertTrue(any("temperature/tint" in row for row in warnings))

    def test_intent_history_chroma_and_variation_suppress_correction(self) -> None:
        metadata = source_metadata(probe())
        for intent in ("dark", "colored", "unknown"):
            group, summary = self._group_and_summary(intent)
            self.assertEqual(review_suggestion(group, metadata, summary)[0], [])
        group, summary = self._group_and_summary()
        group["context"]["transformHistory"] = ["existing creative look"]
        self.assertEqual(review_suggestion(group, metadata, summary)[0], [])
        group["context"]["transformHistory"] = []
        summary["means"]["uMean"] = 190
        self.assertEqual(review_suggestion(group, metadata, summary)[0], [])
        summary["means"]["uMean"] = 128
        summary["maximumMeanLuma"] = 210
        self.assertEqual(review_suggestion(group, metadata, summary)[0], [])

    def test_sample_actual_time_failure_and_non_finite_statistics(self) -> None:
        requested = build_sample_plan(self.plan, self.sources, [declared()], 5)["groups"][0]["samples"][0]
        row = {"id": requested["id"], "requestedTime": requested["sourceTime"], "status": "sampled",
               "actualSourceTime": requested["sourceTime"], "statistics": sample_statistics(), "elapsedMs": 1,
               "frameMetadata": {"pixelFormat": "yuv420p", "range": "tv", "matrix": "bt709",
                                 "primaries": "bt709", "transfer": "bt709", "hdrSignaled": False}}
        validate_sample(row, requested)
        row["actualSourceTime"] = 700
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_sample(row, requested)
        row["actualSourceTime"] = requested["sourceTime"]
        row["statistics"]["yMean"] = float("nan")
        with self.assertRaisesRegex(ValueError, "range"):
            validate_sample(row, requested)


if __name__ == "__main__":
    unittest.main()
