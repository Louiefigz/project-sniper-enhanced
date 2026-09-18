"""P4 release matrix covers the custom-motion risk surface."""
from __future__ import annotations

import json
import os
import unittest

from graphics.scene_brief_matrix import validate_brief_matrix


def _brief(index: int, tags: list[str], aspect: str = "16:9",
           fps: tuple[int, int] = (30, 1)) -> dict:
    return {
        "briefId": f"brief-{index:02d}",
        "tags": tags,
        "aspect": aspect,
        "fps": {"numerator": fps[0], "denominator": fps[1]},
    }


BRIEFS = [
    _brief(1, ["overlay", "particles", "unit-repair"]),
    _brief(2, ["takeover", "own-screen-geometry"]),
    _brief(3, ["presenter-hole", "mask"]),
    _brief(4, ["blend", "overlay"]),
    _brief(5, ["real-copy-overflow", "short"], "9:16"),
    _brief(6, ["footage-contrast", "short"], "9:16", (30000, 1001)),
    _brief(7, ["timing-move", "longform"]),
    _brief(8, ["particles", "short"], "9:16"),
    _brief(9, ["mask", "longform"]),
    _brief(10, ["blend", "takeover"]),
    _brief(11, ["unit-repair", "longform"]),
    _brief(12, ["overlay", "own-screen-geometry"], "9:16"),
]
PROJECT_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", ".."))
ARTIFACT = os.path.join(
    PROJECT_ROOT, "docs", "producer", "command-driven-editing", "contracts",
    "p4-scene-brief-matrix-v1.json")


class SceneBriefMatrixTests(unittest.TestCase):
    def test_twelve_briefs_cover_required_risks(self) -> None:
        proof = validate_brief_matrix(BRIEFS)
        self.assertEqual(proof["briefCount"], 12)
        self.assertEqual(proof["aspects"], ["16:9", "9:16"])

    def test_missing_particle_case_fails(self) -> None:
        broken = [{**row, "tags": [
            tag for tag in row["tags"] if tag != "particles"]}
                  for row in BRIEFS]
        with self.assertRaisesRegex(ValueError, "particles"):
            validate_brief_matrix(broken)

    def test_authoritative_artifact_carries_twelve_unique_briefs(self) -> None:
        with open(ARTIFACT, encoding="utf-8") as handle:
            artifact = json.load(handle)
        self.assertEqual(set(artifact), {
            "schemaVersion", "coverageGate", "scope", "briefs"})
        self.assertEqual(artifact["schemaVersion"], 1)
        self.assertEqual(artifact["coverageGate"], "passed")
        proof = validate_brief_matrix(artifact["briefs"])
        self.assertEqual(proof["briefCount"], 12)
        self.assertEqual(len(proof["fps"]), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
