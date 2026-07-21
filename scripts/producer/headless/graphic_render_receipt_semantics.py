"""Exact non-authorizing wire semantics for one retained graphic render."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import approved_parent_schema_values as values
from . import quality_receipt_json as wire
from .artifact_contract import MediaRefV1

GraphicRenderReceiptSchemaError = wire.QualityReceiptSchemaError

_MAX_BYTES = 1024 * 1024
_GRAPHIC_ID = re.compile(r"g-[0-9a-z]{8}")
_SELECTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_TOP_KEYS = frozenset(
    "admissionArtifactDigest claims graphicId kind media ordinal proof qualityPolicyId "
    "renderArtifactDigest renderBuildDigest renderInputKey "
    "renderIntentDigest requestDigest runtimeImageId schemaVersion selectionId "
    "sourceSnapshotSha256 status tools".split()
)
_TOOL_KEYS = frozenset("ffmpegSha256 ffprobeSha256".split())
_PROOF_KEYS = frozenset(
    "alphaMode decodeMethod occupancyMethod terminalAlphaMethod".split()
)
_CLAIM_KEYS = frozenset(
    "dynamicLibraryClosureVerified executionAttested executionAuthorized "
    "mediaBytesReobserved publicationAuthorized runtimeVerified".split()
)


@dataclass(frozen=True)
class GraphicRenderToolsV1:
    """Declared proof-tool identities; binding must verify them externally."""

    ffmpeg_sha256: str
    ffprobe_sha256: str


@dataclass(frozen=True)
class GraphicRenderProofSemanticsV1:
    """The exact proof methods emitted by the qualified R0 graphics writer."""

    alpha_mode: str
    decode_method: str
    occupancy_method: str
    terminal_alpha_method: str


@dataclass(frozen=True)
class GraphicRenderClaimsV1:
    """Authorities deliberately unavailable from a retained receipt alone."""

    media_bytes_reobserved: bool
    runtime_verified: bool
    dynamic_library_closure_verified: bool
    execution_attested: bool
    execution_authorized: bool
    publication_authorized: bool


@dataclass(frozen=True)
class GraphicRenderReceiptV1:
    """Canonical graphic identity and declared render proof semantics."""

    ordinal: int
    graphic_id: str
    kind: str
    selection_id: str
    admission_artifact_digest: str
    request_digest: str
    quality_policy_id: str
    render_intent_digest: str
    render_input_key: str
    source_snapshot_sha256: str
    media: MediaRefV1
    render_artifact_digest: str
    render_build_digest: str
    runtime_image_id: str
    tools: GraphicRenderToolsV1
    proof: GraphicRenderProofSemanticsV1
    claims: GraphicRenderClaimsV1
    document_json: bytes


def _tools(value: object) -> GraphicRenderToolsV1:
    row = wire.exact(value, _TOOL_KEYS, "graphic render tools")
    parsed = GraphicRenderToolsV1(
        wire.digest(row["ffmpegSha256"], "graphic render ffmpeg"),
        wire.digest(row["ffprobeSha256"], "graphic render ffprobe"),
    )
    if parsed.ffmpeg_sha256 == parsed.ffprobe_sha256:
        raise GraphicRenderReceiptSchemaError("graphic render tool roles alias")
    return parsed


def _proof(value: object) -> GraphicRenderProofSemanticsV1:
    row = wire.exact(value, _PROOF_KEYS, "graphic render proof")
    actual = tuple(row[key] for key in sorted(_PROOF_KEYS))
    expected = (
        "required",
        "ffmpeg-full-xerror",
        "ffmpeg-alpha-sustained-area",
        "ffmpeg-final-encoded-alpha",
    )
    if actual != expected or any(type(item) is not str for item in actual):
        raise GraphicRenderReceiptSchemaError(
            "graphic render proof methods are invalid"
        )
    return GraphicRenderProofSemanticsV1(
        row["alphaMode"],
        row["decodeMethod"],
        row["occupancyMethod"],
        row["terminalAlphaMethod"],
    )


def _claims(value: object) -> GraphicRenderClaimsV1:
    row = wire.exact(value, _CLAIM_KEYS, "graphic render claims")
    if any(type(item) is not bool or item for item in row.values()):
        raise GraphicRenderReceiptSchemaError(
            "graphic render receipt overclaims authority"
        )
    return GraphicRenderClaimsV1(
        row["mediaBytesReobserved"],
        row["runtimeVerified"],
        row["dynamicLibraryClosureVerified"],
        row["executionAttested"],
        row["executionAuthorized"],
        row["publicationAuthorized"],
    )


def _media(value: object) -> MediaRefV1:
    try:
        media = values.parse_media(value)
    except RuntimeError as exc:
        raise GraphicRenderReceiptSchemaError(
            "graphic render media is invalid"
        ) from exc
    facts = media.facts
    shape = (
        facts.video_codec,
        facts.pixel_format,
        facts.profile,
        facts.alpha_mode,
        facts.audio_codec,
        facts.fps_numerator,
        facts.fps_denominator,
    )
    expected = ("prores", "yuva444p12le", "4444", "straight", None, 30, 1)
    if shape != expected:
        raise GraphicRenderReceiptSchemaError("graphic render media is outside R0")
    return media


def _envelope(document: dict) -> tuple[int, str, str]:
    ordinal = document["ordinal"]
    graphic_id = document["graphicId"]
    kind = document["kind"]
    selection_id = document["selectionId"]
    valid = (
        type(document["schemaVersion"]) is int
        and document["schemaVersion"] == 1
        and document["status"] == "declared-private-render-not-execution-attested"
        and type(ordinal) is int
        and ordinal >= 0
        and type(graphic_id) is str
        and bool(_GRAPHIC_ID.fullmatch(graphic_id))
        and type(kind) is str
        and kind == "section-marker"
        and type(selection_id) is str
        and bool(_SELECTION_ID.fullmatch(selection_id))
    )
    if not valid:
        raise GraphicRenderReceiptSchemaError(
            "graphic render receipt envelope is invalid"
        )
    return ordinal, graphic_id, kind


def parse_graphic_render_receipt_v1(raw: object) -> GraphicRenderReceiptV1:
    """Parse one exact canonical R0 receipt without trusting its claims."""
    if type(raw) is not bytes or not 0 < len(raw) <= _MAX_BYTES:
        raise GraphicRenderReceiptSchemaError(
            "graphic render receipt bytes are invalid"
        )
    document = wire.canonical_document(raw, "graphic render receipt")
    wire.exact(document, _TOP_KEYS, "graphic render receipt")
    ordinal, graphic_id, kind = _envelope(document)
    media = _media(document["media"])
    artifact_digest = wire.digest(
        document["renderArtifactDigest"], "graphic render artifact"
    )
    if artifact_digest != media.artifact.sha256:
        raise GraphicRenderReceiptSchemaError(
            "graphic render artifact differs from media"
        )
    image_id = document["runtimeImageId"]
    if type(image_id) is not str or not _IMAGE_ID.fullmatch(image_id):
        raise GraphicRenderReceiptSchemaError(
            "graphic render image identity is invalid"
        )
    return GraphicRenderReceiptV1(
        ordinal,
        graphic_id,
        kind,
        document["selectionId"],
        wire.digest(
            document["admissionArtifactDigest"],
            "graphic render admission artifact",
        ),
        wire.digest(document["requestDigest"], "graphic render request"),
        wire.digest(document["qualityPolicyId"], "graphic render quality policy"),
        wire.digest(document["renderIntentDigest"], "graphic render intent"),
        wire.digest(document["renderInputKey"], "graphic render input key"),
        wire.digest(document["sourceSnapshotSha256"], "graphic source snapshot"),
        media,
        artifact_digest,
        wire.digest(document["renderBuildDigest"], "graphic render build"),
        image_id,
        _tools(document["tools"]),
        _proof(document["proof"]),
        _claims(document["claims"]),
        raw,
    )


def validate_graphic_render_receipt_v1(value: object) -> None:
    """Reject direct construction and hostile equality overloads."""
    valid = type(value) is GraphicRenderReceiptV1
    valid = valid and type(getattr(value, "document_json", None)) is bytes
    if not valid:
        raise GraphicRenderReceiptSchemaError(
            "graphic render receipt instance is invalid"
        )
    parsed = parse_graphic_render_receipt_v1(value.document_json)
    if not wire.same_typed_value(value, parsed):
        raise GraphicRenderReceiptSchemaError(
            "graphic render receipt construction is invalid"
        )
