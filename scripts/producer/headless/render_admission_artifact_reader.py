"""Independent verifier for one closed pre-admission render artifact."""

from __future__ import annotations

import os

from .durable_files import (
    exact_directory_entries,
    open_private_dir,
    read_private_file,
)
from .overlay_source_seal import (
    effective_render_intent,
    render_intents_equal,
    resolve_overlay_source,
)
from .render_admission_schema import (
    MANIFEST_NAME,
    ArtifactOverlay,
    RenderArtifactLocator,
    ResolvedRenderArtifact,
    _artifact_digest,
    _artifact_path,
    _decode,
    _match_raw,
    _read_doc,
    _row_map,
    _selection_directory,
)
from .render_build_receipt_v3_semantics import parse_render_build_receipt_v3
from .request_artifact import (
    canonical_request_document,
    decode_request_document,
)
from .sealed_archive import verify_archive_binding

_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_BUILD_BYTES = 2 * 1024 * 1024
_MAX_TOTAL_PAYLOAD_BYTES = 512 * 1024 * 1024


def _manifest_row(rows: dict[str, dict], path: str) -> dict:
    try:
        return rows[path]
    except KeyError as exc:
        raise RuntimeError(
            "render artifact manifest closure is invalid"
        ) from exc


def _load_overlay(
    root: str, item: dict, rows: dict[str, dict], build_digest: str
) -> ArtifactOverlay:
    overlay_id = item["overlayId"]
    child = _selection_directory(overlay_id)
    directory = os.path.join(root, "overlays", child)
    dir_fd = open_private_dir(directory)
    try:
        expected = {"render-input.tar", "source-seal.json"}
        if not exact_directory_entries(dir_fd, expected):
            raise RuntimeError("render artifact overlay closure is invalid")
        source, raw = _read_doc(dir_fd, "source-seal.json")
    finally:
        os.close(dir_fd)
    prefix = f"overlays/{child}"
    _match_raw(_manifest_row(rows, f"{prefix}/source-seal.json"), raw, 0o600)
    resolved = resolve_overlay_source(
        source, directory, overlay_id, build_digest
    )
    tar = _manifest_row(rows, f"{prefix}/render-input.tar")
    proof = verify_archive_binding(
        resolved.snapshot.path,
        resolved.snapshot.sha256,
        resolved.snapshot.manifest,
    )
    actual = (proof["sizeBytes"], proof["sha256"], proof["mode"])
    if actual != (tar["sizeBytes"], tar["sha256"], tar["mode"]):
        raise RuntimeError("render artifact tar does not match its manifest")
    if not render_intents_equal(
        effective_render_intent(item["entry"]), resolved.intent
    ):
        raise RuntimeError(
            "render artifact source does not match request entry"
        )
    return ArtifactOverlay(
        overlay_id, item["entry"], directory, source, resolved
    )


def _load_root(root: str) -> tuple[dict, bytes, bytes, dict, bytes]:
    root_fd = open_private_dir(root)
    try:
        expected = {
            MANIFEST_NAME,
            "overlays",
            "render-build.json",
            "request.json",
        }
        if not exact_directory_entries(root_fd, expected):
            raise RuntimeError(
                "render admission artifact root closure is invalid"
            )
        manifest, manifest_raw = _read_doc(root_fd, MANIFEST_NAME)
        request_raw = read_private_file(
            root_fd, "request.json", _MAX_JSON_BYTES
        )
        build_raw = read_private_file(
            root_fd, "render-build.json", _MAX_BUILD_BYTES
        )
        build = _decode(build_raw, "render-build.json")
    finally:
        os.close(root_fd)
    return manifest, manifest_raw, request_raw, build, build_raw


def _validate_envelope(
    manifest: dict, request_digest: str, build: dict, build_digest: str
) -> None:
    valid = (
        set(manifest)
        == {
            "buildDigest",
            "files",
            "operation",
            "requestDocumentDigest",
            "schemaVersion",
        }
        and type(manifest.get("schemaVersion")) is int
        and manifest.get("schemaVersion") == 1
        and manifest.get("operation") == "render-overlays"
        and manifest.get("requestDocumentDigest") == request_digest
        and manifest.get("buildDigest") == build_digest
        and set(build) == {"buildDigest", "manifest", "schemaVersion"}
        and type(build.get("schemaVersion")) is int
        and build.get("schemaVersion") == 3
        and build.get("buildDigest") == build_digest
    )
    if not valid:
        raise RuntimeError("render admission artifact envelope is invalid")


def _expected_files(request: dict) -> set[str]:
    expected = {"request.json", "render-build.json"}
    expected.update(
        f"overlays/{_selection_directory(row['overlayId'])}/{name}"
        for row in request["overlays"]
        for name in ("render-input.tar", "source-seal.json")
    )
    return expected


def _validate_overlay_set(root: str, request: dict) -> None:
    overlays_fd = open_private_dir(os.path.join(root, "overlays"))
    try:
        identifiers = {
            _selection_directory(row["overlayId"])
            for row in request["overlays"]
        }
        if not exact_directory_entries(overlays_fd, identifiers):
            raise RuntimeError(
                "render admission artifact overlay set is invalid"
            )
    finally:
        os.close(overlays_fd)


def _validate_payload_budget(rows: dict[str, dict]) -> None:
    total = sum(row["sizeBytes"] for row in rows.values())
    if total > _MAX_TOTAL_PAYLOAD_BYTES:
        raise RuntimeError("render artifact exceeds 512 MiB")


def load_render_admission_artifact(
    authority_root: str, locator: RenderArtifactLocator
) -> ResolvedRenderArtifact:
    """Reload the exact closed artifact and rederive every retained fact."""
    root = _artifact_path(authority_root, locator.artifact_digest)
    manifest, manifest_raw, request_raw, build, build_raw = _load_root(root)
    if _artifact_digest(manifest_raw) != locator.artifact_digest:
        raise RuntimeError("render admission artifact digest mismatch")
    rows = _row_map(manifest)
    request = decode_request_document(request_raw)
    request_digest = canonical_request_document(request)[2]
    build_manifest = build.get("manifest")
    if not isinstance(build_manifest, dict):
        raise RuntimeError("render admission artifact envelope is invalid")
    build_digest = parse_render_build_receipt_v3(build_raw).build_digest
    _validate_envelope(manifest, request_digest, build, build_digest)
    _match_raw(_manifest_row(rows, "request.json"), request_raw, 0o600)
    _match_raw(_manifest_row(rows, "render-build.json"), build_raw, 0o600)
    if set(rows) != _expected_files(request):
        raise RuntimeError(
            "render admission artifact manifest closure is invalid"
        )
    _validate_payload_budget(rows)
    _validate_overlay_set(root, request)
    overlays = tuple(
        _load_overlay(root, item, rows, build_digest)
        for item in request["overlays"]
    )
    return ResolvedRenderArtifact(
        locator.artifact_digest,
        request_digest,
        request,
        build_digest,
        build_manifest,
        overlays,
    )
