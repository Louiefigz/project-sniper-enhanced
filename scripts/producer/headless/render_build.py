"""Content identity for the live host portion of the sealed render lane."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass

from .render_build_manifest_v1_contract import (
    RENDER_BUILD_V1_DIGEST_DOMAIN,
    RENDER_BUILD_V1_POLICY,
)
from .render_build_manifest_v2_contract import (
    RENDER_BUILD_V2_DIGEST_DOMAIN,
    RENDER_BUILD_V2_POLICY,
)
from .render_build_manifest_v3_contract import (
    RENDER_BUILD_V3_DIGEST_DOMAIN,
    RENDER_BUILD_V3_IMPLEMENTATION_PATHS,
    RENDER_BUILD_V3_POLICY,
)
from .safe_source_files import read_stable_owned_file

BUILD_POLICY = RENDER_BUILD_V3_POLICY
BUILD_SCHEMA_VERSION = 3
_IMPLEMENTATION_FILES = RENDER_BUILD_V3_IMPLEMENTATION_PATHS


@dataclass(frozen=True)
class RenderBuildRequest:
    """Explicit execution paths and immutable OCI identity for one release."""

    pipeline_root: str
    runtime_root: str
    python: str
    docker: str
    docker_socket: str
    image_id: str
    user_id: str
    proof_ffmpeg: str
    proof_ffprobe: str
    timeout_seconds: float


def _read_stable(path: str) -> bytes:
    return read_stable_owned_file(path, f"render build input: {path}")


def _digest_row(label: str, path: str) -> dict:
    if not os.path.isabs(path) or os.path.realpath(path) != path:
        raise RuntimeError(f"render build {label} path is not canonical")
    data = _read_stable(path)
    if not data:
        raise RuntimeError(f"render build {label} must be nonempty")
    return {
        "label": label,
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "sizeBytes": len(data),
    }


def _implementation_rows(root: str) -> list[dict]:
    if not os.path.isabs(root) or os.path.realpath(root) != root:
        raise RuntimeError("render build root must be canonical")
    rows = []
    for relative in _IMPLEMENTATION_FILES:
        path = os.path.join(root, relative)
        data = _read_stable(path)
        if not data:
            raise RuntimeError(
                f"render build source must be nonempty: {relative}"
            )
        rows.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "sizeBytes": len(data),
            }
        )
    return rows


def _tool_rows(request: RenderBuildRequest) -> list[dict]:
    return [
        _digest_row("docker", request.docker),
        _digest_row("proof-ffmpeg", request.proof_ffmpeg),
        _digest_row("proof-ffprobe", request.proof_ffprobe),
        _digest_row("python", request.python),
    ]


def _validate_tool_rows(rows: list[dict]) -> None:
    labels = ("docker", "proof-ffmpeg", "proof-ffprobe", "python")
    paths = tuple(row["path"] for row in rows)
    digests = tuple(row["sha256"] for row in rows)
    valid = tuple(row["label"] for row in rows) == labels
    valid = valid and len({path.casefold() for path in paths}) == len(paths)
    valid = valid and len(set(digests)) == len(digests)
    if not valid:
        raise RuntimeError("render build tool roles alias or reorder")


def _socket_row(path: str) -> dict:
    info = os.stat(path)
    return {
        "path": path,
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": stat.S_IFMT(info.st_mode),
        "ownerUid": info.st_uid,
    }


def render_build_manifest(request: RenderBuildRequest) -> dict:
    """Return the exact canonical host/runtime closure used for admission."""
    if request.pipeline_root != _LOADED_ROOT:
        raise RuntimeError(
            "renderer does not execute from its loaded release root"
        )
    implementation = _implementation_rows(request.pipeline_root)
    tools = _tool_rows(request)
    _validate_tool_rows(tools)
    if (
        implementation != _implementation_rows(request.pipeline_root)
        or tools != _tool_rows(request)
        or implementation != list(_LOADED_IMPLEMENTATION)
    ):
        raise RuntimeError("render build closure changed while hashing")
    return {
        "schemaVersion": BUILD_SCHEMA_VERSION,
        "policy": BUILD_POLICY,
        "imageId": request.image_id,
        "userId": request.user_id,
        "dockerSocket": _socket_row(request.docker_socket),
        "runtimeRoot": request.runtime_root,
        "pipelineRoot": request.pipeline_root,
        "timeoutSeconds": request.timeout_seconds,
        "pythonFlags": ["-I", "-S", "-B", "-X", "pycache_prefix=<attempt>"],
        "implementation": implementation,
        "tools": tools,
    }


def render_build_manifest_digest(manifest: dict) -> str:
    """Hash a declared version; hashing alone does not validate its contents.

    Historical V1/V2 hashing remains reproducible. Current stores/loaders require
    the closed V3 parser separately; digest dispatch never admits old execution.
    """
    if type(manifest) is not dict or type(manifest.get("schemaVersion")) is not int:
        raise RuntimeError("render build digest version is invalid")
    versions = {
        (1, RENDER_BUILD_V1_POLICY): RENDER_BUILD_V1_DIGEST_DOMAIN,
        (2, RENDER_BUILD_V2_POLICY): RENDER_BUILD_V2_DIGEST_DOMAIN,
        (3, RENDER_BUILD_V3_POLICY): RENDER_BUILD_V3_DIGEST_DOMAIN,
    }
    domain = versions.get((manifest["schemaVersion"], manifest.get("policy")))
    if domain is None:
        raise RuntimeError("render build digest version is unsupported")
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(domain + encoded).hexdigest()


def render_build_manifests_equal(first: dict, second: dict) -> bool:
    """Compare build manifests as exact canonical JSON values."""
    try:
        left = json.dumps(
            first,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("ascii")
        right = json.dumps(
            second,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError):
        return False
    return left == right


def render_build_digest(request: RenderBuildRequest) -> str:
    """Compute and hash the current exact build manifest."""
    return render_build_manifest_digest(render_build_manifest(request))


_LOADED_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
_LOADED_IMPLEMENTATION = tuple(_implementation_rows(_LOADED_ROOT))
