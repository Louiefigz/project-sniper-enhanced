"""Adversarial contracts for disposable, exact-PTS placement sampling."""
from __future__ import annotations

import json
import subprocess
import unittest
from unittest import mock

from graphics import placement_verify as pv
from graphics.placement_coverage import placement_spans
from planner import free_space_sample as pixels
from planner import verified_frame_sampling as sampling

try:
    from motion import face_track
except ModuleNotFoundError as exc:
    if exc.name != "cv2":
        raise
    face_track = None


def _payload(packets: list, time_base: str = "1/30") -> dict:
    """Build a minimal ffprobe packet-index response."""
    return {"streams": [{"time_base": time_base}], "packets": packets}


def _timestamp_result(payload: object) -> tuple[float, ...]:
    """Parse synthetic metadata through the real ffprobe response adapter."""
    result = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
    with mock.patch.object(sampling.subprocess, "run", return_value=result):
        return sampling.frame_timestamps("render.mp4")


class PacketIndexTests(unittest.TestCase):
    """Malformed metadata cannot masquerade as verified displayed frames."""

    def test_packet_decode_order_is_sorted_into_nonuniform_presentation_order(self) -> None:
        """B-frame packet order does not become presentation order."""
        payload = _payload([{"pts": "60"}, {"pts": "1"},
                            {"pts": "0"}, {"pts": "32"}])
        self.assertEqual(_timestamp_result(payload), (0.0, 1 / 30, 32 / 30, 2.0))

    def test_absent_duplicate_and_invalid_pts_are_rejected(self) -> None:
        """A complete usable index is required, not a partial best guess."""
        invalid = [{}, [], _payload([]), _payload([{}]),
                   _payload([{"pts": 1}, {"pts": 1}]),
                   _payload([{"pts": "N/A"}]),
                   _payload([{"pts": 1}], "0/1"),
                   _payload([{"pts": 1}], "1/0")]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    _timestamp_result(payload)

    def test_subprocess_failure_is_not_an_empty_successful_index(self) -> None:
        """Tool failure must reach the caller's environment-unavailable route."""
        failure = subprocess.TimeoutExpired("ffprobe", 30)
        with mock.patch.object(sampling.subprocess, "run", side_effect=failure):
            with self.assertRaises(subprocess.TimeoutExpired):
                sampling.frame_timestamps("render.mp4")


class FrameSelectionTests(unittest.TestCase):
    """Renderer precision and inclusive boundaries select actual exposed PTS."""

    def test_broll_six_decimal_restart_preserves_rounding_exposed_frame(self) -> None:
        """Restart 1+2/30 serializes above frame 32, leaving 31 and 32 visible."""
        occlusions = {"broll": [[0, 1], [1 + 2 / 30, 3]]}
        stamps = (1.0, 31 / 30, 32 / 30, 33 / 30)
        with mock.patch.object(sampling, "frame_timestamps", return_value=stamps):
            actual = sampling.FrameIndex("render.mp4").samples((1, 1.066667), occlusions, 12)
        self.assertEqual(actual, (31 / 30, 32 / 30))

    def test_card_four_decimal_windows_are_inclusive(self) -> None:
        """Use serialized card times rather than their unrounded plan values."""
        stamps = (1.00006, 1.0001, 1.0005, 1.0011, 1.0012)
        occlusions = {"cards": [[1.00006, 1.00106]]}
        with mock.patch.object(sampling, "frame_timestamps", return_value=stamps):
            actual = sampling.FrameIndex("render.mp4").samples((1, 1.002), occlusions, 12)
        self.assertEqual(actual, (1.00006, 1.0012))

    def test_graphic_rounding_and_point_window_retain_displayed_endpoint(self) -> None:
        """A positive raw graphic can serialize to one inclusive timestamp."""
        clip = {"outStart": 1.00001, "outEnd": 1.00004}
        spans = placement_spans(clip, {}, rendered=True)
        self.assertEqual([(span.start, span.end) for span in spans], [(1.0, 1.0)])
        with mock.patch.object(sampling, "frame_timestamps", return_value=(0.9, 1.0, 1.1)):
            actual = sampling.FrameIndex("render.mp4").samples((1.0, 1.0), {}, 12)
        self.assertEqual(actual, (1.0,))

    def test_sparse_limit_preserves_distinct_first_and_last_nonuniform_pts(self) -> None:
        """Reduction uses actual PTS, retaining both potentially brief edges."""
        stamps = tuple(index * index / 100 for index in range(21))
        with mock.patch.object(sampling, "frame_timestamps", return_value=stamps):
            actual = sampling.FrameIndex("render.mp4").samples((0, 4), {}, 12)
        self.assertEqual(len(actual), 12)
        self.assertEqual((actual[0], actual[-1]), (0.0, 4.0))
        self.assertEqual(tuple(sorted(set(actual))), actual)
        self.assertTrue(set(actual).issubset(stamps))

    def test_invalid_limits_are_rejected_without_division_or_empty_success(self) -> None:
        """A budget below two cannot promise both endpoint frames."""
        for limit in (0, 1, -1, True, 1.5):
            with self.subTest(limit=limit):
                with mock.patch.object(sampling, "frame_timestamps", return_value=(0.0, 1.0)):
                    with self.assertRaises(ValueError):
                        sampling.FrameIndex("render.mp4").samples((0, 1), {}, limit)

    def test_index_is_loaded_once_for_multiple_spans(self) -> None:
        """One output pass never repeats a successful packet inventory."""
        with mock.patch.object(sampling, "frame_timestamps", return_value=(0.0, 1.0)) as load:
            index = sampling.FrameIndex("render.mp4")
            index.samples((0, 0.5), {}, 12)
            index.samples((0.5, 1), {}, 12)
        load.assert_called_once_with("render.mp4")

    def test_failed_index_is_not_reprobed_for_every_span(self) -> None:
        """An unavailable immutable render must not cost 30 seconds per span."""
        with mock.patch.object(sampling, "frame_timestamps", side_effect=ValueError("bad PTS")) as load:
            index = sampling.FrameIndex("render.mp4")
            for window in ((0, 1), (2, 3), (4, 5)):
                with self.assertRaises(ValueError):
                    index.samples(window, {}, 12)
        load.assert_called_once_with("render.mp4")


class ProbeScopeTests(unittest.TestCase):
    """A previous render/probe cannot leak timestamps into another request."""

    def test_scope_is_video_specific_nested_and_restored_after_exception(self) -> None:
        """Context cleanup also runs on geometry and decode failures."""
        self.assertIsNone(sampling.current_frame_samples("a.mp4"))
        with sampling.selected_frame_samples("a.mp4", (1.0,)):
            self.assertEqual(sampling.current_frame_samples("a.mp4"), (1.0,))
            self.assertIsNone(sampling.current_frame_samples("b.mp4"))
            with self.assertRaises(RuntimeError):
                with sampling.selected_frame_samples("b.mp4", (2.0,)):
                    self.assertIsNone(sampling.current_frame_samples("a.mp4"))
                    raise RuntimeError("probe failed")
            self.assertEqual(sampling.current_frame_samples("a.mp4"), (1.0,))
        self.assertIsNone(sampling.current_frame_samples("a.mp4"))
        self.assertIsNone(sampling.current_frame_samples("b.mp4"))

    def test_reused_context_gets_fresh_index_on_each_run(self) -> None:
        """Even the same output path can name a new render on a later pass."""
        observed: list[tuple] = []
        context = pv.VerifyContext("FAIL", {"broll": [[1, 1.5]]})
        clip = {"outStart": 0, "outEnd": 2, "anchor": "headroom",
                "placedBBox": [0, 0, 4, 4]}

        def probe(video: str, _start: float, _end: float, _bbox: tuple) -> tuple:
            observed.append(sampling.current_frame_samples(video))
            return True, {"ok": True}

        indices = [(0.0, 0.5, 1.0, 1.5, 2.0), (0.0, 0.25, 1.0, 1.5, 2.0)]
        with mock.patch.object(sampling, "frame_timestamps", side_effect=indices) as load, \
                mock.patch.object(pv, "verify_placement", side_effect=probe):
            pv.run_verify([clip], "render.mp4", context)
            pv.run_verify([clip], "render.mp4", context)
        self.assertEqual(load.call_count, 2)
        self.assertEqual(observed, [(0.0, 0.5), (2.0,), (0.0, 0.25), (2.0,)])
        self.assertIsNone(context.frame_index)
        self.assertIsNone(sampling.current_frame_samples("render.mp4"))

    def test_full_coverage_needs_no_index_bbox_or_geometry_probe(self) -> None:
        """True full exemption remains lazy and emits a SKIP, not verification."""
        rows: list[dict] = []
        context = pv.VerifyContext("FAIL", {"broll": [[0, 3]]},
                                   emit=lambda **fields: rows.append(fields))
        clip = {"outStart": 1, "outEnd": 2, "anchor": "headroom"}
        with mock.patch.object(sampling, "frame_timestamps") as load, \
                mock.patch.object(pv, "_placed_bbox") as bbox, \
                mock.patch.object(pv, "verify_placement") as probe:
            self.assertEqual(pv.run_verify([clip], "render.mp4", context), 1)
        load.assert_not_called()
        bbox.assert_not_called()
        probe.assert_not_called()
        self.assertEqual([row["status"] for row in rows], ["placement_verify_skip"])

    def test_new_run_retries_previous_index_failure_without_stale_skips(self) -> None:
        """A memoized failure belongs to one pass, not the reused context/path."""
        context = pv.VerifyContext("FAIL", {"broll": [[1, 1.5]]})
        clip = {"outStart": 0, "outEnd": 2, "anchor": "headroom",
                "placedBBox": [0, 0, 4, 4]}
        results = [ValueError("unavailable index"), (0.0, 0.5, 1.0, 1.5, 2.0)]
        with mock.patch.object(sampling, "frame_timestamps", side_effect=results) as load, \
                mock.patch.object(pv, "verify_placement", return_value=(True, {"ok": True})) as probe:
            pv.run_verify([clip], "render.mp4", context)
            load.assert_called_once_with("render.mp4")
            probe.assert_not_called()
            pv.run_verify([clip], "render.mp4", context)
        self.assertEqual(load.call_count, 2)
        self.assertEqual(probe.call_count, 2)
        self.assertIsNone(context.frame_index)


@unittest.skipUnless(face_track is not None, "installed OpenCV required")
class ExactSeekTests(unittest.TestCase):
    """Decoded PTS must substantiate every claimed exact sample."""

    def test_exact_seek_returns_only_matching_decoded_frame(self) -> None:
        """A correctly decoded timestamp does not receive a false mismatch."""
        capture, frame = mock.Mock(), object()
        capture.get.return_value = 1000.0
        with mock.patch.object(face_track, "_read_at", return_value=frame):
            self.assertIs(pixels._checked_sample(capture, 1.0, True), frame)

    def test_missing_neighboring_and_nonfinite_decoded_pts_rejected(self) -> None:
        """NaN comparisons must never turn an unproven seek into a PASS."""
        cases = [(None, 1000.0), (object(), 1033.333),
                 (object(), float("nan")), (object(), float("inf"))]
        for frame, decoded_ms in cases:
            with self.subTest(decoded_ms=decoded_ms, missing=frame is None):
                capture = mock.Mock()
                capture.get.return_value = decoded_ms
                with mock.patch.object(face_track, "_read_at", return_value=frame):
                    with self.assertRaises(RuntimeError):
                        pixels._checked_sample(capture, 1.0, True)

    def test_ordinary_planner_sampling_still_allows_approximate_seek(self) -> None:
        """The strict context must not silently change unrelated planning."""
        capture, frame = mock.Mock(), object()
        capture.get.return_value = 1033.333
        with mock.patch.object(face_track, "_read_at", return_value=frame):
            self.assertIs(pixels._checked_sample(capture, 1.0, False), frame)


if __name__ == "__main__":
    unittest.main(verbosity=2)
