#!/usr/bin/env python3
"""Unit tests for the DEEP STUDY event-layer fixes (acid report 2026-07-10).

One class per fix: (2) cut punches from the faceW step, (3) conflation —
region separation + family dedup, (4) step-vs-eased + sweep gates, plus the
extreme-luma in/out verdict and the chrome cluster gates. All pure functions
on constructed arrays — the e2e coverage lives in test_study_deep."""

import unittest

import numpy as np

from _common import *  # noqa: F401,F403

from study.deep_chrome import chrome_regions
from study.deep_easing import classify_motion
from study.deep_events import _dedup_family
from study.deep_face import _step_event, face_step
from study.deep_regions import component_regions, sweep_from_trace
from study.deep_regions_inout import inout_verdict
from study.deep_signals import SignalTrack


def _sig(fw: list, fx: "list | None" = None) -> SignalTrack:
    sig = SignalTrack(fps=24.0, width=320, height=568)
    sig.face_w = list(fw)
    sig.face_x = list(fx or [0.5] * len(fw))
    sig.face_present = [1] * len(fw)
    sig.d = [1.0] * len(fw)
    sig.luma = [120.0] * len(fw)
    return sig


class StepVsEasedTests(unittest.TestCase):
    """Fix 4: <=3-frame motion = step, never eased; easing needs >=5."""

    def test_instant_step_is_step_even_with_drift_tail(self) -> None:
        path = [1.0] * 5 + [1.25, 1.252, 1.249, 1.251, 1.25, 1.25]
        self.assertEqual(classify_motion(path)["kind"], "step")

    def test_eased_ramp_keeps_its_shape(self) -> None:
        ramp = [1 + 0.25 * (1 - (1 - u / 19) ** 3) for u in range(20)]
        verdict = classify_motion([1.0] * 3 + ramp + [1.25] * 3)
        self.assertEqual(verdict["kind"], "eased")
        self.assertEqual(verdict["easing"]["bestFit"], "power3-out")

    def test_flat_path_returns_none(self) -> None:
        self.assertIsNone(classify_motion([1.0] * 12))


class SweepGateTests(unittest.TestCase):
    """Fix 4: phantom sweeps — growth must be real, >=5 frames, no step."""

    def _trace(self, covs: list) -> dict:
        box = [0.0, 0.0, 0.4, 1.0]
        return {"coverages": covs, "bboxes": [None if c == 0 else box
                                              for c in covs]}

    def test_step_then_drift_is_not_a_sweep(self) -> None:
        covs = [0.0, 0.35] + [0.35 + 0.005 * k for k in range(12)]
        self.assertIsNone(sweep_from_trace(self._trace(covs)))

    def test_short_growth_is_not_a_sweep(self) -> None:
        covs = [0.0, 0.1, 0.2, 0.4, 0.4, 0.4, 0.4]
        self.assertIsNone(sweep_from_trace(self._trace(covs)))

    def test_genuine_monotonic_growth_is_a_sweep(self) -> None:
        covs = [0.0] + [0.4 * k / 9 for k in range(1, 10)] + [0.4] * 4
        sweep = sweep_from_trace(self._trace(covs))
        self.assertIsNotNone(sweep)
        self.assertGreaterEqual(sweep["frames"], 5)


class FacePunchTests(unittest.TestCase):
    """Fix 2: punch magnitude/direction from the faceW step."""

    def test_face_step_across_boundary(self) -> None:
        sig = _sig([0.26] * 10 + [0.32] * 10)
        step = face_step(sig, 10)
        self.assertEqual(step["punch"], "in")
        self.assertAlmostEqual(step["dScalePct"], 23.1, delta=1.5)

    def test_sub_threshold_drift_is_no_punch(self) -> None:
        sig = _sig([0.26] * 10 + [0.27] * 10)
        self.assertIsNone(face_step(sig, 10))

    def test_run_step_found_inside_bounds_only(self) -> None:
        fw = [0.26] * 8 + [0.33] * 8
        idx = list(range(100, 116))
        self.assertIsNotNone(_step_event(fw, idx, 100, 115))
        self.assertIsNone(_step_event(fw, idx, 100, 105))  # step at pad

    def test_smooth_glide_is_not_a_stack_of_steps(self) -> None:
        fw = [0.26 + 0.006 * k for k in range(20)]  # eased push, no plateau
        self.assertIsNone(_step_event(fw, list(range(20)), 0, 19))


class RegionSeparationTests(unittest.TestCase):
    """Fix 3: conflated detections separate by region; dedup keeps richest."""

    def test_two_distant_changes_stay_two_regions(self) -> None:
        mask = np.zeros((100, 100), dtype=bool)
        mask[10:25, 10:30] = True     # a graphic leaving up top
        mask[70:85, 60:90] = True     # a pop landing at the chest
        regions = component_regions(mask)
        self.assertEqual(len(regions), 2)

    def test_adjacent_glyph_blobs_merge(self) -> None:
        mask = np.zeros((100, 100), dtype=bool)
        mask[40:50, 10:30] = True
        mask[40:50, 32:52] = True     # 2px gap: one word, two glyph runs
        self.assertEqual(len(component_regions(mask)), 1)

    def test_dedup_keeps_the_richer_verdict(self) -> None:
        plain = {"t": 5.4, "frame": 162, "type": "graphic-in",
                 "durationFrames": 1, "bbox": [0.0, 0.0, 0.9, 1.0],
                 "transition": None}
        sweep = {"t": 5.5, "frame": 165, "type": "panel-in",
                 "durationFrames": 9, "bbox": [0.0, 0.0, 0.9, 1.0],
                 "transition": {"class": "sweep", "frames": 9}}
        kept = _dedup_family([plain, sweep])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["transition"]["class"], "sweep")

    def test_different_regions_never_dedup(self) -> None:
        a = {"t": 5.0, "frame": 150, "type": "graphic-in",
             "durationFrames": 1, "bbox": [0.0, 0.0, 0.2, 0.2],
             "transition": None}
        b = {"t": 5.05, "frame": 151, "type": "graphic-in",
             "durationFrames": 1, "bbox": [0.7, 0.7, 0.2, 0.2],
             "transition": None}
        self.assertEqual(len(_dedup_family([a, b])), 2)


class InOutVerdictTests(unittest.TestCase):
    """Extreme-luma primary tell; edge fallback for text on dark chrome."""

    def _noise(self, seed: int) -> np.ndarray:
        return np.random.RandomState(seed).randint(
            60, 200, (120, 160), dtype=np.uint8)

    def test_bright_text_arriving_on_footage_reads_in(self) -> None:
        pre = self._noise(1)
        post = pre.copy()
        post[50:70, 40:120] = 245
        bbox = [0.25, 0.4, 0.5, 0.2]
        self.assertEqual(inout_verdict(pre, post, bbox), "in")
        self.assertEqual(inout_verdict(post, pre, bbox), "out")

    def test_text_pop_on_dark_bar_falls_through_to_edges(self) -> None:
        pre = np.full((120, 160), 20, dtype=np.uint8)
        post = pre.copy()
        post[52:60, 44:80], post[52:60, 84:116] = 245, 245
        bbox = [0.25, 0.4, 0.5, 0.15]
        self.assertEqual(inout_verdict(pre, post, bbox), "in")


class ChromeClusterTests(unittest.TestCase):
    """Fix 3: designed chrome clusters; mid-tone flat footage rejected."""

    def _footage(self, seed: int) -> np.ndarray:
        rs = np.random.RandomState(seed)
        small = rs.randint(70, 190, (24, 40), dtype=np.uint8)
        import cv2
        return cv2.resize(small, (640, 360), interpolation=cv2.INTER_NEAREST)

    def test_cream_rail_with_glyphs_clusters_in(self) -> None:
        pre = self._footage(3)
        post = pre.copy()
        post[:, :210] = 235                    # flat cream rail
        post[100:110, 30:150] = 30             # a dark glyph line
        clusters = chrome_regions(pre, post)
        self.assertTrue(clusters["in"], "rail cluster missed")
        self.assertLess(clusters["in"][0]["bbox"][0], 0.1)

    def test_midtone_flat_region_is_not_chrome(self) -> None:
        pre = self._footage(4)
        post = pre.copy()
        post[:, :210] = 120                    # a gray sweater, not chrome
        post[100:110, 30:150] = 100
        self.assertFalse(chrome_regions(pre, post)["in"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
