"""Lifecycle runner for the pinned qualification-mezzanine container."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from headless.container_policy import (
    DockerRuntime,
    attest_image,
    command,
    docker_env,
    reconcile_launch_abort,
    remove_container,
    required_runtime,
)
from headless.qualification_mezzanine_policy import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_RESULT_BYTES,
    QualificationAttestation,
    QualificationLaunch,
    attest_qualification_container,
    container_command,
)

_LAUNCH_TIMEOUT_SECONDS = 10 * 60
_LAUNCH_RECONCILE_SECONDS = 10 * 60


def _control_plane_timeout(request: QualificationLaunch) -> int:
    """Keep startup inside both the qualification and control-plane bounds."""
    return min(request.timeout_seconds, _LAUNCH_TIMEOUT_SECONDS)


def _launch_timeout_error(
    runtime: DockerRuntime,
    config_dir: str,
    request: QualificationLaunch,
    started_at: float,
) -> RuntimeError:
    """Reconcile a timed-out create and return its exact retry verdict."""
    timeout_seconds = _control_plane_timeout(request)
    reconcile_seconds = min(timeout_seconds, _LAUNCH_RECONCILE_SECONDS)
    try:
        reconcile_launch_abort(
            runtime, config_dir, request.name, reconcile_seconds)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        elapsed = time.monotonic() - started_at
        return RuntimeError(
            "qualification launch timed out; "
            f"launchTimeoutSeconds={timeout_seconds}; "
            f"reconcileTimeoutSeconds={reconcile_seconds}; "
            f"elapsedSeconds={elapsed:.3f}; canonicalAbsenceProved=false; "
            "retryAllowed=false; "
            f"reconciliationError={exc}")
    elapsed = time.monotonic() - started_at
    return RuntimeError(
        "qualification launch timed out; "
        f"launchTimeoutSeconds={timeout_seconds}; "
        f"reconcileTimeoutSeconds={reconcile_seconds}; "
        f"elapsedSeconds={elapsed:.3f}; canonicalAbsenceProved=true; "
        "retryAllowed=true")


def _launch(
    runtime: DockerRuntime,
    config_dir: str,
    argv: list[str],
    request: QualificationLaunch,
) -> None:
    started_at = time.monotonic()
    timeout_seconds = _control_plane_timeout(request)
    try:
        result = subprocess.run(
            argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            env=docker_env(config_dir), timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired as exc:
        raise _launch_timeout_error(
            runtime, config_dir, request, started_at) from exc
    container_id = result.stdout.strip()
    valid_id = len(container_id) == 64 and all(
        char in "0123456789abcdef" for char in container_id)
    if result.returncode != 0 or not valid_id:
        reconcile_launch_abort(runtime, config_dir, request.name)
        detail = (result.stderr or result.stdout).strip()[-300:]
        raise RuntimeError(f"qualification container launch failed: {detail}")


def _container_state(
    runtime: DockerRuntime,
    config_dir: str,
    name: str,
) -> str | None:
    try:
        result = subprocess.run(
            command(runtime, "container", "inspect", name, "--format",
                    "{{.State.Status}}"), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, env=docker_env(config_dir),
            timeout=15, check=False)
    except subprocess.TimeoutExpired:
        return None
    return result.stdout.strip() if result.returncode == 0 else "absent"


def _read_result(path: Path) -> dict:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 0 < before.st_size <= MAX_RESULT_BYTES):
            raise RuntimeError("qualification result is not one bounded file")
        payload = os.read(descriptor, before.st_size + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    current = os.lstat(path)
    if (len(payload) != before.st_size
            or any(getattr(before, key) != getattr(after, key) for key in fields)
            or any(getattr(current, key) != getattr(after, key) for key in fields)):
        raise RuntimeError("qualification result changed while reading")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("qualification result is invalid JSON") from exc
    if type(value) is not dict or value.get("schemaVersion") != 1:
        raise RuntimeError("qualification result is malformed")
    if value.get("ok") is not True:
        details = value.get("details")
        suffix = ""
        if isinstance(details, dict):
            suffix = "; details=" + json.dumps(
                details, sort_keys=True, separators=(",", ":"))[:1200]
        raise RuntimeError(
            "qualification worker rejected source: "
            f"{value.get('message', 'unknown')}{suffix}")
    return value


def _wait_result(
    runtime: DockerRuntime,
    config_dir: str,
    request: QualificationLaunch,
) -> dict:
    deadline = time.monotonic() + request.timeout_seconds + 60
    delay, result_path = 0.1, Path(request.output_dir) / "result.json"
    while time.monotonic() < deadline:
        if result_path.exists():
            return _read_result(result_path)
        state = _container_state(runtime, config_dir, request.name)
        if state is not None and state != "running":
            raise RuntimeError("qualification container exited without a result")
        time.sleep(delay)
        delay = min(delay * 1.5, 2.0)
    raise RuntimeError("qualification transcode exceeded its bounded timeout")


def run_isolated_transcode(
    source: str,
    output_dir: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    target_fps: int = 24,
) -> dict:
    """Transcode only inside the attested approved-image container."""
    runtime = required_runtime()
    request = QualificationLaunch(
        source, output_dir, f"sniper-qualification-{uuid.uuid4().hex}",
        timeout_seconds, target_fps)
    with tempfile.TemporaryDirectory(
            prefix=".sniper-qualification-docker-") as config_dir:
        os.chmod(config_dir, 0o700)
        image = attest_image(runtime, config_dir)
        argv = container_command(runtime, request)
        launched, isolation, worker = False, None, None
        try:
            _launch(runtime, config_dir, argv, request)
            launched = True
            isolation = attest_qualification_container(
                runtime, QualificationAttestation(config_dir, request, argv))
            worker = _wait_result(runtime, config_dir, request)
        finally:
            removal = remove_container(runtime, config_dir, request.name) \
                if launched else {"canonicalAbsenceProved": True,
                                  "method": "launch-never-succeeded"}
        return {
            "image": {"imageId": image["Id"],
                      "architecture": image["Architecture"], "os": image["Os"]},
            "isolation": isolation, "removal": removal, "worker": worker,
        }
