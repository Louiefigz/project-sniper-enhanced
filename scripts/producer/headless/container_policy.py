"""Approved-image and Docker control-plane policy for sealed renders."""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import time
from dataclasses import dataclass
from headless.render_log_guard import RenderLogGuard, read_render_log, require_supported_cli

_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_USER_ID = re.compile(r"[1-9][0-9]*:[1-9][0-9]*")
_APPROVAL = "render_image_approval.json"
_ABORT_RECONCILE_SECONDS = 60.0
_MAX_ABORT_RECONCILE_SECONDS = 10 * 60.0
_ABORT_STABLE_SECONDS = 3.0
_ABORT_POLL_SECONDS = 0.25


@dataclass(frozen=True)
class DockerRuntime:
    """Validated local control endpoint and approved immutable image."""

    docker: str
    socket: str
    image_id: str
    user_id: str
    approval: dict


def _read_approval() -> dict:
    path = os.path.join(os.path.dirname(__file__), _APPROVAL)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("renderer image approval must be one regular file")
        with os.fdopen(fd, encoding="utf-8") as handle:
            fd = -1
            value = json.load(handle)
    finally:
        if fd >= 0:
            os.close(fd)
    if value.get("schemaVersion") != 1 or not _IMAGE_ID.fullmatch(
            str(value.get("imageId", ""))):
        raise RuntimeError("renderer image approval is invalid")
    return value


def required_runtime() -> DockerRuntime:
    """Resolve control inputs and reject operator-selected unapproved images."""
    docker_raw = os.environ.get("SNIPER_DOCKER_PATH", "").strip()
    image_id = os.environ.get("SNIPER_RENDER_IMAGE_ID", "").strip()
    user_id = os.environ.get("SNIPER_RENDER_UID_GID", "").strip()
    socket_raw = os.environ.get("SNIPER_DOCKER_SOCKET", "").strip()
    if not docker_raw or not os.path.isabs(docker_raw):
        raise RuntimeError("SNIPER_DOCKER_PATH must be an absolute executable path")
    docker = os.path.realpath(docker_raw)
    if not os.path.isfile(docker) or not os.access(docker, os.X_OK):
        raise RuntimeError(f"SNIPER_DOCKER_PATH is not executable: {docker_raw}")
    approval = _read_approval()
    if image_id != approval["imageId"]:
        raise RuntimeError("SNIPER_RENDER_IMAGE_ID is not the approved image ID")
    if not _USER_ID.fullmatch(user_id):
        raise RuntimeError("SNIPER_RENDER_UID_GID must be a nonroot numeric uid:gid")
    if not socket_raw or not os.path.isabs(socket_raw):
        raise RuntimeError("SNIPER_DOCKER_SOCKET must be an absolute local socket")
    socket_path = os.path.realpath(socket_raw)
    socket_info = os.stat(socket_path)
    if not stat.S_ISSOCK(socket_info.st_mode) or socket_info.st_uid != os.geteuid():
        raise RuntimeError("SNIPER_DOCKER_SOCKET must be a socket owned by this user")
    return DockerRuntime(docker, socket_path, image_id, user_id, approval)


def docker_env(config_dir: str) -> dict[str, str]:
    """No ambient context, TLS, credential helper, or secret reaches Docker."""
    return {"DOCKER_CONFIG": config_dir, "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8", "PATH": "/usr/bin:/bin", "TZ": "UTC"}


def command(runtime: DockerRuntime, *args: str) -> list[str]:
    """Address only the validated per-user local Docker socket."""
    return [runtime.docker, "--host", f"unix://{runtime.socket}", *args]


def _inspect_config(actual: dict, expected: dict) -> None:
    config = actual.get("Config") or {}
    pairs = (("User", "user"), ("Entrypoint", "entrypoint"),
             ("WorkingDir", "workingDir"), ("Env", "environment"),
             ("Volumes", "volumes"),
             ("Healthcheck", "healthcheck"))
    for actual_key, expected_key in pairs:
        if config.get(actual_key) != expected.get(expected_key):
            raise RuntimeError(f"approved image {actual_key} attestation failed")
    labels = config.get("Labels") or {}
    for key, value in expected.get("labels", {}).items():
        if labels.get(key) != value:
            raise RuntimeError(f"approved image label attestation failed: {key}")


def attest_image(runtime: DockerRuntime, config_dir: str) -> dict:
    """Bind the local image to the checked-in inspect and closure receipt."""
    proc = subprocess.run(
        command(runtime, "image", "inspect", runtime.image_id, "--format",
                "{{json .}}"), capture_output=True, text=True,
        stdin=subprocess.DEVNULL, env=docker_env(config_dir), timeout=30)
    if proc.returncode != 0:
        raise RuntimeError("approved renderer image is unavailable locally")
    try:
        actual = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Docker image inspect returned invalid JSON") from exc
    expected = runtime.approval
    if (actual.get("Id") != expected["imageId"]
            or actual.get("Architecture") != expected["architecture"]
            or actual.get("Os") != expected["os"]):
        raise RuntimeError("approved image identity/platform attestation failed")
    _inspect_config(actual, {**expected["config"], "labels": expected["labels"]})
    rootfs = actual.get("RootFS") or {}
    if (rootfs.get("Type") != expected["rootfs"]["type"]
            or rootfs.get("Layers") != expected["rootfs"]["layers"]):
        raise RuntimeError("approved image rootfs attestation failed")
    return actual


def _force_remove(runtime: DockerRuntime, config_dir: str, name: str) -> bool:
    """Request exact-name removal; return whether Docker reported a removal."""
    env = docker_env(config_dir)
    try:
        result = subprocess.run(
            command(runtime, "container", "rm", "--force", name),
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            env=env, timeout=30, check=False)
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def _is_absent(
    runtime: DockerRuntime,
    config_dir: str,
    name: str,
) -> bool | None:
    """Accept only Docker's exact canonical no-such-container response."""
    env = docker_env(config_dir)
    expected = f"Error response from daemon: No such container: {name}"
    try:
        inspect = subprocess.run(command(runtime, "container", "inspect", name),
                                 stdin=subprocess.DEVNULL, capture_output=True,
                                 text=True, env=env, timeout=15, check=False)
    except subprocess.TimeoutExpired:
        return None
    if (inspect.returncode == 1 and inspect.stdout.strip() == "[]"
            and inspect.stderr.strip() == expected):
        return True
    if inspect.returncode != 0:
        raise RuntimeError("container absence check failed ambiguously")
    return False


def remove_container(runtime: DockerRuntime, config_dir: str, name: str) -> dict:
    """Force removal and fail unless the exact random container is absent."""
    for attempt in range(10):
        _force_remove(runtime, config_dir, name)
        if _is_absent(runtime, config_dir, name):
            return {"containerRef": name, "canonicalAbsenceProved": True,
                    "method": "docker-force-remove-plus-exact-inspect-absence"}
        if attempt < 9:
            time.sleep(min(0.05 * (2 ** attempt), 1.0))
    raise RuntimeError("render container remains after forced removal")


def _absence_start(previous: float | None, appeared: bool,
                   absent: bool) -> float | None:
    if not absent:
        return None
    if appeared or previous is None:
        return time.monotonic()
    return previous


def reconcile_launch_abort(runtime: DockerRuntime, config_dir: str,
                           name: str, timeout_seconds: float =
                           _ABORT_RECONCILE_SECONDS) -> None:
    """Remove late creates until absence is continuous after client death."""
    valid_timeout = (
        type(timeout_seconds) in (int, float)
        and 1.0 <= timeout_seconds <= _MAX_ABORT_RECONCILE_SECONDS
    )
    if not valid_timeout:
        raise RuntimeError("launch-abort reconciliation timeout is invalid")
    deadline = time.monotonic() + timeout_seconds
    absent_since = None
    while time.monotonic() < deadline:
        before_absent = _is_absent(runtime, config_dir, name)
        _force_remove(runtime, config_dir, name)
        absent = _is_absent(runtime, config_dir, name)
        # Successful rm is not appearance; only exact observations establish absence.
        absent_since = _absence_start(absent_since, before_absent is not True, absent is True)
        if (absent_since is not None
                and time.monotonic() - absent_since >= _ABORT_STABLE_SECONDS):
            remove_container(runtime, config_dir, name)
            return
        time.sleep(_ABORT_POLL_SECONDS)
    raise RuntimeError("late render-container creation could not be reconciled")


def _exec_cat(runtime: DockerRuntime, config_dir: str,
              name: str, path: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        command(runtime, "container", "exec", name, "/usr/bin/cat", path),
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        env=docker_env(config_dir), timeout=30, check=False)


def _exec_tail(runtime: DockerRuntime, config_dir: str,
               name: str, path: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        command(runtime, "container", "exec", name, "/usr/bin/tail", "-c",
                "4096", path), stdin=subprocess.DEVNULL, capture_output=True,
        text=True, env=docker_env(config_dir), timeout=30, check=False)


def _state(runtime: DockerRuntime, config_dir: str, name: str) -> str:
    proc = subprocess.run(
        command(runtime, "container", "inspect", name, "--format",
                "{{.State.Status}}"), stdin=subprocess.DEVNULL,
        capture_output=True, text=True, env=docker_env(config_dir),
        timeout=15, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else "absent"


def _status_code(raw: str) -> int:
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise RuntimeError("render status is invalid") from exc
    if str(value) != raw.strip() or not 0 <= value <= 255:
        raise RuntimeError("render status is outside the expected range")
    return value


def _stream_output(runtime: DockerRuntime, config_dir: str,
                   name: str, destination: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(destination, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output:
            fd = -1
            proc = subprocess.run(
                command(runtime, "container", "exec", name, "/usr/bin/cat",
                        f"/output/render{os.path.splitext(destination)[1]}"),
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.PIPE,
                env=docker_env(config_dir), timeout=120, check=False)
            output.flush()
            os.fsync(output.fileno())
        size = os.path.getsize(destination)
        if proc.returncode != 0 or not 0 < size <= 512 * 1024 * 1024:
            message = proc.stderr.decode("utf-8", errors="replace").strip()[-240:]
            raise RuntimeError(f"could not stream container render output: {message}")
    except Exception:
        try:
            os.unlink(destination)
        except FileNotFoundError:
            pass
        raise
    finally:
        if fd >= 0:
            os.close(fd)


def wait_and_copy(runtime: DockerRuntime, config_dir: str,
                  name: str, destination: str) -> None:
    """Copy from live quota tmpfs only after the wrapper seals its status."""
    deadline = time.monotonic() + 600
    delay = 0.1
    require_supported_cli(runtime.approval)
    guard = RenderLogGuard()
    while time.monotonic() < deadline:
        status = _exec_cat(runtime, config_dir, name, "/output/status")
        guard.observe(read_render_log(runtime, config_dir, name), time.monotonic())
        if status.returncode == 0:
            break
        if _state(runtime, config_dir, name) != "running":
            raise RuntimeError("render container exited before sealing status")
        time.sleep(delay)
        delay = min(delay * 1.5, 2.0)
    else:
        raise RuntimeError("networkless HyperFrames render exceeded 600s")
    code = _status_code(status.stdout)
    if code != 0:
        log = _exec_tail(runtime, config_dir, name, "/output/render.log")
        tail = log.stdout.strip()[-240:] if log.returncode == 0 else "log unavailable"
        raise RuntimeError(f"networkless HyperFrames render exited {code}: {tail}")
    guard.observe(read_render_log(runtime, config_dir, name), time.monotonic(), finished=True)
    _stream_output(runtime, config_dir, name, destination)
