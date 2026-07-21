"""Typed controller-port harness for mechanical quality-pass tests."""

from __future__ import annotations

import dataclasses
import hashlib
import time
from typing import Any

from headless.quality_pass import QualityPassPorts
from headless.quality_pass_contract import (
    ArtifactRefV1,
    GraphicAssetRefV1,
    MediaFactsV1,
    MediaRefV1,
    graphic_render_intent_digest,
    parse_quality_pass_input,
)
from headless.quality_pass_outputs import (
    CandidateMediaV1,
    CriticReceiptV1,
    GateReceiptV1,
    QcReceiptV1,
    graphic_asset_set_digest,
)
from headless.quality_timing import TimingRecorder
from headless.repair_intent import current_accent_policy
from test_quality_pass_contract import _approved, _document, _plan


def _artifact(path: str, seed: str, size: int = 10) -> ArtifactRefV1:
    return ArtifactRefV1(path, hashlib.sha256(seed.encode()).hexdigest(), size)


def _media(path: str, seed: str) -> MediaRefV1:
    artifact = _artifact(path, seed, 100)
    facts = MediaFactsV1(
        1080, 1920, 4.0, 30, 1, 120, 100, "h264", "yuv420p", "High", "none", "aac"
    )
    return MediaRefV1(artifact, facts)


class _Harness:
    def __init__(self) -> None:
        document = _document(_plan())
        policy = current_accent_policy().policy_id
        document["repairPolicyId"] = policy
        self.request = parse_quality_pass_input(document)
        self.parent = dataclasses.replace(
            _approved(),
            repair_policy_id=policy,
            quality_policy_id=self.request.quality_policy_id,
        )
        self.events: list[str] = []
        self.spans: list[object] = []
        self.override: dict[str, object] = {}

    def _event(self, name: str) -> None:
        self.events.append(name)

    def resolve(self, _ref: object) -> object:
        self._event("resolve")
        return self.override.get("parent", self.parent)

    def gate(self, candidate: Any) -> object:
        self._event("gate")
        good = GateReceiptV1(
            candidate.application.after_digest,
            candidate.parent.base_projection_digest,
            "SECTION_MARKER_ACCENT_V1",
            _artifact("gate.json", "gate"),
        )
        return self.override.get("gate", good)

    def wait(self, _request: object) -> None:
        self._event("wait")

    def render(self, request: Any) -> object:
        self._event("render")
        good = GraphicAssetRefV1(
            request.candidate.application.graphic_id,
            graphic_render_intent_digest(request.decoded_target()),
            _media("graphics/g-00000001.mov", "changed-overlay"),
            _artifact("graphics/g-00000001.receipt.json", "render-receipt"),
            "1" * 64,
            "2" * 64,
        )
        return self.override.get("render", good)

    def composite(self, request: Any) -> object:
        self._event("composite")
        good = CandidateMediaV1(
            request.candidate.application.after_digest,
            request.candidate.parent.base.artifact.sha256,
            graphic_asset_set_digest(request.graphic_assets),
            _media("candidate/final.mp4", "candidate-final"),
            _artifact("candidate/assembly-receipt.json", "assembly"),
            _artifact("candidate/cover.png", "cover"),
            _artifact("candidate/cover-proof.json", "cover-proof"),
            None,
            "omitted-by-policy",
        )
        return self.override.get("composite", good)

    def qc(self, request: Any) -> object:
        self._event("qc")
        good = QcReceiptV1(
            request.candidate.application.after_digest,
            request.media.final.artifact.sha256,
            request.media.assembly_receipt.sha256,
            request.candidate.parent.quality_policy_id,
            _artifact("candidate/audit.json", "audit"),
            _artifact("candidate/full-decode.json", "decode"),
            _artifact("candidate/effect-proof.json", "effect"),
            _artifact("candidate/qc-receipt.json", "qc"),
            "pass",
        )
        return self.override.get("qc", good)

    def queue(self, request: object) -> object:
        self._event("queue")
        return request

    def critics(self, request: Any) -> object:
        self._event("critics")
        digest = request.media.final.artifact.sha256
        evidence = request.qc.receipt.sha256
        good = tuple(
            CriticReceiptV1(
                lens,
                "pass",
                digest,
                evidence,
                _artifact(f"candidate/{lens}-review.json", lens),
            )
            for lens in ("composition", "editorial")
        )
        return self.override.get("critics", good)

    def seal(self, _request: object) -> ArtifactRefV1:
        self._event("seal")
        return _artifact("candidate/evidence.json", "evidence")

    def ports(self) -> QualityPassPorts:
        return QualityPassPorts(
            self.resolve,
            self.gate,
            self.wait,
            self.render,
            self.composite,
            self.qc,
            self.queue,
            self.critics,
            self.seal,
            lambda: TimingRecorder(time.monotonic_ns, self.spans.append),
        )
