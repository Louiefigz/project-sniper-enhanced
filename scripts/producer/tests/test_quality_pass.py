"""Controller ordering and fail-closed tests for the mechanical MP4 pass."""

from __future__ import annotations

import ast
import json
from unittest.mock import patch
import dataclasses
import unittest
from pathlib import Path
from typing import Any

from _common import pl  # noqa: F401
from _quality_pass_fixture import _Harness, _artifact, _media
from headless.quality_pass import (
    QualityPassError,
    run_quality_pass,
    _check_gate, _render_request, _replace_target, _check_candidate, _check_qc,
)
from headless.quality_pass_contract import (
    GraphicAssetRefV1,
    graphic_render_intent_digest,
)
from headless.quality_pass_outputs import (
    GateReceiptV1,
    validate_critic_receipts, QualityPassOutputError,
)


from headless.quality_pass_types import CandidatePlanV1, CompositeRequestV1, QcRequestV1, CriticRequestV1
from headless.repair_intent import RepairApplication, approved_plan_digest


def _historical_candidate(harness: _Harness) -> CandidatePlanV1:
    """Inert TEST receipt for private output-binding units; never admission evidence."""
    plan = harness.parent.decoded_plan()
    before = approved_plan_digest(plan)
    plan['graphicsTrack'][0]['spec']['accent'] = '#FFD400'
    raw = json.dumps(plan, separators=(',', ':'), sort_keys=True).encode()
    receipt = RepairApplication(raw, before, approved_plan_digest(plan),
        ('/graphicsTrack/0/spec/accent',), 'g-00000001', harness.request.repair_policy_id)
    return CandidatePlanV1(harness.parent, receipt)


class QualityPassTests(unittest.TestCase):
    def test_retired_execution_refuses_before_gate_media_or_seal(self) -> None:
        harness = _Harness()
        with patch('subprocess.Popen') as process, \
                self.assertRaisesRegex(ValueError, 'section-marker.*retired'):
            run_quality_pass(harness.request, harness.ports())
        process.assert_not_called()
        self.assertEqual(harness.events, ['resolve'])
        self.assertEqual(harness.parent.decoded_plan()['graphicsTrack'][0]['spec']['accent'], '#054BC9')

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

        request = _render_request(_historical_candidate(harness))
        with self.assertRaisesRegex(QualityPassError, "repair target"):
            _replace_target(request, malicious(request))
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

    def test_historical_wrong_gate_or_unchanged_overlay_is_not_bound(self) -> None:
        harness = _Harness()
        candidate = _historical_candidate(harness)
        gate = GateReceiptV1("0" * 64, harness.parent.base_projection_digest,
                            "SECTION_MARKER_ACCENT_V1", _artifact("gate.json", "bad-gate"))
        with self.assertRaises(QualityPassError):
            _check_gate(candidate, gate)
        with self.assertRaises(QualityPassError):
            _replace_target(_render_request(candidate), harness.parent.graphics_assets[0])
        self.assertEqual(harness.events, [])

    def test_historical_wrong_composite_or_qc_cannot_bind_receipts(self) -> None:
        harness = _Harness()
        candidate = _historical_candidate(harness)
        assets = _replace_target(_render_request(candidate), harness.render(_render_request(candidate)))
        request = CompositeRequestV1(harness.request.request_digest, candidate, assets)
        media = harness.composite(request)
        for changed in (dataclasses.replace(media, base_sha256="0" * 64),
                        dataclasses.replace(media, final=candidate.parent.base)):
            with self.subTest(media=changed), self.assertRaises(QualityPassError):
                _check_candidate(request, changed)
        qc_request = QcRequestV1(candidate, media, assets)
        qc = dataclasses.replace(harness.qc(qc_request), verdict="fail")
        with self.assertRaises((QualityPassError, QualityPassOutputError)):
            _check_qc(qc_request, qc)
        self.assertNotIn("critics", harness.events)

    def test_historical_duplicate_or_wrong_candidate_critics_are_rejected(self) -> None:
        harness = _Harness()
        candidate = _historical_candidate(harness)
        assets = (harness.render(_render_request(candidate)),)
        media = harness.composite(CompositeRequestV1(harness.request.request_digest, candidate, assets))
        qc = harness.qc(QcRequestV1(candidate, media, assets))
        values = harness.critics(CriticRequestV1(candidate, media, qc))
        for changed in ((values[0], values[0]),
                        (dataclasses.replace(values[0], candidate_sha256="0" * 64), values[1])):
            with self.subTest(critics=changed), self.assertRaises(QualityPassOutputError):
                validate_critic_receipts(changed, media.final.artifact.sha256, qc.receipt.sha256)
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
