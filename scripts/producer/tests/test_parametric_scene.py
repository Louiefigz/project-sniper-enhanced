"""Closed parametric briefs compile into governed SceneSpec bundles."""
from __future__ import annotations

import os
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from graphics.parametric_scene import compile_parametric_scene
from graphics.scene_contract import SceneContractError
from graphics.scene_lint import scene_bundle_errors
from graphics.visual_source_policy import policy
from graphics.visual_source_receipt import subject_hash


def _with_source(brief: dict) -> dict:
    """Bind synthetic compiler intent before generation; never creative approval."""
    request = Path(__file__).parent / "fixtures/fire-sparkles-bundle/bundle.json"
    port = policy()["integrated"]["line-swap"]
    brief["visualSources"] = {
        "schemaVersion": 1, "policyVersion": policy()["policyVersion"],
        "subjectSha256": subject_hash(brief),
        "request": {"path": str(request), "sha256": hashlib.sha256(request.read_bytes()).hexdigest()},
        "decisions": [{"route": "custom", "targets": ["parametric-content"],
            "reason": "TEST-only fixed geometry for a compiler contract case.",
            "gapType": "missing-capability", "query": "TEST independent compiler shape geometry",
            "gap": "The inspected single text swap lacks this synthetic compiler's separate shape fields.",
            "scope": "Generate only the selected TEST grammar with the exact fixture content.",
            "inspected": [{"id": "line-swap", "sourceSha256": port["upstreamSha256"],
                "limitation": "Its two text fields do not expose this TEST compiler geometry API."}]}]}
    return brief


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
    return _with_source({
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
    })


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

    def test_source_decisions_bind_both_brief_and_generated_scene_without_mutation(self) -> None:
        brief = _brief()
        before = copy.deepcopy(brief)
        with tempfile.TemporaryDirectory() as tmp:
            scene, _ = compile_parametric_scene(brief, os.path.join(tmp, "attempt"))
        self.assertEqual(brief, before)
        self.assertEqual(scene["visualSources"]["decisions"], brief["visualSources"]["decisions"])
        self.assertNotEqual(scene["visualSources"]["subjectSha256"], brief["visualSources"]["subjectSha256"])

    def test_stale_missing_and_false_catalog_identity_fail_before_writing(self) -> None:
        for mutation in ("stale", "missing", "catalog"):
            brief = _brief()
            if mutation == "stale":
                brief["content"]["leftText"] = "Changed after source review"
            elif mutation == "missing":
                brief["visualSources"] = None
            else:
                port = policy()["integrated"]["line-swap"]
                brief["visualSources"]["decisions"] = [{"route": "catalog", "targets": ["parametric-content"],
                    "reason": "TEST false catalog label", "configuration": "TEST generated geometry",
                    "catalog": [{"id": "line-swap", "sourceSha256": port["upstreamSha256"]}]}]
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                attempt = os.path.join(tmp, "attempt")
                with self.assertRaises(SceneContractError):
                    compile_parametric_scene(brief, attempt)
                self.assertFalse(os.path.exists(attempt))

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
