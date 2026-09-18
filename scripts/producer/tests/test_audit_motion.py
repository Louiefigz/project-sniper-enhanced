"""audit_motion tests — the deterministic motion-quality backstop (Audit B).

Synthetic ffmpeg clips exercise each check's WARN vs PASS branch plus the
clean-cut gate. All clips are tiny (<=5s, 320x240, 24fps) so the suite stays
fast; the whole class skips when ffmpeg is absent (like the other motion tests).
"""
import glob
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403


def _run_ff(args: list) -> None:
    """Run an ffmpeg build command, raising on failure (test-fixture only)."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def _concat_clip(path: str, sources: list, dur: float) -> None:
    """Concat N lavfi sources (each ``dur`` seconds) into hard-cut segments."""
    inputs: list = []
    for src in sources:
        sep = ":" if "=" in src else "="   # "color=c=black" already has one
        inputs += ["-f", "lavfi", "-i", f"{src}{sep}s=320x240:r=24:d={dur}"]
    labels = "".join(f"[{i}:v]" for i in range(len(sources)))
    chain = f"{labels}concat=n={len(sources)}:v=1:a=0[v]"
    _run_ff([*inputs, "-filter_complex", chain, "-map", "[v]",
             "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
             "-pix_fmt", "yuv420p", path])


def _produced_plan(punch_ins: list) -> dict:
    """A produced longform plan carrying the given punchIns (nothing else)."""
    return {"target": {"mode": "longform", "treatment": "produced"},
            "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 30.0,
                          "speed": 1.0}],
            "punchIns": punch_ins}


class AuditMotionTests(unittest.TestCase):
    """check_pacing_rendered / check_presence / check_smoothness + the gate."""

    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            raise unittest.SkipTest("ffmpeg not on PATH")
        cls.dir = tempfile.mkdtemp(prefix="selftest-audit-motion-")
        cls.cuts = os.path.join(cls.dir, "cuts.mp4")
        cls.static = os.path.join(cls.dir, "static30.mp4")
        cls.zoom = os.path.join(cls.dir, "zoom.mp4")
        cls.midcut = os.path.join(cls.dir, "midcut.mp4")
        # 5x1s distinct patterns -> four hard cuts at 1/2/3/4s (well-paced).
        _concat_clip(cls.cuts, ["testsrc2", "color=c=black", "color=c=white",
                                "smptebars", "testsrc"], 1.0)
        # 30s of one solid color -> zero visual change (a long still stretch).
        _run_ff(["-f", "lavfi", "-i", "color=c=steelblue:s=320x240:r=24:d=30",
                 "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
                 "-pix_fmt", "yuv420p", cls.static])
        # 3s continuous slow zoom -> motion, but no scene-cut discontinuity.
        _run_ff(["-f", "lavfi", "-i", "testsrc2=s=320x240:r=24:d=3",
                 "-vf", "zoompan=z='min(zoom+0.002,1.5)':d=1:s=320x240:fps=24",
                 "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
                 "-pix_fmt", "yuv420p", cls.zoom])
        # A hard cut dead-center (1.5s) of a 3s clip -> a mid-window snap.
        _concat_clip(cls.midcut, ["testsrc2", "smptebars"], 1.5)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.dir, ignore_errors=True)

    # -- check_pacing_rendered (cut-manifest sanity, NOT a rate gate) -----------
    def test_pacing_cuts_manifest_passes(self) -> None:
        # A single-segment plan declares no internal cuts, so any render is fine:
        # informational PASS carrying the rendered rate, never a WARN.
        res = amot.check_pacing_rendered(self.cuts, 5.0,
                                         _produced_plan([]), "longform")
        self.assertTrue(res)
        self.assertFalse([r for r in res if r.status == amot.WARN], res)
        self.assertTrue(any(r.status == amot.PASS and "changes/min" in r.measured
                            for r in res))

    def test_pacing_cuts_absent_warns(self) -> None:
        # A plan declaring 4 cuts (5 segments) but a render with ZERO scene
        # changes = the cuts never composited (a frozen render) -> WARN.
        plan = {"target": {"mode": "longform", "treatment": "produced"},
                "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 6.0,
                              "speed": 1.0} for _ in range(5)],
                "punchIns": []}
        res = amot.check_pacing_rendered(self.static, 30.0, plan, "longform")
        failures = [r for r in res if r.status == amot.FAIL]
        self.assertTrue(failures)
        self.assertTrue(any("plan cuts" in r.measured for r in failures), res)

    def test_same_camera_cuts_pass_with_exact_delivery_lineage(self) -> None:
        plan = {"target": {"mode": "longform", "treatment": "produced"},
                "cutTrack": [
                    {"sourceId": "raw", "start": 0.0, "end": 2.0},
                    {"sourceId": "raw", "start": 3.0, "end": 5.0},
                    {"sourceId": "raw", "start": 6.0, "end": 8.0},
                ]}
        proof = amot.CutProof(3, 144, "assembled-final")
        with mock.patch.object(amot, "_scene_times", return_value=[]), \
                mock.patch.object(
                    amot, "_seams_manifested", return_value=(0, 2)), \
                mock.patch.object(
                    amot, "_sealed_cut_lineage", return_value=proof):
            res = amot.check_pacing_rendered(
                self.static, 6.0, plan, "longform")
        self.assertEqual(res[0].status, amot.PASS)
        self.assertIn("144 exact frames", res[0].measured)

    def test_lineage_with_wrong_part_cardinality_fails_closed(self) -> None:
        plan = {"target": {"mode": "longform", "treatment": "produced"},
                "cutTrack": [
                    {"sourceId": "raw", "start": 0.0, "end": 2.0},
                    {"sourceId": "raw", "start": 3.0, "end": 5.0},
                    {"sourceId": "raw", "start": 6.0, "end": 8.0},
                ]}
        proof = amot.CutProof(2, 144, "assembled-final")
        with mock.patch.object(amot, "_scene_times", return_value=[]), \
                mock.patch.object(
                    amot, "_seams_manifested", return_value=(0, 2)), \
                mock.patch.object(
                    amot, "_sealed_cut_lineage", return_value=proof):
            res = amot.check_pacing_rendered(
                self.static, 6.0, plan, "longform")
        self.assertEqual(res[0].status, amot.FAIL)

    # -- check_presence --------------------------------------------------------
    def test_presence_moving_window_passes(self) -> None:
        plan = _produced_plan([{"role": "aliveness", "outStart": 0.0,
                                "outEnd": 3.0, "kind": "ramp"}])
        res = amot.check_presence(self.zoom, plan, self.dir)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].status, amot.PASS)
        self.assertIn("show motion", res[0].measured)
        # Temp frames must be cleaned up.
        self.assertEqual(glob.glob(os.path.join(self.dir, "_presence_*")), [])

    def test_presence_static_window_warns(self) -> None:
        plan = _produced_plan([{"role": "aliveness", "outStart": 0.0,
                                "outEnd": 3.0, "kind": "ramp"}])
        res = amot.check_presence(self.static, plan, self.dir)
        self.assertTrue(any(r.status == amot.FAIL and "is static" in r.measured
                            for r in res), res)
        self.assertEqual(glob.glob(os.path.join(self.dir, "_presence_*")), [])

    # -- check_smoothness ------------------------------------------------------
    def test_smoothness_continuous_push_passes(self) -> None:
        plan = _produced_plan([{"role": "emphasis", "outStart": 0.0,
                                "outEnd": 3.0, "kind": "punch-in"}])
        res = amot.check_smoothness(self.zoom, plan)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].status, amot.PASS)
        self.assertIn("smooth", res[0].measured)

    def test_smoothness_mid_window_cut_warns(self) -> None:
        # A hard cut at 1.5s inside a [0,3] eased push is an unexpected splice.
        plan = _produced_plan([{"role": "emphasis", "outStart": 0.0,
                                "outEnd": 3.0, "kind": "punch-in"}])
        res = amot.check_smoothness(self.midcut, plan)
        self.assertTrue(any(r.status == amot.FAIL and "splice" in r.measured
                            for r in res), res)

    # -- clean-cut gate --------------------------------------------------------
    def test_clean_cut_plan_skips_all_three(self) -> None:
        # clean-cut leaves the engaging tracks empty: nothing to verify.
        plan = {"target": {"mode": "longform", "treatment": "clean-cut"},
                "punchIns": [
                    {"role": "aliveness", "outStart": 0.0, "outEnd": 3.0},
                    {"role": "emphasis", "outStart": 0.0, "outEnd": 3.0}]}
        self.assertEqual(
            amot.check_pacing_rendered(self.cuts, 5.0, plan, "longform"), [])
        self.assertEqual(amot.check_presence(self.zoom, plan, self.dir), [])
        self.assertEqual(amot.check_smoothness(self.zoom, plan), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
