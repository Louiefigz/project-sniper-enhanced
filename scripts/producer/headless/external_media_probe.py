"""Networkless, nonroot, bounded full-decode admission for external media."""
from __future__ import annotations

import json
import math
import os
import re
import stat
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict
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
from headless.external_media_probe_policy import (
    MediaProbeLimits,
    PROBE_MEMORY_MIB,
    attest_probe_container,
    container_command,
    validate_probe_document,
)
from headless.external_media_snapshot import (
    ExternalMediaSnapshot,
    capture_external_media_snapshot,
    verify_external_media_snapshot,
)
from headless.network_probe import probe_container

CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
POLICY_VERSION = "sniper-external-media-probe-v3"  # v3: 4-CPU / 4-thread validation decode (2026-09-07)
MAX_RESULT_BYTES = 64 * 1024
_STATE_INTERVAL_SECONDS = 2.0


def _launch(runtime, config_dir: str, launch: list[str], name: str) -> str:
    try:
        result = subprocess.run(
            launch, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            env=docker_env(config_dir), timeout=60, check=False)
    except subprocess.TimeoutExpired as exc:
        reconcile_launch_abort(runtime, config_dir, name)
        raise RuntimeError("external-media container launch timed out") from exc
    container_id = result.stdout.strip()
    if result.returncode != 0 or not CONTAINER_ID.fullmatch(container_id):
        detail = (result.stderr or result.stdout).strip()[-300:]
        raise RuntimeError(f"external-media container launch failed: {detail}")
    return container_id


def _state(runtime: DockerRuntime, config_dir: str, name: str,
           timeout_seconds: float = 15.0) -> dict | None:
    """Observe only the held container within the remaining host allowance."""
    if type(timeout_seconds) not in (int, float) \
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 15:
        raise RuntimeError("external-media state timeout is invalid")
    result = subprocess.run(
        command(runtime, "container", "inspect", name, "--format",
                "{{json .State}}"), stdin=subprocess.DEVNULL,
        capture_output=True, text=True, env=docker_env(config_dir),
        timeout=timeout_seconds, check=False)
    if result.returncode != 0:
        return None
    try:
        state = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return state if type(state) is dict else None


def _terminal_failure(state: dict | None) -> str:
    """Classify a probe that died before publishing its result document."""
    if state is None:
        return "external-media probe state unavailable before result"
    code = state.get("ExitCode")
    if state.get("OOMKilled") is True:
        return (
            "external-media probe exceeded its "
            f"{PROBE_MEMORY_MIB} MiB memory limit (OOMKilled)")
    if type(code) is int:
        suffix = " (SIGKILL or bounded-memory OOM)" if code == 137 else ""
        return f"external-media probe exited without a result: exit {code}{suffix}"
    return "external-media probe exited without a result"


def _read_result(runtime, config_dir: str, name: str) -> str | None:
    """Read one bounded result; reject special files before any blocking read."""
    del runtime, name
    path = Path(config_dir) / "result" / "result.json"
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(descriptor)
        valid = (
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and before.st_uid == os.getuid()
            and 0 < before.st_size <= MAX_RESULT_BYTES
        )
        if not valid:
            raise RuntimeError("external-media result is not one bounded file")
        payload = os.read(descriptor, before.st_size + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    current = os.lstat(path)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    stable = len(payload) == before.st_size and all(
        getattr(before, key) == getattr(after, key)
        == getattr(current, key) for key in fields)
    if not stable:
        raise RuntimeError("external-media result changed while reading")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("external-media result is not UTF-8") from exc


def _decode_result(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("external-media probe result is invalid JSON") \
            from exc
    if type(value) is dict and value.get("ok") is False:
        code = str(value.get("code", "DECODE_REJECTED"))
        raise RuntimeError(f"external-media decode rejected: {code}")
    return value


def _remaining(deadline: float) -> float:
    """Never give a daemon observation or late result a renewed wait clock."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError("external-media host wait deadline exceeded")
    return remaining


def _is_terminal(state: dict | None) -> bool:
    """An inspect error or a running container's ExitCode is not proved death."""
    if state is None or type(state.get("Running")) is not bool:
        raise RuntimeError("external-media probe state unavailable or malformed before result")
    status = state.get("Status")
    if type(status) is not str or status not in {
            "created", "running", "paused", "restarting", "removing", "exited", "dead"}:
        raise RuntimeError("external-media probe state unavailable or malformed before result")
    if status in {"exited", "dead"}:
        if state["Running"] or type(state.get("OOMKilled")) is not bool \
                or type(state.get("ExitCode")) is not int:
            raise RuntimeError("external-media probe terminal state is malformed")
        return True
    if status == "running" and not state["Running"]:
        raise RuntimeError("external-media probe running state is inconsistent")
    return False


def _pending_result(runtime: DockerRuntime, config_dir: str, name: str, deadline: float) -> str | None:
    """Recheck publication after definite termination before failing promptly."""
    try:
        state = _state(runtime, config_dir, name, min(15.0, _remaining(deadline)))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("external-media probe state observation failed before result") from error
    _remaining(deadline)
    if not _is_terminal(state):
        return None
    raw = _read_result(runtime, config_dir, name)
    _remaining(deadline)
    if raw is not None:
        return raw
    raise RuntimeError(_terminal_failure(state))


def _completed_result(raw: str, deadline: float) -> dict:
    """Keep existing result validation while rejecting post-deadline success."""
    _remaining(deadline)
    value = _decode_result(raw)
    _remaining(deadline)
    return value


def _wait_result(runtime: DockerRuntime, config_dir: str, name: str,
                 max_wait_seconds: int = 110) -> dict:
    """Poll local publication quickly; inspect exact ownership only periodically."""
    if type(max_wait_seconds) is not int or not 110 <= max_wait_seconds <= 3645:
        raise RuntimeError("external-media host wait bound is invalid")
    deadline = time.monotonic() + max_wait_seconds
    delay = 0.05
    next_state_check = 0.0
    while time.monotonic() < deadline:
        raw = _read_result(runtime, config_dir, name)
        if raw is not None:
            return _completed_result(raw, deadline)
        if time.monotonic() >= next_state_check:
            raw = _pending_result(runtime, config_dir, name, deadline)
            next_state_check = time.monotonic() + _STATE_INTERVAL_SECONDS
        if raw is not None:
            return _completed_result(raw, deadline)
        time.sleep(min(delay, _remaining(deadline)))
        delay = min(delay * 1.5, 1.0)
    raise RuntimeError(
        f"external-media bounded decode exceeded {max_wait_seconds} seconds")


def _probe(runtime: DockerRuntime, config_dir: str, snapshot: ExternalMediaSnapshot,
           limits: MediaProbeLimits) -> dict:
    name = f"sniper-media-probe-{uuid.uuid4().hex}"
    os.mkdir(Path(config_dir) / "result", 0o700)
    launch = container_command(runtime, config_dir, name, snapshot.path, limits)
    container_ref = name
    try:
        container_ref = _launch(runtime, config_dir, launch, name)
        isolation = attest_probe_container(
            runtime, config_dir, name, snapshot.path, launch)
        network = probe_container(runtime, config_dir, name)
        decoded = validate_probe_document(
            _wait_result(
                runtime,
                config_dir,
                container_ref,
                max(110, limits.max_decode_seconds + 20),
            ),
            limits,
        )
        return {
            "isolation": isolation,
            "network": network,
            "decoded": decoded,
        }
    finally:
        removal = remove_container(runtime, config_dir, container_ref)
        if not removal.get("canonicalAbsenceProved"):
            raise RuntimeError("external-media probe removal was not proved")


def probe_external_media_snapshot(
    snapshot: ExternalMediaSnapshot,
    limits: MediaProbeLimits = MediaProbeLimits(),
) -> dict:
    """Attest the approved image and fully decode one immutable snapshot."""
    verify_external_media_snapshot(snapshot)
    runtime = required_runtime()
    with tempfile.TemporaryDirectory(prefix=".sniper-media-probe-") as config_dir:
        os.chmod(config_dir, 0o700)
        image = attest_image(runtime, config_dir)
        evidence = _probe(runtime, config_dir, snapshot, limits)
    verify_external_media_snapshot(snapshot)
    return {
        "schemaVersion": 1,
        "policy": POLICY_VERSION,
        "snapshot": {
            "path": snapshot.path,
            "sha256": snapshot.sha256,
            "sizeBytes": snapshot.size_bytes,
        },
        "limits": asdict(limits),
        "image": image,
        **evidence,
    }


def admit_external_media(
    source: str,
    snapshot_store: str,
    limits: MediaProbeLimits = MediaProbeLimits(),
) -> dict:
    """Snapshot then decode external media; return no receipt on any failure."""
    snapshot = capture_external_media_snapshot(source, snapshot_store)
    return probe_external_media_snapshot(snapshot, limits)
