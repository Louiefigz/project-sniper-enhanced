"""Pinned-container policy for over-cap qualification mezzanines."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from headless.container_policy import (
    DockerRuntime,
    command,
    docker_env,
)
from headless.external_media_snapshot import MAX_EXTERNAL_MEDIA_BYTES

MAX_QUALIFICATION_SOURCE_BYTES = 64 * 1024 ** 3
MEMORY_BYTES = 2 * 1024 ** 3
CPU_NANOS = 4_000_000_000
PIDS_LIMIT = 128
MAX_RESULT_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 3 * 60 * 60
PROJECT_FPS = {24, 25, 30, 50, 60}
_WORKER_PATHS = (
    Path(__file__).with_name("qualification_mezzanine_worker.js"),
    Path(__file__).with_name("qualification_mezzanine_worker_media.js"),
)


@dataclass(frozen=True)
class QualificationLaunch:
    """One exact isolated-container request."""

    source: str
    output_dir: str
    name: str
    timeout_seconds: int
    target_fps: int


@dataclass(frozen=True)
class QualificationAttestation:
    """Resolved-container observation inputs."""

    config_dir: str
    launch: QualificationLaunch
    expected_command: list[str]


def _worker_source() -> str:
    payload = b"\n".join(path.read_bytes() for path in _WORKER_PATHS)
    if not 0 < len(payload) <= 256 * 1024:
        raise RuntimeError("qualification worker is not one bounded script")
    return payload.decode("utf-8")

def _mount(source: str, destination: str, readonly: bool = False) -> str:
    if "," in source:
        raise RuntimeError("qualification mount path cannot contain commas")
    suffix = ",readonly" if readonly else ""
    return f"type=bind,src={source},dst={destination}{suffix}"

def container_command(
    runtime: DockerRuntime,
    request: QualificationLaunch,
) -> list[str]:
    """Build the exact secret-free qualification container launch."""
    if (type(request.timeout_seconds) is not int
            or not 300 <= request.timeout_seconds <= 24 * 60 * 60):
        raise RuntimeError("qualification timeout must be 300..86400 seconds")
    if type(request.target_fps) is not int or request.target_fps not in PROJECT_FPS:
        raise RuntimeError("qualification project fps is unsupported")
    source_real = os.path.realpath(request.source)
    output_real = os.path.realpath(request.output_dir)
    uid, gid = runtime.user_id.split(":", 1)
    scratch = (f"/scratch:rw,nosuid,nodev,noexec,size=256m,"
               f"uid={uid},gid={gid},mode=0700")
    result = command(
        runtime, "run", "--detach", "--pull", "never", "--name", request.name,
        "--platform", "linux/arm64", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        "--user", runtime.user_id, "--pids-limit", str(PIDS_LIMIT),
        "--memory", "2g", "--memory-swap", "2g", "--cpus", "4",
        "--init", "--stop-timeout", "5", "--log-driver", "none",
        "--ulimit", "nofile=256:256", "--hostname", "sniper-mezzanine",
        "--tmpfs", scratch,
        "--mount", _mount(source_real, "/input/source", True),
        "--mount", _mount(output_real, "/output"),
        "--entrypoint", "/usr/bin/node",
    )
    for key, value in {
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC",
        "TMPDIR": "/scratch",
    }.items():
        result.extend(("--env", f"{key}={value}"))
    result.extend((
        runtime.image_id, "-e", _worker_source(),
        str(MAX_EXTERNAL_MEDIA_BYTES), str(MAX_QUALIFICATION_SOURCE_BYTES),
        str(request.timeout_seconds), str(request.target_fps),
    ))
    return result

def _inspect(
    runtime: DockerRuntime,
    config_dir: str,
    name: str,
) -> dict:
    result = subprocess.run(
        command(runtime, "container", "inspect", name, "--format", "{{json .}}"),
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        env=docker_env(config_dir), timeout=15, check=False)
    if result.returncode != 0:
        raise RuntimeError("could not inspect qualification container")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("qualification inspect returned invalid JSON") from exc

def _expected_environment(runtime: DockerRuntime) -> dict[str, str]:
    expected = dict(
        row.split("=", 1)
        for row in runtime.approval["config"]["environment"])
    expected.update({
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC",
        "TMPDIR": "/scratch",
    })
    return expected

def _mounts_match(actual: dict, request: QualificationLaunch) -> bool:
    mounts = actual.get("Mounts") or []
    by_target = {row.get("Destination"): row for row in mounts}
    source_mount, output_mount = (
        by_target.get("/input/source") or {},
        by_target.get("/output") or {},
    )
    return (
        len(mounts) == 2
        and source_mount.get("Source") == os.path.realpath(request.source)
        and source_mount.get("RW") is False
        and output_mount.get("Source") == os.path.realpath(request.output_dir)
        and output_mount.get("RW") is True
    )

def _host_policy_matches(runtime: DockerRuntime, host: dict) -> bool:
    required = {
        "NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
        "CapDrop": ["ALL"], "Memory": MEMORY_BYTES,
        "MemorySwap": MEMORY_BYTES, "NanoCpus": CPU_NANOS,
        "PidsLimit": PIDS_LIMIT, "Init": True,
    }
    scratch = set(str((host.get("Tmpfs") or {}).get("/scratch", "")).split(","))
    uid, gid = runtime.user_id.split(":", 1)
    scratch_base = {"rw", "nosuid", "nodev", "noexec",
                    f"uid={uid}", f"gid={gid}", "mode=0700"}
    scratch_size = scratch - scratch_base
    return (
        all(host.get(key) == value for key, value in required.items())
        and host.get("SecurityOpt") == ["no-new-privileges:true"]
        and host.get("CapAdd") in (None, [])
        and (host.get("LogConfig") or {}).get("Type") == "none"
        and scratch_base.issubset(scratch)
        and scratch_size in ({"size=256m"}, {"size=268435456"})
    )

def attest_qualification_container(
    runtime: DockerRuntime,
    request: QualificationAttestation,
) -> dict:
    """Reobserve Docker-resolved isolation before accepting any output."""
    launch = request.launch
    actual = _inspect(runtime, request.config_dir, launch.name)
    config, host, state = (
        actual.get("Config") or {},
        actual.get("HostConfig") or {},
        actual.get("State") or {},
    )
    image_index = request.expected_command.index(runtime.image_id)
    expected_cmd = request.expected_command[image_index + 1:]
    environment = dict(
        row.split("=", 1) for row in config.get("Env") or [] if "=" in row)
    networks = (actual.get("NetworkSettings") or {}).get("Networks") or {}
    identity = (
        state.get("Running")
        and actual.get("Image") == runtime.image_id
        and config.get("User") == runtime.user_id
        and config.get("Entrypoint") == ["/usr/bin/node"]
        and config.get("Cmd") == expected_cmd
        and environment == _expected_environment(runtime)
        and len(environment) == len(_expected_environment(runtime))
        and set(networks) == {"none"}
    )
    if not (identity and _host_policy_matches(runtime, host)
            and _mounts_match(actual, launch)):
        raise RuntimeError("qualification container isolation attestation failed")
    command_hash = hashlib.sha256(
        json.dumps(expected_cmd, ensure_ascii=True, separators=(",", ":"))
        .encode("ascii")).hexdigest()
    return {"imageId": actual["Image"], "containerId": actual["Id"],
        "networkMode": host["NetworkMode"], "nonrootUser": config["User"],
        "readonlyRoot": host["ReadonlyRootfs"],
        "sourceMount": {"path": os.path.realpath(launch.source), "readonly": True},
        "outputMount": {"path": os.path.realpath(launch.output_dir),
                        "narrowWrite": True},
        "memoryBytes": host["Memory"], "cpuNanos": host["NanoCpus"],
        "pidsLimit": host["PidsLimit"], "resolvedCommandSha256": command_hash,
    }
