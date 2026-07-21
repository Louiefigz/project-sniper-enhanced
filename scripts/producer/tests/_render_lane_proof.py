"""Complete synthetic worker proof for render-lane contract tests."""
from __future__ import annotations

import hashlib
import io
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path

from headless.container_io import SealedInput, verify_snapshot_archive

_CONTAINER_NAME = "sniper-render-" + "d" * 32


@dataclass(frozen=True)
class ProofInputs:
    expected_copy: tuple[str, ...] = ()
    snapshot: SealedInput | None = None


def _synthetic_entries() -> dict[str, bytes]:
    return {"motion/compositions/section-marker.html": b"<html></html>",
            "motion/hyperframes.json": b"{}", "motion/index.html": b"<html></html>",
            "motion/package.json": b"{}",
            "request/asset-bindings.json": b"[]",
            "request/variables.json": b"{}"}


def _archive(path: Path, snapshot: SealedInput | None = None
             ) -> tuple[str, list[dict], dict]:
    archive_path = Path(str(path) + ".input.tar")
    if snapshot is not None:
        archive_path.write_bytes(Path(snapshot.path).read_bytes())
        archive_path.chmod(0o600)
        manifest = list(snapshot.manifest)
        retained = verify_snapshot_archive(
            str(archive_path), snapshot.sha256, snapshot.manifest)
        return snapshot.sha256, manifest, {**retained,
            "members": list(retained["members"])}
    entries = _synthetic_entries()
    manifest = [{"path": name, "sizeBytes": len(data),
                 "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in sorted(entries.items())]
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    entries["request/input-manifest.json"] = manifest_bytes
    with tarfile.open(archive_path, "w", format=tarfile.USTAR_FORMAT) as archive:
        for name, data in sorted(entries.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o444, 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(data))
    archive_path.chmod(0o600)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    retained = verify_snapshot_archive(str(archive_path), digest, tuple(manifest))
    return digest, manifest, {**retained, "members": list(retained["members"])}


def _container(image_id: str, snapshot: str, container_name: str) -> dict:
    host = {
        "NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
        "CapDrop": ["ALL"], "CapAdd": None, "Devices": [],
        "DeviceRequests": None, "Memory": 4 * 1024 ** 3,
        "MemorySwap": 4 * 1024 ** 3, "NanoCpus": 4_000_000_000,
        "PidsLimit": 256, "ShmSize": 1024 ** 3, "Init": True,
        "AutoRemove": True, "PublishAllPorts": False,
        "SecurityOpt": ["no-new-privileges:true"], "PidMode": "",
        "UTSMode": "", "UsernsMode": "", "IpcMode": "private",
        "CgroupnsMode": "private",
        "Ulimits": [{"Name": "nofile", "Hard": 4096, "Soft": 4096}],
        "LogConfig": {"Type": "none"}, "RestartPolicy": {"Name": "no"},
        "Tmpfs": {"/scratch": "rw,nosuid,nodev,noexec,size=2g,uid=501,gid=20,mode=0700",
                  "/output": "rw,nosuid,nodev,noexec,size=512m,uid=501,gid=20,mode=0700"},
        "Mounts": [{"Type": "bind", "Source": "/sealed.tar",
                    "Target": "/request/render-input.tar", "ReadOnly": True}],
    }
    return {
        "Id": "b" * 64, "Image": image_id, "Args": ["render"],
        "State": {"Running": True, "Status": "running", "Paused": False,
                  "Restarting": False, "OOMKilled": False, "Dead": False},
        "Config": {"Image": image_id, "Entrypoint": ["/entrypoint"],
                   "WorkingDir": "/scratch", "User": "501:20",
                   "Cmd": ["render"], "Env": ["TZ=UTC",
                   f"SNIPER_INPUT_SHA256={snapshot}"], "Labels": {
                       "io.project-sniper.render-name": container_name}},
        "HostConfig": host,
        "Mounts": [{"Type": "bind", "Destination": "/request/render-input.tar",
                    "Source": "/sealed.tar", "RW": False,
                    "Propagation": "rprivate"}],
        "NetworkSettings": {"Networks": {"none": {"IPAddress": "",
                            "GlobalIPv6Address": "", "Gateway": "",
                            "IPv6Gateway": "", "MacAddress": ""}}, "Ports": {}},
    }


def _runtime(path: Path, media_digest: str, image_id: str,
             inputs: ProofInputs) -> dict:
    snapshot, manifest, retained = _archive(path, inputs.snapshot)
    container = _container(image_id, snapshot, _CONTAINER_NAME)
    denied = {"reached": False, "error": "ENETUNREACH"}
    components = [{"Name": name, "Version": "1"}
                  for name in ("Engine", "containerd", "runc", "docker-init")]
    return {
        "schemaVersion": 1, "policy": "sniper-oci-render-v2", "imageId": image_id,
        "snapshotSha256": snapshot, "snapshotManifest": manifest,
        "outputSha256": media_digest, "imageAttestation": {
            "Id": image_id, "Config": {"Entrypoint": ["/entrypoint"]}},
        "containerBeforeOutput": container, "containerAfterOutput": container,
        "containerRemoval": {"canonicalAbsenceProved": True},
        "activeNetworkProof": {"hostDecoyPositive": True, "container": {
            "ownLoopback": {"ok": True}, "hostLoopbackDecoy": denied,
            "externalIpv4": denied, "externalIpv6": denied,
            "dns": {"resolved": False, "error": "EAI_AGAIN"}}},
        "dockerRuntime": {"server": {"Version": "1", "ApiVersion": "1",
            "Os": "linux", "Arch": "arm64", "KernelVersion": "kernel",
            "Components": components}, "runtime": {"OSType": "linux",
            "KernelVersion": "kernel", "Driver": "overlayfs",
            "CgroupDriver": "cgroupfs", "DefaultRuntime": "runc",
            "SecurityOptions": []}}, "attestationScope": {},
        "retainedInputArchive": retained,
    }

def build_full_proof(path: Path, key: str, image_id: str,
                     inputs: ProofInputs = ProofInputs()) -> dict:
    media = path.read_bytes()
    media_digest = hashlib.sha256(media).hexdigest()
    copy_bytes = json.dumps(list(inputs.expected_copy), ensure_ascii=False,
                            separators=(",", ":")).encode()
    runtime = _runtime(path, media_digest, image_id, inputs)
    proof = {
        "schemaVersion": 1, "kind": "section-marker",
        "asset": {"sha256": media_digest, "sizeBytes": len(media),
                  "codec": "prores", "profile": "4444",
                  "pixelFormat": "yuva444p12le", "width": 1080,
                  "height": 1920, "durationS": 2.5,
                  "frameCount": 75, "fps": 30.0},
        "decode": {"decoded": True, "method": "ffmpeg-full-xerror"},
        "terminalFrame": {"frame": 74, "maxAlpha8": 0,
                          "meanAlpha8": 0.0,
                          "method": "ffmpeg-final-encoded-alpha"},
        "alphaMode": "required",
        "occupancy": {"basis": "synthetic alpha measurement",
                      "canvasPx": [1080, 1920], "mode": "alpha-overlay",
                      "measured": {"meanRatio": 0.1,
                                   "meaningfulFrameFraction": 1.0,
                                   "meaningfulFrames": 25,
                                   "method": "ffmpeg-alpha-sustained-area",
                                   "peakRatio": 0.2, "sampleFps": 10,
                                   "sampledFrames": 25, "sustainedRatio": 0.05}},
        "assetInputs": list(inputs.snapshot.asset_bindings) if inputs.snapshot else [],
        "copy": {"method": "validated-template-input",
                 "expected": list(inputs.expected_copy),
                 "sha256": hashlib.sha256(copy_bytes).hexdigest(),
                 "renderInputKey": key, "note": "test"},
        "runtimeAttestation": runtime,
        "sidecar": str(path) + ".proof.json",
    }
    disk = {name: value for name, value in proof.items() if name != "sidecar"}
    Path(proof["sidecar"]).write_text(json.dumps(disk), encoding="utf-8")
    Path(proof["sidecar"]).chmod(0o600)
    return proof
