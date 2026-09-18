"""Stable Docker Engine/runtime envelope used by render cache and receipts."""
from __future__ import annotations

import copy
import functools
import hashlib
import json
import os
import subprocess
import threading

from headless.container_policy import DockerRuntime, command, docker_env

__all__ = ["daemon_identity", "file_sha256"]
_CACHE_LOCK = threading.Lock()
_CACHE: tuple[tuple, dict] | None = None

_INFO_FORMAT = (
    '{"OSType":{{json .OSType}},"Architecture":{{json .Architecture}},'
    '"KernelVersion":{{json .KernelVersion}},"Driver":{{json .Driver}},'
    '"CgroupDriver":{{json .CgroupDriver}},'
    '"CgroupVersion":{{json .CgroupVersion}},'
    '"SecurityOptions":{{json .SecurityOptions}},'
    '"DefaultRuntime":{{json .DefaultRuntime}}}')


def _run_json(runtime: DockerRuntime, config_dir: str,
              arguments: tuple[str, ...], label: str) -> dict:
    proc = subprocess.run(
        command(runtime, *arguments), stdin=subprocess.DEVNULL,
        capture_output=True, text=True, env=docker_env(config_dir),
        timeout=30, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"could not attest Docker {label} identity")
    try:
        value = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Docker {label} identity is invalid JSON") from exc
    if not isinstance(value, dict) or not value:
        raise RuntimeError(f"Docker {label} identity is empty")
    return value


def _identity_key(runtime: DockerRuntime) -> tuple:
    rows = []
    for path in (runtime.docker, runtime.socket):
        info = os.stat(path)
        rows.append((os.path.realpath(path), info.st_dev, info.st_ino,
                     info.st_size, info.st_mtime_ns, info.st_ctime_ns))
    return runtime.image_id, *rows


@functools.lru_cache(maxsize=128)
def _hash_inode(path: str, identity: tuple[int, ...]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        before = os.fstat(handle.fileno())
        actual = (before.st_dev, before.st_ino, before.st_size,
                  before.st_mtime_ns, before.st_ctime_ns)
        if actual != identity:
            raise RuntimeError(f"cache-identity input changed before hashing: {path}")
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(handle.fileno())
        if actual != (after.st_dev, after.st_ino, after.st_size,
                      after.st_mtime_ns, after.st_ctime_ns):
            raise RuntimeError(f"cache-identity input changed while hashing: {path}")
    return digest.hexdigest()


def file_sha256(path: str) -> str:
    """Hash a stable inode once per unchanged identity in this process."""
    path = os.path.realpath(path)
    info = os.stat(path)
    identity = (info.st_dev, info.st_ino, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns)
    return _hash_inode(path, identity)


def _probe_identity(runtime: DockerRuntime, config_dir: str) -> dict:
    server = _run_json(runtime, config_dir,
                       ("version", "--format", "{{json .Server}}"), "server")
    info = _run_json(runtime, config_dir,
                     ("info", "--format", _INFO_FORMAT), "runtime")
    required_server = ("Version", "ApiVersion", "Os", "Arch", "Components",
                       "KernelVersion")
    required_info = ("OSType", "Architecture", "KernelVersion", "Driver",
                     "CgroupDriver", "CgroupVersion", "DefaultRuntime")
    if (any(not server.get(key) for key in required_server)
            or any(not info.get(key) for key in required_info)
            or not isinstance(info.get("SecurityOptions"), list)):
        raise RuntimeError("Docker runtime identity lacks required stable facts")
    return {"server": server, "runtime": info}


def daemon_identity(runtime: DockerRuntime, config_dir: str) -> dict:
    """Probe once per stable local daemon/socket identity, then reuse safely."""
    global _CACHE
    key = _identity_key(runtime)
    with _CACHE_LOCK:
        if _CACHE is None or _CACHE[0] != key:
            _CACHE = (key, _probe_identity(runtime, config_dir))
        return copy.deepcopy(_CACHE[1])
