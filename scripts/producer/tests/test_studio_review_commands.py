"""Studio command handoff regressions; no models, media, or server launched."""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from studio import studio_review, studio_server
from studio.studio_review import ProducerPaths
from studio.studio_server import StudioServerError
from _studio_preview_startup_fixture import PreviewStartupFixture


class ManifestHandoffTests(unittest.TestCase):
    """The gated manifest must remain the manifest used by reassembly."""

    def setUp(self) -> None:
        """Build only isolated path fixtures, including shell-sensitive names."""
        temporary = tempfile.TemporaryDirectory(prefix="studio argv $() ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        producer = self.root / "producer"
        producer.mkdir()
        (self.root / "source").mkdir()
        self.paths = ProducerPaths.resolve(str(producer))
        self.workspace_manifest = self.root / "source" / "asset_manifest.json"
        self.workspace_manifest.write_text("{}")

    def _run(self, **kwargs: object) -> tuple[mock.Mock, str]:
        """Record commands, never execute the sync or assemble subprocess."""
        output = io.StringIO()
        with mock.patch.object(studio_review.subprocess, "run",
                               return_value=mock.Mock(returncode=0)) as run:
            with contextlib.redirect_stdout(output):
                self.assertEqual(studio_review.cmd_sync(self.paths, **kwargs), 0)
        return run, output.getvalue()

    def test_workspace_manifest_reaches_both_workers(self) -> None:
        """Standard producer/source layout cannot lose manifest on rebuild."""
        run, _ = self._run(apply=True, assemble=True)
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            args = call.args[0]
            self.assertEqual(args[args.index("--manifest") + 1], str(self.workspace_manifest))

    def test_explicit_manifest_beats_beside_and_workspace_on_rebuild(self) -> None:
        """Neither discovery location may replace an explicit override."""
        Path(self.paths.manifest).write_text("{}")
        override = self.root / "override's manifest.json"
        override.write_text("{}")
        run, _ = self._run(apply=True, assemble=True, manifest=str(override))
        for call in run.call_args_list:
            args = call.args[0]
            self.assertEqual(args[args.index("--manifest") + 1], str(override))

    def test_printed_followup_preserves_override_as_safe_argv(self) -> None:
        """Copy/paste must not expand shell syntax in workspace paths."""
        override = self.root / "override's manifest.json"
        override.write_text("{}")
        _, output = self._run(apply=True, manifest=str(override))
        args = shlex.split(output.splitlines()[-1].strip())
        self.assertEqual(args[2:5], [self.paths.base, self.paths.plan, self.paths.final])
        self.assertEqual(args[args.index("--manifest") + 1], str(override))

    def test_assemble_without_apply_rejects_before_spawn(self) -> None:
        """An explicit rebuild request must not silently become dry-run."""
        with mock.patch.object(studio_review.subprocess, "run") as run:
            with self.assertRaisesRegex(StudioServerError, "--apply"):
                studio_review.cmd_sync(self.paths, assemble=True)
        run.assert_not_called()

    def test_missing_explicit_manifest_does_not_fall_back(self) -> None:
        """A typo cannot silently choose a different source authority."""
        with mock.patch.object(studio_review.subprocess, "run") as run:
            with self.assertRaisesRegex(StudioServerError, "manifest"):
                studio_review.cmd_sync(self.paths, manifest=str(self.root / "absent.json"))
        run.assert_not_called()

    def test_failed_sync_never_rebuilds(self) -> None:
        """Gate failure must propagate unchanged without running assembly."""
        with mock.patch.object(studio_review.subprocess, "run",
                               return_value=mock.Mock(returncode=2)) as run:
            code = studio_review.cmd_sync(self.paths, apply=True, assemble=True)
        self.assertEqual(code, 2)
        self.assertEqual(run.call_count, 1)

    def test_missing_base_guidance_uses_workspace_manifest(self) -> None:
        """Recommend smart dispatch without replacing an existing final."""
        message = studio_review._base_missing_message(self.paths)
        command = next(line.strip() for line in message.splitlines() if line.startswith("  "))
        args = shlex.split(command)
        self.assertEqual(args[args.index("--manifest") + 1], str(self.workspace_manifest))
        self.assertNotIn("&&", message)


class PreviewStartupTests(PreviewStartupFixture):
    """Actual log/record I/O with an explicit inert Popen and original fake clock."""

    def test_original_foreground_pid_and_space_path_are_recorded_only_when_ready(self) -> None:
        """Require SDK foreground ownership instead of persisting its launcher PID."""
        record = self._launch()
        self.assertEqual((record.pid, record.port), (45678, 3990))
        self.assertEqual(studio_server.read_record(str(self.studio)), record)
        self.assertIn("--foreground", self.argv)
        self.assertIn("--json", self.argv)
        self.assertEqual(self.options["cwd"], str(self.studio))
        self.assertEqual(self.options["env"]["HYPERFRAMES_PREVIEW_HOST"], "127.0.0.1")
        self.process.terminate.assert_not_called()

    def test_exact_installed_tool_and_no_download_environment(self) -> None:
        """Override only required local pins while retaining unrelated caller env."""
        with mock.patch.dict(os.environ, {"TEST_STUDIO_EXTRA": "kept", "DO_NOT_TRACK": "0"}):
            self._launch()
        self.assertEqual(self.argv[0], self.tools["node"])
        env = self.options["env"]
        for key in ("HYPERFRAMES_BROWSER_PATH", "PRODUCER_HEADLESS_SHELL_PATH",
                    "HYPERFRAMES_FFMPEG_PATH", "HYPERFRAMES_FFPROBE_PATH"):
            self.assertEqual(env[key], str(self.cli))
        for key in ("HYPERFRAMES_NO_UPDATE_CHECK", "HYPERFRAMES_NO_AUTO_INSTALL",
                    "HYPERFRAMES_NO_TELEMETRY", "DO_NOT_TRACK"):
            self.assertEqual(env[key], "1")
        self.assertEqual(env["TEST_STUDIO_EXTRA"], "kept")
        self.assertEqual(env["SNIPER_NODE_PATH"], str(self.node))
        self.assertTrue(studio_server.command_is_preview(" ".join(self.argv), str(self.studio), 3990))

    def test_missing_cached_browser_and_resolver_failure_prevent_spawn(self) -> None:
        """A stale memo or unavailable installed tool must not reach SDK fallback."""
        self.tools["browser"] = str(self.root / "absent-browser")
        self._refused("browser", stopped=False)
        self.assertFalse(hasattr(self, "argv"))
        with mock.patch.object(studio_server, "resolve_tools", side_effect=RuntimeError("TEST missing browser")), \
                mock.patch.object(studio_server.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "TEST missing browser"):
                studio_server.launch_preview(str(self.cli), str(self.studio), 3990)
        spawn.assert_not_called()

    def _unsupported_node(self, path: Path) -> None:
        """An executable that cannot retain ps ownership must never reach Popen."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("TEST unsupported node pin; never executed")
        path.chmod(0o700)
        self.tools["node"] = str(path)
        with mock.patch.object(studio_server, "resolve_tools", return_value=self.tools), \
                mock.patch.object(studio_server.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(StudioServerError, "Node pin"):
                studio_server.launch_preview(str(self.cli), str(self.studio), 3990)
        spawn.assert_not_called()
        self.assertIsNone(studio_server.read_record(str(self.studio)))

    def test_unsupported_node_names_and_whitespace_paths_prevent_spawn(self) -> None:
        """Custom names, spaces and other whitespace cannot create an unowned child."""
        for relative in ("custom-node", "space path/node", "tab\tpath/node"):
            with self.subTest(relative=relative):
                self._unsupported_node(self.root / relative)

    def test_context_uses_exact_local_argv_and_environment(self) -> None:
        """The ordinary context command shares preview's installed-only pins."""
        paths = ProducerPaths.resolve(str(self.root))
        record = studio_server.ServerRecord(3990, 45678, "TEST", "TEST")
        done = mock.Mock(returncode=0, stdout="{}", stderr="")
        with mock.patch.object(studio_review, "read_record", return_value=record), \
                mock.patch.object(studio_review, "is_live_preview", return_value=True), \
                mock.patch.object(studio_server, "resolve_tools", return_value=self.tools), \
                mock.patch.object(studio_review.subprocess, "run", return_value=done) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            node, env = studio_server.local_sdk_environment()
            self.assertEqual(studio_review.cmd_context(paths, "selection,lint"), 0)
        run.assert_called_once_with([node, studio_review.HYPERFRAMES_BIN, "preview", "--context",
            "--json", "--port", "3990", "--context-fields", "selection,lint"],
            cwd=paths.studio_dir, capture_output=True, text=True, check=False, env=env)

    def test_runtime_override_refuses_startup_and_context_before_sdk_spawn(self) -> None:
        """Neither command may load an inherited remote or project runtime."""
        paths = ProducerPaths.resolve(str(self.root))
        record = studio_server.ServerRecord(3990, 45678, "TEST", "TEST")
        for value in ("https://TEST.invalid/runtime.js", " /api/projects/studio/preview/runtime.js \t"):
            with mock.patch.dict(os.environ, {"HYPERFRAME_RUNTIME_URL": value}), \
                    mock.patch.object(studio_review, "read_record", return_value=record), \
                    mock.patch.object(studio_review, "is_live_preview", return_value=True), \
                    mock.patch.object(studio_server, "resolve_tools", return_value=self.tools), \
                    mock.patch.object(studio_server.subprocess, "Popen") as spawn, \
                    mock.patch.object(studio_review.subprocess, "run") as run:
                self.assertRaisesRegex(StudioServerError, "unset HYPERFRAME_RUNTIME_URL",
                    studio_server.launch_preview, str(self.cli), str(self.studio), 3990)
                self.assertRaisesRegex(StudioServerError, "unset HYPERFRAME_RUNTIME_URL",
                    studio_review.cmd_context, paths)
                spawn.assert_not_called()
                run.assert_not_called()
            self.assertFalse(self.log.exists())
            self.assertIsNone(studio_server.read_record(str(self.studio)))

    def test_empty_runtime_override_preserves_upstream_default_and_unrelated_env(self) -> None:
        """Empty and trimmed-empty settings retain the installed runtime path."""
        for value in ("", " \t\n "):
            with mock.patch.dict(os.environ, {"HYPERFRAME_RUNTIME_URL": value, "TEST_STUDIO_EXTRA": "kept"}):
                self._launch()
            self.assertEqual(self.options["env"]["HYPERFRAME_RUNTIME_URL"], value)
            self.assertEqual(self.options["env"]["TEST_STUDIO_EXTRA"], "kept")
            self.assertEqual(self.argv[0], self.tools["node"])

    def test_stale_existing_ready_log_is_not_new_startup_evidence(self) -> None:
        """Even matching old PID/project/port bytes precede this launch's offset."""
        self.log.parent.mkdir()
        self.log.write_bytes(self.payload)
        self.payload = b""
        self._refused("deadline")

    def test_complete_line_can_arrive_in_multiple_bounded_reads(self) -> None:
        """Do not confuse a split stdout write with malformed completed JSON."""
        self.payload, self.partial = self.payload[:45], self.payload[45:]
        self.assertEqual(self._launch().pid, 45678)

    def test_bad_oversize_truncated_or_absent_readiness_never_records(self) -> None:
        """Keep malformed, missing and failed SDK startup distinct from success."""
        cases = (b'{"operation":]\n', b"x" * 65_537, self.payload[:-1], b"",
                 b'{"schemaVersion":1,"operation":"start","ok":false,"error":{}}\n')
        for payload in cases:
            self.process.reset_mock()
            self.payload, self.now = payload, 0.0
            with self.subTest(payload=payload[:25]):
                self._refused("startup|deadline|bound|Expecting")

    def test_fallback_reuse_or_foreign_identity_is_refused(self) -> None:
        """Never record requested port/PID when the SDK reports something else."""
        cases = (dict(port=3991), dict(pid=99999), dict(projectDir=str(self.root)),
                 dict(state="reused"), dict(mode="background"), dict(host="0.0.0.0"),
                 dict(port=3990.0), dict(pid=45678.0), dict(ready=1))
        for change in cases:
            self.process.reset_mock()
            self.payload = self._ready(**change)
            with self.subTest(change=change):
                self._refused("foreign|reused")

    def test_early_exit_does_not_publish_or_kill_another_pid(self) -> None:
        """A returned Popen is not server readiness, even when stale bytes exist."""
        self.process.poll.return_value = 1
        self._refused("exited", stopped=False)

    def test_read_and_cleanup_share_original_deadline(self) -> None:
        """TERM wait and KILL wait consume the reserved tail, never a new budget."""
        self.payload = b""
        waits = []
        def wait(timeout: float) -> int:
            """Model exactly the elapsed wait requested of the owned TEST child."""
            waits.append(timeout)
            self.now += timeout
            if len(waits) == 1:
                raise subprocess.TimeoutExpired("TEST child", timeout)
            return 0
        self.process.wait.side_effect = wait
        self._refused("deadline")
        self.assertEqual(len(waits), 2)
        self.assertAlmostEqual(self.now, 10.0)
        self.process.kill.assert_called_once()

    def test_slow_original_read_cannot_turn_late_ready_bytes_into_success(self) -> None:
        """Charge the original metadata read before interpreting the ready row."""
        original = os.pread
        def slow(fd: int, size: int, offset: int) -> bytes:
            """Read only the exact TEST log descriptor before consuming its time."""
            self.assertEqual(fd, self.descriptor)
            data = original(fd, size, offset)
            self.now = 8.0
            return data
        with mock.patch.object(studio_server.os, "pread", side_effect=slow):
            self._refused("deadline")

    def test_stop_identity_refuses_sibling_prefix_and_accepts_spaces(self) -> None:
        """An exact path boundary prevents signaling another project's preview."""
        argv = f"node /TEST/hyperframes/cli.js preview {self.studio} --port 3990 --foreground --json"
        self.assertTrue(studio_server.command_is_preview(argv, str(self.studio), 3990))
        sibling = argv.replace(str(self.studio), str(self.studio) + "-sibling")
        self.assertFalse(studio_server.command_is_preview(sibling, str(self.studio), 3990))
        self.assertFalse(studio_server.command_is_preview("echo " + argv, str(self.studio), 3990))

    def test_late_record_publication_is_removed_and_original_child_stopped(self) -> None:
        """A completed file write cannot refund the original startup deadline."""
        original = studio_server.write_record
        def slow(directory: str, record: studio_server.ServerRecord) -> None:
            """Touch only this launch's exact original TEST record before expiry."""
            self.assertEqual(directory, str(self.studio))
            original(directory, record)
            self.now = 8.0
        with mock.patch.object(studio_server, "write_record", side_effect=slow):
            self._refused("deadline")
if __name__ == "__main__":
    unittest.main()
