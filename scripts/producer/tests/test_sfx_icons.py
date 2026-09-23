"""SFX starter pack + Lucide icon resolution (kept from the 2026-07-11 sprint;
the xfade transition family from the same sprint was operator-rejected and
removed — see test_transitions_ban.py / FAILURE_LEDGER LL-014)."""
import unittest
from pathlib import Path
from unittest import mock

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

    def test_retained_sfx_event_metadata_keeps_pack_name_and_group_key(self) -> None:
        """A historical DTO remains readable; this does not admit its visual."""
        event = tr.TransitionEvent(2.0, "white-flash", "whoosh-soft")
        self.assertEqual(event.sfx, "whoosh-soft")
        self.assertEqual(tr._sfx_key(event), "whoosh-soft")
        path, lead = sfxlib.resolve(event.sfx)
        self.assertTrue(Path(path).is_file())
        self.assertGreaterEqual(lead, 0)

    def test_retained_sfx_metadata_defaults_to_silent(self) -> None:
        """The inert event contract preserves explicit sound intent."""
        silent = tr.TransitionEvent(2.0, "white-flash")
        audible = tr.TransitionEvent(2.0, "white-flash", True)
        self.assertFalse(silent.sfx)
        self.assertTrue(audible.sfx)

    def test_retired_transition_parse_rejects_every_sfx_intent(self) -> None:
        """No silent, explicit or malformed SFX revives retired visual presets."""
        for sfx in (None, False, True, "whoosh-soft", "airhorn", 3):
            event = {"outTime": 2.0, "kind": "white-flash"}
            if sfx is not None:
                event["sfx"] = sfx
            with self.subTest(sfx=sfx), mock.patch("subprocess.run") as run:
                with self.assertRaisesRegex(ValueError, "retired"):
                    tr.parse_events([event], 10.0)
            run.assert_not_called()

    def test_grouped_audio_graph_delays_each_source(self) -> None:
        """Inspect pure filter math for historical event metadata, never execute."""
        events = [tr.TransitionEvent(2.0, "white-flash", True),
                  tr.TransitionEvent(4.0, "light-leak", "click"),
                  tr.TransitionEvent(6.0, "light-leak", "click")]
        fc = tr.build_audio_graph(events, {True: (1, tr.WHOOSH_LEAD_S),
                                           "click": (2, 0.01)})
        self.assertIn("[1:a]adelay=1700|1700", fc)     # 2.0 - 0.3 lead
        self.assertIn("[2:a]asplit=2", fc)             # click used twice
        self.assertIn("adelay=3990|3990", fc)          # 4.0 - 0.01 lead
        self.assertIn("amix=inputs=4:duration=first:normalize=0[aout]", fc)

    def test_sfx_field_linter_validates_pack_names_independently_of_visual_admission(self) -> None:
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
