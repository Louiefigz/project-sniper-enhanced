"""Adversarial image-attestation and container-cleanup tests."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from headless import container_live_policy as live_policy
from headless import container_policy as policy
from headless import docker_identity


def _inspect(approval: dict) -> dict:
    config = approval["config"]
    return {
        "Id": approval["imageId"], "Architecture": approval["architecture"],
        "Os": approval["os"],
        "Config": {"User": config["user"],
                   "Entrypoint": config["entrypoint"],
                   "WorkingDir": config["workingDir"],
                   "Env": config["environment"],
                   "Volumes": config["volumes"],
                   "Healthcheck": config["healthcheck"],
                   "Labels": approval["labels"]},
        "RootFS": {"Type": approval["rootfs"]["type"],
                   "Layers": approval["rootfs"]["layers"]},
    }


def _runtime() -> policy.DockerRuntime:
    approval = policy._read_approval()
    return policy.DockerRuntime("/docker", "/socket", approval["imageId"],
                                "501:20", approval)


def _expectation(runtime: policy.DockerRuntime) -> live_policy.ContainerExpectation:
    return live_policy.ContainerExpectation(
        "c" * 64, "render-name", "/sealed.tar", {"TZ": "UTC"},
        ("render", "project"))


def _live(runtime: policy.DockerRuntime) -> dict:
    expected = _expectation(runtime)
    return {
        "Id": expected.container_id, "Name": "/render-name",
        "Image": runtime.image_id,
        "State": {"Running": True, "Status": "running", "Paused": False,
                  "Restarting": False, "OOMKilled": False, "Dead": False},
        "Config": {"Image": runtime.image_id, "User": runtime.user_id,
                   "Entrypoint": runtime.approval["config"]["entrypoint"],
                   "WorkingDir": "/scratch", "Hostname": "sniper-render",
                   "StopTimeout": 10, "Cmd": list(expected.command),
                   "Labels": {**runtime.approval["labels"],
                              "io.project-sniper.render-name": expected.name},
                   "Env": runtime.approval["config"]["environment"] + ["TZ=UTC"]},
        "HostConfig": {
            "NetworkMode": "none", "ReadonlyRootfs": True,
            "Privileged": False, "CapAdd": None, "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"], "Devices": [],
            "PidsLimit": 256, "PidMode": "", "IpcMode": "private",
            "UTSMode": "", "UsernsMode": "", "CgroupnsMode": "private",
            "DeviceRequests": None, "NanoCpus": 4_000_000_000,
            "Memory": 4 * 1024 ** 3, "MemorySwap": 4 * 1024 ** 3,
            "ShmSize": 1024 ** 3, "Init": True, "AutoRemove": True,
            "PublishAllPorts": False,
            "Ulimits": [{"Name": "nofile", "Hard": 4096, "Soft": 4096}],
            "LogConfig": {"Type": "none"}, "RestartPolicy": {"Name": "no"},
            "Tmpfs": {
                "/scratch": ("rw,nosuid,nodev,noexec,size=2g,uid=501,gid=20,"
                             "mode=0700"),
                "/output": ("rw,nosuid,nodev,noexec,size=2g,uid=501,gid=20,"
                            "mode=0700")},
            "Mounts": [{"Type": "bind", "Source": "/sealed.tar",
                        "Target": "/request/render-input.tar", "ReadOnly": True}]},
        "Mounts": [{"Type": "bind", "Source": "/sealed.tar",
                    "Destination": "/request/render-input.tar", "RW": False,
                    "Propagation": "rprivate"}],
        "NetworkSettings": {"Networks": {"none": {
            "IPAddress": "", "GlobalIPv6Address": "", "Gateway": "",
            "IPv6Gateway": "", "MacAddress": ""}}, "Ports": {}},
    }


class ContainerPolicyTests(unittest.TestCase):
    def test_daemon_identity_is_probed_once_per_stable_socket_identity(self) -> None:
        prior = docker_identity._CACHE
        self.addCleanup(lambda: setattr(docker_identity, "_CACHE", prior))
        docker_identity._CACHE = None
        value = {"server": {"Version": "29"}, "runtime": {"Driver": "overlay"}}
        with mock.patch.object(docker_identity, "_identity_key",
                               return_value=("stable",)), \
                mock.patch.object(docker_identity, "_probe_identity",
                                  return_value=value) as probe:
            first = docker_identity.daemon_identity(_runtime(), "/config-a")
            first["server"]["Version"] = "mutated-copy"
            second = docker_identity.daemon_identity(_runtime(), "/config-b")
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(second["server"]["Version"], "29")

    def test_exact_approved_inspect_receipt_passes(self) -> None:
        runtime = _runtime()
        result = subprocess.CompletedProcess([], 0, json.dumps(_inspect(
            runtime.approval)), "")
        with mock.patch.object(policy.subprocess, "run", return_value=result):
            actual = policy.attest_image(runtime, "/config")
        self.assertEqual(actual["Id"], runtime.image_id)

    def test_wrong_image_facts_fail_before_render(self) -> None:
        runtime = _runtime()
        mutations = (
            ("architecture", lambda row: row.update(Architecture="amd64")),
            ("entrypoint", lambda row: row["Config"].update(Entrypoint=["/bin/sh"])),
            ("label", lambda row: row["Config"]["Labels"].update(
                {"io.project-sniper.hyperframes-version": "0.7.34"})),
            ("volumes", lambda row: row["Config"].update(Volumes={"/host": {}})),
            ("rootfs", lambda row: row["RootFS"].update(Layers=[])),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                actual = copy.deepcopy(_inspect(runtime.approval))
                mutate(actual)
                result = subprocess.CompletedProcess([], 0, json.dumps(actual), "")
                with mock.patch.object(policy.subprocess, "run", return_value=result):
                    with self.assertRaisesRegex(RuntimeError, "attestation"):
                        policy.attest_image(runtime, "/config")

    def test_live_container_exact_policy_passes(self) -> None:
        runtime = _runtime()
        result = subprocess.CompletedProcess([], 0, json.dumps(_live(runtime)), "")
        with mock.patch.object(live_policy.subprocess, "run", return_value=result):
            actual = live_policy.attest_container(runtime, "/config",
                                                  _expectation(runtime))
        self.assertTrue(actual["State"]["Running"])

    def test_live_container_security_mutations_fail(self) -> None:
        runtime = _runtime()
        mutations = (
            lambda row: row["HostConfig"].update(NetworkMode="host"),
            lambda row: row["HostConfig"].update(ReadonlyRootfs=False),
            lambda row: row["HostConfig"].update(Privileged=True),
            lambda row: row["HostConfig"].update(CapAdd=["SYS_ADMIN"]),
            lambda row: row["HostConfig"].update(SecurityOpt=[]),
            lambda row: row["HostConfig"].update(PidMode="host"),
            lambda row: row["Config"].update(User="0:0"),
            lambda row: row["Config"].update(Cmd=["shell"]),
            lambda row: row["State"].update(Running=False),
            lambda row: row["Mounts"].append(
                {"Type": "bind", "Source": "/var/run/docker.sock",
                 "Destination": "/socket", "RW": True}),
        )
        for mutate in mutations:
            actual = _live(runtime)
            mutate(actual)
            result = subprocess.CompletedProcess([], 0, json.dumps(actual), "")
            with mock.patch.object(live_policy.subprocess, "run",
                                   return_value=result):
                with self.assertRaisesRegex(RuntimeError, "live container"):
                    live_policy.attest_container(runtime, "/config",
                                                 _expectation(runtime))

    def test_operator_cannot_select_another_valid_sha256_image(self) -> None:
        old = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        os.environ.update({
            "SNIPER_DOCKER_PATH": "/usr/local/bin/docker",
            "SNIPER_RENDER_IMAGE_ID": "sha256:" + "d" * 64,
            "SNIPER_RENDER_UID_GID": "501:20",
            "SNIPER_DOCKER_SOCKET": "/missing/docker.sock",
        })
        with self.assertRaisesRegex(RuntimeError, "not the approved image"):
            policy.required_runtime()

    def test_abort_reconciliation_catches_a_late_create(self) -> None:
        times = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 4.0, 4.1]
        with mock.patch.object(policy.time, "monotonic", side_effect=times), \
                mock.patch.object(policy.time, "sleep"), \
                mock.patch.object(policy, "_force_remove",
                                  side_effect=[False, True, False]) as remove, \
                mock.patch.object(policy, "_is_absent", side_effect=[True, True, False, True, True, True]), \
                mock.patch.object(policy, "remove_container") as final_remove:
            policy.reconcile_launch_abort(_runtime(), "/config", "render-name")
        self.assertEqual(remove.call_count, 3)
        final_remove.assert_called_once()

    def test_abort_reconciliation_supports_bounded_long_launches(self) -> None:
        times = [0.0, 0.0, 0.0, 0.0, 61.0, 61.0, 61.0, 65.0, 65.0]
        with mock.patch.object(policy.time, "monotonic", side_effect=times), \
                mock.patch.object(policy.time, "sleep"), \
                mock.patch.object(
                    policy, "_force_remove",
                    side_effect=[False, True, False]) as remove, \
                mock.patch.object(policy, "_is_absent", side_effect=[True, True, False, True, True, True]), \
                mock.patch.object(policy, "remove_container") as final_remove:
            policy.reconcile_launch_abort(
                _runtime(), "/config", "render-name", 600)
        self.assertEqual(remove.call_count, 3)
        final_remove.assert_called_once()

    def test_successful_rm_of_absent_name_does_not_reset_observed_absence(self) -> None:
        times = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 4.0, 4.1]
        with mock.patch.object(policy.time, "monotonic", side_effect=times), \
                mock.patch.object(policy.time, "sleep"), \
                mock.patch.object(policy, "_force_remove", return_value=True) as remove, \
                mock.patch.object(policy, "_is_absent", return_value=True), \
                mock.patch.object(policy, "remove_container") as final_remove:
            policy.reconcile_launch_abort(_runtime(), "/config", "render-name")
        self.assertEqual(remove.call_count, 3)
        final_remove.assert_called_once()

    def test_unknown_pre_removal_presence_resets_stable_absence(self) -> None:
        times = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 4.0, 4.1]
        with mock.patch.object(policy.time, "monotonic", side_effect=times), \
                mock.patch.object(policy.time, "sleep"), \
                mock.patch.object(policy, "_force_remove", return_value=True) as remove, \
                mock.patch.object(policy, "_is_absent", side_effect=[True, True, None, True, True, True]), \
                mock.patch.object(policy, "remove_container") as final_remove:
            policy.reconcile_launch_abort(_runtime(), "/config", "render-name")
        self.assertEqual(remove.call_count, 3)
        final_remove.assert_called_once()

    def test_abort_reconciliation_rejects_unbounded_deadlines(self) -> None:
        for invalid in (0, 601, True, "600", float("inf"), float("nan")):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                    RuntimeError, "timeout is invalid"):
                policy.reconcile_launch_abort(
                    _runtime(), "/config", "render-name", invalid)

    def test_live_tmpfs_output_is_copied_only_after_zero_status(self) -> None:
        missing = subprocess.CompletedProcess([], 1, "", "missing")
        running = subprocess.CompletedProcess([], 0, "running\n", "")
        status = subprocess.CompletedProcess([], 0, "0\n", "")
        with mock.patch.object(policy.subprocess, "run",
                               side_effect=[missing, running, status]), \
                mock.patch.object(policy, "read_render_log", return_value=b"[initSession:screenshot] pollHfReady complete\n[initSession:screenshot] pollSubCompositionTimelines complete (ready)\n"), \
                mock.patch.object(policy.time, "sleep"), \
                mock.patch.object(policy, "_stream_output") as stream:
            policy.wait_and_copy(_runtime(), "/config", "render-name",
                                 "/stage/render.mov")
        stream.assert_called_once()

    def test_nonzero_render_status_rejects_output(self) -> None:
        status = subprocess.CompletedProcess([], 0, "9\n", "")
        with mock.patch.object(policy.subprocess, "run", return_value=status), \
                mock.patch.object(policy, "read_render_log", return_value=b""):
            with self.assertRaisesRegex(RuntimeError, "exited 9"):
                policy.wait_and_copy(_runtime(), "/config", "render-name",
                                     "/stage/render.mov")

    def test_exec_stream_writes_exact_bytes_without_docker_cp(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            destination = os.path.join(root, "render.mov")

            def fake_run(command, **kwargs):
                self.assertIn("exec", command)
                self.assertNotIn("cp", command)
                kwargs["stdout"].write(b"exact-media")
                return subprocess.CompletedProcess(command, 0, b"", b"")

            with mock.patch.object(policy.subprocess, "run", side_effect=fake_run):
                policy._stream_output(_runtime(), "/config", "render-name",
                                      destination)
            with open(destination, "rb") as handle:
                self.assertEqual(handle.read(), b"exact-media")

    def test_exec_stream_overrides_restrictive_umask(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            destination = os.path.join(root, "render.mov")

            def fake_run(command, **kwargs):
                kwargs["stdout"].write(b"exact-media")
                return subprocess.CompletedProcess(command, 0, b"", b"")

            previous = os.umask(0o777)
            try:
                with mock.patch.object(policy.subprocess, "run",
                                       side_effect=fake_run):
                    policy._stream_output(
                        _runtime(), "/config", "render-name", destination)
            finally:
                os.umask(previous)
            self.assertEqual(os.stat(destination).st_mode & 0o777, 0o600)
            self.assertEqual(Path(destination).read_bytes(), b"exact-media")

    def test_failed_partial_exec_stream_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            destination = os.path.join(root, "render.mov")

            def fake_run(command, **kwargs):
                kwargs["stdout"].write(b"partial")
                return subprocess.CompletedProcess(command, 9, b"", b"failed")

            with mock.patch.object(policy.subprocess, "run", side_effect=fake_run):
                with self.assertRaisesRegex(RuntimeError, "could not stream"):
                    policy._stream_output(_runtime(), "/config", "render-name",
                                          destination)
            self.assertFalse(os.path.exists(destination))


if __name__ == "__main__":
    unittest.main(verbosity=2)
