"""Bounded read-only color sampling inside the native admission jail.

The diagnostic used to launch ``color_diagnostic_worker.js`` in the approved
container. It now runs the same analysis (headless/color_diagnostic_native.py)
with every decoder confined by the native jail: no network, no writes, no
process creation, a kernel memory limit and process-group reaping. There is no
unconfined host fallback: without the jail the diagnostic fails.
"""
from __future__ import annotations

import time

from color.deadline import require_time, wall_budget
from headless.color_diagnostic_native import analyze
from headless.native_media_runtime import NativeRuntimeError
from headless.native_media_sandbox import JailRejection, verified_runtime
from headless.process_runner import ProcessReapError


class ColorIsolationError(RuntimeError):
    """Report observed cleanup without implying successful analysis or approval."""

    def __init__(self, message: str, cleanup_verified: bool, elapsed_ms: int) -> None:
        """Retain uncertainty when a confined process could not be proved gone."""
        super().__init__(message)
        self.cleanup_verified = cleanup_verified
        self.elapsed_ms = elapsed_ms


def _isolation(runtime) -> dict:
    """The confinement every sample and probe ran under."""
    return {"kind": "macos-seatbelt", "policy": runtime.identity["policy"],
            "profileSha256": runtime.identity["profileSha256"], "network": "denied",
            "processCreation": "denied", "writes": "/dev/null only", "memoryMiB": 768}


def _isolated(source: str, request: dict, started: float) -> dict:
    """Run one admitted source through the jailed analysis within the request deadline."""
    timings, deadline = {}, started + request["timeoutSeconds"]
    with wall_budget(deadline):
        runtime = verified_runtime()
    timings["runtimeVerificationMs"] = round((time.monotonic() - started) * 1000)
    phase = time.monotonic()
    worker = analyze(source, request)
    timings["jailedWorkerMs"] = round((time.monotonic() - phase) * 1000)
    require_time(deadline)
    return {"runtime": runtime.identity, "isolation": _isolation(runtime),
            "removal": {"canonicalAbsenceProved": True, "method": "native-jail-process-group-reaped"},
            "worker": worker, "phaseTimingsMs": timings,
            "elapsedMs": round((time.monotonic() - started) * 1000)}


def run_isolated(source: str, request: dict) -> dict:
    """No host fallback; failures carry only positively observed cleanup facts."""
    started = time.monotonic()
    try:
        return _isolated(source, request, started)
    except ProcessReapError as exc:
        raise ColorIsolationError(str(exc), False, round((time.monotonic() - started) * 1000)) from exc
    except (OSError, RuntimeError, ValueError, NativeRuntimeError, JailRejection) as exc:
        raise ColorIsolationError(str(exc), True, round((time.monotonic() - started) * 1000)) from exc
