"""graphics_planner_sequences + graphics_copy — the sequence-list copy seam.

The DETERMINISTIC half (sequence_beats) surfaces candidate beats from ordinal
clusters; the SEMANTIC half (the brain/agent in the skill flow) writes copy that
graphics_copy.fill_list_spec times to the anchors. These tests cover the code
halves; the brain's read-and-write judgment happens in the skill, not here.
"""
import unittest

from _common import *  # noqa: F401,F403


def _words(text: str, step: float = 0.5) -> list:
    """Lay out a sentence as timed words (the transcript shape)."""
    out, t = [], 0.0
    for tok in text.split():
        out.append({"word": tok, "start": round(t, 3), "end": round(t + 0.4, 3)})
        t += step
    return out


TH = lambda t: ("talking-head", None)          # noqa: E731
UNTAGGED = lambda t: (None, None)              # noqa: E731
SCREEN = lambda t: ("screen-share", None)      # noqa: E731


class SequenceBeatTests(unittest.TestCase):
    """sequence_beats — clustering, gating, anchors; NO semantic decision."""

    REAL = "First, sharpen the pain. Then, gather your proof. Finally, ship it."

    def test_cluster_yields_one_needscopy_beat(self) -> None:
        beats = gseq.sequence_beats(_words(self.REAL), "longform", TH, 60.0)
        self.assertEqual(len(beats), 1)
        b = beats[0]
        self.assertTrue(b["needsCopy"])
        self.assertEqual(b["spec"], {})                 # copy is NOT written here
        self.assertEqual(b["anchor"], "own-screen")
        self.assertEqual(b["kind"], "whiteboard-list")
        self.assertEqual(len(b["anchors"]), 3)          # first / then / finally
        self.assertEqual(b["anchors"][0]["atSec"], 0.0)
        self.assertTrue(all(a["atSec"] >= 0 for a in b["anchors"]))
        self.assertIn("sharpen", b["rawSpan"].lower())

    def test_lone_ordinal_is_not_a_beat(self) -> None:
        # A single "first" (even clause-marked) is not a run — needs 2+.
        self.assertEqual(
            gseq.sequence_beats(_words("First, do the thing and move on."),
                                "longform", TH, 60.0), [])

    def test_weak_only_run_needs_a_strong_anchor(self) -> None:
        # "then … next" with no first/second/finally = temporal chatter, dropped.
        self.assertEqual(
            gseq.sequence_beats(_words("I did it then I moved on then next okay"),
                                "longform", TH, 60.0), [])

    def test_untagged_state_defaults_talking_head(self) -> None:
        # An untagged plan still surfaces beats (matches the R14 retarget gate).
        self.assertEqual(
            len(gseq.sequence_beats(_words(self.REAL), "longform", UNTAGGED, 60.0)),
            1)

    def test_explicit_screen_share_opts_out(self) -> None:
        self.assertEqual(
            gseq.sequence_beats(_words(self.REAL), "longform", SCREEN, 60.0), [])


class FillListSpecTests(unittest.TestCase):
    """graphics_copy.fill_list_spec — LLM labels → timed spec (or drop)."""

    def _beat(self):
        return gseq.sequence_beats(
            _words(SequenceBeatTests.REAL), "longform", TH, 60.0)[0]

    def test_labels_land_on_their_anchor_times(self) -> None:
        beat = self._beat()
        items = [{"anchorIndex": 0, "label": "Sharpen the pain"},
                 {"anchorIndex": 1, "label": "Gather your proof"},
                 {"anchorIndex": 2, "label": "Ship it"}]
        cand = gcopy.fill_list_spec(beat, items, title="The play")
        self.assertIsNotNone(cand)
        self.assertNotIn("needsCopy", cand)
        self.assertEqual(cand["spec"]["title"], "The play")
        self.assertEqual(cand["spec"]["item1"], "Sharpen the pain")
        self.assertEqual(cand["spec"]["at1"], beat["anchors"][0]["atSec"])
        self.assertEqual(cand["spec"]["at3"], beat["anchors"][2]["atSec"])
        self.assertEqual(cand["confidence"], "high")    # 3 items

    def test_dropped_when_fewer_than_two_items(self) -> None:
        # The brain judged it not a real list → no items → drop (clean head).
        self.assertIsNone(gcopy.fill_list_spec(self._beat(), []))
        self.assertIsNone(gcopy.fill_list_spec(
            self._beat(), [{"anchorIndex": 0, "label": "only one"}]))

    def test_bad_items_are_skipped_not_trusted(self) -> None:
        beat = self._beat()
        items = [{"anchorIndex": 0, "label": "Kept one"},
                 {"anchorIndex": 9, "label": "out of range"},   # dropped
                 {"anchorIndex": 1, "label": ""},               # empty, dropped
                 {"anchorIndex": 2, "label": "Kept two"}]
        cand = gcopy.fill_list_spec(beat, items)
        self.assertEqual([k for k in cand["spec"] if k.startswith("item")],
                         ["item1", "item2"])

    def test_oversized_label_and_title_request_rewrite(self) -> None:
        """Fit failures keep complete copy pending instead of truncating it."""
        beat = self._beat()
        long_label = "one two three four five six seven eight"
        cand = gcopy.fill_list_spec(
            beat, [{"anchorIndex": 0, "label": long_label},
                   {"anchorIndex": 1, "label": "fine"}],
            title="a very long title indeed here")
        self.assertTrue(cand["needsCopy"])
        self.assertEqual(cand["spec"], {})
        self.assertEqual(cand["copyRepair"]["originalItems"][0]["label"],
                         long_label)
        self.assertEqual([row["field"] for row in cand["copyRepair"]["issues"]],
                         ["title", "items[0].label"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
