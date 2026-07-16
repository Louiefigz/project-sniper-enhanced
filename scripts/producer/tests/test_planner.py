"""planner tests (split from selftest.py)."""
import unittest

from _common import *  # noqa: F401,F403


class AnchorOffsetTests(unittest.TestCase):
    """Face-relative overlay offsets (R3/R4): deviation math, guards, failures."""

    def test_non_face_anchor_is_zero(self) -> None:
        self.assertEqual(ga.resolve_offset({"anchor": "free-band"}), (0, 0))
        self.assertEqual(ga.resolve_offset({"anchor": "focus-shift"}), (0, 0))

    def test_nominal_face_gives_no_offset(self) -> None:
        # A comp authored for the nominal head needs ~no translation there.
        e = {"anchor": "headroom", "faceBBoxNorm": list(ga._NOMINAL_FACE)}
        self.assertEqual(ga.resolve_offset(e), (0, 0))

    def test_headroom_tracks_face_deviation(self) -> None:
        # A lower + right-of-center face pushes the headroom widget down + right.
        e = {"anchor": "headroom", "faceBBoxNorm": [0.55, 0.35, 0.28, 0.30]}
        dx, dy = ga.resolve_offset(e)
        self.assertGreater(dx, 0)
        self.assertGreater(dy, 0)

    def test_offset_capped_for_pathological_bbox(self) -> None:
        # A face jammed in the corner can't fling the overlay off-canvas.
        e = {"anchor": "chest", "faceBBoxNorm": [0.0, 0.0, 0.05, 0.05]}
        dx, dy = ga.resolve_offset(e)
        self.assertLessEqual(abs(dx), ga._OFFSET_CAP_X)
        self.assertLessEqual(abs(dy), ga._OFFSET_CAP_Y)

    def test_missing_bbox_raises(self) -> None:
        # A face anchor without a bbox must fail loud, never render at (0,0).
        self.assertRaises(ValueError, ga.resolve_offset, {"anchor": "beside-face"})
        self.assertRaises(ValueError, ga.resolve_offset,
                          {"anchor": "headroom", "faceBBoxNorm": [0.1, 0.1, 0.1]})


class FreeSpacePlacementTests(unittest.TestCase):
    """Placement v2: free-space region geometry, scoring, fallback, clamps.

    The pure math (no cv2) — the fix for graphics-landing-on-the-face. Numbers use
    the real car3 face box ([0.35,0.2534,...] → px) so a regression shows up as a
    graphic drifting back onto the head.
    """

    CANVAS = (1080, 1920)
    FACE = (378.0, 486.5, 370.5, 370.6)     # car3 face box in px (high + large)

    def test_expand_face_lifts_top_for_hair(self) -> None:
        # The hair sits ABOVE the Haar box: top grows by 40% of face height.
        x0, y0, x1, y1 = fs.expand_face(self.FACE)
        self.assertAlmostEqual(y0, 486.5 - 0.40 * 370.6, places=1)
        self.assertAlmostEqual(x0, 378.0 - 0.25 * 370.5, places=1)
        self.assertEqual(y1, 486.5 + 370.6)              # bottom = chin, no growth

    def test_body_column_spans_chin_to_bottom(self) -> None:
        x0, y0, x1, y1 = fs.body_column(self.FACE, self.CANVAS[1])
        self.assertEqual(y0, 486.5 + 370.6)              # starts at the chin
        self.assertEqual(y1, 1920)                       # runs to the frame bottom
        self.assertAlmostEqual(x1 - x0, 370.5 * 2.2, places=1)

    def test_expand_face_uses_measured_hair_top(self) -> None:
        # A MEASURED hair top replaces the 40% guess, clamped to [0, face_top].
        self.assertEqual(fs.expand_face(self.FACE, hair_top=300.0)[1], 300.0)
        self.assertEqual(fs.expand_face(self.FACE, hair_top=-50.0)[1], 0.0)
        self.assertEqual(fs.expand_face(self.FACE, hair_top=9999.0)[1], self.FACE[1])
        # No measurement -> the 40%-of-face-height fallback.
        self.assertAlmostEqual(fs.expand_face(self.FACE)[1], 486.5 - 0.40 * 370.6,
                               places=1)

    def test_measured_hair_top_drives_headroom_and_flag(self) -> None:
        measured = fs.assemble_free_map(self.FACE, set(), self.CANVAS, hair_top=300.0)
        self.assertTrue(measured.hair_measured)
        self.assertEqual(measured.region("headroom").y1, 300)   # band bottom = hair
        guessed = fs.assemble_free_map(self.FACE, set(), self.CANVAS)
        self.assertFalse(guessed.hair_measured)

    def test_headroom_is_top_region_on_clear_frame(self) -> None:
        # No busy background -> the empty headliner scores highest.
        fmap = fs.assemble_free_map(self.FACE, set(), self.CANVAS)
        self.assertEqual(fmap.regions[0].name, "headroom")
        self.assertGreater(fmap.region("headroom").emptiness, 0.6)
        # Headroom's bottom is the hair line (expanded face top), never the face.
        self.assertEqual(fmap.region("headroom").y1, int(fmap.expanded_face[1]))

    def test_narrow_side_band_is_dropped(self) -> None:
        # car3's face crowds the right edge (only ~89px) -> below min_band -> gone.
        fmap = fs.assemble_free_map(self.FACE, set(), self.CANVAS)
        self.assertIsNone(fmap.region("right-of-face"))
        self.assertIsNotNone(fmap.region("left-of-face"))

    def test_place_content_centers_and_clears_face(self) -> None:
        # A graphic centered into headroom must sit fully above the expanded face.
        fmap = fs.assemble_free_map(self.FACE, set(), self.CANVAS)
        content = (100, 700, 900, 900)               # 800x200, center (500,800)
        region = fmap.region("headroom")
        dx, dy = fs.place_content(content, region)
        placed_bottom = content[3] + dy
        self.assertLessEqual(placed_bottom, fmap.expanded_face[1])   # clears hair
        self.assertGreaterEqual(content[1] + dy, region.y0)          # inside band

    def test_place_content_symmetric_overflow_when_wider_than_band(self) -> None:
        # A footprint wider than the band (drop-shadow) centers, doesn't shove off.
        fmap = fs.assemble_free_map(self.FACE, set(), self.CANVAS)
        content = (26, 751, 964, 994)                # 938 wide > 870 band
        region = fmap.region("headroom")
        dx, _dy = fs.place_content(content, region)
        placed_cx = (content[0] + content[2]) / 2 + dx
        self.assertAlmostEqual(placed_cx, region.center[0], delta=1)  # band midpoint

    def test_choose_region_prefers_anchor_region(self) -> None:
        fmap = fs.assemble_free_map(self.FACE, set(), self.CANVAS)
        region, fallback = ga._choose_region(fmap, "headroom", (100, 700, 900, 900))
        self.assertEqual(region.name, "headroom")
        self.assertFalse(fallback)

    def test_choose_region_falls_back_when_preferred_busy(self) -> None:
        # Flood the headroom band with busy cells -> its emptiness drops below the
        # prefer threshold -> placement falls back to a feasible region (logged).
        busy = {(r, c) for r in range(3) for c in range(11)}   # rows/cols over headroom
        fmap = fs.assemble_free_map(self.FACE, busy, self.CANVAS)
        self.assertLess(fmap.region("headroom").emptiness,
                        fs.FREE_SPACE["prefer_emptiness"])
        region, fallback = ga._choose_region(fmap, "headroom", (100, 900, 900, 1100))
        self.assertTrue(fallback)
        self.assertNotEqual(region.name, "headroom")

    def test_choose_region_none_when_nothing_fits(self) -> None:
        # A graphic taller than every band can't be placed -> (None, True).
        fmap = fs.assemble_free_map(self.FACE, set(), self.CANVAS)
        giant = (0, 0, 1000, 1900)
        region, fallback = ga._choose_region(fmap, "headroom", giant)
        self.assertIsNone(region)
        self.assertTrue(fallback)

    def test_beside_face_resolves_to_a_side_band(self) -> None:
        fmap = fs.assemble_free_map(self.FACE, set(), self.CANVAS)
        region, _fb = ga._choose_region(fmap, "beside-face", (60, 500, 210, 800))
        self.assertIn(region.name, ("left-of-face", "right-of-face"))

    def test_caption_band_drops_when_body_high(self) -> None:
        # car3: chin at ~857 (above mid-frame) -> captions recommended LOWER.
        fmap = fs.assemble_free_map(self.FACE, set(), self.CANVAS)
        band = fs.suggest_caption_band(fmap)
        self.assertIsNotNone(band)
        self.assertGreater(band[0], 1000)
        self.assertLessEqual(band[1], self.CANVAS[1] - fs.SAFE_BOX["bottom"])

    def test_caption_band_none_when_face_low(self) -> None:
        # A small, low face leaves the mid-frame clear -> keep the default band.
        low_face = (440.0, 1200.0, 200.0, 200.0)
        fmap = fs.assemble_free_map(low_face, set(), self.CANVAS)
        self.assertIsNone(fs.suggest_caption_band(fmap))


class PlannerRulesTests(unittest.TestCase):
    """MG-4 trigger→template mapping + R12 legality (graphics_planner_rules)."""

    def test_r12_blocklist(self) -> None:
        self.assertTrue(gpr.is_generic_entity("AI"))
        self.assertTrue(gpr.is_generic_entity("SaaS"))
        self.assertTrue(gpr.is_generic_entity("software"))
        self.assertFalse(gpr.is_generic_entity("Codex"))
        self.assertFalse(gpr.is_generic_entity("Eleven Labs"))

    def test_classify_entity(self) -> None:
        # Specific + cached mark -> icon-badge; specific w/o mark -> chip-row;
        # generic -> reject (R12 rules 1/2/3).
        self.assertEqual(gpr.classify_entity("Codex"), ("icon-badge", "codex.svg"))
        self.assertEqual(gpr.classify_entity("HeyGen"), ("chip-row", None))
        self.assertEqual(gpr.classify_entity("AI"), ("reject", None))

    def test_resolve_icon_is_local_only(self) -> None:
        self.assertEqual(gpr.resolve_icon("gemini"), "gemini.svg")
        self.assertIsNone(gpr.resolve_icon("no-such-brand-xyz"))

    def test_template_for_is_mode_aware(self) -> None:
        self.assertEqual(gpr.template_for("number", "50 dollars", "short")[0],
                         "stat-card")
        self.assertEqual(gpr.template_for("enumeration", "two years", "short")[0],
                         "stat-card")            # measure noun -> quantity
        self.assertEqual(gpr.template_for("enumeration", "three things", "short")[0],
                         "list-build")
        self.assertEqual(gpr.template_for("enumeration", "three things", "longform")[0],
                         "glass-rail")
        self.assertEqual(gpr.template_for("contrast", "x", "short")[0], "versus-split")
        self.assertEqual(gpr.template_for("thesis", "x", "short")[0], "kinetic-quote")
        self.assertEqual(gpr.template_for("topic-boundary", "okay so", "short")[0],
                         "section-marker")          # headroom header, not a wipe
        self.assertEqual(gpr.template_for("topic-boundary", "okay so", "longform")[0],
                         "glass-takeover-bg")

    def test_anchor_from_visual_state(self) -> None:
        # Talking-head: compact graphics ride the headroom; screen-share forces a
        # cutaway (own-screen) + operator flag; takeover kinds are own-screen.
        self.assertEqual(gpr.anchor_for("icon-badge", None, "short"),
                         ("headroom", False))
        self.assertEqual(gpr.anchor_for("icon-badge", "screen-share", "short"),
                         ("own-screen", True))
        self.assertEqual(gpr.anchor_for("versus-split", "talking-head", "short"),
                         ("free-band", False))
        self.assertEqual(gpr.anchor_for("glass-takeover-bg", None, "longform"),
                         ("own-screen", True))

    def test_apply_corrections(self) -> None:
        self.assertEqual(gpr.apply_corrections("Hagen", {"Hagen": "HeyGen"}),
                         "HeyGen")


class PlannerDensityTests(unittest.TestCase):
    """MG-4 density + doctrine trim (graphics_planner_density)."""

    def test_overlap_keeps_the_stronger(self) -> None:
        strong = _cand(0.0, 3.0, "high")
        weak = _cand(1.0, 4.0, "medium")
        accepted, rejected = gpd.trim([weak, strong], [])
        self.assertEqual([c["confidence"] for c in accepted], ["high"])
        self.assertTrue(any("overlaps" in r["reason"] for r in rejected))

    def test_one_mark_once(self) -> None:
        # Same mark within the window -> the later graphic is dropped (R12);
        # far enough apart -> both survive.
        a = _cand(0.0, 2.0, marks=["codex.svg"])
        b = _cand(5.0, 7.0, marks=["codex.svg"])
        far = _cand(20.0, 22.0, marks=["codex.svg"])
        accepted, rejected = gpd.trim([a, b, far], [])
        self.assertEqual(len(accepted), 2)
        self.assertTrue(any("one-mark-once" in r["reason"] for r in rejected))

    def test_zone_budget(self) -> None:
        zones = [{"outStart": 0.0, "outEnd": 10.0, "budget": "low"}]  # ~1/10s
        accepted, rejected = gpd.trim([_cand(0.0, 2.0), _cand(5.0, 7.0)], zones)
        self.assertEqual(len(accepted), 1)
        self.assertTrue(any("budget" in r["reason"] for r in rejected))

    def test_treatment_map_shapes(self) -> None:
        short = gpd.suggest_treatment_map("short", 40.0, lambda t: (None, None))
        self.assertEqual(len(short), 1)
        self.assertEqual(short[0]["treatment"], "kinetic")
        longform = gpd.suggest_treatment_map("longform", 800.0,
                                             lambda t: (None, None))
        self.assertEqual(len(longform), 2)              # intro + body
        self.assertEqual(longform[0]["budget"], "high")
        self.assertEqual(longform[1]["budget"], "low")


class PlannerAssembleTests(unittest.TestCase):
    """MG-4 end-to-end assembly: detect -> map -> group (graphics_planner)."""

    def _assemble(self, words: list[dict], mode: str = "short") -> tuple:
        return gp.assemble(words, mode, 10.0, {}, lambda t: (None, None), 1.5)

    def test_adjacent_entities_group_into_one_icon_badge(self) -> None:
        words = _mid_sentence(("I", 0.0, 0.2), ("use", 0.3, 0.5),
                              ("Codex", 0.6, 0.9), ("and", 1.0, 1.1),
                              ("Gemini", 1.2, 1.6), ("daily.", 1.7, 2.0))
        cands, _ = self._assemble(words)
        badges = [c for c in cands if c["kind"] == "icon-badge"]
        self.assertEqual(len(badges), 1)                # folded, not two graphics
        self.assertIn("icon1", badges[0]["spec"])
        self.assertIn("icon2", badges[0]["spec"])

    def test_generic_entity_is_rejected_not_proposed(self) -> None:
        words = _mid_sentence(("We", 0.0, 0.2), ("run", 0.3, 0.5),
                              ("AI", 0.6, 0.9), ("models.", 1.0, 1.3))
        cands, rejected = self._assemble(words)
        self.assertFalse(any(c["kind"] in ("icon-badge", "chip-row") for c in cands))
        self.assertTrue(any("AI" in r["evidence"] and "generic" in r["reason"]
                            for r in rejected))

    def test_number_maps_to_stat_card(self) -> None:
        words = _mid_sentence(("It", 0.0, 0.2), ("costs", 0.3, 0.5),
                              ("50", 0.6, 0.8), ("dollars.", 0.9, 1.2))
        cands, _ = self._assemble(words)
        self.assertTrue(any(c["kind"] == "stat-card" for c in cands))

if __name__ == "__main__":
    unittest.main(verbosity=2)
