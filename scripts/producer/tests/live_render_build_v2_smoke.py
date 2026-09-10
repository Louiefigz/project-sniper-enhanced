"""One opt-in actual V2 sealed section marker, not matrix or quality approval.

Uses the normal prepare_overlay_launch -> launch_overlay boundary, retained
exact source/build/request, and existing approved local OCI image. No fallback,
network, downloads, canonical project writes or historical receipt updates.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import file_hash, write_new
from headless.render_build import render_build_manifests_equal
from headless.render_lane import (
    OverlayPreparationRequest, RenderExecutionPolicy, launch_overlay, prepare_overlay_launch,
)
from headless.render_runtime import RendererRuntime, current_render_build_manifest
from headless.request_artifact import store_request_artifact


def runtime() -> RendererRuntime:
    """Use explicit existing approved settings, not a caller-selected image."""
    root = str(Path(__file__).resolve().parents[3])
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("Existing host proof decoders are required")
    return RendererRuntime(root, root, os.path.realpath(sys.executable),
        os.path.realpath(os.environ["SNIPER_DOCKER_PATH"]),
        os.path.realpath(os.environ["SNIPER_DOCKER_SOCKET"]),
        os.environ["SNIPER_RENDER_IMAGE_ID"], os.environ["SNIPER_RENDER_UID_GID"],
        os.path.realpath(ffmpeg), os.path.realpath(ffprobe), timeout_seconds=90)


def run(directory: Path, result: dict) -> None:
    """Keep one explicit 2.5-second request and current V2 build unchanged."""
    current = runtime()
    before = current_render_build_manifest(current)
    write_new(directory / "build-before.json", before)
    authority = directory / "authority"
    authority.mkdir(mode=0o700)
    (authority / "attempts").mkdir(mode=0o700)
    attempt = authority / "attempts" / "section-marker-v2"
    attempt.mkdir(mode=0o700)
    entry = {"kind": "section-marker", "outStart": 0, "outEnd": 2.5, "anchor": "free-band",
        "spec": {"num": "System No.1", "line1": "Current V2", "line2": "Boundary",
                 "side": "left", "accent": "#054BC9"}}
    artifact = store_request_artifact(str(authority), {"schemaVersion": 1, "operation": "render-overlays",
        "overlays": [{"overlayId": "section-1", "entry": entry}]})
    start = time.monotonic()
    prepared = prepare_overlay_launch(OverlayPreparationRequest(str(authority), str(attempt),
        attempt.name, artifact, "section-1"), current)
    result["prepareMs"] = round((time.monotonic() - start) * 1000)
    start = time.monotonic()
    result["launch"] = launch_overlay(RenderExecutionPolicy("sealed-oci-v2"), prepared, current)
    result["launchMs"] = round((time.monotonic() - start) * 1000)
    after = current_render_build_manifest(current)
    write_new(directory / "build-after.json", after)
    if not render_build_manifests_equal(before, after):
        raise RuntimeError("Actual V2 build changed during the smoke")
    result["buildUnchanged"] = True
    result["passed"] = True


def main() -> None:
    """Retain every failed attempt and report its actual wall time."""
    start = time.monotonic()
    directory = Path(tempfile.mkdtemp(prefix="sniper-render-build-v2-live-", dir="/private/tmp"))
    runner_sha = file_hash(Path(__file__).resolve())
    result = {"kind": "actual-current-v2-single-overlay-smoke", "passed": False,
        "runnerAtStartSha256": runner_sha, "artifactDir": str(directory),
        "deliveryApproved": False, "matrixQualified": False, "hostPortable": False}
    print(json.dumps({"phase": "start", "artifactDir": str(directory)}), flush=True)
    try:
        run(directory, result)
        if runner_sha != file_hash(Path(__file__).resolve()):
            raise RuntimeError("Smoke runner changed during execution")
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        result["passed"] = False
        result["error"] = str(error)
        result["errorChain"] = error_chain(error)
    retain_final_build(directory, result)
    result["elapsedMs"] = round((time.monotonic() - start) * 1000)
    write_new(directory / "result.json", result)
    print(json.dumps(result), flush=True)
    raise SystemExit(0 if result["passed"] else 1)


def error_chain(error: BaseException) -> list[str]:
    """Keep the initiating validation failure as well as any cleanup failure."""
    errors, seen = [], set()
    while error is not None and id(error) not in seen and len(errors) < 5:
        seen.add(id(error))
        errors.append(f"{type(error).__name__}: {error}"[:2000])
        error = error.__cause__ or error.__context__
    return errors


def retain_final_build(directory: Path, result: dict) -> None:
    """Capture source drift even after a failed launch; never upgrade failure."""
    if (directory / "build-after.json").exists() or not (directory / "build-before.json").exists():
        return
    try:
        after = current_render_build_manifest(runtime())
        write_new(directory / "build-after.json", after)
        before = json.loads((directory / "build-before.json").read_text())
        result["buildUnchanged"] = render_build_manifests_equal(before, after)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        result["buildAfterCaptureError"] = str(error)


if __name__ == "__main__":
    main()
