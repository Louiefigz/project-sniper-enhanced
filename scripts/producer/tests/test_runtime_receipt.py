"""Runtime-attestation persistence and media-binding regressions."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from headless.runtime_receipt import bind_runtime_receipt, write_runtime_receipt

_IMAGE = "sha256:" + "a" * 64


def _receipt(media: bytes) -> dict:
    container = {
        "Id": "b" * 64, "Image": _IMAGE,
        "State": {"Running": True, "Status": "running", "Paused": False,
                  "Restarting": False, "OOMKilled": False, "Dead": False},
        "Config": {"Image": _IMAGE, "Entrypoint": ["/entrypoint"],
                   "WorkingDir": "/scratch", "User": "501:20",
                   "Cmd": ["render"], "Env": ["TZ=UTC",
                   "SNIPER_INPUT_SHA256=" + "c" * 64], "Labels": {
                       "io.project-sniper.hyperframes-version": "0.7.33"}},
        "Args": ["render"],
        "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True,
                       "Privileged": False, "CapDrop": ["ALL"], "CapAdd": None,
                       "Devices": [], "DeviceRequests": None,
                       "Memory": 4 * 1024 ** 3, "MemorySwap": 4 * 1024 ** 3,
                       "NanoCpus": 4_000_000_000, "PidsLimit": 256,
                       "ShmSize": 1024 ** 3, "Init": True, "AutoRemove": True,
                       "PublishAllPorts": False,
                       "SecurityOpt": ["no-new-privileges:true"],
                       "PidMode": "", "UTSMode": "", "UsernsMode": "",
                       "IpcMode": "private", "CgroupnsMode": "private",
                       "Ulimits": [{"Name": "nofile", "Hard": 4096, "Soft": 4096}],
                       "LogConfig": {"Type": "none"},
                       "RestartPolicy": {"Name": "no"},
                       "Tmpfs": {
                           "/scratch": ("rw,nosuid,nodev,noexec,size=2g,uid=501,"
                                        "gid=20,mode=0700"),
                           "/output": ("rw,nosuid,nodev,noexec,size=1g,uid=501,"
                                       "gid=20,mode=0700")},
                       "Mounts": [{"Type": "bind", "Source": "/sealed.tar",
                                   "Target": "/request/render-input.tar",
                                   "ReadOnly": True}]},
        "Mounts": [{"Type": "bind", "Destination": "/request/render-input.tar",
                    "Source": "/sealed.tar", "RW": False,
                    "Propagation": "rprivate"}],
        "NetworkSettings": {"Networks": {"none": {"IPAddress": "",
                            "GlobalIPv6Address": "", "Gateway": "",
                            "IPv6Gateway": "", "MacAddress": ""}}, "Ports": {}}}
    denied = {"reached": False, "error": "ENETUNREACH"}
    components = [{"Name": name, "Version": "1"}
                  for name in ("Engine", "containerd", "runc", "docker-init")]
    return {"schemaVersion": 1, "policy": "policy", "imageId": _IMAGE,
            "snapshotSha256": "c" * 64,
            "snapshotManifest": [{"path": "motion/index.html", "sizeBytes": 1,
                                  "sha256": "d" * 64}],
            "outputSha256": hashlib.sha256(media).hexdigest(),
            "imageAttestation": {"Id": _IMAGE,
                                 "Config": {"Entrypoint": ["/entrypoint"], "Labels": {
                                     "io.project-sniper.hyperframes-version": "0.7.33"}}},
            "containerBeforeOutput": container,
            "containerAfterOutput": container,
            "containerRemoval": {"canonicalAbsenceProved": True},
            "dockerRuntime": {
                "server": {"Version": "1", "ApiVersion": "1", "Os": "linux",
                           "Arch": "arm64", "KernelVersion": "kernel",
                           "Components": components},
                "runtime": {"OSType": "linux", "KernelVersion": "kernel",
                            "Driver": "overlayfs", "CgroupDriver": "cgroupfs",
                            "CgroupVersion": "2", "DefaultRuntime": "runc",
                            "SecurityOptions": []}},
            "activeNetworkProof": {"hostDecoyPositive": True,
                                   "container": {"ownLoopback": {"ok": True},
                                   "hostLoopbackDecoy": denied,
                                   "externalIpv4": denied, "externalIpv6": denied,
                                   "dns": {"resolved": False, "error": "EAI_AGAIN"}}}}


def _proof(path: str, media: bytes) -> dict:
    sidecar = path + ".proof.json"
    Path(sidecar).write_text(json.dumps({"asset": {"sha256": "old"}}))
    return {"asset": {"sha256": hashlib.sha256(media).hexdigest()},
            "sidecar": sidecar}


class RuntimeReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch(
            "headless.runtime_receipt.verify_snapshot_archive",
            return_value={"sha256": "c" * 64, "members": ("motion/index.html",)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_exact_pre_post_receipt_is_embedded_in_asset_proof(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            media = b"exact-media"
            path = os.path.join(root, "render.mov")
            Path(path).write_bytes(media)
            write_runtime_receipt(path, _receipt(media))
            bound = bind_runtime_receipt(path, _proof(path, media))
            persisted = json.loads(Path(path + ".proof.json").read_text())
            self.assertEqual(bound["runtimeAttestation"]["imageId"], _IMAGE)
            self.assertEqual(persisted["runtimeAttestation"]["outputSha256"],
                             hashlib.sha256(media).hexdigest())
            self.assertNotIn("sidecar", persisted)

    def test_bound_proof_validates_in_memory_before_any_json_round_trip(self) -> None:
        """The opening worker validates the bound proof directly; a tuple of archive
        members must not read as a different archive than the sidecar's list."""
        from headless.runtime_receipt import validate_runtime_attestation
        with tempfile.TemporaryDirectory() as root:
            media = b"exact-media"
            path = os.path.join(root, "render.mov")
            Path(path).write_bytes(media)
            write_runtime_receipt(path, _receipt(media))
            bound = bind_runtime_receipt(path, _proof(path, media))
            retained = bound["runtimeAttestation"]["retainedInputArchive"]
            self.assertEqual(retained["members"], ["motion/index.html"])
            validate_runtime_attestation(bound["runtimeAttestation"], path,
                                         hashlib.sha256(media).hexdigest(), _IMAGE)
            persisted = json.loads(Path(path + ".proof.json").read_text())
            validate_runtime_attestation(persisted["runtimeAttestation"], path,
                                         hashlib.sha256(media).hexdigest(), _IMAGE)

    def test_receipt_for_different_media_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "render.mov")
            Path(path).write_bytes(b"new-media")
            write_runtime_receipt(path, _receipt(b"old-media"))
            with self.assertRaisesRegex(RuntimeError, "not bound"):
                bind_runtime_receipt(path, _proof(path, b"new-media"))

    def test_stored_network_policy_mutation_is_rejected_offline(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path, media = os.path.join(root, "render.mov"), b"media"
            Path(path).write_bytes(media)
            receipt = _receipt(media)
            receipt["containerAfterOutput"]["HostConfig"]["NetworkMode"] = "host"
            write_runtime_receipt(path, receipt)
            with self.assertRaisesRegex(RuntimeError, "offline (container|host) policy"):
                bind_runtime_receipt(path, _proof(path, media))

    def test_symlink_receipt_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "render.mov")
            Path(path).write_bytes(b"media")
            target = os.path.join(root, "target.json")
            Path(target).write_text(json.dumps(_receipt(b"media")))
            os.symlink(target, path + ".runtime.json")
            with self.assertRaises(OSError):
                bind_runtime_receipt(path, _proof(path, b"media"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
