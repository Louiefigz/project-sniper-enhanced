"""Attempt-bound receipts for prevalidated overlay source capsules."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from .container_io import promote_regular
from .overlay_seal_store import (
    OverlaySealLocator, read_overlay_receipt, store_overlay_receipt)
from .overlay_source_seal import (
    OVERLAY_SOURCE_KEYS,
    OverlaySourceCapture,
    ResolvedOverlaySeal,
    capture_overlay_source,
    effective_render_intent,
    render_intents_equal,
    resolve_overlay_source,
)

_ATTEMPT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_KIND = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


@dataclass(frozen=True)
class OverlayPrepareRequest:
    """Attempt identity plus one controller-selected entry to freeze."""

    attempt_root: str
    attempt_id: str
    request_digest: str
    build_digest: str
    pipeline_root: str
    entry: dict[str, Any]
    selection_id: str


@dataclass(frozen=True)
class OverlaySealBinding:
    """Attempt-wide identities the overlay receipt must match."""

    attempt_root: str
    attempt_id: str
    request_digest: str
    build_digest: str
    selection_id: str


@dataclass(frozen=True)
class OverlayImportRequest:
    """Retained artifact source copied into one admitted attempt seal."""

    attempt_root: str
    attempt_id: str
    request_digest: str
    build_digest: str
    selection_id: str
    source_value: dict
    snapshot_path: str


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                             sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("overlay receipt is not canonical JSON") from exc
    return encoded.encode("ascii")


def _source_value(value: dict) -> dict:
    return {key: value[key] for key in OVERLAY_SOURCE_KEYS}


def _receipt(request: OverlayPrepareRequest, intent: dict[str, Any],
             directory: str) -> dict:
    capture = OverlaySourceCapture(
        request.pipeline_root, intent, request.build_digest, request.selection_id)
    source = capture_overlay_source(capture, directory)
    return {**source, "attemptId": request.attempt_id,
            "requestDigest": request.request_digest}


def _seal_id(request: OverlayPrepareRequest, intent: dict[str, Any]) -> str:
    value = {"attemptId": request.attempt_id,
             "requestDigest": request.request_digest,
             "buildDigest": request.build_digest,
             "selectionId": request.selection_id, "intent": intent}
    return hashlib.sha256(
        b"sniper-overlay-seal-id-v1\0" + _canonical(value)).hexdigest()


def _validate_prepare(request: OverlayPrepareRequest) -> None:
    valid = (_ATTEMPT.fullmatch(request.attempt_id)
             and _DIGEST.fullmatch(request.request_digest)
             and _DIGEST.fullmatch(request.build_digest)
             and _KIND.fullmatch(request.selection_id))
    if not valid:
        raise RuntimeError("overlay attempt identity is invalid")
    if (not os.path.isabs(request.attempt_root)
            or os.path.realpath(request.attempt_root) != request.attempt_root):
        raise RuntimeError("overlay attempt root must be canonical")


def prepare_overlay(request: OverlayPrepareRequest) -> OverlaySealLocator:
    """Freeze one effective entry and atomically publish its retained seal."""
    _validate_prepare(request)
    intent = effective_render_intent(request.entry)
    seal_id = _seal_id(request, intent)
    locator = store_overlay_receipt(
        request.attempt_root, seal_id,
        lambda directory: _canonical(_receipt(request, intent, directory)) + b"\n")
    binding = OverlaySealBinding(
        request.attempt_root, request.attempt_id, request.request_digest,
        request.build_digest, request.selection_id)
    if not render_intents_equal(load_overlay(locator, binding).intent, intent):
        raise RuntimeError("existing overlay seal is bound to another intent")
    return locator


def _import_receipt(request: OverlayImportRequest, directory: str) -> bytes:
    source_dir = os.path.dirname(request.snapshot_path)
    resolved = resolve_overlay_source(
        request.source_value, source_dir, request.selection_id,
        request.build_digest)
    if resolved.snapshot.path != request.snapshot_path:
        raise RuntimeError("imported overlay snapshot path is invalid")
    target = os.path.join(directory, "render-input.tar")
    promote_regular(request.snapshot_path, target, resolved.snapshot.sha256,
                    resolved.snapshot.size_bytes)
    value = {**request.source_value, "attemptId": request.attempt_id,
             "requestDigest": request.request_digest}
    return _canonical(value) + b"\n"


def import_overlay_source(request: OverlayImportRequest) -> OverlaySealLocator:
    """Copy a verified pre-admission capsule without reading live sources."""
    identity = OverlayPrepareRequest(
        request.attempt_root, request.attempt_id, request.request_digest,
        request.build_digest, "", {}, request.selection_id)
    _validate_prepare(identity)
    resolved = resolve_overlay_source(
        request.source_value, os.path.dirname(request.snapshot_path),
        request.selection_id, request.build_digest)
    seal_id = _seal_id(identity, resolved.intent)
    locator = store_overlay_receipt(
        request.attempt_root, seal_id,
        lambda directory: _import_receipt(request, directory))
    binding = OverlaySealBinding(
        request.attempt_root, request.attempt_id, request.request_digest,
        request.build_digest, request.selection_id)
    if not render_intents_equal(load_overlay(locator, binding).intent,
                                resolved.intent):
        raise RuntimeError("imported overlay seal changed intent")
    return locator


def _read_locator(locator: OverlaySealLocator) -> dict:
    raw = read_overlay_receipt(locator)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("overlay seal receipt is invalid JSON") from exc
    if raw != _canonical(value) + b"\n":
        raise RuntimeError("overlay seal receipt is not canonical JSON")
    return value


def _validate_envelope(value: dict, binding: OverlaySealBinding,
                       directory: str) -> None:
    keys = set(OVERLAY_SOURCE_KEYS) | {"attemptId", "requestDigest"}
    valid = (isinstance(value, dict) and set(value) == keys
             and value.get("attemptId") == binding.attempt_id
             and value.get("requestDigest") == binding.request_digest
             and value.get("buildDigest") == binding.build_digest
             and value.get("selectionId") == binding.selection_id
             and os.path.commonpath((binding.attempt_root, directory))
             == binding.attempt_root)
    if not valid:
        raise RuntimeError("overlay seal envelope is invalid")


def load_overlay(locator: OverlaySealLocator,
                 binding: OverlaySealBinding) -> ResolvedOverlaySeal:
    """Load and independently rederive one immutable attempt overlay seal."""
    value = _read_locator(locator)
    directory = os.path.dirname(locator.path)
    _validate_envelope(value, binding, directory)
    return resolve_overlay_source(
        _source_value(value), directory, binding.selection_id,
        binding.build_digest)
