#!/usr/bin/env python3
"""NATEHERK comp-grammar pack tests (NATEHERK_STUDY.md §5 items 1-3).

Item 1 — statement-card 'nateherk' variant (eyebrow-first + two-line accent
headline + opacity-first ramps) behind new tokens; item 2 — exit grammar
(spec.exit 'blur-recede' + statements[] replace) with its lint; item 3 —
skeletonFirst() helper + evidence-ribbon slots. Contract surface only — the
renders are exercised out-of-suite (same doctrine as the jaden pack tests).
Every default keeps the pre-pack behavior byte-identical (additive law).
"""
import unittest
from pathlib import Path

from _common import *  # noqa: F401,F403

_REPO = Path(__file__).resolve().parents[3]           # PROJECT_SNIPER
_MOTION = _REPO / "templates" / "motion"
_COMPS = _MOTION / "compositions"


class NateherkTokensTests(unittest.TestCase):
    """The §3 rank 2-4 + T-D tokens exist in BOTH twins and agree."""

    def test_motion_tokens_js_carries_the_pack(self) -> None:
        js = (_MOTION / "motion-tokens.js").read_text(encoding="utf-8")
        self.assertIn("TEXT_RAMP_S = 0.2", js)          # rank 4: 120-250ms ramp
        self.assertIn("EYEBROW_LEAD_S = 0.25", js)      # rank 3: band 0.08-0.5
        self.assertIn("SKELETON_GAP_S = 0.35", js)      # rank 2
        self.assertIn("EXIT_BLUR_S = 0.15", js)         # T-D: ~150ms
        for helper in ("textRamp", "skeletonFirst", "blurRecede"):
            self.assertIn(helper, js)
        # Jaden pack law untouched (different lane).
        self.assertIn("POP_IN_S = 2 / FPS", js)
        self.assertIn("instantOut", js)

    def test_tokens_css_carries_the_twins(self) -> None:
        css = (_MOTION / "tokens.css").read_text(encoding="utf-8")
        for tok in ("--eyebrow-font", "--eyebrow-dot", "--eyebrow-lead: 0.25s",
                    "--text-ramp-dur: 0.2s", "--skeleton-gap: 0.35s",
                    "--exit-blur-dur: 0.15s"):
            self.assertIn(tok, css)
        self.assertIn("--pop-in-dur", css)              # jaden twin untouched

    def test_python_twin_matches(self) -> None:
        self.assertEqual(eoc.EXIT_BLUR_S, 0.15)
        self.assertIn("blur-recede", eoc.EXITS)


class NateherkCompContractTests(unittest.TestCase):
    """New comp variables exist; every default names the pre-pack build."""

    def _comp(self, name: str) -> str:
        return (_COMPS / f"{name}.html").read_text(encoding="utf-8")

    def test_statement_card_nateherk_variant(self) -> None:
        html = self._comp("statement-card")
        self.assertIn("/motion-tokens.js", html)
        for var in ('"id":"variant"', '"id":"eyebrow"', '"id":"headlineLines"',
                    '"id":"statements"', '"id":"statementLands"',
                    '"id":"exit"', '"id":"evidenceSource"'):
            self.assertIn(var, html)
        # Defaults keep the classic path: variant classic, exit hold.
        self.assertIn('"id":"variant","type":"enum","label":"Build grammar","default":"classic"', html)
        self.assertIn('"id":"exit","type":"enum","label":"Exit","default":"hold"', html)
        # The classic word-rise build survives verbatim (untouched lane).
        self.assertIn("y: 22", html)
        self.assertIn("stagger: 0.055", html)
        # v2 replace grammar pieces: 2 empty frames + 0.3s ramp (T-E).
        self.assertIn("2 / M.FPS", html)
        self.assertIn("SWAP_RAMP_S = 0.3", html)

    def test_glass_rail_opt_ins(self) -> None:
        html = self._comp("glass-rail")
        self.assertIn("/motion-tokens.js", html)
        self.assertIn('"id":"build","type":"enum","label":"Build grammar","default":"stamp"', html)
        self.assertIn('"id":"exit","type":"enum","label":"Exit","default":"fade"', html)
        self.assertIn("skeletonFirst", html)
        self.assertIn("blurRecede", html)
        self.assertIn('back.out(1.6)', html)            # stamp build intact

    def test_stat_card_opt_ins(self) -> None:
        html = self._comp("stat-card")
        self.assertIn("/motion-tokens.js", html)
        self.assertIn('"id":"build","type":"enum","label":"Build grammar","default":"pop"', html)
        for var in ('"id":"eyebrow"', '"id":"evidenceSource"', '"id":"evidenceDate"'):
            self.assertIn(var, html)
        self.assertIn("skeletonFirst", html)
        self.assertIn('back.out(1.5)', html)            # pop build intact

    def test_list_build_opt_in(self) -> None:
        html = self._comp("list-build")
        self.assertIn("/motion-tokens.js", html)
        self.assertIn('"id":"build","type":"enum","label":"Build grammar","default":"pop"', html)
        self.assertIn("skeletonFirst", html)
        self.assertIn('back.out(1.5)', html)            # pop build intact


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
    """The rule fires through plan_lint (same wire the renderers trust)."""

    def _plan(self, graphics: list[dict]) -> dict:
        return {
            "planVersion": 1,
            "target": {"mode": "longform", "durationTargetS": 60, "excerpt": True},
            "cutTrack": [{"sourceId": "raw-1", "start": i * 3.0,
                          "end": (i + 1) * 3.0, "speed": 1.0} for i in range(20)],
            "reframe": {"strategy": "face"},
            "captions": {"burn": False, "style": "line"},
            "graphicsTrack": graphics,
        }

    def test_blur_recede_passes_on_a_healthy_window(self) -> None:
        # Windows end 0.5-1.0s clear of the 3s-grid seams: a blur-recede that
        # ends ON a seam is now the LL-001 runway ERROR (FAILURE_LEDGER.md),
        # so "healthy" includes seam runway, not just window length.
        gfx = [{"outStart": s, "outEnd": s + 9.0, "kind": "statement-card",
                "spec": {"text": "x", "exit": "blur-recede"},
                "anchor": "own-screen", "reason": "beat"}
               for s in (4.0, 24.5, 44.0)]
        rep = pl.lint(self._plan(gfx), MANIFEST)
        self.assertFalse([e for e in rep.errors if "exit" in e], rep.errors)

    def test_degenerate_clamp_fails_through_lint(self) -> None:
        gfx = [{"outStart": 2.95, "outEnd": 11.9, "kind": "statement-card",
                "spec": {"text": "x", "exit": "blur-recede"},
                "anchor": "own-screen", "reason": "beat", "exitOnCut": True}]
        rep = pl.lint(self._plan(gfx), MANIFEST)
        self.assertTrue(any("cannot complete" in e for e in rep.errors),
                        rep.errors)

    def test_unknown_exit_fails_through_lint(self) -> None:
        gfx = [{"outStart": 4.0, "outEnd": 13.0, "kind": "statement-card",
                "spec": {"text": "x", "exit": "poof"},
                "anchor": "own-screen", "reason": "beat"}]
        rep = pl.lint(self._plan(gfx), MANIFEST)
        self.assertTrue(any("spec.exit" in e for e in rep.errors), rep.errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
