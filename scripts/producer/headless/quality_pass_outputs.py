"""Typed intermediate receipts for the headless MP4 quality-pass controller."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass

from .quality_pass_contract import (
    ArtifactRefV1,
    GraphicAssetRefV1,
    MediaRefV1,
    QualityPassContractError,
    validate_artifact_ref,
    validate_graphic_asset,
    validate_media_ref,
)

_DIGEST = re.compile(r"[0-9a-f]{64}")
_LENSES = {"composition", "editorial"}


class QualityPassOutputError(RuntimeError):
    """A stage output is malformed or contradicts upstream authority."""


@dataclass(frozen=True)
class GateReceiptV1:
    """Deterministic eligibility result for the frozen repaired plan."""

    plan_digest: str
    base_projection_digest: str
    effect_class: str
    receipt: ArtifactRefV1


@dataclass(frozen=True)
class CandidateMediaV1:
    """Fully recomposited private MP4 and exact assembly evidence."""

    plan_digest: str
    base_sha256: str
    graphic_asset_set_digest: str
    final: MediaRefV1
    assembly_receipt: ArtifactRefV1
    cover: ArtifactRefV1
    cover_proof: ArtifactRefV1
    proxy: MediaRefV1 | None
    proxy_disposition: str


@dataclass(frozen=True)
class QcReceiptV1:
    """Complete deterministic QC closure for one exact candidate MP4."""

    plan_digest: str
    final_sha256: str
    assembly_receipt_sha256: str
    quality_policy_id: str
    audit: ArtifactRefV1
    full_decode: ArtifactRefV1
    effect_proof: ArtifactRefV1
    receipt: ArtifactRefV1
    verdict: str


@dataclass(frozen=True)
class CriticReceiptV1:
    """One rendered lens verdict bound to the same immutable evidence."""

    lens: str
    verdict: str
    candidate_sha256: str
    evidence_digest: str
    artifact: ArtifactRefV1


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode("ascii")


def graphic_asset_set_digest(assets: tuple[GraphicAssetRefV1, ...]) -> str:
    """Hash the exact ordered graphic render set consumed by composition."""
    if type(assets) is not tuple or not assets:
        raise QualityPassOutputError("graphic asset set is empty")
    for asset in assets:
        try:
            validate_graphic_asset(asset)
        except QualityPassContractError as exc:
            raise QualityPassOutputError(str(exc)) from exc
    raw = _canonical([asdict(asset) for asset in assets])
    return hashlib.sha256(b"sniper-graphic-asset-set-v1\0" + raw).hexdigest()


def _digests(*values: str) -> bool:
    return all(type(value) is str and _DIGEST.fullmatch(value) for value in values)


def validate_gate_receipt(value: object) -> None:
    """Require a positive receipt for the sole registered effect class."""
    if type(value) is not GateReceiptV1:
        raise QualityPassOutputError("deterministic gate receipt is invalid")
    try:
        validate_artifact_ref(value.receipt)
    except QualityPassContractError as exc:
        raise QualityPassOutputError(str(exc)) from exc
    if (
        not _digests(value.plan_digest, value.base_projection_digest)
        or type(value.effect_class) is not str
        or value.effect_class != "SECTION_MARKER_ACCENT_V1"
    ):
        raise QualityPassOutputError("deterministic gate identity is invalid")


def validate_candidate(value: object) -> None:
    """Require complete recomposition outputs with explicit proxy treatment."""
    if type(value) is not CandidateMediaV1:
        raise QualityPassOutputError("candidate media result is invalid")
    try:
        validate_media_ref(value.final)
        validate_artifact_ref(value.assembly_receipt)
        validate_artifact_ref(value.cover)
        validate_artifact_ref(value.cover_proof)
        if value.proxy is not None:
            validate_media_ref(value.proxy)
    except QualityPassContractError as exc:
        raise QualityPassOutputError(str(exc)) from exc
    valid = (
        _digests(value.plan_digest, value.base_sha256, value.graphic_asset_set_digest)
        and type(value.proxy_disposition) is str
        and value.proxy_disposition in {"generated", "omitted-by-policy"}
        and ((value.proxy_disposition == "generated") == (value.proxy is not None))
    )
    if not valid:
        raise QualityPassOutputError("candidate media identity is invalid")
    refs = [
        value.final.artifact,
        value.assembly_receipt,
        value.cover,
        value.cover_proof,
    ]
    if value.proxy is not None:
        refs.append(value.proxy.artifact)
    paths = tuple(ref.relative_path for ref in refs)
    if len(set(paths)) != len(paths):
        raise QualityPassOutputError("candidate artifact paths alias")


def validate_qc_receipt(value: object) -> None:
    """Require Audit B, full decode, and requested-effect evidence to pass."""
    if type(value) is not QcReceiptV1:
        raise QualityPassOutputError("quality receipt is invalid")
    try:
        for artifact in (
            value.audit,
            value.full_decode,
            value.effect_proof,
            value.receipt,
        ):
            validate_artifact_ref(artifact)
    except QualityPassContractError as exc:
        raise QualityPassOutputError(str(exc)) from exc
    valid = (
        _digests(
            value.plan_digest,
            value.final_sha256,
            value.assembly_receipt_sha256,
            value.quality_policy_id,
        )
        and type(value.verdict) is str
        and value.verdict == "pass"
    )
    if not valid:
        raise QualityPassOutputError("quality receipt did not pass")


def validate_critic_receipts(
    values: object, candidate_sha256: str, evidence_digest: str
) -> None:
    """Require exactly one passing composition and editorial rendered critic."""
    valid_inputs = _digests(candidate_sha256, evidence_digest)
    if type(values) is not tuple or len(values) != 2 or not valid_inputs:
        raise QualityPassOutputError("rendered critic set must contain two lenses")
    lenses = []
    for value in values:
        if type(value) is not CriticReceiptV1:
            raise QualityPassOutputError("rendered critic receipt is invalid")
        try:
            validate_artifact_ref(value.artifact)
        except QualityPassContractError as exc:
            raise QualityPassOutputError(str(exc)) from exc
        valid = (
            type(value.lens) is str
            and type(value.verdict) is str
            and value.lens in _LENSES
            and value.verdict == "pass"
            and value.candidate_sha256 == candidate_sha256
            and value.evidence_digest == evidence_digest
            and _digests(value.candidate_sha256, value.evidence_digest)
        )
        if not valid:
            raise QualityPassOutputError("rendered critic identity is invalid")
        lenses.append(value.lens)
    if set(lenses) != _LENSES or len(set(lenses)) != 2:
        raise QualityPassOutputError("rendered critic lenses are incomplete")
    paths = tuple(value.artifact.relative_path for value in values)
    if len(set(paths)) != len(paths):
        raise QualityPassOutputError("rendered critic artifacts alias")
