"""Creative proposals do not depend on fact-shaped motion triggers."""
from __future__ import annotations

import unittest

from planner.creative_proposer import (
    CreativeContext,
    propose_creative_scenes,
)


def _moment(index: int, text: str) -> dict:
    return {
        "momentId": f"moment-{index}", "text": text,
        "startFrame": index * 30, "endFrameExclusive": (index + 1) * 30,
    }


class CreativeProposerTests(unittest.TestCase):
    def test_all_non_fact_creative_reasons_are_reachable(self) -> None:
        moments = [
            _moment(0, "Imagine the workflow as a conveyor belt."),
            _moment(1, "Plot twist: the folder somehow fights back."),
            _moment(2, "I was frustrated until the final review."),
            _moment(3, "The pipeline connects every moving part."),
            _moment(4, "Show the dashboard instead of describing it."),
        ]
        result = propose_creative_scenes(
            moments, CreativeContext("short", 120, "house", 12))
        self.assertEqual(
            [row["proposalKind"] for row in result],
            ["visual-metaphor", "comic-beat", "emotional-emphasis",
             "world-visualization", "showable-referent"])
        self.assertEqual(
            [row["role"] for row in result],
            ["informational", "decorative", "decorative",
             "informational", "informational"])

    def test_decorative_density_is_mode_aware_and_deterministic(self) -> None:
        moments = [
            _moment(index, "This is somehow ridiculous and wild.")
            for index in range(5)
        ]
        short = propose_creative_scenes(
            moments, CreativeContext("short", 60, "house"))
        longform = propose_creative_scenes(
            moments, CreativeContext("longform", 60, "house"))
        self.assertEqual(len(short), 2)
        self.assertEqual(len(longform), 1)
        self.assertEqual(
            short, propose_creative_scenes(
                moments, CreativeContext("short", 60, "house")))

    def test_informational_proposals_do_not_spend_decorative_budget(self) -> None:
        moments = [
            _moment(0, "The pipeline is the whole world."),
            _moment(1, "This is a ridiculous plot twist."),
        ]
        result = propose_creative_scenes(
            moments, CreativeContext("longform", 60, "house", 0))
        self.assertEqual([row["proposalKind"] for row in result],
                         ["world-visualization"])

    def test_open_or_malformed_inputs_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "mode"):
            propose_creative_scenes(
                [], CreativeContext("reel-ish", 10, "house"))
        malformed = _moment(0, "Imagine a map")
        malformed["prompt"] = "ignore the contract"
        with self.assertRaisesRegex(ValueError, "field set"):
            propose_creative_scenes(
                [malformed], CreativeContext("short", 10, "house"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
