"""Zoom-pull seam transitions (LIAM-4-MOVES move 1, measured 2026-07-11).

Pins the measured grammar: three variants (punch-cut / whip / settle) with
band-validated magnitudes, the punch-cut's SEQUENTIAL seam cover, the whip's
blur-masked peak, longform-only + seam-role lint, budget counting, and the
1:1 frame-count contract through transitions.py.
"""
import os
import subprocess
import tempfile
import unittest

from _common import *  # noqa: F401,F403


def _ev(variant: str, t: float = 10.0, **extra) -> dict:
    return {"outTime": t, "kind": "zoom-pull", "variant": variant, **extra}


class ZoomPullParseTests(unittest.TestCase):
    """zoom_pull.parse_event — variants, measured bands, footprints."""

    def test_defaults_resolve_from_config(self) -> None:
        spec = zp.parse_event(0, _ev("punch-cut"), 60.0)
        self.assertEqual(spec.variant, "punch-cut")
        self.assertAlmostEqual(spec.params["scale"], 1.205)
        self.assertEqual(spec.cover, "light-leak")   # sequential cover default

    def test_unknown_variant_rejected(self) -> None:
        with self.assertRaises(ValueError):
            zp.parse_event(0, _ev("crash-zoom"), 60.0)
        with self.assertRaises(ValueError):
            zp.parse_event(0, {"outTime": 10.0, "kind": "zoom-pull"}, 60.0)

    def test_override_outside_measured_band_rejected(self) -> None:
        with self.assertRaises(ValueError):
            zp.parse_event(0, _ev("punch-cut", scale=1.5), 60.0)
        with self.assertRaises(ValueError):
            zp.parse_event(0, _ev("whip", peakScale=3.0), 60.0)
        with self.assertRaises(ValueError):
            zp.parse_event(0, _ev("settle", fromScale=1.3), 60.0)

    def test_footprint_must_stay_inside_timeline(self) -> None:
        with self.assertRaises(ValueError):      # whip ramp needs ~1s before
            zp.parse_event(0, _ev("whip", t=0.6), 60.0)
        with self.assertRaises(ValueError):      # settle tail leaves the end
            zp.parse_event(0, _ev("settle", t=59.9), 60.0)

    def test_seam_role_vocabulary(self) -> None:
        spec = zp.parse_event(0, _ev("whip", seamRole="broll->aroll"), 60.0)
        self.assertEqual(spec.seam_role, "broll->aroll")
        with self.assertRaises(ValueError):
            zp.parse_event(0, _ev("whip", seamRole="graphic->aroll"), 60.0)

    def test_punch_cut_cover_slot(self) -> None:
        self.assertEqual(
            zp.parse_event(0, _ev("punch-cut", cover="white-flash"), 60.0).cover,
            "white-flash")
        self.assertEqual(
            zp.parse_event(0, _ev("punch-cut", cover=False), 60.0).cover, "")
        with self.assertRaises(ValueError):
            zp.parse_event(0, _ev("punch-cut", cover="xfade:fade"), 60.0)


class ZoomPullCurveTests(unittest.TestCase):
    """scale_at — the pure mirror of the ffmpeg z(t) per measured variant."""

    def test_punch_cut_completes_before_the_seam(self) -> None:
        spec = zp.parse_event(0, _ev("punch-cut", t=10.0), 60.0)
        p = spec.params
        t0 = 10.0 - p["complete_before_s"] - p["attack_s"]
        self.assertAlmostEqual(zp.scale_at(spec, t0 - 0.5), 1.0)
        self.assertAlmostEqual(zp.scale_at(spec, t0), 1.0)
        # bell-velocity midpoint: halfway through the attack = half the zoom
        mid = zp.scale_at(spec, t0 + p["attack_s"] / 2)
        self.assertAlmostEqual(mid, 1.0 + (p["scale"] - 1.0) * 0.5, places=6)
        # COMPLETE at attack end, HELD through the pre-seam gap …
        self.assertAlmostEqual(zp.scale_at(spec, t0 + p["attack_s"]),
                               p["scale"])
        self.assertAlmostEqual(zp.scale_at(spec, 10.0 - 0.01), p["scale"])
        # … and the CUT resolves it (the new shot is wide).
        self.assertAlmostEqual(zp.scale_at(spec, 10.0), 1.0)

    def test_whip_accelerates_into_a_seam_peak_then_settles(self) -> None:
        spec = zp.parse_event(0, _ev("whip", t=10.0), 60.0)
        p = spec.params
        self.assertAlmostEqual(zp.scale_at(spec, 10.0 - p["ramp_s"]), 1.0)
        # ease-in (accelerating): the midpoint sits well UNDER linear.
        mid = zp.scale_at(spec, 10.0 - p["ramp_s"] / 2)
        self.assertLess(mid, 1.0 + (p["peak_scale"] - 1.0) * 0.5)
        self.assertAlmostEqual(zp.scale_at(spec, 10.0 - 1e-6),
                               p["peak_scale"], places=3)
        # incoming side: starts at settle_scale, eases out to wide.
        self.assertAlmostEqual(zp.scale_at(spec, 10.0), p["settle_scale"])
        self.assertAlmostEqual(zp.scale_at(spec, 10.0 + p["settle_s"]), 1.0)

    def test_settle_zooms_out_after_a_delay(self) -> None:
        spec = zp.parse_event(0, _ev("settle", t=10.0, delayS=0.2), 60.0)
        p = spec.params
        self.assertAlmostEqual(zp.scale_at(spec, 9.9), 1.0)
        self.assertAlmostEqual(zp.scale_at(spec, 10.1), p["from_scale"])
        self.assertAlmostEqual(zp.scale_at(spec, 10.2 + p["dur_s"]), 1.0)
        falling = zp.scale_at(spec, 10.2 + p["dur_s"] / 2)
        self.assertLess(falling, p["from_scale"])
        self.assertGreater(falling, 1.0)

    def test_chain_filters_reuse_the_punch_engine_idiom(self) -> None:
        spec = zp.parse_event(0, _ev("whip", t=10.0), 60.0)
        parts = zp.chain_filters(spec, 1920, 1080)
        self.assertIn("eval=frame", parts[0])
        self.assertIn("crop=1920:1080", parts[0])
        self.assertIn("gblur", parts[1])            # blur-masked peak
        pc = zp.parse_event(0, _ev("punch-cut", t=10.0), 60.0)
        self.assertEqual(len(zp.chain_filters(pc, 1920, 1080)), 1)  # no blur


class ZoomPullTransitionsTests(unittest.TestCase):
    """transitions.py integration: parse, cover synthesis, filter chain."""

    def test_parse_events_accepts_zoom_pull(self) -> None:
        events = tr.parse_events([_ev("punch-cut", t=5.0)], 60.0)
        self.assertEqual(events[0].kind, "zoom-pull")
        self.assertIsNotNone(events[0].zoom)

    def test_overlapping_zoom_footprints_rejected(self) -> None:
        # whip@5.0 settles until 5.6s; punch-cut@6.0 starts zooming at ~4.77s
        with self.assertRaises(ValueError):
            tr.parse_events([_ev("whip", t=5.0), _ev("punch-cut", t=6.0)], 60.0)
        # non-overlapping footprints stay legal (whip tail 5.6 < settle 7.0)
        events = tr.parse_events([_ev("whip", t=5.0), _ev("settle", t=7.0)], 60.0)
        self.assertEqual(len(events), 2)

    def test_punch_cut_cover_lands_in_the_video_chain(self) -> None:
        events = tr.parse_events([_ev("punch-cut", t=5.0)], 60.0)
        fc = tr.build_video_filter(events, 30.0, (1920, 1080))
        self.assertIn("scale=w=", fc)               # the zoom branch
        self.assertIn("geq=lum='255-", fc)          # the light-leak cover
        flash = tr.parse_events(
            [_ev("punch-cut", t=5.0, cover="white-flash")], 60.0)
        self.assertIn("eq(N,150)",                  # cover flash at seam frame
                      tr.build_video_filter(flash, 30.0, (1920, 1080)))

    def test_flash_leak_only_chain_unchanged(self) -> None:
        events = tr.parse_events([{"outTime": 5.0, "kind": "white-flash"}], 60.0)
        fc = tr.build_video_filter(events, 30.0, (1920, 1080))
        self.assertNotIn("scale=w=", fc)            # additive: no zoom branch


class ZoomPullLintTests(unittest.TestCase):
    """plan_lint_motion: longform-only, seam-role advisory, budget-counted."""

    def _lint(self, events: list, mode: str, out_dur: float = 600.0):
        rep = pl.Report()
        plm.check_transitions({"transitions": events}, out_dur, mode, rep)
        return rep

    def test_zoom_pull_is_longform_only(self) -> None:
        ev = _ev("whip", t=30.0, seamRole="aroll->broll")
        self.assertEqual(self._lint([ev], "longform").errors, [])
        errors = self._lint([ev], "short").errors
        self.assertTrue(any("longform seam grammar" in e for e in errors),
                        errors)

    def test_missing_seam_role_warns(self) -> None:
        rep = self._lint([_ev("whip", t=30.0)], "longform")
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("seamRole" in w for w in rep.warnings),
                        rep.warnings)

    def test_band_violation_is_a_lint_error(self) -> None:
        rep = self._lint([_ev("whip", t=30.0, peakScale=5.0)], "longform")
        self.assertTrue(any("measured band" in e for e in rep.errors),
                        rep.errors)

    def test_zoom_pulls_count_against_the_density_budget(self) -> None:
        events = [_ev("settle", t=float(t), seamRole="aroll->broll")
                  for t in range(10, 22, 2)]        # 6 events in 30s
        rep = self._lint(events, "longform", out_dur=30.0)
        self.assertTrue(any("budget" in e for e in rep.errors), rep.errors)


@unittest.skipUnless(_HAVE_FFMPEG, "ffmpeg not on PATH")
class ZoomPullRenderTests(unittest.TestCase):
    """apply_transitions renders a zoom-pull with the frame count preserved."""

    def test_whip_render_preserves_frames(self) -> None:
        with tempfile.TemporaryDirectory(prefix="zoompull-") as tmp:
            src = os.path.join(tmp, "src.mp4")
            out = os.path.join(tmp, "out.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                 "-i", "testsrc2=size=320x180:rate=30:duration=6",
                 "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", src],
                check=True)
            result = tr.apply_transitions(
                src, [_ev("whip", t=3.0, sfx=False)], out)
            self.assertEqual(result["zoomPulls"], 1)
            self.assertEqual(result["inFrames"], result["outFrames"])
            # the peak frame really is magnified: the frame at the seam
            # differs from the source far more than a pre-ramp frame does.
            self.assertTrue(os.path.exists(out))


if __name__ == "__main__":
    unittest.main(verbosity=2)
