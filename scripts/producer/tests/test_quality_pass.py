"""Controller ordering and fail-closed tests for the mechanical MP4 pass."""

from __future__ import annotations

import ast
import dataclasses
import unittest
from pathlib import Path
from typing import Any

from _common import pl  # noqa: F401
from _quality_pass_fixture import _Harness, _artifact, _media
from headless.quality_pass import (
    QualityPassError,
    run_quality_pass,
)
from headless.quality_pass_contract import (
    GraphicAssetRefV1,
    graphic_render_intent_digest,
)
from headless.quality_pass_outputs import (
    GateReceiptV1,
)


class QualityPassTests(unittest.TestCase):
    def test_happy_path_reports_only_observed_controller_dispatches(self) -> None:
        harness = _Harness()
        result = run_quality_pass(harness.request, harness.ports())
        self.assertEqual(result.status, "CANDIDATE_CONTRACT_VALIDATED")
        self.assertFalse(result.controller_writer_port_exposed)
        self.assertFalse(result.controller_base_render_port_exposed)
        self.assertEqual(result.controller_overlay_dispatches, 1)
        self.assertEqual(result.controller_composite_dispatches, 1)
        self.assertEqual(
            harness.events,
            [
                "resolve",
                "gate",
                "wait",
                "render",
                "composite",
                "qc",
                "queue",
                "critics",
                "seal",
            ],
        )
        self.assertEqual(len(result.timing.spans), 11)

    def test_render_callback_cannot_mutate_controller_target(self) -> None:
        harness = _Harness()

        def malicious(request: Any) -> GraphicAssetRefV1:
            target = request.decoded_target()
            target["kind"] = "not-section-marker"
            target["spec"]["accent"] = "#ABCDEF"
            return GraphicAssetRefV1(
                request.candidate.application.graphic_id,
                graphic_render_intent_digest(target),
                _media("graphics/g-00000001.mov", "malicious-overlay"),
                _artifact("graphics/g-00000001.receipt.json", "malicious"),
                "1" * 64,
                "2" * 64,
            )

        harness.render = malicious
        with self.assertRaisesRegex(QualityPassError, "repair target"):
            run_quality_pass(harness.request, harness.ports())
        self.assertNotIn("composite", harness.events)

    def test_stale_policy_or_parent_never_reaches_deterministic_gates(self) -> None:
        for mutation in ("policy", "parent"):
            harness = _Harness()
            if mutation == "policy":
                harness.request = dataclasses.replace(
                    harness.request, quality_policy_id="0" * 64
                )
            else:
                harness.override["parent"] = dataclasses.replace(
                    harness.parent,
                    ref=dataclasses.replace(harness.parent.ref, commit_digest="0" * 64),
                )
            with self.subTest(mutation=mutation), self.assertRaises(
                (QualityPassError, RuntimeError)
            ):
                run_quality_pass(harness.request, harness.ports())
            self.assertNotIn("gate", harness.events)

    def test_wrong_gate_or_unchanged_overlay_stops_before_composite(self) -> None:
        cases = []
        gate_harness = _Harness()
        gate_harness.override["gate"] = GateReceiptV1(
            "0" * 64,
            gate_harness.parent.base_projection_digest,
            "SECTION_MARKER_ACCENT_V1",
            _artifact("gate.json", "bad-gate"),
        )
        cases.append(gate_harness)
        render_harness = _Harness()
        render_harness.override["render"] = render_harness.parent.graphics_assets[0]
        cases.append(render_harness)
        for harness in cases:
            with self.subTest(events=harness.events), self.assertRaises(
                QualityPassError
            ):
                run_quality_pass(harness.request, harness.ports())
            self.assertNotIn("composite", harness.events)

    def test_wrong_composite_or_qc_never_reaches_critics(self) -> None:
        composite_harness = _Harness()
        base = composite_harness.composite

        def wrong_composite(request: Any) -> object:
            value = base(request)
            return dataclasses.replace(value, base_sha256="0" * 64)

        composite_harness.composite = wrong_composite
        alias_harness = _Harness()
        alias_composite = alias_harness.composite

        def base_as_final(request: Any) -> object:
            value = alias_composite(request)
            return dataclasses.replace(value, final=request.candidate.parent.base)

        alias_harness.composite = base_as_final
        qc_harness = _Harness()
        original_qc = qc_harness.qc

        def wrong_qc(request: Any) -> object:
            return dataclasses.replace(original_qc(request), verdict="fail")

        qc_harness.qc = wrong_qc
        for harness in (composite_harness, alias_harness, qc_harness):
            with self.subTest(events=harness.events), self.assertRaises(
                QualityPassError
            ):
                run_quality_pass(harness.request, harness.ports())
            self.assertNotIn("critics", harness.events)

    def test_duplicate_or_wrong_candidate_critics_never_seal(self) -> None:
        for mutation in ("duplicate", "wrong-candidate"):
            harness = _Harness()
            original = harness.critics

            def bad(request: Any, kind: str = mutation) -> object:
                values = original(request)
                if kind == "duplicate":
                    return (values[0], values[0])
                return (
                    dataclasses.replace(values[0], candidate_sha256="0" * 64),
                    values[1],
                )

            harness.critics = bad
            with self.subTest(mutation=mutation), self.assertRaises(QualityPassError):
                run_quality_pass(harness.request, harness.ports())
            self.assertNotIn("seal", harness.events)

    def test_controller_imports_exclude_legacy_render_gui_and_palmier(self) -> None:
        root = Path(__file__).resolve().parents[1] / "headless"
        names = []
        for filename in (
            "quality_pass.py",
            "quality_pass_contract.py",
            "quality_pass_outputs.py",
            "quality_timing.py",
        ):
            tree = ast.parse((root / filename).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    names.append(node.module or "")
        forbidden = ("palmier", "assemble", "render", "src.app", "gui")
        self.assertFalse([name for name in names if name.startswith(forbidden)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
