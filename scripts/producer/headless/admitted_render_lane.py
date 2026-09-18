"""Attempt-only production facade for admitted multi-overlay rendering."""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .controller_ownership import ControllerLease, assert_controller_ownership
from .attempt_initialization import validate_attempt_binding
from .docker_identity import file_sha256
from .durability_controller import _trace, resolve_attempt
from .durable_files import locked_private_dir
from .overlay_seal import (
    OverlayImportRequest,
    OverlaySealBinding,
    import_overlay_source,
    load_overlay,
    render_intents_equal,
)
from .overlay_seal_store import OverlaySealLocator
from .process_runner import ProcessRequest
from .render_admission import (
    AdmittedRenderRef,
    ResolvedAdmittedRender,
    load_admitted_render,
)
from .render_admission_schema import ArtifactOverlay
from .render_build import (
    render_build_manifest_digest,
    render_build_manifests_equal,
)
from .render_build_receipt import RenderBuildLocator, store_render_build
from .render_lane import (
    RENDERER_MODE,
    RenderExecutionPolicy,
    _child_environment,
    _resource_request,
    _run_worker,
    _validated_build,
    _validated_result,
    _worker_path,
)
from .render_lane_cache import CacheBinding, prepare_attempt_cache
from .render_runtime import RendererRuntime, current_render_build_manifest
from .resource_ledger import ResourceRequest, container_lease
from .boot_identity import read_boot_id


class AdmittedRenderLaneError(RuntimeError):
    """An admitted attempt is not eligible for deterministic render work."""


_OVERLAY_BATCH_SIZE = 2


@dataclass(frozen=True)
class AdmittedRenderPreparation:
    """Caller-safe summary with no loose artifact, source, or seal paths."""

    reference: AdmittedRenderRef
    artifact_digest: str
    build_digest: str
    overlay_count: int


@dataclass(frozen=True)
class _PreparedOverlay:
    artifact: ArtifactOverlay
    seal: OverlaySealLocator


@dataclass(frozen=True)
class _PreparedAttempt:
    admitted: ResolvedAdmittedRender
    build: RenderBuildLocator
    overlays: tuple[_PreparedOverlay, ...]


@dataclass(frozen=True)
class _LaunchContext:
    attempt_root: str
    attempt_id: str
    artifact_digest: str
    build: RenderBuildLocator
    binding: CacheBinding

    @property
    def build_digest(self) -> str:
        return self.build.build_digest


@dataclass(frozen=True)
class _WorkerContext:
    launch: _LaunchContext
    prepared: _PreparedOverlay
    seal: object
    binding: CacheBinding
    container_name: str
    resources: ResourceRequest


def _validate_admitted(admitted: ResolvedAdmittedRender,
                       boot_id: str) -> None:
    state = admitted.admission.trace_state
    terminal = admitted.admission.terminal_manifest
    if terminal is not None or state.terminal_disposition is not None:
        raise AdmittedRenderLaneError("terminal attempts cannot render")
    if state.phase != "ADMITTED":
        raise AdmittedRenderLaneError("attempt is not in the ADMITTED phase")
    if state.boot_id != boot_id:
        raise AdmittedRenderLaneError("attempt belongs to another boot")


class AdmittedRenderLane:
    """Controller-owned renderer whose only input is authority plus attempt ID."""

    def __init__(self, runtime: RendererRuntime, policy: RenderExecutionPolicy,
                 lease: ControllerLease):
        if policy.renderer_mode != RENDERER_MODE:
            raise AdmittedRenderLaneError(
                f"rendererMode must be exactly {RENDERER_MODE}")
        self.runtime = runtime
        self.policy = policy
        self.lease = lease

    def _validated_build(self, admitted: ResolvedAdmittedRender
                         ) -> RenderBuildLocator:
        live = current_render_build_manifest(self.runtime)
        artifact = admitted.artifact
        valid = (render_build_manifests_equal(live, artifact.build_manifest)
                 and render_build_manifest_digest(live) == artifact.build_digest)
        if not valid:
            raise AdmittedRenderLaneError("live render build differs from admission")
        build = store_render_build(admitted.attempt_root, artifact.build_manifest)
        if build.build_digest != artifact.build_digest:
            raise AdmittedRenderLaneError("retained render build identity changed")
        return build

    def _import_overlay(self, admitted: ResolvedAdmittedRender,
                        overlay: ArtifactOverlay) -> _PreparedOverlay:
        record, artifact = admitted.admission.record, admitted.artifact
        request = OverlayImportRequest(
            admitted.attempt_root, record["attemptId"],
            artifact.artifact_digest, artifact.build_digest,
            overlay.overlay_id, overlay.source_value,
            overlay.resolved.snapshot.path)
        return _PreparedOverlay(overlay, import_overlay_source(request))

    def _prepare(self, admitted: ResolvedAdmittedRender) -> _PreparedAttempt:
        authority = admitted.reference.authority_root
        assert_controller_ownership(self.lease, authority)
        _validate_admitted(admitted, read_boot_id())
        build = self._validated_build(admitted)
        overlays = tuple(self._import_overlay(admitted, overlay)
                         for overlay in admitted.artifact.overlays)
        assert_controller_ownership(self.lease, authority)
        return _PreparedAttempt(admitted, build, overlays)

    def prepare(self, reference: AdmittedRenderRef) -> AdmittedRenderPreparation:
        """Import exact retained source capsules into the admitted attempt."""
        admitted = load_admitted_render(reference)
        prepared = self._prepare(admitted)
        return AdmittedRenderPreparation(
            prepared.admitted.reference, admitted.artifact.artifact_digest,
            prepared.build.build_digest, len(prepared.overlays))

    def _invoke_worker(self, context: _WorkerContext):
        prepared, launch = context.prepared, context.launch
        artifact = prepared.artifact
        worker = {"attemptId": launch.attempt_id,
                  "attemptRoot": launch.attempt_root,
                  "buildDigest": launch.build.build_digest,
                  "cacheDir": context.binding.cache_dir,
                  "requestDigest": launch.artifact_digest,
                  "selectionId": artifact.overlay_id,
                  "sealPath": prepared.seal.path,
                  "sealSha256": prepared.seal.sha256}
        payload = json.dumps(worker, ensure_ascii=True, separators=(",", ":"),
                             sort_keys=True)
        pycache = os.path.join(
            context.binding.temp_dir, f"pycache-{artifact.overlay_id}")
        command = [self.runtime.python, "-I", "-S", "-B", "-X",
                   f"pycache_prefix={pycache}", _worker_path(self.runtime)]
        request = ProcessRequest(
            tuple(command), payload, launch.attempt_root,
            _child_environment(self.runtime, context.binding,
                               context.container_name),
            self.runtime.timeout_seconds)
        return _run_worker(request)

    def _finish_worker(self, context: _WorkerContext, stdout: str) -> dict:
        result, output = _validated_result(
            stdout, context.binding, context.seal,
            (self.runtime.image_id, context.container_name, context.resources))
        if _validated_build(context.launch, self.runtime) \
                != context.launch.build.build_digest:
            raise AdmittedRenderLaneError("render build changed during worker")
        return {"artifactDigest": context.launch.artifact_digest,
                "cacheBinding": {
                    "device": context.binding.cache_device,
                    "inode": context.binding.cache_inode,
                    "ownerReceiptSha256": context.binding.receipt_sha256},
                "launcherSha256": file_sha256(__file__),
                "outputBinding": output,
                "renderBuildReceipt": context.launch.build.build_digest,
                "rendererMode": RENDERER_MODE, "result": result,
                "selectionId": context.prepared.artifact.overlay_id}

    def _launch_one(self, prepared: _PreparedOverlay,
                    launch: _LaunchContext) -> dict:
        _validated_build(launch, self.runtime)
        seal_binding = OverlaySealBinding(
            launch.attempt_root, launch.attempt_id, launch.artifact_digest,
            launch.build.build_digest, prepared.artifact.overlay_id)
        seal = load_overlay(prepared.seal, seal_binding)
        if not render_intents_equal(
                seal.intent, prepared.artifact.resolved.intent):
            raise AdmittedRenderLaneError("attempt seal differs from artifact")
        resources = _resource_request(launch, self.runtime)
        with container_lease(resources) as container_name:
            context = _WorkerContext(
                launch, prepared, seal, launch.binding, container_name, resources)
            proc = self._invoke_worker(context)
            return self._finish_worker(context, proc.stdout)

    def _render_batch(self, overlays: tuple[_PreparedOverlay, ...],
                      launch: _LaunchContext) -> tuple[dict, ...]:
        if len(overlays) == 1:
            return (self._launch_one(overlays[0], launch),)
        with ThreadPoolExecutor(
                max_workers=len(overlays),
                thread_name_prefix="sniper-overlay") as executor:
            futures = [executor.submit(self._launch_one, item, launch)
                       for item in overlays]
            return tuple(future.result() for future in futures)

    @staticmethod
    def _next_batch(overlays: tuple[_PreparedOverlay, ...]
                    ) -> tuple[_PreparedOverlay, ...]:
        batch, keys = [], set()
        for item in overlays:
            key = item.artifact.resolved.key
            if key in keys or len(batch) == _OVERLAY_BATCH_SIZE:
                break
            batch.append(item)
            keys.add(key)
        return tuple(batch)

    def _render_overlays(self, overlays: tuple[_PreparedOverlay, ...],
                         launch: _LaunchContext) -> tuple[dict, ...]:
        results, pending = [], overlays
        while pending:
            batch = self._next_batch(pending)
            results.extend(self._render_batch(batch, launch))
            pending = pending[len(batch):]
        return tuple(results)

    def _launch_locked(self, reference: AdmittedRenderRef,
                       attempt_fd: int) -> tuple[dict, ...]:
        admitted = load_admitted_render(reference)
        prepared = self._prepare(admitted)
        identity = (admitted.admission.record["attemptId"],
                    admitted.artifact.artifact_digest,
                    prepared.build.build_digest, self.runtime.image_id)
        binding = prepare_attempt_cache(admitted.attempt_root, identity)
        launch = _LaunchContext(
            admitted.attempt_root, admitted.admission.record["attemptId"],
            admitted.artifact.artifact_digest, prepared.build, binding)
        _validated_build(launch, self.runtime)
        boot_id = read_boot_id()
        trace = _trace(reference.authority_root,
                       admitted.admission.record, boot_id)
        trace.append("WORKER_START", {
            "operation": "render-overlays",
            "overlayCount": len(prepared.overlays)})
        results = self._render_overlays(prepared.overlays, launch)
        validate_attempt_binding(
            reference.authority_root, admitted.admission.record, attempt_fd)
        assert_controller_ownership(self.lease, reference.authority_root)
        self._validated_build(admitted)
        return results

    def launch(self, reference: AdmittedRenderRef) -> tuple[dict, ...]:
        """Render every admitted overlay in request order under one launch lock."""
        assert_controller_ownership(self.lease, reference.authority_root)
        admission = resolve_attempt(
            reference.authority_root, reference.attempt_id)
        attempt_root = os.path.join(
            reference.authority_root, "attempts",
            admission.record["attemptId"])
        with locked_private_dir(attempt_root,
                                ".admitted-render.lock") as attempt_fd:
            validate_attempt_binding(
                reference.authority_root, admission.record, attempt_fd)
            results = self._launch_locked(reference, attempt_fd)
            validate_attempt_binding(
                reference.authority_root, admission.record, attempt_fd)
        return results
