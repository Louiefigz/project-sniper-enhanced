"""Normalize one qualified admitted-render result into a durable receipt."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .artifact_contract import MediaRefV1, validate_media_ref
from .graphic_render_receipt_semantics import (
    GraphicRenderReceiptV1,
    parse_graphic_render_receipt_v1,
)
from .graphic_render_receipt_writer_wire import (
    encode_receipt,
    is_r0_media,
    media_document,
    proof_methods,
    validate_lane_leaves,
)
from .quality_pass_contract import graphic_render_intent_digest

_DIGEST = re.compile(r"[0-9a-f]{64}")
_GRAPHIC_ID = re.compile(r"g-[0-9a-z]{8}")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_LANE_KEYS = frozenset(
    "artifactDigest cacheBinding launcherSha256 outputBinding "
    "renderBuildReceipt rendererMode result selectionId".split()
)
_RESULT_KEYS = frozenset("cached fmt key kind path proof".split())
_OUTPUT_KEYS = frozenset("device inode sha256 sizeBytes".split())
_CACHE_KEYS = frozenset("device inode ownerReceiptSha256".split())
_ASSET_KEYS = frozenset(
    "codec durationS fps frameCount height pixelFormat profile sha256 "
    "sizeBytes width".split()
)


class GraphicRenderReceiptWriterError(RuntimeError):
    """A supposedly validated lane result cannot form a durable receipt."""


@dataclass(frozen=True)
class GraphicRenderReceiptAuthorityV1:
    """Controller-owned identities unavailable from worker output alone."""

    ordinal: int
    graphic_id: str
    selection_id: str
    admission_artifact_digest: str
    request_digest: str
    quality_policy_id: str
    media: MediaRefV1
    render_build_digest: str
    render_input_key: str
    source_snapshot_sha256: str
    runtime_image_id: str
    proof_ffmpeg_sha256: str
    proof_ffprobe_sha256: str


@dataclass(frozen=True)
class _LaneEvidenceV1:
    admission_artifact_digest: str
    kind: str
    render_input_key: str
    source_snapshot_sha256: str
    proof: dict


def _exact(value: object, keys: frozenset[str], label: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise GraphicRenderReceiptWriterError(f"{label} keys are invalid")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise GraphicRenderReceiptWriterError(f"{label} is invalid")
    return value


def _authority(value: object) -> GraphicRenderReceiptAuthorityV1:
    if type(value) is not GraphicRenderReceiptAuthorityV1:
        raise GraphicRenderReceiptWriterError(
            "graphic render receipt authority is invalid"
        )
    try:
        validate_media_ref(value.media)
    except RuntimeError as exc:
        raise GraphicRenderReceiptWriterError(
            "graphic render receipt media is invalid"
        ) from exc
    digests = (
        value.admission_artifact_digest,
        value.request_digest,
        value.quality_policy_id,
        value.render_build_digest,
        value.render_input_key,
        value.source_snapshot_sha256,
        value.proof_ffmpeg_sha256,
        value.proof_ffprobe_sha256,
    )
    valid = type(value.ordinal) is int and value.ordinal >= 0
    valid = valid and all(
        type(item) is str and _DIGEST.fullmatch(item) for item in digests
    )
    valid = valid and type(value.graphic_id) is str
    valid = valid and bool(_GRAPHIC_ID.fullmatch(value.graphic_id))
    valid = valid and type(value.selection_id) is str and value.selection_id
    valid = valid and value.selection_id == value.graphic_id
    valid = valid and type(value.runtime_image_id) is str
    valid = valid and bool(_IMAGE_ID.fullmatch(value.runtime_image_id))
    valid = valid and value.proof_ffmpeg_sha256 != value.proof_ffprobe_sha256
    valid = valid and is_r0_media(value.media)
    if not valid:
        raise GraphicRenderReceiptWriterError(
            "graphic render receipt authority values are invalid"
        )
    return value


def _lane(value: object, authority: GraphicRenderReceiptAuthorityV1) -> _LaneEvidenceV1:
    lane = _exact(value, _LANE_KEYS, "admitted render result")
    result = _exact(lane["result"], _RESULT_KEYS, "render worker result")
    output = _exact(lane["outputBinding"], _OUTPUT_KEYS, "render output binding")
    cache = _exact(lane["cacheBinding"], _CACHE_KEYS, "render cache binding")
    try:
        validate_lane_leaves(lane, result, output, cache)
    except ValueError as exc:
        raise GraphicRenderReceiptWriterError(str(exc)) from exc
    proof = result["proof"]
    runtime = proof.get("runtimeAttestation") if type(proof) is dict else None
    runtime_map = runtime if type(runtime) is dict else {}
    actual = (
        lane["artifactDigest"],
        lane["selectionId"],
        lane["renderBuildReceipt"],
        lane["rendererMode"],
        result["fmt"],
        result["key"],
        runtime_map.get("snapshotSha256"),
        runtime_map.get("imageId"),
    )
    expected = (
        authority.admission_artifact_digest,
        authority.selection_id,
        authority.render_build_digest,
        "sealed-oci-v2",
        "mov",
        authority.render_input_key,
        authority.source_snapshot_sha256,
        authority.runtime_image_id,
    )
    if actual != expected:
        raise GraphicRenderReceiptWriterError(
            "admitted render lane identity is invalid"
        )
    return _lane_evidence(lane, result, output, proof)


def _lane_evidence(
    lane: dict, result: dict, output: dict, proof: dict
) -> _LaneEvidenceV1:
    if type(proof) is not dict:
        raise GraphicRenderReceiptWriterError("render proof is invalid")
    runtime = proof.get("runtimeAttestation")
    copy = proof.get("copy")
    asset = proof.get("asset")
    asset_map = asset if type(asset) is dict else {}
    valid = type(runtime) is dict and type(copy) is dict and type(asset) is dict
    valid = valid and type(copy.get("renderInputKey")) is str
    valid = valid and copy.get("renderInputKey") == result["key"]
    valid = valid and type(proof.get("kind")) is str
    valid = valid and result["kind"] == proof.get("kind")
    valid = valid and type(asset_map.get("sha256")) is str
    valid = valid and output.get("sha256") == asset_map.get("sha256")
    valid = valid and type(asset_map.get("sizeBytes")) is int
    valid = valid and output.get("sizeBytes") == asset_map.get("sizeBytes")
    if not valid:
        raise GraphicRenderReceiptWriterError("render proof does not match lane output")
    return _LaneEvidenceV1(
        _digest(lane["artifactDigest"], "render admission artifact"),
        result["kind"],
        result["key"],
        _digest(runtime.get("snapshotSha256"), "render source snapshot"),
        proof,
    )


def _media_matches(authority: GraphicRenderReceiptAuthorityV1, proof: dict) -> None:
    asset = _exact(proof.get("asset"), _ASSET_KEYS, "render proof asset")
    media, facts = authority.media.artifact, authority.media.facts
    expected = (
        media.sha256,
        media.size_bytes,
        facts.width,
        facts.height,
        facts.duration_seconds,
        facts.fps,
        facts.frame_count,
        facts.video_codec,
        facts.pixel_format,
        facts.profile,
    )
    actual = tuple(
        asset[key]
        for key in (
            "sha256",
            "sizeBytes",
            "width",
            "height",
            "durationS",
            "fps",
            "frameCount",
            "codec",
            "pixelFormat",
            "profile",
        )
    )
    typed = all(
        type(item) is type(expected[index]) for index, item in enumerate(actual)
    )
    numeric = typed and math.isfinite(asset["durationS"])
    numeric = numeric and math.isfinite(asset["fps"])
    if actual != expected or not typed or not numeric:
        raise GraphicRenderReceiptWriterError(
            "render proof asset differs from generation media"
        )


def _receipt_document(
    checked: GraphicRenderReceiptAuthorityV1,
    evidence: _LaneEvidenceV1,
    methods: dict,
    intent_digest: str,
) -> dict:
    return {
        "schemaVersion": 1,
        "status": "declared-private-render-not-execution-attested",
        "ordinal": checked.ordinal,
        "graphicId": checked.graphic_id,
        "kind": evidence.kind,
        "selectionId": checked.selection_id,
        "admissionArtifactDigest": checked.admission_artifact_digest,
        "requestDigest": checked.request_digest,
        "qualityPolicyId": checked.quality_policy_id,
        "renderIntentDigest": intent_digest,
        "renderInputKey": evidence.render_input_key,
        "sourceSnapshotSha256": evidence.source_snapshot_sha256,
        "media": media_document(checked.media),
        "renderArtifactDigest": checked.media.artifact.sha256,
        "renderBuildDigest": checked.render_build_digest,
        "runtimeImageId": checked.runtime_image_id,
        "tools": {
            "ffmpegSha256": checked.proof_ffmpeg_sha256,
            "ffprobeSha256": checked.proof_ffprobe_sha256,
        },
        "proof": methods,
        "claims": {
            "dynamicLibraryClosureVerified": False,
            "executionAttested": False,
            "executionAuthorized": False,
            "mediaBytesReobserved": False,
            "publicationAuthorized": False,
            "runtimeVerified": False,
        },
    }


def build_graphic_render_receipt_v1(
    authority: object, plan_row: object, lane_result: object
) -> GraphicRenderReceiptV1:
    """Create a canonical receipt from the qualified admitted lane result."""
    checked = _authority(authority)
    if type(plan_row) is not dict or plan_row.get("id") != checked.graphic_id:
        raise GraphicRenderReceiptWriterError(
            "graphic render plan row identity is invalid"
        )
    evidence = _lane(lane_result, checked)
    if evidence.kind != plan_row.get("kind"):
        raise GraphicRenderReceiptWriterError("graphic render kind is stale")
    _media_matches(checked, evidence.proof)
    try:
        methods = proof_methods(evidence.proof)
        intent_digest = graphic_render_intent_digest(plan_row)
    except (RuntimeError, ValueError) as exc:
        raise GraphicRenderReceiptWriterError(
            "graphic render receipt inputs are invalid"
        ) from exc
    document = _receipt_document(checked, evidence, methods, intent_digest)
    try:
        return parse_graphic_render_receipt_v1(encode_receipt(document))
    except (RuntimeError, TypeError, ValueError) as exc:
        raise GraphicRenderReceiptWriterError(
            "graphic render receipt normalization failed"
        ) from exc
