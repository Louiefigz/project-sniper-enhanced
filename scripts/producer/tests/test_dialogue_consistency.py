"""Fast in-memory channel/section checks; no media processes or model calls."""

import os
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.audit_checks import CheckResult  # noqa: E402
from audit.audio_quality import _channel_result, check_audio_quality  # noqa: E402
from audit.dialogue_consistency import check_dialogue_consistency  # noqa: E402
from audit import audit_render  # noqa: E402
from compile_timeline import Segment, TimelineMap  # noqa: E402

RATE = 8000


def _stereo(duration: float = 4.0, amplitude: float = 0.07) -> np.ndarray:
    """Stable speech-band test tone isolates level/channel defects."""
    mono = amplitude * np.sin(2 * np.pi * 440 * np.arange(round(duration * RATE)) / RATE)
    return np.column_stack([mono, mono])


def _sections() -> dict:
    """Two explicit adjacent output intervals, unrelated to raw source time."""
    return {"audioReviewSections": [{"start": 0, "end": 2, "label": "first"},
                                     {"start": 2, "end": 4, "label": "second"}]}


def _rows(samples: np.ndarray, plan: dict | None = None) -> dict:
    """Index returned findings while keeping individual timed intervals."""
    return {row.name: row for row in check_dialogue_consistency(samples, plan or {})}


def _audit_plan(timeline: dict | None) -> dict:
    """Capture Audit B's plan wiring while mocking every external media check."""
    checks = ("check_duration", "check_loudness", "check_format", "check_file_budget",
              "check_cover", "check_glitch_screens", "check_pacing_rendered",
              "check_presence", "check_smoothness", "check_eye_trace")
    with ExitStack() as stack:
        for name in checks:
            stack.enter_context(patch.object(audit_render, name, return_value=[]))
        stack.enter_context(patch.object(audit_render, "_load_json", side_effect=[_sections(), timeline]))
        stack.enter_context(patch.object(audit_render, "measure_delivery", return_value={}))
        stack.enter_context(patch.object(audit_render, "has_audio_stream", return_value=True))
        stack.enter_context(patch.object(audit_render, "_fallback_duration", return_value=4))
        captured = stack.enter_context(patch.object(audit_render, "check_audio_quality", return_value=[]))
        audit_render._deterministic_checks(audit_render.Probed("local", "local.mp4", "longform", {}, {}))
    return captured.call_args.args[1]


class DialogueConsistencyTests(unittest.TestCase):
    """Channel faults fail; level changes request review without changing audio."""

    def test_balanced_stereo_passes_global_and_intervals(self) -> None:
        rows = _rows(_stereo(), _sections())
        self.assertTrue(all(row.status == "pass" for row in rows.values()))

    def test_quiet_balanced_audio_has_no_channel_fault(self) -> None:
        rows = _rows(_stereo(amplitude=0.008), _sections())
        self.assertEqual(rows["audio_channel_balance"].status, "pass")
        self.assertEqual(rows["audio_channel_intervals"].status, "pass")

    def test_alternating_dead_channels_cannot_cancel_in_global_median(self) -> None:
        samples = _stereo()
        samples[:2 * RATE, 1] = 0
        samples[2 * RATE:, 0] = 0
        rows = _rows(samples)
        self.assertEqual(rows["audio_channel_balance"].status, "pass")
        faults = [row for name, row in rows.items() if name.startswith("audio_channel_interval_")]
        self.assertTrue(faults)
        self.assertTrue(all(row.status == "fail" for row in faults))
        self.assertIn("0.000-4.000s", faults[0].measured)
        self.assertEqual(_channel_result(samples).status, "fail")

    def test_local_dropout_in_otherwise_balanced_clip_fails(self) -> None:
        samples = _stereo()
        samples[RATE:round(1.2 * RATE), 1] = 0
        rows = _rows(samples)
        self.assertEqual(rows["audio_channel_balance"].status, "pass")
        self.assertTrue(any(row.status == "fail" and "1.000-1.200s" in row.measured
                            for row in rows.values()))

    def test_final_partial_window_is_checked(self) -> None:
        samples = _stereo(2.025)
        samples[2 * RATE:, 1] = 0
        rows = _rows(samples)
        self.assertTrue(any(row.status == "fail" and "2.000-2.025s" in row.measured
                            for row in rows.values()))

    def test_loud_section_cannot_hide_quiet_section_channel_fault(self) -> None:
        samples = _stereo(amplitude=0.7)
        samples[2 * RATE:] *= 0.02
        samples[2 * RATE:, 1] = 0
        rows = _rows(samples)
        self.assertEqual(rows["audio_channel_balance"].status, "pass")
        self.assertTrue(any(row.status == "fail" and "4.000s" in row.measured
                            for row in rows.values()))

    def test_consistently_imbalanced_channels_keep_global_failure(self) -> None:
        samples = _stereo()
        samples[:, 1] *= 0.1
        result = _rows(samples)["audio_channel_balance"]
        self.assertEqual(result.status, "fail")
        self.assertIn("median delta +20.0 dB", result.measured)

    def test_silence_does_not_claim_dialogue_was_checked(self) -> None:
        rows = _rows(np.zeros((RATE, 2)))
        self.assertEqual(rows["audio_channel_balance"].status, "fail")
        self.assertEqual(rows["audio_dialogue_consistency"].status, "warn")

    def test_nonfinite_audio_cannot_pass(self) -> None:
        for bad in (np.nan, np.inf, -np.inf):
            samples = _stereo()
            samples[-1, 1] = bad
            rows = check_dialogue_consistency(samples, _sections())
            self.assertEqual([(row.name, row.status) for row in rows],
                             [("audio_dialogue_samples", "fail")])

    def test_invalid_audio_shapes_and_types_fail(self) -> None:
        inputs = [np.zeros(5), np.zeros((0, 2)), np.zeros((5, 1)),
                  np.array([["a", "b"]]), np.ones((2, 2), dtype=complex)]
        for samples in inputs:
            self.assertEqual(check_dialogue_consistency(samples, {})[0].status, "fail")

    def test_finite_values_that_overflow_metrics_cannot_pass(self) -> None:
        rows = check_dialogue_consistency(np.full((RATE, 2), 1e200), {})
        self.assertEqual(rows[0].name, "audio_dialogue_samples")
        self.assertEqual(rows[0].status, "fail")

    def test_large_adjacent_change_warns_with_time_and_delta(self) -> None:
        samples = _stereo()
        samples[2 * RATE:] *= 0.25
        original = samples.copy()
        rows = _rows(samples, _sections())
        result = rows["audio_dialogue_level_change_000001"]
        self.assertEqual(result.status, "warn")
        self.assertIn("at 2.000s; -12.0 dB", result.measured)
        self.assertIn("intentional whispers", result.detail)
        self.assertEqual(rows["audio_dialogue_consistency"].status, "warn")
        np.testing.assert_array_equal(samples, original)

    def test_modest_adjacent_change_does_not_warn(self) -> None:
        samples = _stereo()
        samples[2 * RATE:] *= 0.75
        rows = _rows(samples, _sections())
        self.assertEqual(rows["audio_dialogue_consistency"].status, "pass")
        self.assertFalse(any("level_change" in name for name in rows))

    def test_missing_single_or_silent_sections_do_not_claim_comparison(self) -> None:
        single = {"audioReviewSections": [_sections()["audioReviewSections"][0]]}
        self.assertEqual(_rows(_stereo())["audio_dialogue_consistency"].status, "warn")
        self.assertEqual(_rows(_stereo(), single)["audio_dialogue_consistency"].status, "warn")
        samples = _stereo()
        samples[2 * RATE:] = 0
        self.assertEqual(_rows(samples, _sections())["audio_dialogue_consistency"].status, "warn")

    def test_numeric_ordered_nonoverlapping_duration_bounded_sections_required(self) -> None:
        first, second = _sections()["audioReviewSections"]
        invalid = [None, [], {}, [None], [{**first, "start": True}],
                   [{**first, "start": "0"}], [{**first, "end": np.inf}],
                   [{**first, "end": np.nan}], [{**first, "end": 10**1000}],
                   [{**first, "start": -1}], [{**first, "end": 4.0001}],
                   [{**first, "start": 2}], [{**first, "label": " "}],
                   [{**first, "end": 0.00001}], [second, first],
                   [first, {**second, "start": 1.9}]]
        for value in invalid:
            rows = _rows(_stereo(), {"audioReviewSections": value})
            self.assertEqual(rows["audio_dialogue_consistency"].status, "fail", repr(value))

    def test_gaps_are_allowed_and_final_partial_section_is_measured(self) -> None:
        plan = {"audioReviewSections": [{"start": 0, "end": 1, "label": "intro"},
                                        {"start": 2, "end": 2.15, "label": "tail"}]}
        rows = _rows(_stereo(2.15), plan)
        self.assertEqual(rows["audio_dialogue_consistency"].status, "pass")
        self.assertIn("2.000-2.150s", rows["audio_dialogue_section_000001"].measured)

    def test_audio_quality_calls_shared_checks_and_stops_on_nonfinite_audio(self) -> None:
        samples = _stereo()
        samples[0, 0] = np.nan
        with patch("audit.audio_quality._decode_stereo", return_value=samples), \
                patch("audit.audio_quality._timing_result", return_value=CheckResult("timing", "pass", "")), \
                patch("audit.audio_quality._hum_result") as hum:
            results = check_audio_quality("unused-local-path", _sections())
        hum.assert_not_called()
        self.assertEqual(results[-1].name, "audio_dialogue_samples")
        self.assertEqual(results[-1].status, "fail")

    def test_audit_b_uses_mapped_output_seconds(self) -> None:
        timeline = TimelineMap([Segment(0, "a", 100, 110, 5, 0, 2),
                                Segment(1, "b", 500, 501, 0.5, 2, 4)])
        plan = _audit_plan(timeline.to_dict())
        self.assertEqual(plan["audioReviewSections"], [
            {"start": 0, "end": 2, "label": "picture cut 0: a"},
            {"start": 2, "end": 4, "label": "picture cut 1: b"}])

    def test_audit_b_missing_map_does_not_trust_edit_plan_section_clock(self) -> None:
        self.assertNotIn("audioReviewSections", _audit_plan(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
