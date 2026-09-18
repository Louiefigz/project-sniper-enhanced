"""Authority-scoped canonical request bytes for the sealed overlay lane."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass

from .durable_files import (
    DurableFileError,
    locked_private_dir,
    open_private_dir,
    open_private_file,
    private_child_dir,
    read_private_file,
    write_all,
)

_DIGEST = re.compile(r"[0-9a-f]{64}")
_OVERLAY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_MAX_REQUEST_BYTES = 8 * 1024 * 1024
REQUESTS_DIR = "requests"


@dataclass(frozen=True)
class RequestArtifactLocator:
    """Content-addressed request path and domain-separated identity."""

    path: str
    request_digest: str


@dataclass(frozen=True)
class SelectedOverlay:
    """One controller-selected row loaded from exact request bytes."""

    request_digest: str
    overlay_id: str
    entry: dict


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                             sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("headless request is not canonical JSON") from exc
    return (encoded + "\n").encode("ascii")


def _digest(raw: bytes) -> str:
    return hashlib.sha256(b"sniper-headless-request-v1\0" + raw).hexdigest()


def _validate(value: object) -> dict:
    valid = (isinstance(value, dict)
             and set(value) == {"operation", "overlays", "schemaVersion"}
             and type(value.get("schemaVersion")) is int
             and value.get("schemaVersion") == 1
             and value.get("operation") == "render-overlays"
             and isinstance(value.get("overlays"), list)
             and 0 < len(value["overlays"]) <= 4096)
    if not valid:
        raise RuntimeError("headless request envelope is invalid")
    identifiers = []
    for row in value["overlays"]:
        row_ok = (isinstance(row, dict)
                  and set(row) == {"entry", "overlayId"}
                  and isinstance(row.get("overlayId"), str)
                  and _OVERLAY_ID.fullmatch(row["overlayId"])
                  and isinstance(row.get("entry"), dict))
        if not row_ok:
            raise RuntimeError("headless request overlay row is invalid")
        identifiers.append(row["overlayId"])
    if len(set(identifiers)) != len(identifiers):
        raise RuntimeError("headless request overlay IDs must be unique")
    return value


def _decode(raw: bytes) -> dict:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("headless request artifact is invalid JSON") from exc
    value = _validate(value)
    if raw != _canonical(value):
        raise RuntimeError("headless request artifact is not exact canonical JSON")
    return value


def canonical_request_document(request: dict) -> tuple[dict, bytes, str]:
    """Freeze one request and return its canonical bytes and document digest."""
    frozen = _validate(json.loads(_canonical(request)))
    raw = _canonical(frozen)
    if len(raw) > _MAX_REQUEST_BYTES:
        raise RuntimeError("headless request artifact exceeds 8 MiB")
    return frozen, raw, _digest(raw)


def decode_request_document(raw: bytes) -> dict:
    """Validate exact canonical request bytes without filesystem authority."""
    if len(raw) > _MAX_REQUEST_BYTES:
        raise RuntimeError("headless request artifact exceeds 8 MiB")
    return _decode(raw)


def _expected_path(authority_root: str, digest: str) -> str:
    if (not os.path.isabs(authority_root)
            or os.path.realpath(authority_root) != authority_root
            or not _DIGEST.fullmatch(digest)):
        raise RuntimeError("headless request authority or digest is invalid")
    return os.path.join(authority_root, REQUESTS_DIR, f"{digest}.json")


def _write_request_once(requests_fd: int, name: str, raw: bytes) -> None:
    try:
        fd = open_private_file(
            requests_fd, name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except DurableFileError as exc:
        if not isinstance(exc.__cause__, FileExistsError):
            raise
        existing = read_private_file(requests_fd, name, _MAX_REQUEST_BYTES)
        if existing != raw:
            raise RuntimeError("request digest path contains other bytes")
    else:
        try:
            write_all(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(requests_fd)


def store_request_artifact(authority_root: str,
                           request: dict) -> RequestArtifactLocator:
    """Durably publish canonical request bytes before attempt admission."""
    _, raw, digest = canonical_request_document(request)
    with locked_private_dir(authority_root, ".request-artifact.lock") as root_fd:
        requests_fd = private_child_dir(root_fd, REQUESTS_DIR)
        try:
            name = f"{digest}.json"
            _write_request_once(requests_fd, name, raw)
        finally:
            os.close(requests_fd)
    return RequestArtifactLocator(_expected_path(authority_root, digest), digest)


def load_request_artifact(authority_root: str,
                          locator: RequestArtifactLocator) -> dict:
    """Reload exact authority-scoped bytes and independently derive identity."""
    expected = _expected_path(authority_root, locator.request_digest)
    if locator.path != expected or os.path.realpath(locator.path) != locator.path:
        raise RuntimeError("headless request artifact locator is invalid")
    requests_fd = open_private_dir(os.path.join(authority_root, REQUESTS_DIR))
    try:
        raw = read_private_file(
            requests_fd, os.path.basename(expected), _MAX_REQUEST_BYTES)
    finally:
        os.close(requests_fd)
    if _digest(raw) != locator.request_digest:
        raise RuntimeError("headless request artifact digest mismatch")
    return decode_request_document(raw)


def select_overlay(authority_root: str, locator: RequestArtifactLocator,
                   overlay_id: str) -> SelectedOverlay:
    """Select exactly one ID from trusted artifact bytes, never caller entry data."""
    if not _OVERLAY_ID.fullmatch(str(overlay_id)):
        raise RuntimeError("overlay selection ID is invalid")
    value = load_request_artifact(authority_root, locator)
    matches = [row for row in value["overlays"] if row["overlayId"] == overlay_id]
    if len(matches) != 1:
        raise RuntimeError("overlay selection is absent or ambiguous")
    entry = json.loads(_canonical(matches[0]["entry"]))
    return SelectedOverlay(locator.request_digest, overlay_id, entry)
