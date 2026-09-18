"""graphics_reference — the reference-driven graphic mechanism (cross-format).

Deterministic half: deictic DISCOVERY (showing-language slots) + the PLACEMENT
engine (aspect/state -> anchor). Semantic half: the brain names the referent +
picks a HyperFrames comp, exercised through fill_reference_spec. Placement is
the system's job; the brain supplies only the comp + content.
"""
import unittest

from _common import *  # noqa: F401,F403
from planner.graphics_planner_longform import Ctx


def _words(text: str, t0: float = 0.0, step: float = 0.5) -> list:
    out, t = [], t0
    for tok in text.split():
        out.append({"word": tok, "start": round(t, 3), "end": round(t + 0.4, 3)})
        t += step
    return out


TH = lambda t: ("talking-head", None)          # noqa: E731
SCREEN = lambda t: ("screen-share", None)      # noqa: E731


def _ctx(words, mode="short", state_fn=TH, out_dur=400.0, aspect="9:16"):
    return Ctx(words, mode, aspect, state_fn, out_dur)


class ReferenceBeatTests(unittest.TestCase):
    """reference_beats — deictic showing-language slots; NO semantic call."""

    def test_showing_phrase_surfaces_a_slot(self) -> None:
        beats = gref.reference_beats(_ctx(_words("okay so look at this workflow here")))
        self.assertEqual(len(beats), 1)
        b = beats[0]
        self.assertTrue(b["needsContent"])
        self.assertEqual(b["trigger"], "reference")
        self.assertIn("look at this", b["rawSpan"].lower())

    def test_no_showing_language_no_slot(self) -> None:
        self.assertEqual(
            gref.reference_beats(_ctx(_words("i think prompting is mostly broken"))), [])

    def test_bare_this_is_too_noisy_to_fire(self) -> None:
        # "this is important" is not a SHOWING phrase — no slot (brain-worthy only).
        self.assertEqual(
            gref.reference_beats(_ctx(_words("this is important for everyone"))), [])

    def test_min_gap_spreads_slots(self) -> None:
        close = _words("look at this thing", t0=0.0) + _words("look at this too", t0=3.0)
        self.assertEqual(len(gref.reference_beats(_ctx(close))), 1)

    def test_is_cross_format(self) -> None:
        # The SAME cue fires in a long, too (mechanism is both-format).
        self.assertEqual(
            len(gref.reference_beats(
                _ctx(_words("now look at this chart"), mode="longform", aspect="16:9"))),
            1)


class PlacementTests(unittest.TestCase):
    """place — the system's job: aspect + state -> anchor."""

    def test_short_talking_head_goes_headroom(self) -> None:
        self.assertEqual(gref.place("9:16", "talking-head"), "headroom")

    def test_long_talking_head_goes_full_frame(self) -> None:
        self.assertEqual(gref.place("16:9", "talking-head"), "own-screen")

    def test_screen_share_keeps_the_screen_the_star(self) -> None:
        self.assertEqual(gref.place("9:16", "screen-share"), "own-screen")
        self.assertEqual(gref.place("16:9", "screen-share"), "own-screen")


class FillReferenceSpecTests(unittest.TestCase):
    """fill_reference_spec — brain's comp + copy -> a placed candidate, or None."""

    def _short_beat(self):
        return gref.reference_beats(
            _ctx(_words("okay look at this workflow now")))[0]

    def _long_beat(self):
        return gref.reference_beats(
            _ctx(_words("okay look at this workflow now"),
                 mode="longform", aspect="16:9"))[0]

    def test_brain_picks_a_comp_system_keeps_placement(self) -> None:
        beat = self._long_beat()
        cand = gref.fill_reference_spec(
            beat, "statement-card", {"text": "The one workflow", "bg": "cream"})
        self.assertIsNotNone(cand)
        self.assertEqual(cand["kind"], "statement-card")
        self.assertEqual(cand["anchor"], "own-screen")     # system's, unchanged
        self.assertNotIn("needsContent", cand)
        self.assertEqual(cand["spec"]["text"], "The one workflow")

    def test_empty_spec_drops_the_slot(self) -> None:
        self.assertIsNone(gref.fill_reference_spec(self._long_beat(), "statement-card", {}))

    def test_aspect_illegal_comp_is_refused(self) -> None:
        # A 16:9-only comp on a 9:16 short slot is not legal -> None.
        self.assertIsNone(gref.fill_reference_spec(
            self._short_beat(), "statement-card", {"text": "x"}))

    def test_short_uses_a_vertical_comp_at_headroom(self) -> None:
        beat = self._short_beat()
        cand = gref.fill_reference_spec(
            beat, "kinetic-quote", {"quote": "the one workflow"})
        self.assertIsNotNone(cand)
        self.assertEqual(cand["anchor"], "headroom")


class SuppressCoveredTests(unittest.TestCase):
    def test_a_taken_beat_suppresses_the_reference(self) -> None:
        beats = gref.reference_beats(_ctx(_words("okay look at this workflow now")))
        taken = [{"outStart": beats[0]["outStart"], "outEnd": beats[0]["outEnd"],
                  "kind": "chip-row"}]
        kept, rejected = gref.suppress_covered(beats, taken)
        self.assertEqual(kept, [])
        self.assertEqual(len(rejected), 1)
        self.assertIn("chip-row", rejected[0]["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
