"""graphics_planner_gauge — the milestone GAUGE lane (shorts).

Deterministic half: find a numeric CLIMB (arithmetic, not semantics) and surface
a beat with per-milestone anchors. Semantic half: the brain writes the label +
maps each milestone to a bar position, exercised via fill_gauge_spec.
"""
import unittest

from _common import *  # noqa: F401,F403
from planner.graphics_planner_longform import Ctx


def _words(text: str, step: float = 0.5) -> list:
    out, t = [], 0.0
    for tok in text.split():
        out.append({"word": tok, "start": round(t, 3), "end": round(t + 0.4, 3)})
        t += step
    return out


TH = lambda t: ("talking-head", None)          # noqa: E731


def _ctx(words, mode="short", aspect="9:16", out_dur=120.0):
    return Ctx(words, mode, aspect, TH, out_dur)


class GaugeBeatTests(unittest.TestCase):
    CLIMB = "you go from 1k to 10k to 100k to 1M followers fast"

    def test_climb_surfaces_a_gauge_beat(self) -> None:
        beats = ggauge.gauge_beats(_ctx(_words(self.CLIMB)))
        self.assertEqual(len(beats), 1)
        b = beats[0]
        self.assertTrue(b["needsCopy"])
        self.assertEqual(b["kind"], "widget-gauge")
        self.assertEqual(b["anchor"], "headroom")
        self.assertEqual(len(b["marks"]), 4)             # 1k,10k,100k,1M
        self.assertNotIn("pos1", b.get("spec", {}))       # positions are the brain's

    def test_flat_or_descending_numbers_are_not_a_gauge(self) -> None:
        self.assertEqual(
            ggauge.gauge_beats(_ctx(_words("i had 3 dogs and 2 cats and 1 fish"))), [])

    def test_too_few_milestones_no_beat(self) -> None:
        # two numbers is not a climb (needs 3+).
        self.assertEqual(
            ggauge.gauge_beats(_ctx(_words("from 1k up to 10k in a month"))), [])

    def test_longform_gets_no_gauge(self) -> None:
        # widget-gauge is a 9:16 comp; a long expresses the climb elsewhere.
        self.assertEqual(
            ggauge.gauge_beats(_ctx(_words(self.CLIMB), mode="longform", aspect="16:9")),
            [])


class FillGaugeSpecTests(unittest.TestCase):
    def _beat(self):
        return ggauge.gauge_beats(_ctx(_words(GaugeBeatTests.CLIMB)))[0]

    def test_positions_land_on_milestone_times(self) -> None:
        beat = self._beat()
        cand = ggauge.fill_gauge_spec(beat, "Followers", [
            {"markIndex": 0, "pos": 0.1}, {"markIndex": 1, "pos": 0.4},
            {"markIndex": 2, "pos": 0.7}, {"markIndex": 3, "pos": 1.0}])
        self.assertIsNotNone(cand)
        self.assertEqual(cand["spec"]["label"], "Followers")
        self.assertEqual(cand["spec"]["pos1"], 0.1)
        self.assertEqual(cand["spec"]["at1"], 0.0)        # first mark at beat start
        self.assertNotIn("needsCopy", cand)

    def test_non_monotonic_positions_are_refused(self) -> None:
        # a gauge climbs — a position that goes backwards is not a climb.
        self.assertIsNone(ggauge.fill_gauge_spec(self._beat(), "x", [
            {"markIndex": 0, "pos": 0.8}, {"markIndex": 1, "pos": 0.3}]))

    def test_out_of_range_position_refused(self) -> None:
        self.assertIsNone(ggauge.fill_gauge_spec(self._beat(), "x", [
            {"markIndex": 0, "pos": 0.1}, {"markIndex": 1, "pos": 1.5}]))

    def test_fewer_than_two_positions_dropped(self) -> None:
        self.assertIsNone(ggauge.fill_gauge_spec(
            self._beat(), "x", [{"markIndex": 0, "pos": 0.2}]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
