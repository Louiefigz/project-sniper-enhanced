"""graphics_planner_illustration + graphics_copy.fill_illustration_spec —
the concept-illustration b-roll lane.

Deterministic half surfaces legal SLOTS (talking-head body sentences, spread,
minus receipt/cutaway collisions); the SEMANTIC half (the brain picks a real
pool illustration) is exercised through fill_illustration_spec. No regex decides
which beat is worth a visual — the brain does, in the skill.
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


def _ctx(words, mode="longform", state_fn=TH, out_dur=400.0, aspect="16:9"):
    return Ctx(words, mode, aspect, state_fn, out_dur)


class IllustrationBeatTests(unittest.TestCase):
    """illustration_beats — legal slots only; NO semantic worthiness call."""

    # Two body sentences ~40s apart, both past the 120s hook window.
    WORDS = (_words("We are getting your data ready for the launch.", t0=150.0)
             + _words("Then we map the roadmap to real growth.", t0=195.0))

    def test_body_sentences_become_slots(self) -> None:
        beats = gillu.illustration_beats(_ctx(self.WORDS))
        self.assertEqual(len(beats), 2)
        b = beats[0]
        self.assertTrue(b["needsConcept"])
        self.assertIsNone(b["assetId"])
        self.assertEqual(b["anchor"], "own-screen")
        self.assertEqual(b["kind"], "broll-illustration")
        self.assertIn("data", b["rawSpan"].lower())

    def test_hook_window_is_body_only(self) -> None:
        # A sentence inside the first 120s (the hook) is never an illustration slot.
        self.assertEqual(
            gillu.illustration_beats(
                _ctx(_words("Getting your data ready early.", t0=10.0))), [])

    def test_min_gap_spreads_slots(self) -> None:
        # Two sentences 5s apart → only the first earns a slot (30s min-gap).
        close = (_words("First concept sentence here now.", t0=150.0)
                 + _words("Second concept sentence here now.", t0=155.0))
        self.assertEqual(len(gillu.illustration_beats(_ctx(close))), 1)

    def test_screen_share_earns_no_slot(self) -> None:
        self.assertEqual(
            gillu.illustration_beats(_ctx(self.WORDS, state_fn=SCREEN)), [])

    def test_shorts_earn_no_slot(self) -> None:
        self.assertEqual(
            gillu.illustration_beats(_ctx(self.WORDS, mode="short")), [])


class SuppressCoveredTests(unittest.TestCase):
    """A receipt or accepted cutaway already owns the beat → drop the slot."""

    def _beats(self):
        return gillu.illustration_beats(
            _ctx(IllustrationBeatTests.WORDS))

    def test_receipt_suppresses_the_overlapping_slot(self) -> None:
        beats = self._beats()
        receipt = {"outStart": beats[0]["outStart"], "outEnd": beats[0]["outEnd"],
                   "note": "receipt: his channel"}
        kept, rejected = gillu.suppress_covered(beats, [receipt], [])
        self.assertEqual(len(kept), 1)                 # only the 2nd survives
        self.assertEqual(len(rejected), 1)
        self.assertIn("receipt", rejected[0]["reason"])

    def test_own_screen_cutaway_suppresses_the_slot(self) -> None:
        beats = self._beats()
        cut = {"outStart": beats[1]["outStart"], "outEnd": beats[1]["outEnd"],
               "anchor": "own-screen", "kind": "whiteboard-list"}
        kept, rejected = gillu.suppress_covered(beats, [], [cut])
        self.assertEqual(len(kept), 1)
        self.assertIn("cutaway", rejected[0]["reason"])


class FillIllustrationSpecTests(unittest.TestCase):
    """fill_illustration_spec — a REAL pool id → a brollTrack row, or None."""

    def _beat(self):
        return gillu.illustration_beats(_ctx(IllustrationBeatTests.WORDS))[0]

    def test_real_pool_id_fills_a_broll_row(self) -> None:
        beat = self._beat()
        row = gcopy.fill_illustration_spec(
            beat, "growth-illus", ["growth-illus", "team-illus"],
            caption="roadmap to growth")
        self.assertIsNotNone(row)
        self.assertEqual(row["assetId"], "growth-illus")
        self.assertFalse(row["needsOperator"])
        self.assertNotIn("needsConcept", row)          # consumed
        self.assertEqual(row["outStart"], beat["outStart"])
        self.assertEqual(row["label"], "roadmap to growth")

    def test_unknown_id_is_never_invented(self) -> None:
        # No fallback / no invented ids — an id outside the pool drops the slot.
        self.assertIsNone(gcopy.fill_illustration_spec(
            self._beat(), "made-up", ["growth-illus"]))
        self.assertIsNone(gcopy.fill_illustration_spec(
            self._beat(), "", ["growth-illus"]))
        self.assertIsNone(gcopy.fill_illustration_spec(
            self._beat(), "growth-illus", []))

    def test_context_caption_keeps_complete_meaning_without_a_word_limit(self) -> None:
        """Non-render context preserves every word while normalizing whitespace."""
        caption = "  Keep the original footage\nuntil the export passes review  "
        row = gcopy.fill_illustration_spec(
            self._beat(), "growth-illus", ["growth-illus"], caption)
        self.assertEqual(row["label"], " ".join(caption.split()))
        self.assertNotIn("copyRepair", row)


if __name__ == "__main__":
    unittest.main(verbosity=2)
