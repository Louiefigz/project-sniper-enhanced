"""Post-launch attestation of Docker-resolved render-container facts."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

from headless.container_policy import DockerRuntime, command, docker_env

HYPERFRAMES_VERSION_LABEL = "io.project-sniper.hyperframes-version"


def output_tmpfs_size(version: object) -> str:
    """Keep exact historical quotas; give 0.8.31 its required disk headroom."""
    quotas = {"0.7.33": "1g", "0.8.31": "2g"}
    if type(version) is not str or version not in quotas:
        raise RuntimeError("unsupported renderer version for output tmpfs policy")
    return quotas[version]


@dataclass(frozen=True)
class ContainerExpectation:
    """Daemon-resolved facts expected after a detached launch."""

    container_id: str
    name: str
    snapshot: str
    environment: dict[str, str]
    command: tuple[str, ...]


def _required_host() -> dict:
    return {"NetworkMode": "none", "ReadonlyRootfs": True,
            "Privileged": False, "CapDrop": ["ALL"],
            "Memory": 4 * 1024 ** 3, "MemorySwap": 4 * 1024 ** 3,
            "NanoCpus": 4_000_000_000, "PidsLimit": 256,
            "ShmSize": 1024 ** 3, "Init": True, "AutoRemove": True,
            "PublishAllPorts": False}


def _host_policy(actual: dict, expected: ContainerExpectation, version: object) -> None:
    host = actual.get("HostConfig") or {}
    for key, value in _required_host().items():
        if host.get(key) != value:
            raise RuntimeError(f"live container host policy failed: {key}")
    if ((host.get("SecurityOpt") or []) != ["no-new-privileges:true"]
            or host.get("CapAdd") not in (None, [])
            or host.get("Devices") not in (None, [])
            or host.get("DeviceRequests") not in (None, [])
            or host.get("Ulimits") != [{"Name": "nofile", "Hard": 4096,
                                        "Soft": 4096}]):
        raise RuntimeError("live container privilege/limit policy failed")
    namespaces = (host.get("PidMode"), host.get("UTSMode"),
                  host.get("UsernsMode"))
    if (any(namespaces) or host.get("IpcMode") != "private"
            or host.get("CgroupnsMode") != "private"):
        raise RuntimeError("live container host namespace policy failed")
    if ((host.get("LogConfig") or {}).get("Type") != "none"
            or (host.get("RestartPolicy") or {}).get("Name") != "no"):
        raise RuntimeError("live container lifecycle policy failed")
    uid, gid = actual["Config"]["User"].split(":", 1)
    quota = output_tmpfs_size(version)
    expected_tmpfs = {
        "/scratch": f"rw,nosuid,nodev,noexec,size=2g,uid={uid},gid={gid},mode=0700",
        "/output": f"rw,nosuid,nodev,noexec,size={quota},uid={uid},gid={gid},mode=0700"}
    if host.get("Tmpfs") != expected_tmpfs:
        raise RuntimeError("live container tmpfs policy failed")
    mounts = actual.get("Mounts") or []
    source = os.path.realpath(expected.snapshot)
    valid = [row for row in mounts if row.get("Type") == "bind"
             and row.get("Source") == source
             and row.get("Destination") == "/request/render-input.tar"
             and row.get("RW") is False]
    host_mounts = host.get("Mounts") or []
    host_valid = [row for row in host_mounts if row.get("Type") == "bind"
                  and row.get("Source") == source
                  and row.get("Target") == "/request/render-input.tar"
                  and row.get("ReadOnly") is True]
    if (len(mounts) != 1 or len(valid) != 1 or len(host_mounts) != 1
            or len(host_valid) != 1 or mounts[0].get("Propagation") != "rprivate"):
        raise RuntimeError("live container mount policy failed")


def _environment(config: dict, runtime: DockerRuntime,
                 expected: ContainerExpectation) -> None:
    rows = config.get("Env") or []
    pairs = [row.split("=", 1) for row in rows if "=" in row]
    if len(pairs) != len(rows) or len({key for key, _ in pairs}) != len(rows):
        raise RuntimeError("live container has duplicate/invalid environment keys")
    actual = dict(pairs)
    base = dict(row.split("=", 1)
                for row in runtime.approval["config"]["environment"])
    if actual != {**base, **expected.environment}:
        raise RuntimeError("live container environment attestation failed")


def _network(actual: dict) -> None:
    networks = (actual.get("NetworkSettings") or {}).get("Networks") or {}
    if set(networks) != {"none"}:
        raise RuntimeError("live container network attachment policy failed")
    none = networks["none"]
    keys = ("IPAddress", "GlobalIPv6Address", "Gateway", "IPv6Gateway",
            "MacAddress")
    if any(none.get(key) for key in keys) \
            or (actual.get("NetworkSettings") or {}).get("Ports") not in (None, {}):
        raise RuntimeError("network-none container unexpectedly received an address")


def attest_container(runtime: DockerRuntime, config_dir: str,
                     expected: ContainerExpectation) -> dict:
    """Re-read daemon-resolved security facts before trusting output."""
    proc = subprocess.run(
        command(runtime, "container", "inspect", expected.container_id,
                "--format", "{{json .}}"), stdin=subprocess.DEVNULL,
        capture_output=True, text=True, env=docker_env(config_dir),
        timeout=30, check=False)
    if proc.returncode != 0:
        raise RuntimeError("could not inspect launched render container")
    try:
        actual = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("launched container inspect returned invalid JSON") from exc
    config, state = actual.get("Config") or {}, actual.get("State") or {}
    approved = runtime.approval["config"]
    labels = {**runtime.approval["labels"],
              "io.project-sniper.render-name": expected.name}
    bad_state = (state.get("Status") != "running" or state.get("Paused")
                 or state.get("Restarting") or state.get("OOMKilled")
                 or state.get("Dead"))
    if (actual.get("Id") != expected.container_id
            or actual.get("Name") != f"/{expected.name}"
            or actual.get("Image") != runtime.image_id or not state.get("Running")
            or bad_state
            or config.get("Image") != runtime.image_id
            or config.get("User") != runtime.user_id
            or config.get("Entrypoint") != approved["entrypoint"]
            or config.get("WorkingDir") != "/scratch"
            or config.get("Hostname") != "sniper-render"
            or config.get("StopTimeout") != 10
            or config.get("Labels") != labels
            or config.get("Cmd") != list(expected.command)):
        raise RuntimeError("live container identity/command attestation failed")
    _environment(config, runtime, expected)
    _host_policy(actual, expected, runtime.approval["labels"].get(HYPERFRAMES_VERSION_LABEL))
    _network(actual)
    return actual
