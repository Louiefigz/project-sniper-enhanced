"""Bind retained Docker attestations to the exact rendered media bytes."""
from __future__ import annotations

import json
import os
import re
import stat
import tempfile

from headless.container_io import promote_regular, verify_snapshot_archive


def _read_json(path: str) -> dict:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.geteuid()):
            raise RuntimeError("runtime receipt must be one user-owned regular file")
        with os.fdopen(fd, encoding="utf-8") as handle:
            fd = -1
            value = json.load(handle)
            after = os.fstat(handle.fileno())
        identity = (before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns)
        if identity != (after.st_dev, after.st_ino, after.st_size,
                        after.st_mtime_ns):
            raise RuntimeError("runtime receipt changed while reading")
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(value, dict):
        raise RuntimeError("runtime receipt must contain a JSON object")
    return value


def _write_new_json(path: str, value: dict) -> None:
    directory = os.path.dirname(path) or "."
    prefix = f".{os.path.basename(path)}."
    fd, temporary = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        promote_regular(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def write_runtime_receipt(media_path: str, receipt: dict) -> str:
    """Write one no-replace receipt beside a controller-owned candidate."""
    path = media_path + ".runtime.json"
    if os.path.lexists(path):
        raise RuntimeError("runtime receipt destination already exists")
    _write_new_json(path, receipt)
    return path


_SHA256 = re.compile(r"[0-9a-f]{64}")
_REQUIRED_HOST = {"NetworkMode": "none", "ReadonlyRootfs": True,
                  "Privileged": False, "CapDrop": ["ALL"],
                  "Memory": 4 * 1024 ** 3, "MemorySwap": 4 * 1024 ** 3,
                  "NanoCpus": 4_000_000_000, "PidsLimit": 256,
                  "ShmSize": 1024 ** 3, "Init": True, "AutoRemove": True,
                  "PublishAllPorts": False}


def _host_shape(host: dict, user: str, source: str) -> dict:
    uid, gid = user.split(":", 1)
    tmpfs = {
        "/scratch": f"rw,nosuid,nodev,noexec,size=2g,uid={uid},gid={gid},mode=0700",
        "/output": f"rw,nosuid,nodev,noexec,size=512m,uid={uid},gid={gid},mode=0700"}
    host_mounts = host.get("Mounts") or []
    valid_mount = (len(host_mounts) == 1
                   and host_mounts[0].get("Type") == "bind"
                   and host_mounts[0].get("Source") == source
                   and host_mounts[0].get("Target") == "/request/render-input.tar"
                   and host_mounts[0].get("ReadOnly") is True)
    namespaces = (host.get("PidMode"), host.get("UTSMode"), host.get("UsernsMode"))
    if (any(host.get(key) != expected for key, expected in _REQUIRED_HOST.items())
            or host.get("SecurityOpt") != ["no-new-privileges:true"]
            or host.get("CapAdd") not in (None, []) or host.get("Devices") not in (None, [])
            or host.get("DeviceRequests") not in (None, []) or any(namespaces)
            or host.get("IpcMode") != "private" or host.get("CgroupnsMode") != "private"
            or host.get("Ulimits") != [{"Name": "nofile", "Hard": 4096, "Soft": 4096}]
            or (host.get("LogConfig") or {}).get("Type") != "none"
            or (host.get("RestartPolicy") or {}).get("Name") != "no"
            or host.get("Tmpfs") != tmpfs or not valid_mount):
        raise RuntimeError("stored runtime receipt fails offline host policy")
    return host


def _container_shape(value: dict, image_id: str, image: dict,
                     snapshot_sha256: str) -> dict:
    config, host = value.get("Config") or {}, value.get("HostConfig") or {}
    state, network = value.get("State") or {}, value.get("NetworkSettings") or {}
    mounts = value.get("Mounts") or []
    networks = network.get("Networks") or {}
    none = networks.get("none") or {}
    addresses = ("IPAddress", "GlobalIPv6Address", "Gateway", "IPv6Gateway",
                 "MacAddress")
    valid_mount = (len(mounts) == 1 and mounts[0].get("Type") == "bind"
                   and mounts[0].get("Destination") == "/request/render-input.tar"
                   and mounts[0].get("RW") is False
                   and mounts[0].get("Propagation") == "rprivate")
    rows = config.get("Env") or []
    pairs = [row.split("=", 1) for row in rows if "=" in row]
    env = dict(pairs)
    bad_state = (state.get("Paused") or state.get("Restarting")
                 or state.get("OOMKilled") or state.get("Dead"))
    if (value.get("Image") != image_id or config.get("Image") != image_id
            or config.get("Entrypoint") != (image.get("Config") or {}).get("Entrypoint")
            or config.get("WorkingDir") != "/scratch" or config.get("User") in ("", "0", "0:0")
            or not state.get("Running") or state.get("Status") != "running" or bad_state
            or config.get("Cmd") != value.get("Args")
            or len(pairs) != len(rows) or len(env) != len(rows)
            or env.get("SNIPER_INPUT_SHA256") != snapshot_sha256
            or set(networks) != {"none"} or any(none.get(key) for key in addresses)
            or network.get("Ports") not in (None, {}) or not valid_mount):
        raise RuntimeError("stored runtime receipt fails offline container policy")
    source = mounts[0].get("Source")
    _host_shape(host, config["User"], source)
    return {"Id": value.get("Id"), "Image": image_id, "Cmd": config.get("Cmd"),
            "Env": config.get("Env"), "Labels": config.get("Labels"),
            "User": config.get("User"), "HostConfig": host,
            "Mount": mounts[0], "Networks": networks}


def _network_proof(receipt: dict) -> None:
    active = receipt.get("activeNetworkProof") or {}
    container = active.get("container") or {}
    denied = [container.get(key) or {} for key in
              ("hostLoopbackDecoy", "externalIpv4", "externalIpv6")]
    if (active.get("hostDecoyPositive") is not True
            or (container.get("ownLoopback") or {}).get("ok") is not True
            or any(row.get("reached") is not False or not row.get("error")
                   for row in denied)
            or (container.get("dns") or {}).get("resolved") is not False):
        raise RuntimeError("stored runtime receipt fails active network proof")


def _manifest(receipt: dict) -> None:
    rows = receipt.get("snapshotManifest")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("stored runtime receipt has no sealed-input manifest")
    paths = []
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("path"), str)
                or not isinstance(row.get("sizeBytes"), int)
                or row["sizeBytes"] < 0
                or not _SHA256.fullmatch(str(row.get("sha256", "")))):
            raise RuntimeError("stored sealed-input manifest is invalid")
        paths.append(row["path"])
    if len(paths) != len(set(paths)) or paths != sorted(paths):
        raise RuntimeError("stored sealed-input manifest paths are not canonical")


def _docker_identity(receipt: dict) -> None:
    identity = receipt.get("dockerRuntime") or {}
    server, runtime = identity.get("server") or {}, identity.get("runtime") or {}
    components = {row.get("Name"): row.get("Version")
                  for row in server.get("Components") or []}
    if (not server.get("Version") or not server.get("ApiVersion")
            or server.get("Os") != "linux" or server.get("Arch") != "arm64"
            or not all(components.get(key) for key in
                       ("Engine", "containerd", "runc", "docker-init"))
            or runtime.get("OSType") != "linux"
            or runtime.get("KernelVersion") != server.get("KernelVersion")
            or not runtime.get("Driver") or not runtime.get("CgroupDriver")
            or not runtime.get("DefaultRuntime")
            or not isinstance(runtime.get("SecurityOptions"), list)):
        raise RuntimeError("stored runtime receipt lacks Docker runtime identity")


def _validate(receipt: dict, media_sha256: str) -> None:
    before = receipt.get("containerBeforeOutput") or {}
    after = receipt.get("containerAfterOutput") or {}
    image = receipt.get("imageAttestation") or {}
    expected = receipt.get("imageId")
    if (receipt.get("schemaVersion") != 1
            or receipt.get("outputSha256") != media_sha256
            or image.get("Id") != expected or before.get("Image") != expected
            or after.get("Image") != expected or before.get("Id") != after.get("Id")
            or not _SHA256.fullmatch(str(receipt.get("snapshotSha256", "")))
            or not (receipt.get("containerRemoval") or {}).get(
                "canonicalAbsenceProved")):
        raise RuntimeError("runtime receipt is not bound to media/container identity")
    snapshot = receipt["snapshotSha256"]
    if _container_shape(before, expected, image, snapshot) != _container_shape(
            after, expected, image, snapshot):
        raise RuntimeError("runtime container policy changed during output streaming")
    _network_proof(receipt)
    _docker_identity(receipt)
    _manifest(receipt)


def validate_runtime_attestation(receipt: dict, media_path: str,
                                 media_sha256: str,
                                 expected_image_id: str) -> None:
    """Revalidate worker runtime evidence and the retained sealed archive."""
    if not isinstance(receipt, dict) or receipt.get("imageId") != expected_image_id:
        raise RuntimeError("runtime receipt image is not controller-approved")
    _validate(receipt, media_sha256)
    retained = verify_snapshot_archive(
        media_path + ".input.tar", receipt["snapshotSha256"],
        tuple(receipt["snapshotManifest"]))
    retained = {**retained, "members": list(retained["members"])}
    if receipt.get("retainedInputArchive") != retained:
        raise RuntimeError("runtime receipt retained archive proof is inconsistent")


def bind_runtime_receipt(media_path: str, proof: dict) -> dict:
    """Validate and embed raw pre/post runtime evidence in the asset proof."""
    receipt = _read_json(media_path + ".runtime.json")
    media_sha256 = str((proof.get("asset") or {}).get("sha256", ""))
    _validate(receipt, media_sha256)
    receipt["retainedInputArchive"] = verify_snapshot_archive(
        media_path + ".input.tar", receipt["snapshotSha256"],
        tuple(receipt["snapshotManifest"]))
    bound = {**proof, "runtimeAttestation": receipt}
    sidecar = bound.get("sidecar")
    if sidecar != media_path + ".proof.json":
        raise RuntimeError("asset proof sidecar is not bound to candidate media")
    disk_proof = {key: value for key, value in bound.items() if key != "sidecar"}
    os.unlink(sidecar)
    _write_new_json(sidecar, disk_proof)
    return bound
