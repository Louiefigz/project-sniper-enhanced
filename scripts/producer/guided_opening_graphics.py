"""Private ordinary-at-rate OCI integration with existing owned resource leases.

This is explicitly NOT the current fixed30 presealed V2 launch qualification.
No host fallback, caller-selected container name or unheld shared-cache reuse.
The server must reconcile these exact ledgers after any hard process-group kill
before success or retry; Docker containers are outside that POSIX process group.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from cut_preview_io import digest, file_hash, write_new
from graphics import graphics_render
from guided_opening_graphic_proof import graphic_intent, intent_record, verify_graphic_result
from guided_opening_claim import registration_intent, resource_request
from guided_opening_inputs import OpeningInputs
from headless.render_runtime import RendererRuntime, current_render_build_manifest
from headless.resource_ledger import ResourceRequest, container_lease, registered_containers, removed_containers


def graphics_runtime(inputs: OpeningInputs, pipeline: dict, claim: object) -> RendererRuntime:
    """Require explicit existing approved local OCI controls and captured templates."""
    snapshot = inputs.value["pipeline"]["snapshotRoot"]
    if graphics_render.PIPELINE_ROOT != snapshot:
        raise RuntimeError("opening graphics must execute the exact pinned snapshot templates")
    tools = pipeline["tools"]
    required = ("SNIPER_RUNTIME_REPO_ROOT", "SNIPER_DOCKER_PATH", "SNIPER_DOCKER_SOCKET",
                "SNIPER_RENDER_IMAGE_ID", "SNIPER_RENDER_UID_GID")
    if any(not os.environ.get(key) for key in required):
        raise RuntimeError("opening graphics require explicit approved sealed-only runtime controls")
    expected = claim.value["runtime"]
    keys = ("runtimeRepoRoot", "dockerPath", "dockerSocketPath", "imageId", "userId")
    if any(os.environ[name] != expected[key] for name, key in zip(required, keys)):
        raise RuntimeError("opening renderer environment differs from exact claimed Docker controls")
    return RendererRuntime(snapshot, os.environ[required[0]], os.path.realpath(sys.executable),
        os.environ[required[1]], os.environ[required[2]], os.environ[required[3]], os.environ[required[4]],
        tools["ffmpeg"]["path"], tools["ffprobe"]["path"], timeout_seconds=90)


@contextmanager
def _tools_environment(runtime: RendererRuntime) -> Iterator[None]:
    """Pinned proof tools for the WHOLE owned graphics phase.

    The intent seal hashes the container cache identity (container_renderer
    .cache_identity reads SNIPER_PROOF_FFMPEG_PATH/FFPROBE_PATH) before any
    container name exists (run #12, 2026-09-06), so the tool paths must be in
    scope from the first attempt on, not only inside the render/proof block.
    """
    values = {"SNIPER_PROOF_FFMPEG_PATH": runtime.proof_ffmpeg,
              "SNIPER_PROOF_FFPROBE_PATH": runtime.proof_ffprobe}
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        _restore_environment(previous)


@contextmanager
def _proof_environment(name: str, runtime: RendererRuntime) -> Iterator[None]:
    """Scope only trusted per-invocation name/tool values; preserve prior ambient state."""
    values = {"SNIPER_RENDER_CONTAINER_NAME": name, "SNIPER_PROOF_FFMPEG_PATH": runtime.proof_ffmpeg,
              "SNIPER_PROOF_FFPROBE_PATH": runtime.proof_ffprobe}
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        _restore_environment(previous)


def _restore_environment(previous: dict[str, str | None]) -> None:
    """Restore only values this owned invocation temporarily changed."""
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _one(row: dict, context: tuple) -> tuple[dict, dict]:
    """Register an exact owned name before spawn; mandatory cleanup is untimed work."""
    root, inputs, pipeline, runtime, clock, claim, observe = context
    attempt = root / "attempts" / f"graphic-{row['order']}"
    attempt.mkdir(mode=0o700)
    cache = attempt / "cache"
    cache.mkdir(mode=0o700)
    intent = clock.phase("graphic-intent-seal", lambda: graphic_intent(row, attempt, inputs.documents["authority"]["frameRate"]))
    target = inputs.documents["authority"]["target"]
    if intent.dimensions != (target["width"], target["height"]):
        raise RuntimeError("opening own-screen asset does not match declared actual full canvas")
    resources = resource_request(claim, row["order"])
    build = clock.phase("graphic-build-before", lambda: current_render_build_manifest(runtime))
    write_new(attempt / "registration-intent.json", registration_intent(claim, row["order"]))
    with container_lease(resources) as name:
        request = {"schemaVersion": 1, "kind": "private-opening-ordinary-at-rate-oci",
            "scope": "not-fixed30-presealed-v2-not-approval", "executionInputHash": inputs.value["executionInputHash"],
            "containerName": name, "imageId": runtime.image_id, "build": build, "intent": intent_record(intent)}
        if observe:
            from guided_caption_graphic_observation import observed_execution_request
            request = observed_execution_request(request, intent)
        request_path = attempt / "execution-request.json"
        write_new(request_path, request)
        held_sha = file_hash(request_path)
        with _proof_environment(name, runtime):
            result, observed = _render_asset(intent, cache, (clock, runtime, name, "actual-ordinary-at-rate-oci"), observe)
            proof = clock.phase("actual-graphic-proof", lambda: verify_graphic_result(result, intent, (runtime.image_id, name, pipeline["tools"])))
        if digest(clock.phase("graphic-build-after", lambda: current_render_build_manifest(runtime))) != digest(build) \
                or file_hash(request_path) != held_sha:
            raise RuntimeError("opening graphic build/request changed during execution")
    if registered_containers(resources) or removed_containers(resources) != (name,):
        raise RuntimeError("opening graphic exact container cleanup is unproved")
    clip = {"path": result["path"], "graphicId": row["graphicId"], "outStart": row["entry"]["outStart"],
        "outEnd": row["entry"]["outEnd"], "anchor": "own-screen", "x": 0, "y": 0,
        "startFrame": row["startFrame"], "endFrameExclusive": row["endFrameExclusive"]}
    evidence = {"graphicId": row["graphicId"], "candidateOrder": row["order"], "requestPath": str(request_path),
        "requestSha256": held_sha, "resourceLedgerPath": str(attempt / "resource-ledger.json"),
        "removedContainerNames": [name], "workerCleanupObserved": True, **proof}
    if observed is not None:
        evidence["captionLayoutObservation"] = observed
    return clip, evidence


def render_opening_graphics(inputs: OpeningInputs, rows: list[dict], context: tuple, screening: object = None) -> dict:
    """Render intersecting originals only, never clip an animation's logical duration."""
    root, pipeline, clock, claim = context
    from guided_caption_screen import admit_screen
    observed_orders = clock.phase("caption-layout-admission", lambda: admit_screen(screening, clock.remaining)) \
        if screening is not None else set()
    if not rows:
        return {"clips": [], "evidence": []}
    runtime = graphics_runtime(inputs, pipeline, claim)
    directory = root / "graphics"
    directory.mkdir(mode=0o700)
    (directory / "attempts").mkdir(mode=0o700)
    clips, evidence = [], []
    with _tools_environment(runtime):
        for row in rows:
            clip, proof = _one(row, (directory, inputs, pipeline, runtime, clock, claim, row["order"] in observed_orders))
            clips.append(clip)
            evidence.append(proof)
    return {"clips": clips, "evidence": evidence}


def _render_asset(intent: object, cache: Path, context: tuple, observe: bool) -> tuple[dict, dict | None]:
    """Legacy uses its old phase; observed path owns its own cleanup-safe timer."""
    clock, runtime, name, stage = context
    if observe:
        from guided_caption_graphic_observation import render_observed_graphic
        return render_observed_graphic(intent, cache / (intent.key + ".mp4"), (clock, runtime, name))
    result = clock.phase(stage, lambda: graphics_render.render_entry_at_rate(
        intent.row["entry"], str(cache), intent.rate.token), limit=runtime.timeout_seconds)
    return result, None
