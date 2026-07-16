"""SFX starter pack + Lucide icon resolution (kept from the 2026-07-11 sprint;
the xfade transition family from the same sprint was operator-rejected and
removed — see test_transitions_ban.py / FAILURE_LEDGER LL-014)."""
import unittest

from _common import *  # noqa: F401,F403


class SfxLibraryTests(unittest.TestCase):
    """The vendored pack resolves; unknown names fail loudly."""

    def test_every_pack_name_resolves_to_a_built_file(self) -> None:
        for name in sfxlib.available():
            path, lead = sfxlib.resolve(name)
            self.assertTrue(os.path.isfile(path), path)
            self.assertGreaterEqual(lead, 0.0)
            self.assertLessEqual(lead, sfxlib.PACK[name]["dur"])

    def test_unknown_name_lists_the_pack(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            sfxlib.resolve("airhorn")
        self.assertIn("whoosh-soft", str(ctx.exception))

    def test_sfx_slot_accepts_pack_name(self) -> None:
        events = tr.parse_events(
            [{"outTime": 2.0, "kind": "white-flash", "sfx": "whoosh-soft"}],
            10.0)
        self.assertEqual(events[0].sfx, "whoosh-soft")

    def test_sfx_is_silent_unless_explicitly_requested(self) -> None:
        silent = tr.parse_events(
            [{"outTime": 2.0, "kind": "white-flash"}], 10.0)
        audible = tr.parse_events(
            [{"outTime": 2.0, "kind": "white-flash", "sfx": True}], 10.0)
        self.assertFalse(silent[0].sfx)
        self.assertTrue(audible[0].sfx)

    def test_sfx_slot_rejects_unknown_name_and_non_bool(self) -> None:
        with self.assertRaises(ValueError):
            tr.parse_events([{"outTime": 2.0, "kind": "white-flash",
                              "sfx": "airhorn"}], 10.0)
        with self.assertRaises(ValueError):
            tr.parse_events([{"outTime": 2.0, "kind": "white-flash",
                              "sfx": 3}], 10.0)

    def test_grouped_audio_graph_delays_each_source(self) -> None:
        events = [tr.TransitionEvent(2.0, "white-flash", True),
                  tr.TransitionEvent(4.0, "light-leak", "click"),
                  tr.TransitionEvent(6.0, "light-leak", "click")]
        fc = tr.build_audio_graph(events, {True: (1, tr.WHOOSH_LEAD_S),
                                           "click": (2, 0.01)})
        self.assertIn("[1:a]adelay=1700|1700", fc)     # 2.0 - 0.3 lead
        self.assertIn("[2:a]asplit=2", fc)             # click used twice
        self.assertIn("adelay=3990|3990", fc)          # 4.0 - 0.01 lead
        self.assertIn("amix=inputs=4:duration=first:normalize=0[aout]", fc)

    def test_lint_sfx_name_validated_through_the_pack(self) -> None:
        def lint(events):
            rep = pl.Report()
            plm.check_transitions({"transitions": events}, 60.0,
                                  "longform", rep)
            return rep
        ok = lint([{"outTime": 10.0, "kind": "white-flash", "sfx": "click"}])
        self.assertEqual(ok.errors, [])
        bad = lint([{"outTime": 10.0, "kind": "white-flash",
                     "sfx": "airhorn"}])
        self.assertTrue(any("unknown sfx" in e for e in bad.errors),
                        bad.errors)


class IconResolutionTests(unittest.TestCase):
    """Combined order: Simple Icons brand mark > vendored Lucide glyph."""

    def test_brand_mark_wins_the_collision(self) -> None:
        # 'github' exists in BOTH vocabularies — the brand mark must win.
        self.assertIn("github", ilu.vendored())
        self.assertEqual(ilib.resolve_name("github"), "github")

    def test_lucide_glyph_fallback(self) -> None:
        self.assertEqual(ilib.resolve_name("check"), "lucide/check")
        self.assertEqual(ilib.resolve_name("database"), "lucide/database")

    def test_explicit_lucide_prefix_forces_the_glyph(self) -> None:
        self.assertEqual(ilib.resolve_name("lucide/github"), "lucide/github")

    def test_unknown_name_fails_loudly_with_both_vocabularies(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            ilib.resolve_name("definitely-not-an-icon")
        msg = str(ctx.exception)
        self.assertIn("Brand marks", msg)
        self.assertIn("Lucide glyphs", msg)

    def test_whole_curated_subset_is_vendored(self) -> None:
        missing = set(ilu.LUCIDE_NAMES) - ilu.vendored()
        self.assertEqual(missing, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
