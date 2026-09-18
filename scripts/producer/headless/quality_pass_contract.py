"""Closed request and approved-parent types for headless MP4 quality passes."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from fingerprints import base_plan_digest, plan_content_hash

from .artifact_contract import (
    ArtifactContractError,
    ArtifactRefV1,
    MediaFactsV1,
    MediaRefV1,
    validate_artifact_ref as _validate_artifact_ref,
    validate_media_ref as _validate_media_ref,
)
from .quality_pass_input import (
    QualityPassInputError,
    QualityPassInputV1,
    parse_quality_pass_input as _parse_quality_pass_input,
    validate_quality_pass_input as _validate_quality_pass_input,
)
from .repair_intent import (
    ParentRefV1,
    approved_plan_digest,
    validate_parent_ref,
)

__all__ = [
    "ApprovedParentV1",
    "ArtifactRefV1",
    "GraphicAssetRefV1",
    "MediaFactsV1",
    "MediaRefV1",
    "ParentRefV1",
    "QualityPassContractError",
    "QualityPassInputV1",
    "graphic_render_intent_digest",
    "parse_quality_pass_input",
    "validate_approved_parent",
    "validate_artifact_ref",
    "validate_graphic_asset",
    "validate_media_ref",
    "validate_quality_pass_input",
]

_DIGEST = re.compile(r"[0-9a-f]{64}")
_GRAPHIC_ID = re.compile(r"g-[0-9a-z]{8}")
_LENSES = ("composition", "editorial")


class QualityPassContractError(RuntimeError):
    """A quality-pass request or resolved approved parent is not closed."""


@dataclass(frozen=True)
class GraphicAssetRefV1:
    """One stable graphic's generation-local, already-validated render."""

    graphic_id: str
    render_intent_digest: str
    media: MediaRefV1
    receipt: ArtifactRefV1
    render_artifact_digest: str
    render_build_digest: str


@dataclass(frozen=True)
class ApprovedParentV1:
    """Controller-resolved parent; callers never construct this from JSON."""

    ref: ParentRefV1
    generation_verification: ArtifactRefV1
    repair_policy_id: str
    quality_policy_id: str
    plan_json: bytes
    plan_artifact: ArtifactRefV1
    plan_content_hash: str
    base: MediaRefV1
    base_plan: ArtifactRefV1
    base_receipt: ArtifactRefV1
    base_projection_digest: str
    timeline_map: ArtifactRefV1
    prebound_clips: ArtifactRefV1
    graphics_assets: tuple[GraphicAssetRefV1, ...]
    final: MediaRefV1
    assembly_receipt: ArtifactRefV1
    cover: ArtifactRefV1
    cover_proof: ArtifactRefV1
    qc_receipt: ArtifactRefV1
    final_approval: ArtifactRefV1

    def decoded_plan(self) -> dict:
        """Return a disposable plan copy while retaining immutable source bytes."""
        return json.loads(self.plan_json)


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise QualityPassContractError("quality-pass JSON is not canonical") from exc
    return encoded.encode("ascii")


def parse_quality_pass_input(value: object) -> QualityPassInputV1:
    """Parse exact V1 input; no semantic fallback or alternate realization."""
    try:
        return _parse_quality_pass_input(value)
    except QualityPassInputError as exc:
        raise QualityPassContractError(str(exc)) from exc


def validate_quality_pass_input(value: object) -> None:
    """Reject direct dataclass construction that bypassed the parser."""
    try:
        _validate_quality_pass_input(value)
    except QualityPassInputError as exc:
        raise QualityPassContractError(str(exc)) from exc


def validate_artifact_ref(value: object) -> None:
    """Require one normalized nonempty generation-relative file reference."""
    try:
        _validate_artifact_ref(value)
    except ArtifactContractError as exc:
        raise QualityPassContractError(str(exc)) from exc


def validate_media_ref(value: object) -> None:
    """Require complete positive media facts bound to artifact byte length."""
    try:
        _validate_media_ref(value)
    except ArtifactContractError as exc:
        raise QualityPassContractError(str(exc)) from exc


def validate_graphic_asset(value: object) -> None:
    """Require one exact stable-ID render asset and sealed receipt binding."""
    if type(value) is not GraphicAssetRefV1:
        raise QualityPassContractError("graphic asset reference is invalid")
    validate_media_ref(value.media)
    validate_artifact_ref(value.receipt)
    digests = (
        value.render_intent_digest,
        value.render_artifact_digest,
        value.render_build_digest,
    )
    valid = type(value.graphic_id) is str and bool(
        _GRAPHIC_ID.fullmatch(value.graphic_id)
    )
    if not valid or not all(
        type(item) is str and _DIGEST.fullmatch(item) for item in digests
    ):
        raise QualityPassContractError("graphic asset identity is invalid")


def _plan_bytes(parent: ApprovedParentV1) -> dict:
    try:
        plan = json.loads(parent.plan_json)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualityPassContractError("approved plan bytes are invalid") from exc
    if not isinstance(plan, dict) or _canonical(plan) != parent.plan_json:
        raise QualityPassContractError("approved plan is not exact canonical JSON")
    raw_digest = hashlib.sha256(parent.plan_json).hexdigest()
    if (
        parent.plan_artifact.sha256 != raw_digest
        or parent.plan_artifact.size_bytes != len(parent.plan_json)
    ):
        raise QualityPassContractError("approved plan artifact binding is invalid")
    return plan


def _plan_graphic_ids(plan: dict) -> tuple[str, ...]:
    track = plan.get("graphicsTrack")
    if not isinstance(track, list) or not track:
        raise QualityPassContractError("approved parent has no graphics track")
    ids = tuple(row.get("id") for row in track if isinstance(row, dict))
    valid = (
        len(ids) == len(track)
        and len(set(ids)) == len(ids)
        and all(type(item) is str and _GRAPHIC_ID.fullmatch(item) for item in ids)
    )
    if not valid:
        raise QualityPassContractError("approved graphics identities are invalid")
    return ids


def _validate_parent_refs(parent: ApprovedParentV1) -> None:
    for value in (
        parent.generation_verification,
        parent.plan_artifact,
        parent.base_plan,
        parent.base_receipt,
        parent.timeline_map,
        parent.prebound_clips,
        parent.assembly_receipt,
        parent.cover,
        parent.cover_proof,
        parent.qc_receipt,
        parent.final_approval,
    ):
        validate_artifact_ref(value)
    validate_media_ref(parent.base)
    validate_media_ref(parent.final)
    for asset in parent.graphics_assets:
        validate_graphic_asset(asset)


def _parent_artifacts(parent: ApprovedParentV1) -> tuple[ArtifactRefV1, ...]:
    direct = (
        parent.generation_verification,
        parent.plan_artifact,
        parent.base.artifact,
        parent.base_plan,
        parent.base_receipt,
        parent.timeline_map,
        parent.prebound_clips,
        parent.final.artifact,
        parent.assembly_receipt,
        parent.cover,
        parent.cover_proof,
        parent.qc_receipt,
        parent.final_approval,
    )
    graphics = tuple(
        ref
        for asset in parent.graphics_assets
        for ref in (asset.media.artifact, asset.receipt)
    )
    return direct + graphics


def validate_approved_parent(parent: object) -> None:
    """Validate the complete already-resolved generation contract in memory."""
    if type(parent) is not ApprovedParentV1:
        raise QualityPassContractError("approved parent instance is invalid")
    try:
        validate_parent_ref(parent.ref)
    except RuntimeError as exc:
        raise QualityPassContractError(str(exc)) from exc
    _validate_parent_refs(parent)
    plan = _plan_bytes(parent)
    digests = (
        parent.repair_policy_id,
        parent.quality_policy_id,
        parent.plan_content_hash,
        parent.base_projection_digest,
    )
    if not all(type(item) is str and _DIGEST.fullmatch(item) for item in digests):
        raise QualityPassContractError("approved parent digest is invalid")
    valid = (
        parent.ref.plan_digest == approved_plan_digest(plan)
        and parent.plan_content_hash == plan_content_hash(plan)
        and parent.base_projection_digest == base_plan_digest(plan)
    )
    if not valid:
        raise QualityPassContractError("approved parent plan identity is invalid")
    paths = tuple(ref.relative_path for ref in _parent_artifacts(parent))
    if len(set(paths)) != len(paths):
        raise QualityPassContractError("approved parent artifact paths alias")
    plan_ids = _plan_graphic_ids(plan)
    asset_ids = tuple(asset.graphic_id for asset in parent.graphics_assets)
    if asset_ids != plan_ids:
        raise QualityPassContractError(
            "approved graphic assets do not exactly match plan order"
        )
    for row, asset in zip(plan["graphicsTrack"], parent.graphics_assets):
        if asset.render_intent_digest != graphic_render_intent_digest(row):
            raise QualityPassContractError(
                "approved graphic render intent does not match plan"
            )


def graphic_render_intent_digest(entry: dict) -> str:
    """Bind a graphic asset to the exact canonical stable-ID plan row."""
    if type(entry) is not dict:
        raise QualityPassContractError("graphic render intent is invalid")
    return hashlib.sha256(
        b"sniper-graphic-render-intent-v1\0" + _canonical(entry)
    ).hexdigest()
