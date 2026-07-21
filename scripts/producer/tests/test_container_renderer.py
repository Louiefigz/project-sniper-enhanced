"""Contract tests for the immutable networkless renderer adapter."""
from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from _common import pl  # noqa: F401
from headless import container_renderer as cr
from headless.container_io import SealedInput
from headless.container_policy import DockerRuntime

_IMAGE = "sha256:" + "a" * 64


def _paths() -> cr.RenderPaths:
    runtime = DockerRuntime("/docker", "/docker.sock", _IMAGE, "501:20", {})
    snapshot = SealedInput("/private/render-input.tar", "b" * 64, ())
    return cr.RenderPaths(runtime, "/docker-config", snapshot,
                          "/private/copied.mov")


class _InterruptingProcess:
    returncode = None

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.killed = False

    def communicate(self, timeout: int | None = None) -> tuple[str, str]:
        if not self.killed:
            raise self.error
        return "", ""

    def kill(self) -> None:
        self.killed = True


class ContainerRendererTests(unittest.TestCase):
    def test_command_mounts_only_sealed_input_and_has_output_quota(self) -> None:
        paths = _paths()
        request = cr.RenderRequest("compositions/section-marker.html", "mov",
                                   "/final/section-marker.mov", paths.snapshot,
                                   "sniper-render-" + "d" * 32)
        command = cr._command(paths, request, "sniper-render-test")
        self.assertEqual(command[command.index("--network") + 1], "none")
        self.assertIn("--read-only", command)
        self.assertEqual(command[command.index("--user") + 1], "501:20")
        self.assertEqual(command[command.index("--cap-drop") + 1], "ALL")
        self.assertEqual(command[command.index("--pull") + 1], "never")
        self.assertEqual(command[command.index("--host") + 1],
                         "unix:///docker.sock")
        joined = "\n".join(command)
        self.assertIn("src=/private/render-input.tar", joined)
        self.assertIn("/output:rw,nosuid,nodev,noexec,size=512m", joined)
        self.assertIn("--detach", command)
        self.assertNotIn("node_modules", joined)
        self.assertNotIn("src=/pipeline", joined)
        self.assertIn("--rm", command)
        self.assertEqual(command[command.index("--log-driver") + 1], "none")
        self.assertEqual(command[command.index("--memory-swap") + 1], "4g")
        self.assertIn("io.project-sniper.render-name=sniper-render-test", command)

    def test_environment_has_no_account_or_secret_state(self) -> None:
        env = cr._container_env(_paths().snapshot)
        self.assertNotIn("HOME", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertEqual(env["TZ"], "UTC")
        self.assertEqual(env["PRODUCER_LOW_MEMORY_MODE"], "false")
        self.assertEqual(env["SNIPER_INPUT_SHA256"], "b" * 64)
        self.assertEqual(env["TMPDIR"], "/scratch")

    def test_detached_launch_requires_one_exact_container_id(self) -> None:
        value = "c" * 64
        self.assertEqual(cr._container_id(value + "\n"), value)
        for invalid in ("", "short", value + "\nwarning", "sha256:" + value):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(RuntimeError, "invalid container ID"):
                    cr._container_id(invalid)

    def test_keyboard_interrupt_reaps_client_and_removes_container(self) -> None:
        process = _InterruptingProcess(KeyboardInterrupt())
        with mock.patch.object(cr.subprocess, "Popen", return_value=process), \
                mock.patch.object(cr, "reconcile_launch_abort") as remove:
            with self.assertRaises(KeyboardInterrupt):
                cr._run(["docker"], _paths(), "sniper-render-test")
        self.assertTrue(process.killed)
        remove.assert_called_once()

    def test_timeout_reaps_client_and_removes_container(self) -> None:
        process = _InterruptingProcess(subprocess.TimeoutExpired("docker", 60))
        with mock.patch.object(cr.subprocess, "Popen", return_value=process), \
                mock.patch.object(cr, "reconcile_launch_abort") as remove:
            with self.assertRaisesRegex(RuntimeError, "launch exceeded 60s"):
                cr._run(["docker"], _paths(), "sniper-render-test")
        self.assertTrue(process.killed)
        remove.assert_called_once()

    def test_cancel_cleanup_failure_is_not_silently_ignored(self) -> None:
        process = _InterruptingProcess(KeyboardInterrupt())
        with mock.patch.object(cr.subprocess, "Popen", return_value=process), \
                mock.patch.object(cr, "reconcile_launch_abort",
                                  side_effect=RuntimeError("still present")):
            with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
                cr._run(["docker"], _paths(), "sniper-render-test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
