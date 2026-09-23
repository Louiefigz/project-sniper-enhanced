#!/usr/bin/env python3
"""MODULE comp-grammar pack tests (MODULE_STUDY.md §5 items 1-3).

Item 1 — statement-card 'module' variant (eyebrow-first + two-line accent
headline + opacity-first ramps) behind new tokens; item 2 — exit grammar
(spec.exit 'blur-recede' + statements[] replace) with its lint; item 3 —
skeletonFirst() helper + evidence-ribbon slots. Contract surface only — the
renders are exercised out-of-suite (same doctrine as the punch pack tests).
Every default keeps the pre-pack behavior byte-identical (additive law).
"""
import unittest
from pathlib import Path

from _common import *  # noqa: F401,F403

_REPO = Path(__file__).resolve().parents[3]           # PROJECT_SNIPER
_MOTION = _REPO / "templates" / "motion"
_COMPS = _MOTION / "compositions"


class ModuleTokensTests(unittest.TestCase):
    """The §3 rank 2-4 + T-D tokens exist in BOTH twins and agree."""

    def test_motion_tokens_js_carries_the_pack(self) -> None:
        js = (_MOTION / "motion-tokens.js").read_text(encoding="utf-8")
        self.assertIn("TEXT_RAMP_S = 0.2", js)          # rank 4: 120-250ms ramp
        self.assertIn("EYEBROW_LEAD_S = 0.25", js)      # rank 3: band 0.08-0.5
        self.assertIn("SKELETON_GAP_S = 0.35", js)      # rank 2
        self.assertIn("EXIT_BLUR_S = 0.15", js)         # T-D: ~150ms
        for helper in ("textRamp", "skeletonFirst", "blurRecede"):
            self.assertIn(helper, js)
        # Punch pack law untouched (different lane).
        self.assertIn("POP_IN_S = 2 / FPS", js)
        self.assertIn("instantOut", js)

    def test_tokens_css_carries_the_twins(self) -> None:
        css = (_MOTION / "tokens.css").read_text(encoding="utf-8")
        for tok in ("--eyebrow-font", "--eyebrow-dot", "--eyebrow-lead: 0.25s",
                    "--text-ramp-dur: 0.2s", "--skeleton-gap: 0.35s",
                    "--exit-blur-dur: 0.15s"):
            self.assertIn(tok, css)
        self.assertIn("--pop-in-dur", css)              # punch twin untouched

    def test_python_twin_matches(self) -> None:
        self.assertEqual(eoc.EXIT_BLUR_S, 0.15)
        self.assertIn("blur-recede", eoc.EXITS)


class ModuleCompContractTests(unittest.TestCase):
    """Retired module opt-ins cannot make house HTML executable again."""

    def test_all_prior_variants_are_rejected(self) -> None:
        from graphics.template_contract import entry_errors
        for kind in ("statement-card", "glass-rail", "stat-card", "list-build"):
            for spec in ({"variant": "classic"}, {"variant": "module"}, {"build": "pop"}, {"build": "skeleton"}):
                row = {"kind": kind, "outStart": 0, "outEnd": 4, "spec": spec}
                self.assertTrue(any("retired" in error for error in entry_errors(row)))
                self.assertFalse((_COMPS / (kind + ".html")).exists())


class ExitGrammarTests(unittest.TestCase):
    """spec.exit vocabulary + the T-D blur-recede-vs-clamp rule (item 2)."""

    def _entry(self, start: float, end: float, exit_kind: str | None,
               on_cut: bool = False) -> dict:
        spec = {"text": "x"}
        if exit_kind is not None:
            spec["exit"] = exit_kind
        return {"outStart": start, "outEnd": end, "kind": "statement-card",
                "anchor": "own-screen", "reason": "beat", "spec": spec,
                "exitOnCut": on_cut}

    def test_absent_exit_is_untouched(self) -> None:
        errs, warns = eoc.exit_grammar_issues(
            self._entry(0.0, 4.0, None), "g[0]", [2.0], 1.0)
        self.assertEqual((errs, warns), ([], []))

    def test_unknown_exit_errors(self) -> None:
        errs, _ = eoc.exit_grammar_issues(
            self._entry(0.0, 4.0, "poof"), "g[0]", [], 1.0)
        self.assertTrue(errs and "spec.exit" in errs[0], errs)

    def test_hold_and_fade_pass(self) -> None:
        for kind in ("hold", "fade"):
            errs, warns = eoc.exit_grammar_issues(
                self._entry(0.0, 4.0, kind), "g[0]", [0.05], 1.0)
            self.assertEqual((errs, warns), ([], []), kind)

    def test_blur_cannot_complete_before_clamp_is_error(self) -> None:
        # exitOnCut clamps 2.95->9.0 to the 3.0 seam: 0.05s < EXIT_BLUR_S.
        errs, _ = eoc.exit_grammar_issues(
            self._entry(2.95, 9.0, "blur-recede", on_cut=True),
            "g[0]", [3.0], 1.0)
        self.assertTrue(errs and "cannot complete" in errs[0], errs)

    def test_blur_eating_hold_floor_is_warning(self) -> None:
        # Clamped to 1.0s: blur fits (>=0.15) but content hold 0.85 < 1.0.
        errs, warns = eoc.exit_grammar_issues(
            self._entry(2.0, 9.0, "blur-recede", on_cut=True),
            "g[0]", [3.0], 1.0)
        self.assertEqual(errs, [])
        self.assertTrue(warns and "hold floor" in warns[0], warns)

    def test_healthy_blur_window_is_clean(self) -> None:
        errs, warns = eoc.exit_grammar_issues(
            self._entry(0.0, 9.0, "blur-recede", on_cut=True),
            "g[0]", [9.0], 1.0)
        self.assertEqual((errs, warns), ([], []))


class ExitGrammarLintWireTests(unittest.TestCase):
    """Current source admission runs before an old template's exit grammar."""

    def test_retired_statement_cannot_pass_with_any_exit(self) -> None:
        for exit_kind in ("hold", "fade", "blur-recede", "poof"):
            plan = good_plan()
            plan["graphicsTrack"] = [{"kind": "statement-card", "outStart": 2.95,
                "outEnd": 11.9, "spec": {"text": "TEST", "exit": exit_kind}, "exitOnCut": True}]
            self.assertTrue(any("retired" in error for error in pl.lint(plan, MANIFEST).errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
