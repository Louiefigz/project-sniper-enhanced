"""motion tests (split from selftest.py)."""
import unittest

from _common import *  # noqa: F401,F403


class TransitionEngineTests(unittest.TestCase):
    """transitions.py — seam-cover primitives (R15: no naked butt joints)."""

    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("ffmpeg") is None:
            raise unittest.SkipTest("ffmpeg not on PATH")
        cls.dir = tempfile.mkdtemp(prefix="selftest-transitions-")
        cls.src = os.path.join(cls.dir, "src.mp4")
        tr.run_ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=4",
                   "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=4",
                   "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-b:a", "128k", "-shortest", cls.src])
        cls.out = os.path.join(cls.dir, "out.mp4")
        cls.result = tr.apply_transitions(
            cls.src, [{"outTime": 2.0, "kind": "white-flash", "sfx": True}], cls.out)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_event_validation_rejects_bad_input(self) -> None:
        with self.assertRaises(ValueError):     # unsorted / too close
            tr.parse_events([{"outTime": 3.0, "kind": "white-flash"},
                             {"outTime": 2.0, "kind": "light-leak"}], 10.0)
        with self.assertRaises(ValueError):     # unknown kind
            tr.parse_events([{"outTime": 2.0, "kind": "cross-dissolve"}], 10.0)
        with self.assertRaises(ValueError):     # outside the edge margin
            tr.parse_events([{"outTime": 9.9, "kind": "white-flash"}], 10.0)
        with self.assertRaises(ValueError):     # non-boolean sfx
            tr.parse_events([{"outTime": 2.0, "kind": "white-flash",
                              "sfx": "yes"}], 10.0)

    def test_frame_count_preserved_exactly(self) -> None:
        self.assertEqual(self.result["inFrames"], self.result["outFrames"])
        self.assertEqual(tr.probe_video_frames(self.out),
                         tr.probe_video_frames(self.src))

    def test_seam_frame_is_white(self) -> None:
        # The full-white frame sits exactly on outTime (frame 48 @24fps).
        self.assertGreater(_frame_yavg(self.out, 48), 200.0)

    def test_neighbor_frames_stay_clean(self) -> None:
        # One frame after the seam is already the clean new shot (3-frame law);
        # compare against the source's own frame so scene content cancels out.
        self.assertLess(abs(_frame_yavg(self.out, 49) - _frame_yavg(self.src, 49)), 8.0)
        self.assertLess(abs(_frame_yavg(self.out, 36) - _frame_yavg(self.src, 36)), 8.0)

    def test_audio_duration_preserved(self) -> None:
        self.assertLess(abs(self.result["audioOutS"] - self.result["audioInS"]),
                        tr.AUDIO_DUR_TOL_S)


class BaselineLookTests(unittest.TestCase):
    """baseline_look: crop geometry, frame preservation, output res, the
    crop-actually-applied marker mapping, and the upscale-warning path."""

    def test_crop_window_geometry_4k(self) -> None:
        # The pro spec on a 4K frame: window 3000x1688 at (420,106) — the
        # hand-computed chest-up recrop (centerY 0.44 pulls the window up).
        spec = bl.parse_spec({"zoom": 1.28, "centerX": 0.5, "centerY": 0.44})
        self.assertEqual(bl.crop_window(3840, 2160, spec), (3000, 1688, 420, 106))

    def test_crop_window_clamps_at_edges(self) -> None:
        # An extreme center can't push the window outside the frame.
        spec = bl.parse_spec({"zoom": 1.28, "centerX": 0.0, "centerY": 1.0})
        cw, ch, x, y = bl.crop_window(3840, 2160, spec)
        self.assertEqual((x, y), (0, 2160 - ch))

    def test_spec_rejections(self) -> None:
        self.assertRaises(ValueError, bl.parse_spec, {"zoom": 3.0})
        self.assertRaises(ValueError, bl.parse_spec, {"centerX": 1.5})
        self.assertRaises(ValueError, bl.parse_spec, {"grade": "teal-orange"})
        self.assertRaises(ValueError, bl.parse_spec, {"outW": 1919})

    @unittest.skipUnless(_HAVE_FFMPEG, "ffmpeg not installed")
    def test_render_preserves_frames_and_maps_the_crop(self) -> None:
        # zoom 1.25 on 640x360 -> window (512,288) at (64,36); the marker at
        # source (180,110) must land at ((180-64)*640/512, (110-36)*360/288)
        # = (145.0, 92.5). The window is BELOW the 640x360 canvas, so the
        # upscale warn must fire too (this drives that path deliberately).
        with tempfile.TemporaryDirectory(prefix="producer-bltest-") as td:
            src = os.path.join(td, "src.mp4")
            out = os.path.join(td, "out.mp4")
            _tiny_marked_clip(src)
            spec = bl.parse_spec({"zoom": 1.25, "centerY": 0.5, "grade": "warm",
                                  "outW": 640, "outH": 360})
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = bl.apply_baseline_look(src, spec, out)
            self.assertEqual(result["inFrames"], result["outFrames"])
            self.assertEqual(result["outRes"], [640, 360])
            self.assertEqual(result["cropWindow"], [512, 288, 64, 36])
            warns = [json.loads(ln) for ln in buf.getvalue().splitlines()]
            self.assertTrue(any(w.get("reason") == "upscale" for w in warns))
            mx, my = _marker_center(out, 1.0, 640, 360)
            self.assertLess(abs(mx - 145.0), 4.0)
            self.assertLess(abs(my - 92.5), 4.0)


class PunchInPanTests(unittest.TestCase):
    """punch_in pan-aware recompose: ramp centerX/centerY targets, ease
    validation + smoothstep shape, and the rendered translation vector."""

    def _ramp(self, **extra) -> pin.PunchWindow:
        (w,) = pin.parse_windows([{
            "outStart": 0.0, "outEnd": 4.0,
            "ramp": {"direction": "in", "ratePctPerS": 2.0}, **extra}])
        return w

    def test_ramp_center_and_ease_default_backward_compatible(self) -> None:
        w = self._ramp()
        self.assertEqual((w.center_x, w.center_y, w.ease), (0.5, 0.5, "linear"))

    def test_bad_ease_rejected(self) -> None:
        self.assertRaises(ValueError, self._ramp, ease="bounce")

    def test_smooth_ease_monotonic_with_exact_endpoints(self) -> None:
        # Smoothstep reshapes the trajectory but keeps the endpoints: the
        # scale must rise monotonically from the wide baseline to ramp_peak,
        # sit below linear early, above it late, and match at the midpoint.
        smooth, linear = self._ramp(ease="smooth"), self._ramp()
        samples = [pin.ramp_scale_at(smooth, t / 10.0) for t in range(41)]
        self.assertAlmostEqual(samples[0], 1.0, places=6)
        self.assertAlmostEqual(samples[-1], smooth.ramp_peak, places=6)
        self.assertTrue(all(b >= a - 1e-9 for a, b in zip(samples, samples[1:])))
        self.assertLess(pin.ramp_scale_at(smooth, 1.0), pin.ramp_scale_at(linear, 1.0))
        self.assertGreater(pin.ramp_scale_at(smooth, 3.0), pin.ramp_scale_at(linear, 3.0))
        self.assertAlmostEqual(pin.ramp_scale_at(smooth, 2.0),
                               pin.ramp_scale_at(linear, 2.0), places=6)

    def test_ramp_filter_carries_center_and_time_based_crop(self) -> None:
        # The crop x/y must recompute the scaled dims from t (crop's in_w/in_h
        # constants freeze at the pre-zoom link config — the old bare crop=W:H
        # silently anchored every ramp top-left).
        fc = pin.build_filter(1920, 1080, [self._ramp(centerX=0.35)])
        self.assertIn("x='clip(0.350000*max(1920", fc)
        self.assertIn("y='clip(0.500000*max(1080", fc)

    @unittest.skipUnless(_HAVE_FFMPEG, "ffmpeg not installed")
    def test_render_recomposes_toward_off_center_target(self) -> None:
        # Marker at source center (180,110); ramp 2%/s over [0,4] toward
        # centerX 0.35. At t=3.9 (z=1.078, sw=688, sh=388) the x-crop pins to
        # the left edge (clip(0.35*688-320,0,48)=0) while a centered crop
        # would sit at 24 — the marker must land at (193.5, 104.6), i.e. the
        # crop center drifted from 0.5 toward 0.35. Frame count must hold.
        with tempfile.TemporaryDirectory(prefix="producer-pantest-") as td:
            src = os.path.join(td, "src.mp4")
            out = os.path.join(td, "out.mp4")
            _tiny_marked_clip(src)
            win = self._ramp(centerX=0.35)
            with contextlib.redirect_stdout(io.StringIO()):
                result = pin.apply_punch_ins(src, [win], out)
            self.assertEqual(result["inFrames"], result["outFrames"])
            z = pin.ramp_scale_at(win, 3.9)
            sw, sh = int(640 * z / 2) * 2, int(360 * z / 2) * 2
            xc = min(max(0.35 * sw - 320.0, 0.0), sw - 640.0)
            yc = min(max(0.5 * sh - 180.0, 0.0), sh - 360.0)
            want = (180.0 * sw / 640.0 - xc, 110.0 * sh / 360.0 - yc)
            got = _marker_center(out, 3.9, 640, 360)
            self.assertLess(abs(got[0] - want[0]), 4.0)
            self.assertLess(abs(got[1] - want[1]), 4.0)


class MomentumZoneTests(unittest.TestCase):
    """momentum_zones — cluster list / sequence / count runs into hot zones."""

    def _words(self, n: int, step: float = 1.0) -> list:
        return [{"word": f"w{i}", "start": i * step, "end": i * step + 0.4}
                for i in range(n)]

    def test_run_clusters_into_one_zone(self) -> None:
        # Three momentum triggers 2s apart -> one zone spanning them, items=3.
        words = self._words(20)
        cands = [{"trigger": "enumeration", "wordIndices": [1]},
                 {"trigger": "sequence", "wordIndices": [3]},
                 {"trigger": "number", "wordIndices": [5]}]
        zones = mt.momentum_zones(cands, words, gap_s=8.0)
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]["items"], 3)
        self.assertLessEqual(zones[0]["outStart"], 1.0)
        self.assertGreaterEqual(zones[0]["outEnd"], 5.0)

    def test_lone_item_is_not_a_zone(self) -> None:
        words = self._words(10)
        cands = [{"trigger": "number", "wordIndices": [2]}]
        self.assertEqual(mt.momentum_zones(cands, words), [])

    def test_far_apart_runs_split(self) -> None:
        # Two enumerations early, two numbers ~40s later -> two separate zones.
        words = self._words(60)
        cands = [{"trigger": "enumeration", "wordIndices": [1]},
                 {"trigger": "enumeration", "wordIndices": [2]},
                 {"trigger": "number", "wordIndices": [40]},
                 {"trigger": "number", "wordIndices": [41]}]
        self.assertEqual(len(mt.momentum_zones(cands, words, gap_s=8.0)), 2)

    def test_non_momentum_triggers_ignored(self) -> None:
        words = self._words(10)
        cands = [{"trigger": "thesis", "wordIndices": [1]},
                 {"trigger": "entity", "wordIndices": [2]}]
        self.assertEqual(mt.momentum_zones(cands, words), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
