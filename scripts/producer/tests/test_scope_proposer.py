"""graphics_planner scope-gating — the proposer emits ONLY in-scope lanes."""
import unittest

from _common import *  # noqa: F401,F403 — gp alias
import graphics_planner as gp


def _proposal() -> dict:
    return {
        "candidates": [{"kind": "card"}],
        "brollReceipts": [{"assetId": "b1"}],
        "brollIllustration": [{"kind": "illus"}],
        "gaugeBeats": [{"kind": "gauge"}],
        "references": [{"kind": "ref"}],
        "treatmentMap": [{"treatment": "kinetic"}],
        "zoom": {"punchIns": [{"role": "emphasis", "outStart": 1.0},
                              {"role": "aliveness", "outStart": 0.0}]},
        "momentumZones": [{"start": 0}],
        "meta": {"candidateCount": 1, "receiptCount": 1,
                 "illustrationCount": 1, "referenceCount": 1},
    }


class ScopeProposerTests(unittest.TestCase):
    def test_produced_keeps_everything(self) -> None:
        p = gp._apply_scope(_proposal(), {"scope": "produced"})
        self.assertTrue(p["candidates"] and p["brollReceipts"])
        self.assertEqual(len(p["zoom"]["punchIns"]), 2)

    def test_trim_strips_every_lane(self) -> None:
        p = gp._apply_scope(_proposal(), {"scope": "trim"})
        for lane in ("candidates", "brollReceipts", "brollIllustration",
                     "gaugeBeats", "references", "treatmentMap"):
            self.assertEqual(p[lane], [], lane)
        self.assertEqual(p["zoom"]["punchIns"], [])

    def test_light_keeps_only_aliveness_creep(self) -> None:
        p = gp._apply_scope(_proposal(), {"scope": "light"})
        self.assertEqual(p["candidates"], [])       # no graphics
        self.assertEqual(p["brollReceipts"], [])    # no b-roll
        self.assertEqual([z["role"] for z in p["zoom"]["punchIns"]], ["aliveness"])

    def test_directive_waives_one_lane_only(self) -> None:
        p = gp._apply_scope(_proposal(), {"scope": "full", "lanes": {"broll": "off"}})
        self.assertEqual(p["brollReceipts"], [])          # waived
        self.assertTrue(p["candidates"])                  # graphics untouched
        self.assertEqual(len(p["zoom"]["punchIns"]), 2)   # motion untouched

    def test_momentum_gated_off_graphics_lane(self) -> None:
        # momentumZones is a graphic/cut pacing hint — moot when graphics are off,
        # so trim clears it (kept when produced).
        self.assertEqual(gp._apply_scope(_proposal(), {"scope": "trim"})["momentumZones"], [])
        self.assertTrue(gp._apply_scope(_proposal(), {"scope": "produced"})["momentumZones"])

    def test_meta_counts_refreshed_after_gating(self) -> None:
        p = gp._apply_scope(_proposal(), {"scope": "trim"})
        self.assertEqual(p["meta"]["candidateCount"], 0)
        self.assertEqual(p["meta"]["receiptCount"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
