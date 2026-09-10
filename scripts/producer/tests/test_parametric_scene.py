"""Closed parametric briefs compile into governed SceneSpec bundles."""
from __future__ import annotations

import os
import tempfile
import unittest

from graphics.parametric_scene import compile_parametric_scene
from graphics.scene_contract import SceneContractError
from graphics.scene_lint import scene_bundle_errors


def _brief(grammar: str = "split-cards") -> dict:
    content = {
        "split-cards": {"leftText": "Before", "rightText": "After"},
        "stat-stack": {
            "title": "Results", "stat1": "Fast", "stat2": "Safe",
            "stat3": "Editable",
        },
        "labeled-arrow": {
            "source": "Raw cut", "label": "local repair",
            "target": "Reviewed cut",
        },
    }[grammar]
    return {
        "grammar": grammar, "sceneId": f"scene-{grammar}",
        "timing": {
            "startFrame": 120, "endFrameExclusive": 210,
            "fps": {"numerator": "30000", "denominator": "1001"},
            "timelineMapHash": "c" * 64,
        },
        "canvas": {"width": 1920, "height": 1080},
        "content": {**content, "accent": "#054BC9"},
        "renderMode": "overlay-alpha",
        "provenance": {"origin": "autopilot"},
        "captionPolicy": "suppress-overlap",
    }


class ParametricSceneTests(unittest.TestCase):
    def test_every_closed_grammar_builds_a_linted_bundle(self) -> None:
        for grammar in ("split-cards", "stat-stack", "labeled-arrow"):
            with self.subTest(grammar=grammar), tempfile.TemporaryDirectory() as tmp:
                attempt = os.path.join(tmp, "attempt")
                scene, snapshot = compile_parametric_scene(
                    _brief(grammar), attempt)
                self.assertEqual(scene_bundle_errors(scene, snapshot), [])
                self.assertEqual(
                    scene["composition"]["bundleHash"], snapshot.digest)
                self.assertEqual(
                    snapshot.manifest["runtime"]["hyperframesVersion"],
                    "0.8.31")

    def test_unknown_grammar_fails_before_writing(self) -> None:
        brief = _brief()
        brief["grammar"] = "arbitrary-javascript"
        with tempfile.TemporaryDirectory() as tmp:
            attempt = os.path.join(tmp, "attempt")
            with self.assertRaisesRegex(SceneContractError, "unsupported"):
                compile_parametric_scene(brief, attempt)
            self.assertFalse(os.path.exists(attempt))

    def test_real_copy_overflow_is_bounded(self) -> None:
        brief = _brief()
        brief["content"]["leftText"] = "x" * 161
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SceneContractError, "1..160"):
                compile_parametric_scene(
                    brief, os.path.join(tmp, "attempt"))

    def test_attempt_directory_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attempt = os.path.join(tmp, "attempt")
            os.mkdir(attempt)
            with self.assertRaisesRegex(SceneContractError, "must not exist"):
                compile_parametric_scene(_brief(), attempt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
