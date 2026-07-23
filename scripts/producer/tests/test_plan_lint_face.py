#!/usr/bin/env python3
"""plan_lint_face tests — the face-aware placement lint pack (v3 item #6).

One focused test class per check (a-d) with synthetic plans, plus the faceCx
stamp helper, the plan-side contentBBox WARN (e), and the plan_lint.lint()
dispatch wiring. All findings route through the gate-policy layer, so the
routed severities (WARN → warnings, FAIL → errors) are asserted too.
"""

from __future__ import annotations

import copy
import unittest

from _common import *  # noqa: F401,F403
from _common import MANIFEST, good_plan

import gate_policy as gpol
import plan_lint as pl
import plan_lint_face as plf


def _short_plan(**overrides) -> dict:
    """A lint-clean short plan, mutated per test (deep copy of the fixture)."""
    plan = copy.deepcopy(good_plan())
    plan.update(overrides)
    return plan


class CaptionFaceBandTests(unittest.TestCase):
    """(a) karaoke/line band vs the faceBBoxNorm bottom edge."""

    def test_face_into_band_warns_with_overlap_px(self) -> None:
        # chin at (0.35 + 0.28) * 1920 = 1209.6px → 59.6px into [1150, 1340].
        plan = _short_plan(faceBBoxNorm=[0.25, 0.35, 0.5, 0.28])
        verdicts = plf.check_caption_band(plan)
        self.assertEqual(len(verdicts), 1, verdicts)
        v = verdicts[0]
        self.assertEqual((v.gate, v.severity, v.lane),
                         ("caption_face_band", "WARN", "captions"))
        self.assertIn("60px into the karaoke caption band", v.evidence)

    def test_clear_face_and_face_relative_styles_silent(self) -> None:
        clear = _short_plan(faceBBoxNorm=[0.25, 0.1, 0.5, 0.3])  # chin at 768px
        self.assertEqual(plf.check_caption_band(clear), [])
        exempt = _short_plan(faceBBoxNorm=[0.25, 0.35, 0.5, 0.28])
        exempt["captions"]["style"] = "minimal"                  # face-aware
        self.assertEqual(plf.check_caption_band(exempt), [])
        off = _short_plan(faceBBoxNorm=[0.25, 0.35, 0.5, 0.28])
        off["captions"]["burn"] = False                          # not burned
        self.assertEqual(plf.check_caption_band(off), [])

    def test_band_y_offset_shifts_the_band_up(self) -> None:
        plan = _short_plan(faceBBoxNorm=[0.25, 0.35, 0.5, 0.28])
        plan["captions"]["bandYOffsetPx"] = 100    # band top 1150 → 1050
        (v,) = plf.check_caption_band(plan)
        self.assertIn("160px into the karaoke caption band [1050,1240]",
                      v.evidence)

    def test_missing_face_box_is_skip_with_evidence(self) -> None:
        (v,) = plf.check_caption_band(_short_plan())
        self.assertEqual(v.severity, "SKIP")
        self.assertIn("faceBBoxNorm is missing", v.evidence)
        # Routed through the policy table it lands as a labeled warning.
        out = gpol.to_gate_json([v], {"mode": "short"})
        self.assertTrue(out["ok"])
        self.assertIn("SKIP", out["warnings"][0])


class HookCardFaceTests(unittest.TestCase):
    """(b) expanded face box vs the fixed 250-560 hook band."""

    def test_high_face_overlapping_band_warns_per_card(self) -> None:
        # Face y0=96px, chin=480px → expanded box reaches into [250, 560].
        plan = _short_plan(faceBBoxNorm=[0.3, 0.05, 0.4, 0.2])
        verdicts = plf.check_hook_cards(plan)
        self.assertEqual(len(verdicts), 1, verdicts)  # one per card window
        v = verdicts[0]
        self.assertEqual((v.gate, v.severity), ("hook_card_face", "WARN"))
        self.assertIn("titleCards[0] window [0.0,2.5]", v.evidence)
        self.assertIn("overlaps the fixed hook band y [250,560] by 230px",
                      v.evidence)

    def test_low_face_clear_of_band_silent(self) -> None:
        # Face y0=1056px — expanded top ≈ 902px, far below the 560px band end.
        plan = _short_plan(faceBBoxNorm=[0.3, 0.55, 0.4, 0.2])
        self.assertEqual(plf.check_hook_cards(plan), [])

    def test_cards_without_face_box_skip_with_evidence(self) -> None:
        (v,) = plf.check_hook_cards(_short_plan())
        self.assertEqual((v.gate, v.severity), ("hook_card_face", "SKIP"))
        self.assertIn("1 titleCards", v.evidence)

    def test_no_cards_no_verdicts(self) -> None:
        plan = _short_plan(faceBBoxNorm=[0.3, 0.05, 0.4, 0.2], titleCards=[])
        self.assertEqual(plf.check_hook_cards(plan), [])


class PipHoleFaceCxTests(unittest.TestCase):
    """(c) live hole-comps need a measured faceCx (renderer defaults 0.5)."""

    def _longform(self, entry: dict) -> dict:
        plan = _short_plan(graphicsTrack=[entry])
        plan["target"]["mode"] = "longform"
        return plan

    def test_live_hole_without_face_cx_warns(self) -> None:
        entry = {"outStart": 10.0, "outEnd": 14.0, "kind": "nateherk-takeover",
                 "anchor": "own-screen", "spec": {}, "reason": "credibility"}
        (v,) = plf.check_pip_hole_face_cx(self._longform(entry))
        self.assertEqual((v.gate, v.severity), ("pip_hole_face_cx", "WARN"))
        self.assertIn("defaults the face crop to 0.5", v.evidence)
        self.assertIn("stamp_face_cx", v.evidence)

    def test_measured_face_cx_and_inactive_hole_silent(self) -> None:
        stamped = {"outStart": 10.0, "outEnd": 14.0, "kind": "nateherk-takeover",
                   "anchor": "own-screen", "spec": {}, "faceCx": 0.62}
        self.assertEqual(plf.check_pip_hole_face_cx(self._longform(stamped)), [])
        # A registered kind whose hole is NOT live (no presenterFrame opt-in)
        # never fills the hole, so faceCx is irrelevant.
        opaque = {"outStart": 10.0, "outEnd": 14.0, "kind": "nateherk-scoreboard",
                  "anchor": "free-band", "spec": {}}
        self.assertEqual(plf.check_pip_hole_face_cx(self._longform(opaque)), [])

    def test_stamp_face_cx_writes_the_entry_key(self) -> None:
        plan = _short_plan(faceBBoxNorm=[0.2, 0.1, 0.4, 0.3])
        entry = {"kind": "nateherk-takeover", "spec": {}}
        self.assertEqual(plf.stamp_face_cx(entry, plan), 0.4)  # 0.2 + 0.4/2
        self.assertEqual(entry["faceCx"], 0.4)                 # the renderer's key
        own = {"kind": "nateherk-takeover", "faceBBoxNorm": [0.5, 0.1, 0.3, 0.3]}
        self.assertEqual(plf.stamp_face_cx(own, plan), 0.65)   # entry bbox wins

    def test_stamp_face_cx_fails_closed_without_a_face_box(self) -> None:
        with self.assertRaises(ValueError):
            plf.stamp_face_cx({"kind": "nateherk-takeover"}, _short_plan())


class GraphicBrollOverlapTests(unittest.TestCase):
    """(d) face-anchored graphics over b-roll = the face is not on screen."""

    def _entry(self, anchor: str, s: float, e: float) -> dict:
        return {"outStart": s, "outEnd": e, "kind": "chip-row", "anchor": anchor,
                "spec": {}, "reason": "x", "faceBBoxNorm": [0.3, 0.2, 0.4, 0.3]}

    def test_face_anchor_over_broll_fails_and_blocks(self) -> None:
        # good_plan's brollTrack covers [9.0, 10.5]; headroom is face-anchored.
        plan = _short_plan(graphicsTrack=[self._entry("headroom", 9.5, 11.0)])
        (v,) = plf.check_graphic_broll_overlap(plan)
        self.assertEqual((v.gate, v.severity),
                         ("graphic_broll_face_overlap", "FAIL"))
        self.assertIn("overlaps brollTrack[0] [9,10.5]", v.evidence)
        self.assertEqual(gpol.resolve(v, {"mode": "short"}), "block")

    def test_non_face_anchor_and_disjoint_windows_silent(self) -> None:
        free = _short_plan(graphicsTrack=[self._entry("free-band", 9.5, 11.0)])
        self.assertEqual(plf.check_graphic_broll_overlap(free), [])
        apart = _short_plan(graphicsTrack=[self._entry("headroom", 12.0, 14.0)])
        self.assertEqual(plf.check_graphic_broll_overlap(apart), [])


class PlacementContentBBoxTests(unittest.TestCase):
    """(e, plan side) placed shorts entries without a measured contentBBox."""

    def _placed(self, **extra) -> dict:
        entry = {"outStart": 12.0, "outEnd": 15.0, "kind": "chip-row",
                 "anchor": "free-band", "spec": {}, "reason": "x",
                 "placement": {"x": 120, "y": 300}, **extra}
        return _short_plan(graphicsTrack=[entry])

    def test_placement_without_content_bbox_warns(self) -> None:
        (v,) = plf.check_placement_content_bbox(self._placed())
        self.assertEqual((v.gate, v.severity), ("placement_content_bbox", "WARN"))
        self.assertIn("degenerates to the bare point", v.evidence)

    def test_stamped_bbox_silent(self) -> None:
        plan = self._placed(contentBBox=[100, 250, 800, 600])
        self.assertEqual(plf.check_placement_content_bbox(plan), [])


class LintDispatchTests(unittest.TestCase):
    """plan_lint.lint() actually runs the pack and routes severities."""

    def test_lint_routes_warn_and_fail_through_gate_policy(self) -> None:
        plan = _short_plan(faceBBoxNorm=[0.25, 0.35, 0.5, 0.28])
        plan["graphicsTrack"] = [{
            "outStart": 9.5, "outEnd": 11.0, "kind": "chip-row",
            "anchor": "headroom", "spec": {}, "reason": "x",
            "faceBBoxNorm": [0.25, 0.35, 0.5, 0.28],
        }]
        rep = pl.lint(plan, MANIFEST)
        self.assertTrue(any("caption_face_band:" in w for w in rep.warnings),
                        rep.warnings)
        self.assertTrue(any("graphic_broll_face_overlap:" in e
                            for e in rep.errors), rep.errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
