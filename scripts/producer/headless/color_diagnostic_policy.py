"""Reuse approved decoder isolation for bounded read-only color sampling."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from cut_preview_io import read_bytes
from color.deadline import wall_budget, require_time
from headless.container_policy import DockerRuntime, attest_image, remove_container, required_runtime
from headless.external_media_probe import _launch
from headless.external_media_probe_policy import (
    MediaProbeLimits,
    NODE_PROBE,
    attest_probe_container,
    container_command as probe_command,
)
from headless.network_probe import probe_container

WORKER = Path(__file__).with_name("color_diagnostic_worker.js")


class ColorIsolationError(RuntimeError):
    """Report observed cleanup without implying successful analysis or approval."""

    def __init__(self, message: str, cleanup_verified: bool, elapsed_ms: int) -> None:
        """Retain uncertainty when launch/removal cannot be positively reconciled."""
        super().__init__(message)
        self.cleanup_verified = cleanup_verified
        self.elapsed_ms = elapsed_ms


def container_command(runtime: DockerRuntime, config_dir: str, source: str, request: dict) -> tuple[str, list[str]]:
    """Retain all mount/resource controls; replace only the inert worker payload."""
    name = f"sniper-color-diagnostic-{uuid.uuid4().hex}"
    command = probe_command(runtime, config_dir, name, source, MediaProbeLimits())
    if command.count(NODE_PROBE) != 1:
        raise RuntimeError("color diagnostic probe-launch compatibility changed")
    index = command.index(NODE_PROBE)
    worker = read_bytes(WORKER, 128 * 1024).decode("utf8")
    return name, command[:index] + [worker, json.dumps(request, allow_nan=False)]


def _wait(config_dir: str, deadline: float) -> dict:
    """Bound the attempt; retain structured worker failures rather than hiding them."""
    while time.monotonic() < deadline:
        try:
            raw = read_bytes(Path(config_dir) / "result" / "result.json", 64 * 1024).decode("utf8")
        except FileNotFoundError:
            raw = None
        if raw is not None:
            value = json.loads(raw)
            if type(value) is not dict or value.get("status") not in {"complete", "partial", "failed"}:
                raise RuntimeError("color worker result is malformed")
            return value
        time.sleep(0.1)
    raise RuntimeError("color worker exceeded the private diagnostic deadline")


def _isolated(source: str, request: dict, state: dict, started: float) -> dict:
    """Run one known image, tracking cleanup independently from worker success."""
    timings, deadline = {}, started + request["timeoutSeconds"]
    runtime = required_runtime()
    with tempfile.TemporaryDirectory(prefix=".sniper-color-probe-") as config_dir:
        config_dir = str(Path(config_dir).resolve(strict=True))
        os.chmod(config_dir, 0o700)
        os.mkdir(Path(config_dir) / "result", 0o700)
        with wall_budget(deadline):
            image = attest_image(runtime, config_dir)
        timings["imageAttestationMs"] = round((time.monotonic() - started) * 1000)
        name, launch = container_command(runtime, config_dir, source, request)
        container_ref = name
        try:
            with wall_budget(deadline):
                phase = time.monotonic()
                state["attempted"] = True
                container_ref = _launch(runtime, config_dir, launch, name)
                timings["containerLaunchMs"] = round((time.monotonic() - phase) * 1000)
                phase = time.monotonic()
                isolation = attest_probe_container(runtime, config_dir, name, source, launch)
                network = probe_container(runtime, config_dir, name)
                timings["isolationAndNetworkMs"] = round((time.monotonic() - phase) * 1000)
                phase = time.monotonic()
                worker = _wait(config_dir, deadline)
                timings["remainingWorkerWaitMs"] = round((time.monotonic() - phase) * 1000)
        finally:
            phase = time.monotonic()
            removal = remove_container(runtime, config_dir, container_ref)
            timings["containerTerminationMs"] = round((time.monotonic() - phase) * 1000)
            state["verified"] = removal.get("canonicalAbsenceProved") is True
            if removal.get("canonicalAbsenceProved") is not True:
                raise RuntimeError("color diagnostic container termination was not proved")
        require_time(deadline)
    return {"imageId": image["Id"], "isolation": isolation, "network": network,
            "removal": removal, "worker": worker, "phaseTimingsMs": timings,
            "elapsedMs": round((time.monotonic() - started) * 1000)}


def run_isolated(source: str, request: dict) -> dict:
    """No host fallback; failures carry only positively observed cleanup facts."""
    started, state = time.monotonic(), {"attempted": False, "verified": False}
    try:
        return _isolated(source, request, state, started)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        verified = state["verified"] or not state["attempted"]
        raise ColorIsolationError(str(exc), verified,
                                  round((time.monotonic() - started) * 1000)) from exc
