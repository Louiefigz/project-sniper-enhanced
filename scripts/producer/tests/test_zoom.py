"""zoom tests (split from selftest.py)."""
import unittest

from _common import *  # noqa: F401,F403


class ZoomEngineTests(unittest.TestCase):
    """punch_in ramps + brackets: window expansion, ramp math, filter shape."""

    def test_static_window_parses(self) -> None:
        (w,) = pin.parse_windows([{"outStart": 2.0, "outEnd": 4.0, "zoom": 1.2}])
        self.assertEqual(w.origin, "static")
        self.assertFalse(w.is_ramp)

    def test_bracket_expands_to_in_punch(self) -> None:
        # A bracket renders as its in-punch [s, s+holdS]; the punch-out is the
        # overlay disabling at s+holdS (resolve to wide).
        (w,) = pin.parse_windows(
            [{"outStart": 16.0, "outEnd": 18.4, "zoom": 1.25,
              "bracket": True, "holdS": 1.6}])
        self.assertEqual(w.origin, "bracket")
        self.assertAlmostEqual(w.out_start, 16.0)
        self.assertAlmostEqual(w.out_end, 17.6)
        self.assertAlmostEqual(w.zoom, 1.25)

    def test_ramp_peak_and_scale_math(self) -> None:
        # 0.8%/s over 8s -> +6.4% peak; linear from the wide baseline to the peak.
        (w,) = pin.parse_windows(
            [{"outStart": 6.0, "outEnd": 14.0,
              "ramp": {"direction": "in", "ratePctPerS": 0.8}}])
        self.assertTrue(w.is_ramp)
        self.assertAlmostEqual(w.ramp_peak, 1.064, places=4)
        self.assertAlmostEqual(pin.ramp_scale_at(w, 6.0), 1.0, places=4)
        self.assertAlmostEqual(pin.ramp_scale_at(w, 10.0), 1.032, places=4)
        self.assertAlmostEqual(pin.ramp_scale_at(w, 14.0), 1.064, places=4)

    def test_ramp_out_sweeps_peak_to_baseline(self) -> None:
        (w,) = pin.parse_windows(
            [{"outStart": 0.0, "outEnd": 10.0,
              "ramp": {"direction": "out", "ratePctPerS": 1.0}}])
        self.assertAlmostEqual(pin.ramp_scale_at(w, 0.0), 1.10, places=4)    # peak
        self.assertAlmostEqual(pin.ramp_scale_at(w, 10.0), 1.0, places=4)    # wide

    def test_ramp_peak_over_hard_max_rejected(self) -> None:
        # 3%/s over 30s pushes scale to ~1.9 — past the primitive ceiling.
        self.assertRaises(ValueError, pin.parse_windows,
                          [{"outStart": 0.0, "outEnd": 30.0,
                            "ramp": {"direction": "in", "ratePctPerS": 3.0}}])

    def test_windows_overlap_rejected(self) -> None:
        self.assertRaises(ValueError, pin.parse_windows,
                          [{"outStart": 0.0, "outEnd": 5.0, "zoom": 1.1},
                           {"outStart": 4.0, "outEnd": 8.0, "zoom": 1.1}])

    def test_build_filter_has_ramp_and_static_branches(self) -> None:
        ws = pin.parse_windows(
            [{"outStart": 2.0, "outEnd": 4.0, "zoom": 1.2},
             {"outStart": 6.0, "outEnd": 14.0,
              "ramp": {"direction": "in", "ratePctPerS": 0.8}}])
        fc = pin.build_filter(1080, 1920, ws)
        self.assertIn("eval=frame", fc)                 # the ramp branch
        self.assertIn("scale=1296:2304", fc)            # the static 1.2 punch
        self.assertEqual(fc.count("overlay=enable="), 2)

    def test_push_window_eases_in_then_holds(self) -> None:
        # Eased-attack push: smoothstep 1.0->zoom over attackS, then a constant hold.
        (w,) = pin.parse_windows(
            [{"outStart": 2.0, "outEnd": 4.0, "zoom": 1.2, "attackS": 0.5}])
        self.assertTrue(w.is_push and w.is_animated and not w.is_ramp)
        self.assertAlmostEqual(pin.push_scale_at(w, 2.0), 1.0, places=4)    # baseline
        self.assertAlmostEqual(pin.push_scale_at(w, 2.25), 1.1, places=4)   # smoothstep mid
        self.assertAlmostEqual(pin.push_scale_at(w, 2.5), 1.2, places=4)    # peak at attack end
        self.assertAlmostEqual(pin.push_scale_at(w, 3.9), 1.2, places=4)    # holds after

    def test_push_renders_in_the_animated_branch(self) -> None:
        # A push is per-frame animated (eval=frame), a static punch beside it keeps
        # its single scaled copy; both overlay.
        ws = pin.parse_windows(
            [{"outStart": 2.0, "outEnd": 4.0, "zoom": 1.2, "attackS": 0.5},
             {"outStart": 6.0, "outEnd": 8.0, "zoom": 1.15}])
        fc = pin.build_filter(1080, 1920, ws)
        self.assertIn("eval=frame", fc)                 # the push (per-frame scale)
        self.assertIn("scale=1242:2208", fc)            # the static 1.15 punch
        self.assertEqual(fc.count("overlay=enable="), 2)


class ZoomLintTests(unittest.TestCase):
    """Zoom-track lint: ramp/bracket fields, cadence budget, bracket cap."""

    def _errors(self, plan: dict) -> list[str]:
        return pl.lint(plan, MANIFEST).errors

    def assert_fires(self, plan: dict, needle: str) -> None:
        errors = self._errors(plan)
        self.assertTrue(any(needle in e for e in errors),
                        f"expected {needle!r} in errors: {errors}")

    def _plan(self, punch_ins: list[dict]) -> dict:
        plan = good_plan()          # 30s short: hook cadence budget ~2 events
        plan["punchIns"] = punch_ins
        return plan

    def test_valid_punch_plus_ramp_pass(self) -> None:
        plan = self._plan([
            {"outStart": 2.0, "outEnd": 4.0, "zoom": 1.2},
            {"outStart": 8.0, "outEnd": 16.0,
             "ramp": {"direction": "in", "ratePctPerS": 0.8}}])
        self.assertEqual(self._errors(plan), [])

    def test_valid_bracket_passes(self) -> None:
        plan = self._plan([{"outStart": 10.0, "outEnd": 13.0, "zoom": 1.4,
                            "bracket": True, "holdS": 1.6}])
        self.assertEqual(self._errors(plan), [])

    def test_ramp_rate_out_of_band(self) -> None:
        plan = self._plan([{"outStart": 2.0, "outEnd": 6.0,
                            "ramp": {"direction": "in", "ratePctPerS": 5.0}}])
        self.assert_fires(plan, "ratePctPerS")

    def test_ramp_direction_invalid(self) -> None:
        plan = self._plan([{"outStart": 2.0, "outEnd": 6.0,
                            "ramp": {"direction": "sideways", "ratePctPerS": 0.8}}])
        self.assert_fires(plan, "ramp.direction")

    def test_bracket_zoom_over_step_max(self) -> None:
        plan = self._plan([{"outStart": 10.0, "outEnd": 13.0, "zoom": 1.6,
                            "bracket": True, "holdS": 1.5}])
        self.assert_fires(plan, "bracket zoom")

    def test_bracket_hold_must_leave_release_tail(self) -> None:
        plan = self._plan([{"outStart": 10.0, "outEnd": 12.0, "zoom": 1.3,
                            "bracket": True, "holdS": 2.0}])   # holdS == duration
        self.assert_fires(plan, "holdS")

    def test_bracket_cap_exceeded(self) -> None:
        plan = self._plan([
            {"outStart": s, "outEnd": s + 1.6, "zoom": 1.3,
             "bracket": True, "holdS": 1.0}
            for s in (1.0, 5.0, 9.0, 13.0)])              # 4 > cap of 3
        self.assert_fires(plan, "brackets exceeds")

    def test_short_cadence_exceeded(self) -> None:
        # R13 short budget = 10/min -> ~5 in a 30s clip; 6 trips it.
        plan = self._plan([
            {"outStart": float(s), "outEnd": float(s) + 1.0, "zoom": 1.1}
            for s in (1, 4, 7, 10, 13, 16)])
        self.assert_fires(plan, "R13 rhythmic cadence")

    def test_longform_body_cadence_exceeded(self) -> None:
        # Long-form body cap is 5/min: 8 semantic events in a 40s body (~3 allowed)
        # trips it. Tested directly — the manifest can't reach the 300s longform floor.
        rep = pl.Report()
        windows = [{"outStart": float(s), "outEnd": float(s) + 1.0}
                   for s in (63, 67, 71, 75, 79, 83, 87, 91)]
        plm._check_zoom_cadence(windows, 100.0, "longform", rep)
        self.assertTrue(any("hook/body" in e for e in rep.errors))

    def test_push_window_lint_clean(self) -> None:
        plan = self._plan([{"outStart": 2.0, "outEnd": 4.0, "zoom": 1.2,
                            "attackS": 0.5, "centerX": 0.5, "centerY": 0.37}])
        self.assertEqual(self._errors(plan), [])

    def test_attack_s_over_window_fails(self) -> None:
        plan = self._plan([{"outStart": 2.0, "outEnd": 4.0, "zoom": 1.2,
                            "attackS": 3.0}])            # attack 3s > 2s window
        self.assert_fires(plan, "attackS")

    def test_aliveness_creeps_exempt_from_cadence(self) -> None:
        # A continuous background aliveness layer does NOT count toward the semantic
        # cadence budget — 4 body creeps that would trip the cap stay lint-clean.
        rep = pl.Report()
        windows = [{"outStart": float(s), "outEnd": float(s) + 4.0,
                    "ramp": {"direction": "in", "ratePctPerS": 0.8},
                    "role": "aliveness"} for s in (65, 72, 79, 86)]
        plm._check_zoom_cadence(windows, 100.0, "longform", rep)
        self.assertEqual(rep.errors, [])


class ZoomProposerTests(unittest.TestCase):
    """MG-4 SEMANTIC (long-form) zoom proposer: thesis punches/brackets, boundary
    out, ramp, and the rhetorical-question thesis it keys on."""

    def _thesis(self, conf: str, idx: list[int], text: str) -> dict:
        return {"trigger": "thesis", "confidence": conf,
                "wordIndices": idx, "text": text}

    def test_high_thesis_brackets_medium_punches(self) -> None:
        words = _mid_sentence(("Where", 0.0, 0.3), ("are", 0.3, 0.5),
                              ("your", 0.5, 0.7), ("priorities?", 0.7, 1.0),
                              ("The", 5.0, 5.2), ("truth", 5.2, 5.5),
                              ("is", 5.5, 5.7), ("simple.", 5.7, 6.0))
        triggers = [self._thesis("high", [0, 1, 2, 3], "Where are your priorities?"),
                    self._thesis("medium", [4, 5, 6, 7], "The truth is simple.")]
        zoom = gpz.build_zoom_proposal(triggers, words, "longform", 30.0, [])
        by_kind = {c["kind"]: c for c in zoom["punchIns"]}
        self.assertIn("bracket", by_kind)
        self.assertIn("punch-in", by_kind)
        self.assertTrue(by_kind["bracket"]["needsOperator"])
        self.assertAlmostEqual(by_kind["bracket"]["outStart"], 0.0, places=2)
        self.assertAlmostEqual(by_kind["punch-in"]["outStart"], 5.0, places=2)

    def test_bracket_cap_in_proposer(self) -> None:
        words = _mid_sentence(*[(f"Q{i}?", i * 5.0, i * 5.0 + 0.4) for i in range(5)])
        triggers = [self._thesis("high", [i], f"Q{i}?") for i in range(5)]
        zoom = gpz.build_zoom_proposal(triggers, words, "longform", 40.0, [])
        brackets = [c for c in zoom["punchIns"] if c.get("bracket")]
        self.assertEqual(len(brackets), gpz._ZOOM["bracket_max_per_video"])

    def test_push_magnitude_scales_with_importance(self) -> None:
        # MEASURED_EDIT_GRAMMAR §1: push magnitude scales with the beat's importance
        # — a medium-confidence thesis pushes harder than a low-confidence one, and
        # both stay in the measured +7-16% band (not the old flat 1.21).
        words = _mid_sentence(("Big.", 5.0, 5.4), ("Small.", 15.0, 15.4))
        med = self._thesis("medium", [0], "Big.")
        lo = self._thesis("low", [1], "Small.")
        zoom = gpz.build_zoom_proposal([med, lo], words, "longform", 40.0, [])
        punches = {c["confidence"]: c["zoom"] for c in zoom["punchIns"]
                   if c["kind"] == "punch-in"}
        self.assertGreater(punches["medium"], punches["low"])
        self.assertEqual(punches["medium"], gpz._PROP["push_zoom_by_conf"]["medium"])
        self.assertTrue(all(1.05 <= z <= 1.16 for z in punches.values()), punches)

    def test_topic_boundary_becomes_punch_out(self) -> None:
        words = _mid_sentence(("Okay", 3.0, 3.3), ("so", 3.3, 3.6))
        triggers = [{"trigger": "topic-boundary", "confidence": "high",
                     "wordIndices": [0, 1], "text": "Okay so"}]
        zoom = gpz.build_zoom_proposal(triggers, words, "longform", 30.0, [])
        outs = [c for c in zoom["punchIns"] if c["kind"] == "punch-out"]
        self.assertEqual(len(outs), 1)
        self.assertEqual(outs[0]["ramp"]["direction"], "out")

    def test_long_uncut_stretch_gets_ramp(self) -> None:
        plan = {"cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 40.0,
                              "speed": 1.0}]}
        segs = ct.compile_plan(plan).segments
        zoom = gpz.build_zoom_proposal([], [], "longform", 40.0, segs)
        ramps = [c for c in zoom["punchIns"] if c["kind"] == "ramp"]
        self.assertEqual(len(ramps), 1)
        self.assertEqual(ramps[0]["ramp"]["direction"], "in")

    def test_ramp_carries_smooth_ease(self) -> None:
        # MOTION_GRAMMAR_STUDY §8: every animated ramp eases (smoothstep), never the
        # linear creep punch_in defaults to — the machine's lone ramp read mechanical.
        plan = {"cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 40.0,
                              "speed": 1.0}]}
        segs = ct.compile_plan(plan).segments
        zoom = gpz.build_zoom_proposal([], [], "longform", 40.0, segs)
        ramps = [c for c in zoom["punchIns"] if c["kind"] == "ramp"]
        self.assertTrue(ramps and all(c["ease"] == "smooth" for c in ramps))

    def test_lowered_floor_ramps_a_short_stretch(self) -> None:
        # ramp_min_stretch_s lowered 30→10: a 15s uncut stretch now earns an
        # aliveness ramp it would NOT have gotten at the old 30s floor.
        plan = {"cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 15.0,
                              "speed": 1.0}]}
        segs = ct.compile_plan(plan).segments
        zoom = gpz.build_zoom_proposal([], [], "longform", 15.0, segs)
        self.assertEqual(len([c for c in zoom["punchIns"] if c["kind"] == "ramp"]), 1)

    def test_face_center_recomposes_every_candidate(self) -> None:
        # A given face center makes every semantic candidate recompose toward it
        # (study §1/R16) instead of a fixed-center scale; none is left centered.
        words = _mid_sentence(("Where", 0.0, 0.3), ("are", 0.3, 0.5),
                              ("your", 0.5, 0.7), ("priorities?", 0.7, 1.0))
        triggers = [self._thesis("high", [0, 1, 2, 3], "Where are your priorities?")]
        zoom = gpz.build_zoom_proposal(triggers, words, "longform", 30.0, [],
                                       face_center=(0.4, 0.35))
        self.assertTrue(zoom["punchIns"])
        for c in zoom["punchIns"]:
            self.assertAlmostEqual(c["centerX"], 0.4, places=3)
            self.assertAlmostEqual(c["centerY"], 0.35, places=3)

    def test_no_face_center_leaves_crop_centered(self) -> None:
        # No face center → no centerX/centerY emitted (render falls back to 0.5/0.5).
        plan = {"cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 40.0,
                              "speed": 1.0}]}
        segs = ct.compile_plan(plan).segments
        zoom = gpz.build_zoom_proposal([], [], "longform", 40.0, segs)
        self.assertTrue(all("centerX" not in c for c in zoom["punchIns"]))

    def _one_long_seg(self):
        return ct.compile_plan({"cutTrack": [{"sourceId": "raw-1", "start": 0.0,
                                              "end": 30.0, "speed": 1.0}]}).segments

    def test_mid_shot_punch_becomes_eased_push(self) -> None:
        # A plain thesis punch landing MID-SHOT eases in (attackS), not a snap (G6).
        words = _mid_sentence(("The", 10.0, 10.2), ("truth", 10.2, 10.5),
                              ("is", 10.5, 10.7), ("simple.", 10.7, 11.0))
        triggers = [self._thesis("medium", [0, 1, 2, 3], "The truth is simple.")]
        zoom = gpz.build_zoom_proposal(triggers, words, "longform", 30.0,
                                       self._one_long_seg())
        punch = next(c for c in zoom["punchIns"] if c["kind"] == "punch-in")
        self.assertIn("attackS", punch)
        self.assertGreater(punch["attackS"], 0.0)

    def test_punch_on_a_cut_stays_a_hard_step(self) -> None:
        # A thesis beat AT a cut (t≈0, the segment open) stays a hard step — a step
        # reads as intentional at a cut (G6) — so no attackS.
        words = _mid_sentence(("The", 0.0, 0.2), ("truth", 0.2, 0.5),
                              ("is", 0.5, 0.7), ("simple.", 0.7, 1.0))
        triggers = [self._thesis("medium", [0, 1, 2, 3], "The truth is simple.")]
        zoom = gpz.build_zoom_proposal(triggers, words, "longform", 30.0,
                                       self._one_long_seg())
        punch = next(c for c in zoom["punchIns"] if c["kind"] == "punch-in")
        self.assertNotIn("attackS", punch)

    def test_creep_carpets_the_frozen_tail_after_a_punch(self) -> None:
        # v1 left a punch-carrying segment frozen after ~1.6s; now an aliveness creep
        # fills the tail, starting after the punch and ending at the segment's cut.
        words = _mid_sentence(("The", 2.0, 2.2), ("truth", 2.2, 2.5),
                              ("is", 2.5, 2.7), ("simple.", 2.7, 3.0))
        triggers = [self._thesis("medium", [0, 1, 2, 3], "The truth is simple.")]
        zoom = gpz.build_zoom_proposal(triggers, words, "longform", 30.0,
                                       self._one_long_seg())
        creeps = [c for c in zoom["punchIns"] if c.get("role") == "aliveness"]
        punch = next(c for c in zoom["punchIns"] if c["kind"] == "punch-in")
        self.assertEqual(len(creeps), 1)
        self.assertGreaterEqual(creeps[0]["outStart"], punch["outEnd"] - 1e-6)
        self.assertAlmostEqual(creeps[0]["outEnd"], 30.0, places=2)
        self.assertEqual(creeps[0]["ease"], "smooth")

    def test_creep_fills_head_and_gap_between_two_punches(self) -> None:
        # C0679 intro e2e fix: the carpet must fill the segment HEAD (before the
        # first punch) AND the gap BETWEEN two punches — not just the post-last-
        # punch tail. Two theses 25s apart in a 60s segment left ~44s frozen before.
        plan = {"cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 60.0,
                              "speed": 1.0}]}
        segs = ct.compile_plan(plan).segments
        words = _mid_sentence(("The", 25.0, 25.2), ("truth.", 25.2, 25.6),
                              ("Now", 50.0, 50.2), ("this.", 50.2, 50.6))
        triggers = [self._thesis("medium", [0, 1], "The truth."),
                    self._thesis("medium", [2, 3], "Now this.")]
        zoom = gpz.build_zoom_proposal(triggers, words, "longform", 60.0, segs)
        creeps = sorted((c for c in zoom["punchIns"] if c.get("role") == "aliveness"),
                        key=lambda c: c["outStart"])
        self.assertGreaterEqual(len(creeps), 2)               # head + middle gap
        self.assertAlmostEqual(creeps[0]["outStart"], 0.0, places=2)   # head filled
        # never frozen >20s: the union of every zoom leaves no gap past 20s.
        cur = worst = 0.0
        for s, e in sorted((c["outStart"], c["outEnd"]) for c in zoom["punchIns"]):
            worst = max(worst, s - cur); cur = max(cur, e)
        self.assertLess(max(worst, 60.0 - cur), 20.0)

    def test_rhetorical_question_detected_as_thesis(self) -> None:
        # The real gap: a rhetorical question carries no cue/absolute word, so the
        # question pass must surface it, bounded to just the question clause even
        # when the prior clause's copula ("...team is |") wasn't punctuated off.
        words = _mid_sentence(("my", 0.0, 0.2), ("team", 0.2, 0.5), ("is", 0.5, 0.7),
                              ("where", 0.9, 1.1), ("are", 1.1, 1.3),
                              ("your", 1.3, 1.5), ("priorities?", 1.5, 1.9))
        thesis = [c for c in mt.detect_all(words) if c["trigger"] == "thesis"]
        self.assertEqual(len(thesis), 1)
        self.assertEqual(thesis[0]["confidence"], "high")
        self.assertEqual(thesis[0]["text"], "where are your priorities?")


class ZoomProposerShortsTests(unittest.TestCase):
    """MG-4 RHYTHMIC (shorts) zoom proposer — R13: zoom IS the cut."""

    def _segments(self, n: int, seg_s: float) -> list:
        plan = {"cutTrack": [{"sourceId": "raw-1", "start": i * seg_s * 2,
                              "end": i * seg_s * 2 + seg_s, "speed": 1.0}
                             for i in range(n)]}
        return ct.compile_plan(plan).segments

    def test_alternates_a_punch_across_cuts(self) -> None:
        # 4 cut shots -> odd shots (1, 3) punch tight; even hold the wide base, so
        # every cut is a reframe. No brackets/ramps (demoted in shorts).
        segs = self._segments(4, 5.0)                 # out shots 0-5,5-10,10-15,15-20
        zoom = gpz.build_zoom_proposal([], [], "short", 20.0, segs)
        pins = zoom["punchIns"]
        self.assertEqual(zoom["meta"]["grammar"], "rhythmic")
        self.assertEqual([round(c["outStart"], 1) for c in pins], [5.0, 15.0])
        self.assertTrue(all(c["kind"] == "punch-in"
                            and c["trigger"] == "cut-alternation" for c in pins))
        self.assertTrue(all(c["zoom"] == gpz._ZOOM["by_mode"]["short"]["step_median"]
                            for c in pins))
        self.assertEqual(zoom["meta"]["brackets"], 0)

    def test_rhythmic_respects_cadence_cap(self) -> None:
        # 10 fast shots (out_dur 10s) -> 5 odd punches, but the 10/min budget caps
        # it to ~2 so the proposal stays lint-clean.
        segs = self._segments(10, 1.0)                # 10 shots, out_dur 10s
        zoom = gpz.build_zoom_proposal([], [], "short", 10.0, segs)
        allowed = max(1, round(10 * 10.0 / 60.0))
        self.assertLessEqual(len(zoom["punchIns"]), allowed)
        self.assertTrue(all(c["trigger"] == "cut-alternation"
                            for c in zoom["punchIns"]))

    def test_shorts_propose_no_semantic_moves(self) -> None:
        # Even with strong thesis triggers, a short gets the cut-alternation grammar
        # (no thesis brackets — those are long-form only, R13).
        words = _mid_sentence(("Where", 0.0, 0.3), ("now?", 0.3, 0.6))
        triggers = [{"trigger": "thesis", "confidence": "high",
                     "wordIndices": [0, 1], "text": "Where now?"}]
        segs = self._segments(3, 4.0)
        zoom = gpz.build_zoom_proposal(triggers, words, "short", 12.0, segs)
        self.assertTrue(all(c["trigger"] == "cut-alternation"
                            for c in zoom["punchIns"]))
        self.assertEqual(zoom["meta"]["brackets"], 0)

if __name__ == "__main__":
    unittest.main(verbosity=2)
