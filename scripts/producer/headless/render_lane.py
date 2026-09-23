"""Dedicated non-GUI composition root for the sealed OCI graphics renderer."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from typing import Any
from graphics.template_contract import validate_entry
from .overlay_seal import (
    OverlayPrepareRequest,
    OverlaySealBinding,
    ResolvedOverlaySeal,
    effective_render_intent,
    load_overlay,
    prepare_overlay,
    render_intents_equal,
)
from .overlay_seal_store import OverlaySealLocator
from .docker_identity import file_sha256
from .process_runner import ProcessDeadlineError, ProcessRequest, run_text
from .render_lane_cache import CacheBinding, assert_cache_binding, prepare_attempt_cache
from .render_build import render_build_manifest_digest, render_build_manifests_equal
from .render_build_receipt import (
    RenderBuildLocator,
    load_render_build,
    store_render_build,
)
from .render_result import RenderProofIntent, build_expectation, validate_worker_proof
from .resource_ledger import ResourceRequest, container_lease, removed_containers
from .render_runtime import (
    RendererRuntime,
    current_render_build_digest,
    current_render_build_manifest,
)
from .request_artifact import (
    RequestArtifactLocator,
    select_overlay,
)

RENDERER_MODE = "sealed-oci-v2"
_RESULT_KEY = re.compile(r"[0-9a-f]{64}")

@dataclass(frozen=True)
class RenderExecutionPolicy:
    """Closed renderer selection persisted by the future MP4 controller."""

    renderer_mode: str


@dataclass(frozen=True)
class OverlayLaunchRequest:
    """One attempt-bound overlay render request."""

    authority_root: str
    attempt_root: str
    attempt_id: str
    build: RenderBuildLocator
    request: RequestArtifactLocator
    overlay_id: str
    seal: OverlaySealLocator

    @property
    def build_digest(self) -> str:
        return self.build.build_digest


@dataclass(frozen=True)
class OverlayPreparationRequest:
    """One planned entry plus its already-admitted attempt identities."""

    authority_root: str
    attempt_root: str
    attempt_id: str
    request: RequestArtifactLocator
    overlay_id: str


def prepare_overlay_launch(request: OverlayPreparationRequest,
                           runtime: RendererRuntime) -> OverlayLaunchRequest:
    """Derive and persist every per-overlay fact before worker launch."""
    expected_attempt = os.path.join(
        request.authority_root, "attempts", request.attempt_id)
    if request.attempt_root != expected_attempt:
        raise RuntimeError("overlay attempt is outside its request authority")
    selected = select_overlay(
        request.authority_root, request.request, request.overlay_id)
    validate_entry(selected.entry)
    build = store_render_build(request.attempt_root, current_render_build_manifest(runtime))
    prepared = OverlayPrepareRequest(
        request.attempt_root, request.attempt_id, selected.request_digest,
        build.build_digest, runtime.pipeline_root, selected.entry,
        selected.overlay_id)
    seal = prepare_overlay(prepared)
    return OverlayLaunchRequest(
        request.authority_root, request.attempt_root, request.attempt_id,
        build, request.request, request.overlay_id, seal)


def _validated_build(request: OverlayLaunchRequest,
                     runtime: RendererRuntime) -> str:
    retained = load_render_build(request.attempt_root, request.build)
    live = current_render_build_manifest(runtime)
    digest = render_build_manifest_digest(live)
    if not render_build_manifests_equal(live, retained) or digest != request.build_digest:
        raise RuntimeError("admitted render build drifted")
    return digest


def _child_environment(runtime: RendererRuntime, binding: CacheBinding,
                       container_name: str) -> dict[str, str]:
    return {
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": "/usr/bin:/bin",
        "TMPDIR": binding.temp_dir, "TZ": "UTC",
        "SNIPER_PIPELINE_ROOT": runtime.pipeline_root,
        "SNIPER_RUNTIME_REPO_ROOT": runtime.runtime_root,
        "SNIPER_DOCKER_PATH": runtime.docker,
        "SNIPER_DOCKER_SOCKET": runtime.docker_socket,
        "SNIPER_RENDER_IMAGE_ID": runtime.image_id,
        "SNIPER_RENDER_CONTAINER_NAME": container_name,
        "SNIPER_RENDER_UID_GID": runtime.user_id,
        "SNIPER_PROOF_FFMPEG_PATH": runtime.proof_ffmpeg,
        "SNIPER_PROOF_FFPROBE_PATH": runtime.proof_ffprobe,
    }


def _resource_request(request: OverlayLaunchRequest,
                      runtime: RendererRuntime) -> ResourceRequest:
    return ResourceRequest(
        request.attempt_root, request.attempt_id, runtime.docker,
        runtime.docker_socket, runtime.image_id, runtime.user_id)


def _worker_path(runtime: RendererRuntime) -> str:
    path = os.path.join(runtime.pipeline_root, "scripts", "producer", "headless",
                        "render_worker_bootstrap.py")
    if not os.path.isfile(path):
        raise RuntimeError("headless render worker is missing")
    return path


def _fd_sha256(fd: int) -> str:
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    for chunk in iter(lambda: os.read(fd, 1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _inode_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _fd_binding(fd: int) -> tuple[dict, tuple[int, ...]]:
    before = os.fstat(fd)
    safe = (stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and before.st_uid == os.geteuid()
            and stat.S_IMODE(before.st_mode) == 0o600
            and 0 < before.st_size <= 512 * 1024 * 1024)
    if not safe:
        raise RuntimeError("headless render output inode is unsafe")
    digest = _fd_sha256(fd)
    after = os.fstat(fd)
    if _inode_identity(before) != _inode_identity(after):
        raise RuntimeError("headless render output changed during validation")
    value = {"device": after.st_dev, "inode": after.st_ino,
             "sha256": digest, "sizeBytes": after.st_size}
    return value, _inode_identity(after)


def _opened_output(cache_fd: int, basename: str) -> tuple[dict, tuple[int, ...]]:
    fd = os.open(basename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=cache_fd)
    try:
        return _fd_binding(fd)
    finally:
        os.close(fd)


def _output_binding(path: str, binding: CacheBinding) -> dict:
    if (not os.path.isabs(path) or os.path.realpath(path) != path
            or os.path.dirname(path) != binding.cache_dir):
        raise RuntimeError("headless render worker result escaped its attempt cache")
    cache_fd = os.open(binding.cache_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        assert_cache_binding(cache_fd, binding)
        value, identity = _opened_output(cache_fd, os.path.basename(path))
        current = os.stat(
            os.path.basename(path), dir_fd=cache_fd, follow_symlinks=False)
    finally:
        os.close(cache_fd)
    if identity != _inode_identity(current):
        raise RuntimeError("headless render output changed during validation")
    return value


def _validated_result(stdout: str, binding: CacheBinding,
                      seal: ResolvedOverlaySeal,
                      runtime_identity: tuple[str, str, ResourceRequest]
                      ) -> tuple[dict, dict]:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("headless render worker returned invalid JSON") from exc
    required = {"cached", "fmt", "fps", "key", "kind", "path", "proof"}
    if not isinstance(value, dict) or set(value) != required:
        raise RuntimeError("headless render worker returned an invalid result schema")
    path = value["path"]
    expected_kind = seal.entry["kind"]
    valid = (
        type(value["cached"]) is bool and isinstance(value["proof"], dict)
        and value["fps"] == "30"  # Exact current render_presealed clock; not a catalog-wide rate.
        and isinstance(value["kind"], str) and isinstance(value["fmt"], str)
        and isinstance(value["key"], str) and _RESULT_KEY.fullmatch(value["key"])
        and value["key"] == seal.key
        and isinstance(path, str)
        and value["kind"] == expected_kind
        and value["fmt"] == seal.fmt
        and os.path.basename(path) == f'{value["key"]}.{value["fmt"]}'
    )
    if not valid:
        raise RuntimeError("headless render worker returned invalid result values")
    output = _output_binding(path, binding)
    expected_image_id, container_name, resources = runtime_identity
    container_names = (removed_containers(resources) if value["cached"]
                       else (container_name,))
    expectation = build_expectation(seal.entry, RenderProofIntent(
        seal.fmt, seal.dimensions, seal.expected_copy,
        seal.snapshot.asset_bindings, container_names,
        seal.snapshot.sha256, seal.snapshot.manifest))
    validate_worker_proof(value, output, expectation, expected_image_id)
    final_output = _output_binding(path, binding)
    if final_output != output:
        raise RuntimeError("headless render output changed during proof validation")
    return value, final_output


def _run_worker(request: ProcessRequest) -> Any:
    try:
        proc = run_text(request)
    except ProcessDeadlineError as exc:
        raise RuntimeError("headless render worker exceeded its deadline") from exc
    if proc.returncode:
        raise RuntimeError(
            f"headless render worker failed: {proc.stderr.strip()[-500:]}")
    return proc


def launch_overlay(policy: RenderExecutionPolicy, request: OverlayLaunchRequest,
                   runtime: RendererRuntime) -> dict:
    """Render one entry in a closed child process with no ambient fallback."""
    if policy.renderer_mode != RENDERER_MODE:
        raise RuntimeError(f"rendererMode must be exactly {RENDERER_MODE}")
    _validated_build(request, runtime)
    selected = select_overlay(
        request.authority_root, request.request, request.overlay_id)
    seal_binding = OverlaySealBinding(
        request.attempt_root, request.attempt_id,
        selected.request_digest, request.build_digest, selected.overlay_id)
    seal = load_overlay(request.seal, seal_binding)
    if not render_intents_equal(
            seal.intent, effective_render_intent(selected.entry)):
        raise RuntimeError("overlay seal is not the selected request entry")
    identity = (request.attempt_id, selected.request_digest,
                request.build_digest, runtime.image_id)
    binding = prepare_attempt_cache(request.attempt_root, identity)
    resources = _resource_request(request, runtime)
    with container_lease(resources) as container_name:
        worker = {"attemptId": request.attempt_id,
                  "attemptRoot": request.attempt_root,
                  "buildDigest": request.build_digest,
                  "cacheDir": binding.cache_dir,
                  "requestDigest": selected.request_digest,
                  "selectionId": selected.overlay_id,
                  "sealPath": request.seal.path,
                  "sealSha256": request.seal.sha256}
        payload = json.dumps(worker, ensure_ascii=True, separators=(",", ":"),
                             sort_keys=True)
        pycache = os.path.join(binding.temp_dir, "pycache")
        command = [runtime.python, "-I", "-S", "-B", "-X",
                   f"pycache_prefix={pycache}", _worker_path(runtime)]
        proc = _run_worker(ProcessRequest(
            tuple(command), payload, request.attempt_root,
            _child_environment(runtime, binding, container_name),
            runtime.timeout_seconds))
        seal = load_overlay(request.seal, seal_binding)
        result, output = _validated_result(
            proc.stdout, binding, seal,
            (runtime.image_id, container_name, resources))
        if _validated_build(request, runtime) != request.build_digest:
            raise RuntimeError("render build drifted while worker was executing")
        launcher = file_sha256(__file__)
        return {"cacheBinding": {
            "device": binding.cache_device, "inode": binding.cache_inode,
            "ownerReceiptSha256": binding.receipt_sha256,
        }, "launcherSha256": launcher, "outputBinding": output,
            "renderBuildReceipt": request.build.build_digest,
            "rendererMode": RENDERER_MODE, "result": result}
