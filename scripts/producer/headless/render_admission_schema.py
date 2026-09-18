"""Canonical schema and identity helpers for render admission artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass

from .durable_files import read_private_file
from .overlay_source_seal import ResolvedOverlaySeal

ARTIFACTS_DIR = "render-admission-artifacts"
MANIFEST_NAME = "artifact-manifest.json"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_MAX_JSON_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class RenderArtifactLocator:
    """The only caller-visible identity for a closed render artifact."""

    artifact_digest: str


@dataclass(frozen=True)
class ArtifactOverlay:
    """One exact request row and its independently verified source capsule."""

    overlay_id: str
    entry: dict
    directory: str
    source_value: dict
    resolved: ResolvedOverlaySeal


@dataclass(frozen=True)
class ResolvedRenderArtifact:
    """Verified pre-admission artifact facts derived only from retained bytes."""

    artifact_digest: str
    request_document_digest: str
    request: dict
    build_digest: str
    build_manifest: dict
    overlays: tuple[ArtifactOverlay, ...]


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                             sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("render admission artifact is not canonical JSON") from exc
    return (encoded + "\n").encode("ascii")


def _decode(raw: bytes, label: str) -> dict:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"render artifact {label} is invalid JSON") from exc
    if not isinstance(value, dict) or raw != _canonical(value):
        raise RuntimeError(f"render artifact {label} is not canonical JSON")
    return value


def _artifact_digest(raw: bytes) -> str:
    return hashlib.sha256(
        b"sniper-render-admission-artifact-v1\0" + raw).hexdigest()


def _selection_directory(selection_id: str) -> str:
    return hashlib.sha256(
        b"sniper-render-selection-v1\0" + selection_id.encode("ascii")
    ).hexdigest()


def _artifact_path(authority_root: str, digest: str) -> str:
    if (not os.path.isabs(authority_root)
            or os.path.realpath(authority_root) != authority_root
            or not isinstance(digest, str)
            or not _DIGEST.fullmatch(digest)):
        raise RuntimeError("render admission artifact identity is invalid")
    return os.path.join(authority_root, ARTIFACTS_DIR, digest)


def _read_doc(dir_fd: int, name: str) -> tuple[dict, bytes]:
    raw = read_private_file(dir_fd, name, _MAX_JSON_BYTES)
    return _decode(raw, name), raw


def _row_map(manifest: dict) -> dict[str, dict]:
    rows = manifest.get("files")
    if (not isinstance(rows, list)
            or not all(isinstance(row, dict) for row in rows)):
        raise RuntimeError("render artifact manifest file rows are invalid")
    ordered = sorted(rows, key=lambda row: str(row.get("path", "")))
    valid = (rows == ordered and all(
        set(row) == {"mode", "path", "sha256", "sizeBytes"}
        and isinstance(row["path"], str)
        and _DIGEST.fullmatch(str(row["sha256"]))
        and type(row["mode"]) is int and type(row["sizeBytes"]) is int
        and row["mode"] >= 0 and row["sizeBytes"] >= 0
        for row in rows))
    mapped = {row["path"]: row for row in rows} if valid else {}
    if not valid or len(mapped) != len(rows):
        raise RuntimeError("render artifact manifest file rows are invalid")
    return mapped


def _match_raw(row: dict, raw: bytes, mode: int) -> None:
    actual = (len(raw), hashlib.sha256(raw).hexdigest(), mode)
    expected = (row["sizeBytes"], row["sha256"], row["mode"])
    if actual != expected:
        raise RuntimeError("render artifact file does not match its manifest")
