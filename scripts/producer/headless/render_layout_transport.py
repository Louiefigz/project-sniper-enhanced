"""Opt-in owned-container transport for actual layout frames; legacy is inert."""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import nullcontext
from pathlib import Path

from color.deadline import require_time, wall_budget
from headless.container_io import promote_regular
from headless.container_policy import command, docker_env
from headless.docker_identity import file_sha256
from headless.process_runner import ProcessRequest, run_text
from headless.render_layout_contract import (
    CLI_SHA256, MAX_RESULT_BYTES, OBSERVER_FILES, bounded_bytes,
    encoded_request, role_inventory, sealed_documents,
)
from headless.render_layout_result import validate_observation


def environment(request: object) -> dict[str, str]:
    """No environment or behavior change for ordinary render requests."""
    return {} if request.layout is None else {"SNIPER_LAYOUT_REQUEST": encoded_request(request.layout)}


def work_budget(request: object):
    """Keep one caller-held monotonic cap; mandatory cleanup is outside it."""
    return nullcontext() if request.layout is None else wall_budget(request.layout_deadline)


def guard(request: object) -> None:
    """No result/promotion credit after the original observation work cap."""
    if request.layout is not None:
        require_time(request.layout_deadline)


def approved_sources(runtime: object) -> list[dict]:
    """Fail cheaply until the new local image really contains these exact bytes."""
    root = Path(__file__).resolve().parents[3] / "templates/motion/container"
    pins = runtime.approval.get("probedClosure", {}).get("sha256", {})
    rows = []
    for name in (*OBSERVER_FILES, "render-entrypoint.sh"):
        raw = bounded_bytes(str(root / name), 65536)
        image_path = f"/opt/sniper-motion/container/{name}"
        observed = hashlib.sha256(raw).hexdigest()
        if pins.get(image_path) != observed:
            raise ValueError("layout observer needs a freshly built and approved local image; no fallback")
        rows.append({"path": image_path, "sha256": observed, "sizeBytes": len(raw)})
    if pins.get("/opt/sniper-motion/node_modules/hyperframes/dist/cli.js") != CLI_SHA256:
        raise ValueError("layout observer image CLI pin differs")
    return rows[:-1]


def preflight(runtime: object, request: object) -> None:
    """Check class, actual captured intent and installed observer before Docker."""
    if request.layout is None:
        if request.layout_deadline is not None:
            raise ValueError("layout deadline without explicit observation request")
        return
    guard(request)
    if request.fmt != "mp4" or request.composition != request.layout.get("composition"):
        raise ValueError("layout observation requires the exact own-screen MP4 composition")
    from graphics.render_rate import normalize_render_rate
    rate = normalize_render_rate(request.fps)
    if request.layout["frameRate"] != f"{rate.numerator}/{rate.denominator}":
        raise ValueError("layout render FPS differs from observation clock")
    approved_sources(runtime)
    sealed_documents(request.snapshot, request.layout)
    guard(request)


def copy_observation(paths: object, request: object, container_id: str) -> dict | None:
    """Retain exact bounded actual container bytes before its cleanup."""
    if request.layout is None:
        return None
    guard(request)
    proc = run_text(ProcessRequest(
        tuple(command(paths.runtime, "container", "exec", container_id,
                      "/usr/bin/cat", "/output/layout-observation.json")),
        "", paths.docker_config, docker_env(paths.docker_config),
        min(30, require_time(request.layout_deadline)), max_output_bytes=MAX_RESULT_BYTES))
    if proc.returncode != 0 or proc.stderr:
        raise ValueError("owned layout observation stream failed")
    raw = proc.stdout.encode("utf-8")
    expected = {"observerSources": approved_sources(paths.runtime), "media": {
        "sha256": file_sha256(paths.copied_output), "sizeBytes": os.path.getsize(paths.copied_output)}}
    expected["roleInventory"] = role_inventory(sealed_documents(request.snapshot, request.layout), request.layout["profile"])
    value = validate_observation(json.loads(raw), request.layout, expected)
    guard(request)
    descriptor = os.open(paths.copied_output + ".layout.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return {"sha256": hashlib.sha256(raw).hexdigest(), "sizeBytes": len(raw),
            "profile": request.layout["profile"], "status": value["status"]}


def promote(request: object, copied: str) -> None:
    """Promote only this known sidecar; no current-cache discovery or overwrite."""
    if request.layout is not None:
        guard(request)
        promote_regular(copied + ".layout.json", request.output + ".layout.json")
        guard(request)
