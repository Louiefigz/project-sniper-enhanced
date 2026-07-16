"""palmier translate tests — the plan→Palmier math, pure (no app needed).

Units rules under test (docs/PIPELINE.md): output seconds → integer frames;
keyframes clip-relative; position = TOP-LEFT normalized; scale = normalized
w/h; untranslatable vocabulary (transitions, ramp/bracket punches) fails LOUD.
"""
import unittest

from _common import *  # noqa: F401,F403
from palmier.translate import (TranslateError, TranslateRequest,
                               build_placements, clip_windows,
                               punch_keyframes, top_left, translate)

FPS = 24.0
BASE = (1.0, 0.5, 0.5)


def _cut(*segs):
    return [{"sourceId": "raw-1", "start": s, "end": e, "speed": sp}
            for s, e, sp in segs]


class PlacementTests(unittest.TestCase):
    def test_speed_scales_output_duration(self) -> None:
        p = build_placements(_cut((10.0, 20.0, 1.0), (30.0, 36.0, 2.0)), FPS)
        self.assertEqual((p[0].start_frame, p[0].end_frame), (0, 240))
        self.assertEqual((p[1].start_frame, p[1].end_frame), (240, 312))
        self.assertEqual(p[1].source, (30.0, 36.0))

    def test_clip_windows_split_across_cuts(self) -> None:
        p = build_placements(_cut((0.0, 5.0, 1.0), (10.0, 15.0, 1.0)), FPS)
        spans = clip_windows(p, 4.0, 7.0)
        self.assertEqual(spans, [(0, 4.0, 5.0), (1, 0.0, 2.0)])

    def test_zero_duration_segment_is_an_error(self) -> None:
        with self.assertRaises(TranslateError):
            build_placements(_cut((5.0, 5.0, 1.0)), FPS)


class TopLeftTests(unittest.TestCase):
    def test_centered_zoom_is_symmetric(self) -> None:
        self.assertEqual(top_left(1.2, 0.5, 0.5), (-0.1, -0.1))

    def test_edge_recompose_is_clamped_to_canvas(self) -> None:
        x, y = top_left(1.2, 0.0, 1.0)          # face at frame corner
        self.assertEqual((x, y), (0.0, -0.2))   # never exposes canvas edge


class PunchKeyframeTests(unittest.TestCase):
    def test_eased_punch_rows(self) -> None:
        p = build_placements(_cut((0.0, 10.0, 1.0)), FPS)
        punch = {"outStart": 2.0, "outEnd": 6.0, "zoom": 1.3,
                 "attackS": 0.5, "releaseS": 0.5,
                 "centerX": 0.5, "centerY": 0.4}
        tracks = punch_keyframes([punch], p, BASE, FPS)[0]
        frames = [r[0] for r in tracks["scale"]]
        self.assertEqual((frames[0], frames[-1]), (48, 145))
        scale = {row[0]: row[1:3] for row in tracks["scale"]}
        self.assertEqual(scale[60], [1.3, 1.3])
        self.assertEqual(scale[132], [1.3, 1.3])
        self.assertEqual(scale[48], [1.0, 1.0])
        self.assertEqual(scale[144], [1.0, 1.0])
        x, y = top_left(1.3, 0.5, 0.4)
        position = {row[0]: row[1:3] for row in tracks["position"]}
        self.assertEqual(position[60], [x, y])
        self.assertTrue(all(r[-1] == "smooth" for r in tracks["scale"]))

    def test_punch_composes_with_baseline_instead_of_replacing_it(self) -> None:
        placements = build_placements(_cut((0.0, 10.0, 1.0)), FPS)
        punch = {"outStart": 2.0, "outEnd": 4.0, "zoom": 1.1,
                 "attackS": 0.2, "centerX": 0.5, "centerY": 0.5}
        tracks = punch_keyframes(
            [punch], placements, (1.15, 0.5, 0.5), FPS)[0]
        peak = max(tracks["scale"], key=lambda row: row[1])
        position = {row[0]: row[1:3] for row in tracks["position"]}
        self.assertEqual(peak[1:3], [1.265, 1.265])
        self.assertEqual(position[peak[0]], [-0.1325, -0.1325])

    def test_static_punch_fails_without_proven_hold_semantics(self) -> None:
        p = build_placements(_cut((0.0, 10.0, 1.0)), FPS)
        punch = {"outStart": 2.0, "outEnd": 4.0, "zoom": 1.2}
        with self.assertRaisesRegex(TranslateError, "hold semantics"):
            punch_keyframes([punch], p, BASE, FPS)

    def test_punch_split_across_two_clips(self) -> None:
        p = build_placements(_cut((0.0, 5.0, 1.0), (10.0, 15.0, 1.0)), FPS)
        punch = {"outStart": 4.0, "outEnd": 7.0, "zoom": 1.2,
                 "attackS": 0.2, "releaseS": 0.2}
        tracks = punch_keyframes([punch], p, BASE, FPS)
        self.assertEqual(sorted(tracks.keys()), [0, 1])
        self.assertEqual(tracks[1]["scale"][0][0], 0)   # clip-RELATIVE frames
        self.assertEqual(tracks[0]["scale"][-1][1:3], [1.2, 1.2])
        self.assertEqual(tracks[1]["scale"][0][1:3], [1.2, 1.2])
        self.assertEqual(tracks[1]["scale"][-1][1:3], [1.0, 1.0])

    def test_cross_cut_attack_has_unique_continuous_rows(self) -> None:
        p = build_placements(_cut((0.0, 1.0, 1.0),
                                  (10.0, 12.0, 1.0)), FPS)
        punch = {"outStart": 0.5, "outEnd": 1.5, "zoom": 1.11,
                 "attackS": 0.2}
        tracks = punch_keyframes([punch], p, BASE, FPS)
        first, second = tracks[0]["scale"], tracks[1]["scale"]
        self.assertEqual(first[-1][1:3], [1.11, 1.11])
        self.assertEqual(second[0][1:3], [1.11, 1.11])
        self.assertEqual(second[-1][1:3], [1.0, 1.0])
        self.assertEqual([row[0] for row in second],
                         sorted({row[0] for row in second}))

    def test_c0679_cross_seam_punch_matches_global_envelope(self) -> None:
        p = build_placements(_cut(
            (13.661, 16.661, 1.0),
            (17.081, 35.631, 1.0),
            (36.301, 58.561, 1.0)), FPS)
        punch = {"outStart": 20.53, "outEnd": 22.13,
                 "zoom": 1.11, "attackS": 0.8}
        tracks = punch_keyframes([punch], p, BASE, FPS)
        first, second = tracks[1]["scale"], tracks[2]["scale"]
        self.assertEqual((first[0][0], first[-1][0]), (421, 445))
        self.assertAlmostEqual(first[-1][1], 1.11, places=3)
        self.assertAlmostEqual(second[0][1], 1.11, places=3)
        self.assertEqual(second[-1], [15, 1.0, 1.0, "smooth"])
        self.assertEqual(tracks[1]["position"][-1][1:3],
                         tracks[2]["position"][0][1:3])

    def test_long_push_hold_drops_redundant_per_frame_samples(self) -> None:
        placements = build_placements(_cut((0.0, 10.0, 1.0)), FPS)
        punch = {"outStart": 1.0, "outEnd": 9.0, "zoom": 1.2,
                 "attackS": 0.5, "releaseS": 0.5}
        rows = punch_keyframes([punch], placements, BASE, FPS)[0]["scale"]
        self.assertLess(len(rows), 40)
        self.assertEqual(rows[0][1], 1.0)
        self.assertEqual(max(row[1] for row in rows), 1.2)
        self.assertEqual(rows[-1][1], 1.0)

    def test_c0679_adjacent_ramp_keeps_a_motion_witness(self) -> None:
        placements = build_placements(_cut(
            (13.661, 16.661, 1.0),
            (17.081, 35.631, 1.0),
            (36.301, 58.561, 1.0)), FPS)
        ramp = {"outStart": 3.0, "outEnd": 20.53, "kind": "ramp",
                "role": "aliveness", "ease": "smooth",
                "ramp": {"direction": "in", "ratePctPerS": 0.8}}
        punch = {"outStart": 20.53, "outEnd": 22.13,
                 "zoom": 1.11, "attackS": 0.8}
        rows = punch_keyframes([ramp, punch], placements, BASE, FPS)[1]["scale"]
        self.assertTrue(any(row[0] < 421 and row[1] > 1.01 for row in rows))
        self.assertLess(next(row for row in rows if row[0] == 421)[1], 1.001)

    def test_overlapping_punches_collide_loudly(self) -> None:
        p = build_placements(_cut((0.0, 10.0, 1.0)), FPS)
        punches = [{"outStart": 1.0, "outEnd": 5.0, "zoom": 1.2},
                   {"outStart": 3.0, "outEnd": 7.0, "zoom": 1.4}]
        with self.assertRaises(TranslateError):
            punch_keyframes(punches, p, BASE, FPS)

    def test_smooth_aliveness_ramp_becomes_scale_and_position_keyframes(self) -> None:
        p = build_placements(_cut((0.0, 10.0, 1.0)), FPS)
        ramp = {"outStart": 1.0, "outEnd": 5.0, "kind": "ramp",
                "role": "aliveness", "ease": "smooth",
                "ramp": {"direction": "in", "ratePctPerS": 0.8},
                "centerX": 0.55, "centerY": 0.4}
        tracks = punch_keyframes([ramp], p, BASE, FPS)[0]
        scale = {row[0]: row[1] for row in tracks["scale"]}
        self.assertEqual(scale[24], 1.0)
        self.assertGreater(max(value for frame, value in scale.items()
                               if frame < 120), 1.03)
        self.assertEqual(scale[120], 1.032)
        self.assertEqual(scale[121], 1.0)
        self.assertEqual(tracks["position"][0][1:3], [0.0, 0.0])
        self.assertNotEqual(tracks["position"][-2][1:3], [0.0, 0.0])
        self.assertEqual(tracks["position"][-1][1:3], [0.0, 0.0])

    def test_fractional_ramp_end_never_resets_an_inside_frame_early(self) -> None:
        placements = build_placements(_cut((0.0, 10.0, 1.0)), FPS)
        for fraction in (0.48, 0.52):
            end = 5.0 + fraction / FPS
            ramp = {"outStart": 1.0, "outEnd": end, "ease": "smooth",
                    "ramp": {"direction": "in", "ratePctPerS": 0.8}}
            rows = punch_keyframes(
                [ramp], placements, BASE, FPS)[0]["scale"]
            by_frame = {row[0]: row[1] for row in rows}
            self.assertGreater(by_frame[120], 1.03)
            self.assertEqual(by_frame[121], 1.0)

    def test_constant_position_motion_emits_only_scale(self) -> None:
        placements = build_placements(_cut((0.0, 10.0, 1.0)), FPS)
        punch = {"outStart": 1.0, "outEnd": 3.0, "zoom": 1.1,
                 "attackS": 0.5, "centerX": 0.0, "centerY": 0.0}
        tracks = punch_keyframes([punch], placements, BASE, FPS)[0]
        self.assertIn("scale", tracks)
        self.assertNotIn("position", tracks)
        steps = TranslateTests()._steps(
            TranslateTests()._plan(punchIns=[punch]))
        props = [row["property"] for row in steps
                 if row["op"] == "keyframes"]
        self.assertEqual(props, ["scale"])

    def test_non_smooth_ramp_fails_instead_of_being_approximated(self) -> None:
        p = build_placements(_cut((0.0, 10.0, 1.0)), FPS)
        ramp = {"outStart": 1.0, "outEnd": 5.0,
                "ramp": {"direction": "in", "ratePctPerS": 0.8}}
        with self.assertRaisesRegex(TranslateError, "ease:'smooth'"):
            punch_keyframes([ramp], p, BASE, FPS)

    def test_offtimeline_punch_is_an_error(self) -> None:
        p = build_placements(_cut((0.0, 5.0, 1.0)), FPS)
        with self.assertRaises(TranslateError):
            punch_keyframes([{"outStart": 8.0, "outEnd": 9.0, "zoom": 1.2}],
                            p, BASE, FPS)


class TranslateTests(unittest.TestCase):
    def _plan(self, **extra):
        return {"target": {"mode": "longform"},
                "cutTrack": _cut((0.0, 10.0, 1.0)),
                "captions": {"burn": False}, **extra}

    def _steps(self, plan, graphics_paths=None, canvas=(1920, 1080)):
        request = TranslateRequest(
            fps=FPS, source_path="/src.mp4",
            graphics_paths=graphics_paths or {}, project_name="t",
            width=canvas[0], height=canvas[1])
        return translate(plan, request)

    def test_transitions_error_loudly(self) -> None:
        with self.assertRaises(TranslateError):
            self._steps(self._plan(transitions=[{"kind": "white-flash"}]))

    def test_broll_track_errors_instead_of_disappearing(self) -> None:
        plan = self._plan(brollTrack=[{
            "outStart": 1.0, "outEnd": 3.0, "assetId": "broll-1"}])
        with self.assertRaisesRegex(TranslateError, "brollTrack"):
            self._steps(plan)

    def test_longform_unburned_captions_add_no_steps(self) -> None:
        ops = [s["op"] for s in self._steps(self._plan())]
        self.assertNotIn("warn", ops)           # burn:false is the doctrine

    def test_burned_captions_warn(self) -> None:
        steps = self._steps(self._plan(captions={"burn": True}))
        self.assertTrue(any(s["op"] == "warn" and "captions" in s["message"]
                            for s in steps))

    def test_graphic_without_render_is_an_error(self) -> None:
        plan = self._plan(graphicsTrack=[{"kind": "stat-card",
                                          "outStart": 1.0, "outEnd": 3.0}])
        with self.assertRaises(TranslateError):
            self._steps(plan)

    def test_graphic_window_lands_in_frames(self) -> None:
        plan = self._plan(graphicsTrack=[{"kind": "stat-card",
                                          "outStart": 1.0, "outEnd": 3.0}])
        steps = self._steps(plan, graphics_paths={0: "/g0.mov"})
        overlay = next(s for s in steps if s["op"] == "overlays")
        self.assertEqual(overlay["entries"][0]["startFrame"], 24)
        self.assertEqual(overlay["entries"][0]["endFrame"], 72)

    def test_graphic_rejects_4k_project_canvas(self) -> None:
        plan = self._plan(graphicsTrack=[{"kind": "stat-card",
                                          "outStart": 1.0, "outEnd": 3.0}])
        with self.assertRaises(TranslateError) as ctx:
            self._steps(plan, {0: "/g0.mov"}, canvas=(3840, 2160))
        self.assertIn("3840x2160", str(ctx.exception))
        self.assertIn("1920x1080", str(ctx.exception))

    def test_4k_without_graphics_remains_translatable(self) -> None:
        steps = self._steps(self._plan(), canvas=(3840, 2160))
        project = next(step for step in steps if step["op"] == "project")
        self.assertEqual((project["width"], project["height"]), (3840, 2160))

    def test_short_graphic_accepts_portrait_comp_canvas(self) -> None:
        plan = self._plan(target={"mode": "short"},
                          graphicsTrack=[{"kind": "stat-card",
                                          "outStart": 1.0, "outEnd": 3.0}])
        steps = self._steps(plan, {0: "/g0.mov"}, canvas=(1080, 1920))
        self.assertTrue(any(step["op"] == "overlays" for step in steps))

    def test_baseline_look_becomes_center_transform(self) -> None:
        plan = self._plan(baselineLook={"zoom": 1.15, "centerX": 0.5,
                                        "centerY": 0.42, "grade": "warm"})
        steps = self._steps(plan)
        base = next(s for s in steps if s["op"] == "baseline")
        self.assertAlmostEqual(base["transform"]["width"], 1.15)
        self.assertAlmostEqual(base["transform"]["centerY"],
                               top_left(1.15, 0.5, 0.42)[1] + 1.15 / 2)
        self.assertTrue(any(s["op"] == "warn" and "grade" in s["message"]
                            for s in steps))     # warm grade not translated

    def test_none_baseline_grade_does_not_warn(self) -> None:
        steps = self._steps(self._plan(
            baselineLook={"zoom": 1.0, "grade": "none"}))
        self.assertFalse(any(s["op"] == "warn" and "grade" in s["message"]
                             for s in steps))

    def test_deterministic_step_list(self) -> None:
        plan = self._plan(punchIns=[{"outStart": 1.0, "outEnd": 3.0,
                                     "zoom": 1.2, "attackS": 0.3}])
        self.assertEqual(self._steps(plan), self._steps(plan))

    def test_multi_source_plan_rejected(self) -> None:
        plan = self._plan(cutTrack=[
            {"sourceId": "a", "start": 0.0, "end": 1.0},
            {"sourceId": "b", "start": 0.0, "end": 1.0}])
        with self.assertRaises(TranslateError):
            self._steps(plan)

    def test_music_is_preview_silent_and_deferred_to_audio_authority(self) -> None:
        plan = self._plan(music={"enabled": True, "path": "/bed.mp3",
                                 "duck": False})
        steps = self._steps(plan)
        self.assertFalse(any(s["op"] == "music" for s in steps))
        self.assertFalse(any(s.get("key") == "music" for s in steps))
        self.assertTrue(any(s["op"] == "warn" and "preview-silent" in s["message"]
                            for s in steps))

    def test_audio_processing_is_never_silently_lost(self) -> None:
        steps = self._steps(self._plan(
            audioEnhance={"preset": "voice"},
            audioGain=[{"outStart": 1.0, "outEnd": 2.0, "dB": 2.0}]))
        warnings = [s["message"] for s in steps if s["op"] == "warn"]
        self.assertTrue(any("authoritative audio bus" in message
                            for message in warnings))

    def test_music_unresolved_assetid_is_a_named_error(self) -> None:
        plan = self._plan(music={"enabled": True, "assetId": "music-1"})
        with self.assertRaises(TranslateError) as ctx:
            self._steps(plan)
        self.assertIn("assetId", str(ctx.exception))
        self.assertIn("music-1", str(ctx.exception))


class NtscTimebaseTests(unittest.TestCase):
    """29.97 sources: Palmier conforms clips by REAL TIME at the INTEGER
    project fps, so every frame must be computed at round(fps) — real-rate
    math drifts ~1 frame/33s and the same-track overwrite trims neighbors."""

    # 40 × 3.337s segments ≈ 133s of timeline — several frames of NTSC drift
    CUT = [{"sourceId": "raw-1", "start": i * 4.0, "end": i * 4.0 + 3.337,
            "speed": 1.0} for i in range(40)]

    def _steps(self) -> list[dict]:
        plan = {"target": {"mode": "longform"}, "cutTrack": self.CUT,
                "captions": {"burn": False}}
        request = TranslateRequest(
            fps=29.97, source_path="/src.mp4", graphics_paths={},
            project_name="t", width=1920, height=1080)
        return translate(plan, request)

    def test_placements_land_on_rounded_project_fps_math(self) -> None:
        steps = self._steps()
        self.assertEqual(
            next(s for s in steps if s["op"] == "project")["fps"], 30)
        out_s = 0.0
        for entry in next(s for s in steps if s["op"] == "cuts")["entries"]:
            self.assertEqual(entry["startFrame"], round(out_s * 30))
            out_s += 3.337

    def test_successive_placements_tile_exactly(self) -> None:
        p = build_placements(self.CUT, 30.0)    # translate rounds 29.97 → 30
        for prev, nxt in zip(p, p[1:]):
            self.assertEqual(nxt.start_frame, prev.end_frame)

    def test_rounding_warn_names_the_single_timebase(self) -> None:
        warns = [s["message"] for s in self._steps() if s["op"] == "warn"]
        self.assertTrue(any("rounded" in m and "frame math" in m
                            for m in warns))


class VisualMirrorTranslateTests(unittest.TestCase):
    def _request(self, components=None):
        return TranslateRequest(
            fps=30.0, source_path="/approved/final.mp4", graphics_paths={},
            project_name="mirror", width=1920, height=1080,
            export_path="/out/final.palmier.mp4",
            master_path="/approved/final.mp4", master_hash="abc123",
            master_duration_s=12.5, master_fps=30.0,
            component_paths=components or {})

    def test_rich_plan_becomes_one_visual_master_not_visible_components(self):
        plan = {"cutTrack": _cut((0.0, 10.0, 1.0)),
                "graphicsTrack": [{"kind": "card", "outStart": 1, "outEnd": 3}],
                "transitions": [{"kind": "white-flash", "outTime": 4}],
                "captions": {"burn": True}}
        steps = translate(plan, self._request({0: "/cache/card.mov"}))
        self.assertEqual([step["op"] for step in steps],
                         ["project", "import", "mirror", "component_import", "export"])
        mirror = next(step for step in steps if step["op"] == "mirror")
        self.assertEqual(mirror["entry"]["endFrame"], 375)
        self.assertEqual(mirror["entry"]["masterHash"], "abc123")
        self.assertFalse(any(step["op"] == "overlays" for step in steps))

    def test_master_canvas_and_fps_own_project_settings(self):
        project = translate({"cutTrack": _cut((0, 1, 1))}, self._request())[0]
        self.assertEqual((project["fps"], project["width"], project["height"]),
                         (30, 1920, 1080))


class PreflightTests(unittest.TestCase):
    """push.py --preflight: the editor chip's verdict — pure, exit-0 data."""

    REQUEST = TranslateRequest(
        fps=24.0, source_path="/final.mp4", graphics_paths={},
        project_name="preflight", width=1920, height=1080,
        master_path="/final.mp4", master_hash="approved",
        master_duration_s=10.0, master_fps=24.0)

    def _plan(self, **extra):
        return {"target": {"mode": "longform"},
                "cutTrack": _cut((0.0, 10.0, 1.0)),
                "captions": {"burn": False}, **extra}

    def test_non_exact_plan_is_mirror_ready(self) -> None:
        from palmier.push import preflight
        plan = self._plan(baselineLook={"zoom": 1.1, "grade": "warm"},
                          graphicsTrack=[{"kind": "stat-card",
                                          "outStart": 1.0, "outEnd": 3.0}])
        v = preflight(plan, self.REQUEST)
        self.assertTrue(v["ok"])
        self.assertTrue(v["mirrorReady"])
        self.assertFalse(v["parity"]["fullyEditable"])

    def test_exact_cut_only_plan_reports_ok(self) -> None:
        from palmier.push import preflight
        plan = {"target": {"mode": "longform"},
                "cutTrack": _cut((0.0, 10.0, 1.0))}
        v = preflight(plan, self.REQUEST)
        self.assertTrue(v["ok"])
        self.assertTrue(v["parity"]["fullyEditable"])

    def test_blocked_plan_names_the_blocker(self) -> None:
        from palmier.push import preflight
        v = preflight(self._plan(transitions=[{"kind": "white-flash"}]),
                      self.REQUEST)
        self.assertFalse(v["ok"])
        self.assertIn("unsafe", v["blocked"])

    def test_missing_approved_master_blocks_top_level_readiness(self) -> None:
        from palmier.push import preflight
        v = preflight(self._plan(), None, "QC approval missing")
        self.assertFalse(v["mirrorReady"])
        self.assertTrue(v["parity"]["mirrorReady"])
        self.assertIn("QC approval", v["blocked"])


if __name__ == "__main__":
    unittest.main()
