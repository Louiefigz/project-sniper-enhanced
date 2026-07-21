"""Canonical pre-admission records for graphic receipt fixtures."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from headless.request_artifact import canonical_request_document


@dataclass(frozen=True)
class AdmissionRecordInputV1:
    """Exact retained payload bytes used to build one admission manifest."""

    source_json: bytes
    selection_id: str
    build_digest: str
    plan_row: dict
    render_build_json: bytes


def canonical_line(value: object) -> bytes:
    """Encode the newline-terminated durable render-admission format."""
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )


def render_key(snapshot: str, build: str) -> str:
    """Reproduce the qualified overlay-source key domain."""
    material = snapshot.encode("ascii") + b"\0" + build.encode("ascii")
    return hashlib.sha256(b"sniper-overlay-key-v2\0" + material).hexdigest()


def selection_directory(selection_id: str) -> str:
    """Reproduce the path-free selection directory identity."""
    return hashlib.sha256(
        b"sniper-render-selection-v1\0" + selection_id.encode("ascii")
    ).hexdigest()


def _file(path: str, raw: bytes | None = None) -> dict:
    data = raw if raw is not None else path.encode("ascii")
    return {
        "mode": 0o600,
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "sizeBytes": len(data),
    }


def _snapshot_file(path: str, snapshot_sha256: str) -> dict:
    return {
        "mode": 0o400,
        "path": path,
        "sha256": snapshot_sha256,
        "sizeBytes": 1,
    }


def admission_digest(raw: bytes) -> str:
    """Return the actual render-admission artifact domain digest."""
    return hashlib.sha256(b"sniper-render-admission-artifact-v1\0" + raw).hexdigest()


def admission_records(value: AdmissionRecordInputV1) -> tuple[bytes, bytes, str]:
    """Build an exact request, source-row manifest, and artifact digest."""
    request = {
        "schemaVersion": 1,
        "operation": "render-overlays",
        "overlays": [{"overlayId": value.selection_id, "entry": value.plan_row}],
    }
    _frozen, request_raw, request_digest = canonical_request_document(request)
    prefix = f"overlays/{selection_directory(value.selection_id)}"
    snapshot = json.loads(value.source_json)["snapshotSha256"]
    rows = [
        _file("request.json", request_raw),
        _file("render-build.json", value.render_build_json),
        _snapshot_file(f"{prefix}/render-input.tar", snapshot),
        _file(f"{prefix}/source-seal.json", value.source_json),
    ]
    document = {
        "schemaVersion": 1,
        "operation": "render-overlays",
        "requestDocumentDigest": request_digest,
        "buildDigest": value.build_digest,
        "files": sorted(rows, key=lambda row: row["path"]),
    }
    manifest = canonical_line(document)
    return manifest, request_raw, admission_digest(manifest)
