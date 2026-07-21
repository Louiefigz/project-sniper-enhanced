"""Explicit trusted host runtime validation and build-closure identity."""
from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass

from .render_build import (
    RenderBuildRequest,
    render_build_digest,
    render_build_manifest,
)

_IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
_USER = re.compile(r"[1-9][0-9]*:[1-9][0-9]*")


@dataclass(frozen=True)
class RendererRuntime:
    """Literal, secret-free runtime values allowed into the child process."""

    pipeline_root: str
    runtime_root: str
    python: str
    docker: str
    docker_socket: str
    image_id: str
    user_id: str
    proof_ffmpeg: str
    proof_ffprobe: str
    timeout_seconds: float = 1200.0


def _regular_executable(path: str, label: str) -> str:
    if not os.path.isabs(path) or os.path.realpath(path) != path:
        raise RuntimeError(f"{label} must be a canonical absolute path")
    info = os.stat(path)
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        raise RuntimeError(f"{label} must be an executable regular file")
    return path


def validate_renderer_runtime(runtime: RendererRuntime) -> None:
    """Reject ambient, mutable, unapproved, or nonlocal renderer selection."""
    for root in (runtime.pipeline_root, runtime.runtime_root):
        if not os.path.isabs(root) or os.path.realpath(root) != root:
            raise RuntimeError("renderer roots must be canonical absolute paths")
        if not os.path.isdir(root):
            raise RuntimeError("renderer roots must be directories")
    for path, label in (
            (runtime.python, "python"), (runtime.docker, "docker"),
            (runtime.proof_ffmpeg, "proof ffmpeg"),
            (runtime.proof_ffprobe, "proof ffprobe")):
        _regular_executable(path, label)
    if (not os.path.isabs(runtime.docker_socket)
            or os.path.realpath(runtime.docker_socket) != runtime.docker_socket):
        raise RuntimeError("Docker socket must be a canonical absolute path")
    socket_info = os.stat(runtime.docker_socket)
    if not stat.S_ISSOCK(socket_info.st_mode):
        raise RuntimeError("Docker socket must be an absolute socket")
    if socket_info.st_uid != os.geteuid() or not _IMAGE.fullmatch(runtime.image_id):
        raise RuntimeError("Docker socket owner or renderer image is invalid")
    if not _USER.fullmatch(runtime.user_id) or not 0 < runtime.timeout_seconds <= 3600:
        raise RuntimeError("renderer user or timeout is invalid")
    approval = os.path.join(runtime.pipeline_root, "scripts", "producer",
                            "headless", "render_image_approval.json")
    with open(approval, encoding="utf-8") as handle:
        approved = json.load(handle).get("imageId")
    if approved != runtime.image_id:
        raise RuntimeError("renderer image does not match checked-in approval")


def _build_request(runtime: RendererRuntime) -> RenderBuildRequest:
    return RenderBuildRequest(
        runtime.pipeline_root, runtime.runtime_root, runtime.python,
        runtime.docker, runtime.docker_socket, runtime.image_id,
        runtime.user_id, runtime.proof_ffmpeg, runtime.proof_ffprobe,
        runtime.timeout_seconds)


def current_render_build_digest(runtime: RendererRuntime) -> str:
    """Compute the exact live host closure used by attempt admission."""
    validate_renderer_runtime(runtime)
    return render_build_digest(_build_request(runtime))


def current_render_build_manifest(runtime: RendererRuntime) -> dict:
    """Return the exact live manifest after full runtime validation."""
    validate_renderer_runtime(runtime)
    return render_build_manifest(_build_request(runtime))
