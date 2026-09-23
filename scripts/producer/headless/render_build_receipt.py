"""Attempt-owned retained evidence for one admitted render build manifest."""
from __future__ import annotations

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
from .render_build_manifest_v4_semantics import parse_render_build_manifest_v4
from .render_build_receipt_v4_semantics import parse_render_build_receipt_v4

_DIGEST = re.compile(r"[0-9a-f]{64}")
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class RenderBuildLocator:
    """Attempt-derived path and digest for one canonical build receipt."""

    path: str
    build_digest: str


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                             sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("render build receipt is not canonical JSON") from exc
    return (encoded + "\n").encode("ascii")


def _value(manifest: dict) -> dict:
    if type(manifest) is not dict:
        raise RuntimeError("render build manifest must be an object")
    parsed = parse_render_build_manifest_v4(_canonical(manifest)[:-1])
    return {"buildDigest": parsed.build_digest,
            "manifest": manifest, "schemaVersion": 4}


def encode_render_build_receipt(manifest: dict) -> bytes:
    """Freeze and encode only a closed current V4 build declaration."""
    value = _value(json.loads(_canonical(manifest)))
    raw = _canonical(value)
    if len(raw) > _MAX_RECEIPT_BYTES:
        raise RuntimeError("render build receipt exceeds 2 MiB")
    return raw


def _path(attempt_root: str, digest: str) -> str:
    if (not os.path.isabs(attempt_root)
            or os.path.realpath(attempt_root) != attempt_root
            or not _DIGEST.fullmatch(digest)):
        raise RuntimeError("render build receipt authority is invalid")
    return os.path.join(attempt_root, "work", "render-builds", f"{digest}.json")


def _write_build_once(builds_fd: int, name: str, raw: bytes) -> None:
    try:
        fd = open_private_file(
            builds_fd, name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except DurableFileError as exc:
        if not isinstance(exc.__cause__, FileExistsError):
            raise
        if read_private_file(builds_fd, name, _MAX_RECEIPT_BYTES) != raw:
            raise RuntimeError("render build digest path has other bytes")
    else:
        try:
            write_all(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(builds_fd)


def store_render_build(attempt_root: str,
                       manifest: dict) -> RenderBuildLocator:
    """Persist a closed current V4 build before producing an overlay seal."""
    raw = encode_render_build_receipt(manifest)
    digest = parse_render_build_receipt_v4(raw).build_digest
    with locked_private_dir(attempt_root, ".render-build.lock") as root_fd:
        work_fd = private_child_dir(root_fd, "work")
        builds_fd = private_child_dir(work_fd, "render-builds")
        try:
            name = f"{digest}.json"
            _write_build_once(builds_fd, name, raw)
        finally:
            os.close(builds_fd)
            os.close(work_fd)
    return RenderBuildLocator(_path(attempt_root, digest), digest)


def load_render_build(attempt_root: str,
                      locator: RenderBuildLocator) -> dict:
    """Reload closed current V4 evidence; historical V1 needs its own reader."""
    expected = _path(attempt_root, locator.build_digest)
    if locator.path != expected or os.path.realpath(locator.path) != locator.path:
        raise RuntimeError("render build receipt locator is invalid")
    directory_fd = open_private_dir(os.path.dirname(expected))
    try:
        raw = read_private_file(
            directory_fd, os.path.basename(expected), _MAX_RECEIPT_BYTES)
    finally:
        os.close(directory_fd)
    receipt = parse_render_build_receipt_v4(raw)
    if receipt.build_digest != locator.build_digest:
        raise RuntimeError("render build receipt identity is invalid")
    return json.loads(receipt.manifest.document_json)
