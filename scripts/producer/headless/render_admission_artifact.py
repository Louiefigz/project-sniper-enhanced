"""Closed request, build, and overlay sources published before admission."""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import stat
import uuid
from dataclasses import dataclass

from .authority_record import AuthorityRecordError, ensure_authority_record
from .durable_files import (
    locked_private_dir,
    open_private_dir,
    open_private_file,
    private_child_dir,
    write_all,
)
from .overlay_source_seal import (
    OverlaySourceCapture,
    capture_overlay_source,
    effective_render_intent,
)
from .render_admission_schema import (
    ARTIFACTS_DIR,
    MANIFEST_NAME,
    RenderArtifactLocator,
    ResolvedRenderArtifact,
    _artifact_digest,
    _canonical,
    _selection_directory,
)
from .render_build_receipt import encode_render_build_receipt
from .render_build_receipt_v2_semantics import parse_render_build_receipt_v2
from .render_runtime import RendererRuntime, current_render_build_manifest
from .request_artifact import canonical_request_document

_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_BUILD_BYTES = 2 * 1024 * 1024
_MAX_TOTAL_PAYLOAD_BYTES = 512 * 1024 * 1024
RENDER_ARTIFACT_LOCK = ".render-artifact.lock"


@dataclass(frozen=True)
class RenderArtifactRequest:
    """Mutable request plus explicit runtime to freeze before admission."""

    authority_root: str
    authority_id: str
    request: dict
    runtime: RendererRuntime


def _write_file(dir_fd: int, name: str, raw: bytes) -> None:
    fd = open_private_file(dir_fd, name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        write_all(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(dir_fd)


def _row(path: str, raw: bytes, mode: int = 0o600) -> dict:
    return {
        "mode": mode,
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sizeBytes": len(raw),
    }


def _tar_row(path: str, source: dict, directory: str) -> dict:
    info = os.stat(
        os.path.join(directory, "render-input.tar"), follow_symlinks=False
    )
    return {
        "mode": stat.S_IMODE(info.st_mode),
        "path": path,
        "sha256": source["snapshotSha256"],
        "sizeBytes": info.st_size,
    }


def _merge_epoch(epoch: dict[str, str], source: dict) -> None:
    composition = f"motion/{source['composition']}"
    for row in source["snapshotManifest"]:
        path, digest = row.get("path"), row.get("sha256")
        if path.startswith("request/") or path == composition:
            continue
        if path in epoch and epoch[path] != digest:
            raise RuntimeError(
                "render source closure changed between overlays"
            )
        epoch[path] = digest
    digest = source["sourceCompositionSha256"]
    if composition in epoch and epoch[composition] != digest:
        raise RuntimeError("render source closure changed between overlays")
    epoch[composition] = digest


def _capture_one(
    runtime: RendererRuntime, build_digest: str, item: dict, directory: str
) -> tuple[bytes, dict]:
    intent = effective_render_intent(item["entry"])
    capture = OverlaySourceCapture(
        runtime.pipeline_root, intent, build_digest, item["overlayId"]
    )
    source = capture_overlay_source(capture, directory)
    raw = _canonical(source)
    if len(raw) > _MAX_JSON_BYTES:
        raise RuntimeError("render source receipt exceeds 8 MiB")
    dir_fd = open_private_dir(directory)
    try:
        _write_file(dir_fd, "source-seal.json", raw)
    finally:
        os.close(dir_fd)
    return raw, source


def _add_payload_bytes(current: int, *sizes: int) -> int:
    total = current + sum(sizes)
    if total > _MAX_TOTAL_PAYLOAD_BYTES:
        raise RuntimeError("render artifact exceeds 512 MiB")
    return total


def _payload_result(
    rows: list[dict], request_digest: str, build_digest: str
) -> tuple[list[dict], str, str]:
    return (
        sorted(rows, key=lambda row: row["path"]),
        request_digest,
        build_digest,
    )


def _build_payloads(
    pending: str, pending_fd: int, frozen: dict, runtime: RendererRuntime
) -> tuple[list[dict], str, str]:
    request, request_raw, request_digest = canonical_request_document(frozen)
    build_manifest = current_render_build_manifest(runtime)
    build_raw = encode_render_build_receipt(build_manifest)
    build_digest = parse_render_build_receipt_v2(build_raw).build_digest
    if len(build_raw) > _MAX_BUILD_BYTES:
        raise RuntimeError("render build receipt exceeds 2 MiB")
    _write_file(pending_fd, "request.json", request_raw)
    _write_file(pending_fd, "render-build.json", build_raw)
    rows = [
        _row("request.json", request_raw),
        _row("render-build.json", build_raw),
    ]
    overlays_fd = private_child_dir(pending_fd, "overlays")
    epoch: dict[str, str] = {}
    payload_bytes = len(request_raw) + len(build_raw)
    try:
        for item in request["overlays"]:
            child = _selection_directory(item["overlayId"])
            overlay_fd = private_child_dir(overlays_fd, child)
            directory = os.path.join(pending, "overlays", child)
            os.close(overlay_fd)
            raw, source = _capture_one(runtime, build_digest, item, directory)
            _merge_epoch(epoch, source)
            prefix = f"overlays/{child}"
            rows.append(_row(f"{prefix}/source-seal.json", raw))
            tar = _tar_row(f"{prefix}/render-input.tar", source, directory)
            payload_bytes = _add_payload_bytes(
                payload_bytes, len(raw), tar["sizeBytes"]
            )
            rows.append(tar)
    finally:
        os.close(overlays_fd)
    if _canonical(current_render_build_manifest(runtime)) != _canonical(
        build_manifest
    ):
        raise RuntimeError(
            "render build changed while sealing admission artifact"
        )
    return _payload_result(rows, request_digest, build_digest)


def _pending_dir(
    artifacts_fd: int, artifacts_path: str
) -> tuple[str, str, int]:
    name = f".pending-{uuid.uuid4().hex}"
    path = os.path.join(artifacts_path, name)
    created = False
    try:
        os.mkdir(name, 0o700, dir_fd=artifacts_fd)
        created = True
        os.chmod(name, 0o700, dir_fd=artifacts_fd, follow_symlinks=False)
        os.fsync(artifacts_fd)
        return name, path, open_private_dir(path)
    except BaseException:
        if created:
            shutil.rmtree(path, ignore_errors=True)
        raise


def _build_pending(
    pending: str, pending_fd: int, request: RenderArtifactRequest
) -> str:
    rows, request_digest, build_digest = _build_payloads(
        pending, pending_fd, request.request, request.runtime
    )
    manifest = {
        "buildDigest": build_digest,
        "files": rows,
        "operation": "render-overlays",
        "requestDocumentDigest": request_digest,
        "schemaVersion": 1,
    }
    raw = _canonical(manifest)
    if len(raw) > _MAX_JSON_BYTES:
        raise RuntimeError("render artifact manifest exceeds 8 MiB")
    digest = _artifact_digest(raw)
    _write_file(pending_fd, MANIFEST_NAME, raw)
    return digest


def _publish_pending(
    artifacts_fd: int, pending_name: str, pending_path: str, digest: str
) -> None:
    try:
        os.rename(
            pending_name,
            digest,
            src_dir_fd=artifacts_fd,
            dst_dir_fd=artifacts_fd,
        )
    except OSError as exc:
        if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
            raise
        shutil.rmtree(pending_path)
    os.fsync(artifacts_fd)


def _store_under_lock(root_fd: int, request: RenderArtifactRequest) -> str:
    artifacts_fd = private_child_dir(root_fd, ARTIFACTS_DIR)
    artifacts_path = os.path.join(request.authority_root, ARTIFACTS_DIR)
    pending, pending_fd = "", -1
    try:
        name, pending, pending_fd = _pending_dir(artifacts_fd, artifacts_path)
        digest = _build_pending(pending, pending_fd, request)
        os.close(pending_fd)
        pending_fd = -1
        _publish_pending(artifacts_fd, name, pending, digest)
        return digest
    except BaseException:
        if pending:
            shutil.rmtree(pending, ignore_errors=True)
        raise
    finally:
        if pending_fd >= 0:
            os.close(pending_fd)
        os.close(artifacts_fd)


def store_render_admission_artifact(
    request: RenderArtifactRequest,
) -> RenderArtifactLocator:
    """Capture and atomically publish all render bytes before admission."""
    if type(request) is not RenderArtifactRequest:
        raise RuntimeError("render artifact request is invalid")
    frozen = canonical_request_document(request.request)[0]
    closed = RenderArtifactRequest(
        request.authority_root, request.authority_id, frozen, request.runtime
    )
    with locked_private_dir(
        closed.authority_root, RENDER_ARTIFACT_LOCK
    ) as root:
        try:
            ensure_authority_record(root, closed.authority_id)
        except AuthorityRecordError as exc:
            raise RuntimeError("render artifact authority is invalid") from exc
        digest = _store_under_lock(root, closed)
    locator = RenderArtifactLocator(digest)
    load_render_admission_artifact(closed.authority_root, locator)
    return locator


def load_render_admission_artifact(
    authority_root: str, locator: RenderArtifactLocator
) -> ResolvedRenderArtifact:
    """Reload the exact closed artifact and rederive every retained fact."""
    from .render_admission_artifact_reader import (
        load_render_admission_artifact as load_artifact,
    )

    return load_artifact(authority_root, locator)
