"""Canonical manifest semantics for one retained graphic receipt set."""

from __future__ import annotations

import json
import re
import uuid

from . import quality_receipt_json as wire
from .graphic_render_receipt_store_types import (
    GRAPHIC_RECEIPT_SET_STATUS,
    GraphicRenderReceiptExpectedV1,
    GraphicRenderReceiptSetExpectationV1,
    GraphicRenderReceiptStoreError,
)

_DIGEST = re.compile(r"[0-9a-f]{64}")
_GRAPHIC_ID = re.compile(r"g-[0-9a-z]{8}")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_MAX_BYTES = 2 * 1024 * 1024
_KEYS = frozenset(
    "admissionArtifactDigest attemptId authorityId claims qualityPolicyId "
    "receipts renderBuildDigest requestDigest runtimeImageId schemaVersion "
    "status tools".split()
)
_ROW_KEYS = frozenset("file graphicId ordinal selectionId sha256 sizeBytes".split())
_TOOL_KEYS = frozenset("ffmpegSha256 ffprobeSha256".split())
_CLAIM_KEYS = frozenset(
    "executionAttested executionAuthorized mediaBytesReobserved publicationAuthorized".split()
)


def _digest(value: object) -> bool:
    return type(value) is str and bool(_DIGEST.fullmatch(value))


def _canonical_uuid(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def validate_expectation(value: object) -> GraphicRenderReceiptSetExpectationV1:
    """Reject caller construction that is not an exact closed set identity."""
    if type(value) is not GraphicRenderReceiptSetExpectationV1:
        raise GraphicRenderReceiptStoreError("graphic receipt expectation is invalid")
    shared = (
        value.admission_artifact_digest,
        value.request_digest,
        value.quality_policy_id,
        value.render_build_digest,
        value.proof_ffmpeg_sha256,
        value.proof_ffprobe_sha256,
    )
    valid = all(_digest(item) for item in shared)
    valid = valid and type(value.authority_id) is str
    valid = valid and bool(_IDENTITY.fullmatch(value.authority_id))
    valid = valid and _canonical_uuid(value.attempt_id)
    valid = valid and type(value.runtime_image_id) is str
    valid = valid and bool(_IMAGE_ID.fullmatch(value.runtime_image_id))
    valid = valid and value.proof_ffmpeg_sha256 != value.proof_ffprobe_sha256
    valid = valid and type(value.receipts) is tuple
    valid = valid and len(value.receipts) == 1
    if not valid:
        raise GraphicRenderReceiptStoreError("graphic receipt expectation is invalid")
    _validate_expected_rows(value)
    return value


def _validate_expected_rows(value: GraphicRenderReceiptSetExpectationV1) -> None:
    identities = []
    for ordinal, row in enumerate(value.receipts):
        valid = type(row) is GraphicRenderReceiptExpectedV1
        valid = valid and type(row.ordinal) is int and row.ordinal == ordinal
        valid = valid and type(row.graphic_id) is str
        valid = valid and bool(_GRAPHIC_ID.fullmatch(row.graphic_id))
        valid = valid and row.kind == "section-marker"
        valid = valid and all(
            _digest(item)
            for item in (
                row.render_intent_digest,
                row.render_input_key,
                row.source_snapshot_sha256,
            )
        )
        if not valid:
            raise GraphicRenderReceiptStoreError(
                "graphic receipt expected row is invalid"
            )
        identities.append(row.graphic_id)
    if len(identities) != len(set(identities)):
        raise GraphicRenderReceiptStoreError("graphic receipt expected rows alias")


def _file_name(ordinal: int) -> str:
    return f"receipt-{ordinal:04d}.json"


def build_set_manifest(
    value: GraphicRenderReceiptSetExpectationV1, receipt_rows: tuple[dict, ...]
) -> bytes:
    """Encode one exact newline-framed set manifest."""
    checked = validate_expectation(value)
    if len(receipt_rows) != len(checked.receipts):
        raise GraphicRenderReceiptStoreError("graphic receipt row count is stale")
    document = {
        "schemaVersion": 1,
        "status": GRAPHIC_RECEIPT_SET_STATUS,
        "authorityId": checked.authority_id,
        "attemptId": checked.attempt_id,
        "admissionArtifactDigest": checked.admission_artifact_digest,
        "requestDigest": checked.request_digest,
        "qualityPolicyId": checked.quality_policy_id,
        "renderBuildDigest": checked.render_build_digest,
        "runtimeImageId": checked.runtime_image_id,
        "tools": {
            "ffmpegSha256": checked.proof_ffmpeg_sha256,
            "ffprobeSha256": checked.proof_ffprobe_sha256,
        },
        "receipts": list(receipt_rows),
        "claims": {
            "executionAttested": False,
            "executionAuthorized": False,
            "mediaBytesReobserved": False,
            "publicationAuthorized": False,
        },
    }
    return (
        json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("ascii")


def _shared_identity(document: dict) -> tuple:
    tools = wire.exact(document["tools"], _TOOL_KEYS, "graphic receipt set tools")
    claims = wire.exact(document["claims"], _CLAIM_KEYS, "graphic receipt set claims")
    if any(type(item) is not bool or item for item in claims.values()):
        raise GraphicRenderReceiptStoreError("graphic receipt set overclaims authority")
    return (
        document["authorityId"],
        document["attemptId"],
        document["admissionArtifactDigest"],
        document["requestDigest"],
        document["qualityPolicyId"],
        document["renderBuildDigest"],
        document["runtimeImageId"],
        tools["ffmpegSha256"],
        tools["ffprobeSha256"],
    )


def _manifest_rows(document: dict, expected: tuple) -> tuple[dict, ...]:
    values = document["receipts"]
    if type(values) is not list or len(values) != len(expected):
        raise GraphicRenderReceiptStoreError("graphic receipt manifest rows are stale")
    rows = tuple(values)
    for ordinal, (row, wanted) in enumerate(zip(rows, expected)):
        valid = type(row) is dict and set(row) == _ROW_KEYS
        valid = valid and row.get("ordinal") == ordinal
        valid = valid and row.get("graphicId") == wanted.graphic_id
        valid = valid and row.get("selectionId") == wanted.graphic_id
        valid = valid and row.get("file") == _file_name(ordinal)
        valid = valid and _digest(row.get("sha256"))
        valid = valid and type(row.get("sizeBytes")) is int
        valid = valid and row.get("sizeBytes", 0) > 0
        if not valid:
            raise GraphicRenderReceiptStoreError(
                "graphic receipt manifest row is invalid"
            )
    return rows


def parse_set_manifest(
    raw: object, expectation: GraphicRenderReceiptSetExpectationV1
) -> tuple[dict, ...]:
    """Parse exact retained manifest bytes against controller-derived authority."""
    checked = validate_expectation(expectation)
    valid = type(raw) is bytes and 1 < len(raw) <= _MAX_BYTES
    valid = valid and raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    if not valid:
        raise GraphicRenderReceiptStoreError(
            "graphic receipt manifest bytes are invalid"
        )
    try:
        document = wire.canonical_document(raw[:-1], "graphic receipt set manifest")
        wire.exact(document, _KEYS, "graphic receipt set manifest")
        actual = _shared_identity(document)
    except RuntimeError as exc:
        raise GraphicRenderReceiptStoreError(
            "graphic receipt set manifest is invalid"
        ) from exc
    expected = (
        checked.authority_id,
        checked.attempt_id,
        checked.admission_artifact_digest,
        checked.request_digest,
        checked.quality_policy_id,
        checked.render_build_digest,
        checked.runtime_image_id,
        checked.proof_ffmpeg_sha256,
        checked.proof_ffprobe_sha256,
    )
    envelope = (
        type(document["schemaVersion"]),
        document["schemaVersion"],
        document["status"],
    )
    if envelope != (int, 1, GRAPHIC_RECEIPT_SET_STATUS) or actual != expected:
        raise GraphicRenderReceiptStoreError("graphic receipt set identity is stale")
    return _manifest_rows(document, checked.receipts)
