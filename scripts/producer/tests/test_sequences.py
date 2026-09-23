"""Retired sequence routing and non-rendering historical copy arithmetic."""
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
    """Saved or new ordinal cues cannot select the retired whiteboard template."""

    def test_sequence_planner_requires_current_catalog_selection(self) -> None:
        for mode in ("short", "longform"):
            for state in (TH, UNTAGGED, SCREEN):
                with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "retired"):
                    gseq.sequence_beats(_words("First, sharpen the pain. Then gather proof. Finally ship."),
                                        mode, state, 60.0)


class FillListSpecTests(unittest.TestCase):
    """graphics_copy.fill_list_spec — LLM labels → timed spec (or drop)."""

    def _beat(self):
        # Inert historical data exercises copy/timing preservation, never selection.
        return {"kind": "whiteboard-list", "outStart": 0, "outEnd": 6,
                "anchors": [{"atSec": 0}, {"atSec": 2}, {"atSec": 4}],
                "rawSpan": "First sharpen the pain then gather proof finally ship",
                "spec": {}, "needsCopy": True}

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
