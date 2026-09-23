"""xfade family BAN (2026-07-11, FAILURE_LEDGER LL-014).

The stock ffmpeg-xfade transition sampler was operator-rejected on sight;
longform seams use ONLY Sniper's seam grammar (panel sweeps, face-bridged
recomposition, under-panel cuts, blur-recede, seam-role zoom-pulls —
MODULE_STUDY §2, EDITCRAFT_LESSONS §2.7). These tests pin the ban: any
``xfade:*`` kind is a hard ERROR
in EVERY mode at the lint gate and a loud ValueError at the primitive.
"""
import unittest

from _common import *  # noqa: F401,F403


class XfadeBanLintTests(unittest.TestCase):
    """plan_lint_motion.check_transitions: xfade:* is an ERROR in all modes."""

    def _lint(self, events: list, mode: str, out_dur: float = 60.0):
        rep = pl.Report()
        plm.check_transitions({"transitions": events}, out_dur, mode, rep)
        return rep

    def test_xfade_rejected_in_every_mode(self) -> None:
        for mode in ("short", "longform"):
            for kind in ("xfade:fade", "xfade:wipeleft", "xfade:dissolve",
                         "xfade:anything-at-all"):
                rep = self._lint([{"outTime": 10.0, "kind": kind}], mode)
                self.assertTrue(
                    any("operator-rejected" in e for e in rep.errors),
                    (mode, kind, rep.errors))

    def test_ban_message_names_the_seam_grammar(self) -> None:
        rep = self._lint([{"outTime": 10.0, "kind": "xfade:fade"}], "longform")
        msg = " ".join(rep.errors)
        self.assertIn("transition grammar", msg)
        self.assertIn("panel sweep", msg)
        self.assertIn("LL-014", msg)

    def test_historical_flash_and_leak_shape_parser_is_readable(self) -> None:
        events = [{"outTime": 10.0, "kind": "white-flash"},
                  {"outTime": 20.0, "kind": "light-leak"}]
        for mode in ("short", "longform"):
            self.assertEqual(self._lint(events, mode).errors, [], mode)

    def test_config_vocabulary_is_gone(self) -> None:
        cfg = plm.MOTION["transitions"]
        self.assertNotIn("xfade_kinds", cfg)
        self.assertNotIn("xfade_modes", cfg)
        # flash/leak + the seam-role zoom-pull (continuity mechanism CM-1) —
        # never any xfade vocabulary.
        self.assertEqual(cfg["kinds"], ("white-flash", "light-leak",
                                        "zoom-pull"))


class XfadeBanPrimitiveTests(unittest.TestCase):
    """transitions.parse_events: xfade kinds raise loudly, module is gone."""

    def test_parse_events_rejects_xfade_kind(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            tr.parse_events([{"outTime": 2.0, "kind": "xfade:fade"}], 10.0)
        self.assertIn("retired", str(ctx.exception))

    def test_all_old_presets_reject_in_current_primitive(self) -> None:
        for kind in ("white-flash", "light-leak", "zoom-pull"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "retired"):
                tr.parse_events([{"outTime": 2.0, "kind": kind}], 10.0)

    def test_xfade_module_is_deleted(self) -> None:
        with self.assertRaises(ImportError):
            import motion.transitions_xfade  # noqa: F401


if __name__ == "__main__":
    unittest.main(verbosity=2)
