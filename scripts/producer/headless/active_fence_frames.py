"""Hash-linked canonical journal frames for active-fence transitions."""

from __future__ import annotations

import hashlib
import zlib

from . import quality_receipt_json as wire
from .active_fence_schema import (
    ActiveFenceSchemaError,
    build_active_fence_state_v1,
    validate_active_fence_attempt_id_v1,
)
from .active_fence_types import ActiveFenceStateV1, ActiveFenceTransitionV1
from .operation_wire import canonical

ZERO_EVENT_DIGEST = "0" * 64
MAX_FENCE_FRAME_BYTES = 16_384
_FRAME_DOMAIN = b"sniper-active-generation-fence-frame-v1\0"
_PAYLOAD_KEYS = frozenset(
    "activeAttemptId attemptId authorityId authorityKind event "
    "fenceRevision fenceToken schemaVersion".split()
)
_FRAME_KEYS = frozenset(
    "eventDigest frameVersion payload payloadByteLength payloadCrc32 "
    "priorEventDigest sequence".split()
)
_EVENTS = frozenset({"BOOTSTRAP", "RESERVE", "CANCEL"})


def _payload(
    event: str, attempt_id: str | None, state: ActiveFenceStateV1
) -> dict:
    return {
        "schemaVersion": 1,
        "authorityKind": "active-generation-fence-transition-v1",
        "event": event,
        "attemptId": attempt_id,
        "authorityId": state.authority_id,
        "fenceRevision": state.fence_revision,
        "fenceToken": state.fence_token,
        "activeAttemptId": state.active_attempt_id,
    }


def _encode_transition(
    event: str,
    attempt_id: str | None,
    state: ActiveFenceStateV1,
    chain: tuple[int, str],
) -> ActiveFenceTransitionV1:
    sequence, prior_digest = chain
    payload = _payload(event, attempt_id, state)
    payload_raw = canonical(payload)
    base = {
        "frameVersion": 1,
        "sequence": sequence,
        "priorEventDigest": prior_digest,
        "payloadByteLength": len(payload_raw),
        "payloadCrc32": f"{zlib.crc32(payload_raw) & 0xffffffff:08x}",
        "payload": payload,
    }
    digest = hashlib.sha256(_FRAME_DOMAIN + canonical(base)).hexdigest()
    frame = canonical({**base, "eventDigest": digest})
    if len(frame) > MAX_FENCE_FRAME_BYTES:
        raise ActiveFenceSchemaError("active-fence frame exceeds size limit")
    return ActiveFenceTransitionV1(
        event, attempt_id, state, sequence, prior_digest, digest, frame
    )


def build_active_fence_bootstrap_v1(
    authority_id: str, fence_token: str
) -> ActiveFenceTransitionV1:
    """Build the only valid first transition."""
    state = build_active_fence_state_v1(authority_id, 0, fence_token, None)
    return _encode_transition("BOOTSTRAP", None, state, (1, ZERO_EVENT_DIGEST))


def _next_transition(
    prior: ActiveFenceTransitionV1,
    event: str,
    attempt_id: str,
    fence_token: str,
) -> ActiveFenceTransitionV1:
    if type(prior) is not ActiveFenceTransitionV1 or event not in _EVENTS:
        raise ActiveFenceSchemaError("active-fence predecessor is invalid")
    attempt = validate_active_fence_attempt_id_v1(attempt_id)
    if fence_token == prior.state.fence_token:
        raise ActiveFenceSchemaError(
            "active-fence transition must rotate token"
        )
    active = attempt if event == "RESERVE" else None
    state = build_active_fence_state_v1(
        prior.state.authority_id,
        prior.state.fence_revision + 1,
        fence_token,
        active,
    )
    return _encode_transition(
        event,
        attempt,
        state,
        (prior.sequence + 1, prior.event_digest),
    )


def build_active_fence_reserve_v1(
    prior: ActiveFenceTransitionV1, attempt_id: str, fence_token: str
) -> ActiveFenceTransitionV1:
    """Build an explicit reservation from an inactive predecessor."""
    if prior.state.active_attempt_id is not None:
        raise ActiveFenceSchemaError("active-fence predecessor is reserved")
    return _next_transition(prior, "RESERVE", attempt_id, fence_token)


def build_active_fence_cancel_v1(
    prior: ActiveFenceTransitionV1, attempt_id: str, fence_token: str
) -> ActiveFenceTransitionV1:
    """Build an explicit cancellation of the exact active attempt."""
    attempt = validate_active_fence_attempt_id_v1(attempt_id)
    if prior.state.active_attempt_id != attempt:
        raise ActiveFenceSchemaError(
            "active-fence cancel target is not active"
        )
    return _next_transition(prior, "CANCEL", attempt, fence_token)


def _frame_envelope(raw: bytes) -> tuple[dict, dict, bytes]:
    try:
        frame = wire.canonical_document(raw, "active-fence frame")
        wire.exact(frame, _FRAME_KEYS, "active-fence frame")
        payload = wire.exact(
            frame["payload"], _PAYLOAD_KEYS, "active-fence payload"
        )
        payload_raw = canonical(payload)
        return frame, payload, payload_raw
    except wire.QualityReceiptSchemaError as exc:
        raise ActiveFenceSchemaError(str(exc)) from exc


def _parsed_state(payload: dict) -> ActiveFenceStateV1:
    envelope = (
        type(payload["schemaVersion"]),
        payload["schemaVersion"],
        payload["authorityKind"],
        payload["event"],
    )
    if envelope[:3] != (int, 1, "active-generation-fence-transition-v1"):
        raise ActiveFenceSchemaError(
            "active-fence payload envelope is invalid"
        )
    if envelope[3] not in _EVENTS:
        raise ActiveFenceSchemaError("active-fence event is invalid")
    return build_active_fence_state_v1(
        payload["authorityId"],
        payload["fenceRevision"],
        payload["fenceToken"],
        payload["activeAttemptId"],
    )


def _validate_frame_integrity(frame: dict, payload_raw: bytes) -> None:
    base = {key: frame[key] for key in _FRAME_KEYS - {"eventDigest"}}
    expected = hashlib.sha256(_FRAME_DOMAIN + canonical(base)).hexdigest()
    valid = (
        (type(frame["frameVersion"]), frame["frameVersion"]) == (int, 1)
        and type(frame["sequence"]) is int
        and frame["sequence"] > 0
        and frame["payloadByteLength"] == len(payload_raw)
        and frame["payloadCrc32"]
        == f"{zlib.crc32(payload_raw) & 0xffffffff:08x}"
        and frame["eventDigest"] == expected
    )
    if not valid:
        raise ActiveFenceSchemaError("active-fence frame integrity is invalid")
    try:
        wire.digest(frame["priorEventDigest"], "prior event digest")
        wire.digest(frame["eventDigest"], "event digest")
    except wire.QualityReceiptSchemaError as exc:
        raise ActiveFenceSchemaError(str(exc)) from exc


def parse_active_fence_transition_v1(
    raw: bytes, prior: ActiveFenceTransitionV1 | None
) -> ActiveFenceTransitionV1:
    """Parse one exact frame against its required predecessor."""
    if type(raw) is not bytes or len(raw) > MAX_FENCE_FRAME_BYTES:
        raise ActiveFenceSchemaError("active-fence frame size is invalid")
    frame, payload, payload_raw = _frame_envelope(raw)
    state = _parsed_state(payload)
    _validate_frame_integrity(frame, payload_raw)
    attempt = payload["attemptId"]
    if attempt is not None:
        attempt = validate_active_fence_attempt_id_v1(attempt)
    parsed = ActiveFenceTransitionV1(
        payload["event"],
        attempt,
        state,
        frame["sequence"],
        frame["priorEventDigest"],
        frame["eventDigest"],
        raw,
    )
    if parsed != _expected_transition(parsed, prior):
        raise ActiveFenceSchemaError("active-fence transition is inconsistent")
    return parsed


def _expected_transition(
    parsed: ActiveFenceTransitionV1,
    prior: ActiveFenceTransitionV1 | None,
) -> ActiveFenceTransitionV1:
    if prior is None:
        if parsed.event != "BOOTSTRAP" or parsed.attempt_id is not None:
            raise ActiveFenceSchemaError("journal must begin with BOOTSTRAP")
        return build_active_fence_bootstrap_v1(
            parsed.state.authority_id, parsed.state.fence_token
        )
    if parsed.event == "RESERVE":
        return build_active_fence_reserve_v1(
            prior, parsed.attempt_id or "", parsed.state.fence_token
        )
    if parsed.event == "CANCEL":
        return build_active_fence_cancel_v1(
            prior, parsed.attempt_id or "", parsed.state.fence_token
        )
    raise ActiveFenceSchemaError("BOOTSTRAP may appear only once")
