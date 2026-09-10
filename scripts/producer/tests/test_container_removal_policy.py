"""Exact-target, bounded-retry tests for Docker container removal."""
from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from _common import pl  # noqa: F401
from headless import container_policy as policy


def _runtime() -> policy.DockerRuntime:
    approval = policy._read_approval()
    return policy.DockerRuntime(
        "/docker", "/socket", approval["imageId"], "501:20", approval)


def _removed() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 0, "", "")


def _absent() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        [], 1, "[]\n",
        "Error response from daemon: No such container: render-name\n")


class ContainerRemovalPolicyTests(unittest.TestCase):
    def test_remove_fails_closed_when_container_remains(self) -> None:
        timeout = subprocess.TimeoutExpired("docker", 30)
        live = subprocess.CompletedProcess([], 0, "{}", "")
        results = [timeout, live] + [_removed(), live] * 9
        with mock.patch.object(
                policy.subprocess, "run", side_effect=results), \
                mock.patch.object(policy.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "remains"):
                policy.remove_container(_runtime(), "/config", "render-name")

    def test_remove_accepts_only_exact_inspect_absence(self) -> None:
        with mock.patch.object(
                policy.subprocess, "run",
                side_effect=[_removed(), _absent()]) as runner:
            receipt = policy.remove_container(
                _runtime(), "/config", "render-name")
        self.assertTrue(receipt["canonicalAbsenceProved"])
        self.assertTrue(all(
            call.args[0][-1] == "render-name"
            for call in runner.call_args_list))

    def test_remove_reissues_force_after_live_inspect(self) -> None:
        live = subprocess.CompletedProcess([], 0, "{}", "")
        with mock.patch.object(
                policy.subprocess, "run",
                side_effect=[_removed(), live, _removed(), _absent()]), \
                mock.patch.object(policy.time, "sleep"):
            policy.remove_container(_runtime(), "/config", "render-name")

    def test_remove_retries_force_and_inspect_timeouts(self) -> None:
        force_timeout = subprocess.TimeoutExpired("docker", 30)
        inspect_timeout = subprocess.TimeoutExpired("docker", 15)
        with mock.patch.object(
                policy.subprocess, "run",
                side_effect=[
                    force_timeout, inspect_timeout, _removed(), _absent(),
                ]), mock.patch.object(policy.time, "sleep"):
            receipt = policy.remove_container(
                _runtime(), "/config", "render-name")
        self.assertTrue(receipt["canonicalAbsenceProved"])

    def test_daemon_error_is_not_mistaken_for_absence(self) -> None:
        daemon_error = subprocess.CompletedProcess(
            [], 1, "", "connection lost")
        with mock.patch.object(
                policy.subprocess, "run",
                side_effect=[_removed(), daemon_error]):
            with self.assertRaisesRegex(RuntimeError, "ambiguously"):
                policy.remove_container(
                    _runtime(), "/config", "render-name")


if __name__ == "__main__":
    unittest.main(verbosity=2)
