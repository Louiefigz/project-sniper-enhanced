"""studio_review tests — the operator orchestrator for the Studio lane.

Unit surface only (no live server, no ffmpeg): port picking, server-record
round-trip + parking, preview-process identity, the base-missing error path,
status/next-action logic, and the sync passthrough wiring (subprocess
mocked). Server behavior itself is exercised by the empirical acceptance
run, not here.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import sys
import tempfile
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403

from studio import studio_review, studio_server
from studio.studio_review import ProducerPaths
from studio.studio_server import ServerRecord, StudioServerError
from studio.view_manifest import MANIFEST_NAME


def _record(port: int = 3990, pid: int = 12345) -> ServerRecord:
    return ServerRecord(port=port, pid=pid,
                        url=f"http://localhost:{port}/#project/studio",
                        started_at="2026-08-27T00:00:00+00:00")


def _seal_manifest(studio_dir: str, files: dict | None = None) -> None:
    """A historical V1 view, clean when nothing else is on disk."""
    os.makedirs(studio_dir, exist_ok=True)
    with open(os.path.join(studio_dir, MANIFEST_NAME), "w",
              encoding="utf-8") as handle:
        json.dump({"generator": "studio-project-v1", "files": files or {},
                   "media": {}, "entries": []}, handle)


class PortPickTests(unittest.TestCase):
    def test_skips_occupied_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(("127.0.0.1", 0))
            port = busy.getsockname()[1]
            picked = studio_server.pick_free_port((port, port + 1))
        self.assertEqual(picked, port + 1)

    def test_exhausted_range_fails(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(("127.0.0.1", 0))
            port = busy.getsockname()[1]
            with self.assertRaises(StudioServerError):
                studio_server.pick_free_port((port, port))


class ServerRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="sniper-review-test-")
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def test_round_trip(self) -> None:
        studio_server.write_record(self.dir, _record())
        loaded = studio_server.read_record(self.dir)
        self.assertEqual(loaded, _record())
        studio_server.remove_record(self.dir)
        self.assertIsNone(studio_server.read_record(self.dir))

    def test_missing_reads_none_and_remove_is_idempotent(self) -> None:
        self.assertIsNone(studio_server.read_record(self.dir))
        studio_server.remove_record(self.dir)

    def test_malformed_record_fails_loudly(self) -> None:
        with open(studio_server.record_path(self.dir), "w",
                  encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(StudioServerError):
            studio_server.read_record(self.dir)

    def test_parked_record_removes_then_restores(self) -> None:
        studio_server.write_record(self.dir, _record())
        with studio_server.parked_record(self.dir) as parked:
            self.assertEqual(parked, _record())
            self.assertIsNone(studio_server.read_record(self.dir))
        self.assertEqual(studio_server.read_record(self.dir), _record())

    def test_parked_record_without_record_is_noop(self) -> None:
        with studio_server.parked_record(self.dir) as parked:
            self.assertIsNone(parked)
        self.assertIsNone(studio_server.read_record(self.dir))


class PreviewIdentityTests(unittest.TestCase):
    _OURS = ("node /repo/templates/motion/node_modules/hyperframes/dist/"
             "cli.js preview /p/studio --port 3990")

    def test_command_is_preview(self) -> None:
        self.assertTrue(studio_server.command_is_preview(
            self._OURS, "/p/studio", 3990))
        self.assertFalse(studio_server.command_is_preview(
            "vim notes.txt", "/p/studio", 3990))

    def test_identity_requires_our_dir_and_port(self) -> None:
        # BUG-6 regression: marker words alone must not read as ours.
        self.assertFalse(studio_server.command_is_preview(
            self._OURS, "/OTHER/studio", 3990))     # another project
        self.assertFalse(studio_server.command_is_preview(
            self._OURS, "/p/studio", 3991))         # different port
        self.assertFalse(studio_server.command_is_preview(
            "tail -f /Users/me/logs/hyperframes/preview-server.log",
            "/p/studio", 3990))                     # log tail, not a server
        self.assertFalse(studio_server.command_is_preview(
            "node cli.js preview /p/studio --port 39901",
            "/p/studio", 3990))                     # port must match exactly

    def test_live_check_rejects_foreign_and_dead_pids(self) -> None:
        ours = _record(pid=os.getpid())     # a python process, not a preview
        self.assertFalse(studio_server.is_live_preview("/p/studio", ours))
        dead = _record(pid=2 ** 22 + 1)
        self.assertFalse(studio_server.is_live_preview("/p/studio", dead))


class _ProducerDirCase(unittest.TestCase):
    """Shared temp producer dir + captured-stdout helper."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="sniper-review-test-")
        self.addCleanup(self.tmp.cleanup)
        self.paths = ProducerPaths.resolve(self.tmp.name)
        stop = mock.patch.object(studio_review, 'stop_preview')
        stop.start()
        self.addCleanup(stop.stop)

    def _touch(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("x")

    def _status_output(self) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(studio_review.cmd_status(self.paths), 0)
        return out.getvalue()


class BaseMissingTests(_ProducerDirCase):
    def test_open_without_plan_names_the_plan(self) -> None:
        with self.assertRaises(StudioServerError) as caught:
            studio_review.cmd_open(self.paths)
        self.assertIn("edit_plan.json", str(caught.exception))

    def test_open_without_base_prints_the_render_commands(self) -> None:
        self._touch(self.paths.plan)
        with self.assertRaises(StudioServerError) as caught:
            studio_review.cmd_open(self.paths)
        message = str(caught.exception)
        self.assertIn("--skip-graphics", message)
        self.assertIn("base_final.mp4", message)
        self.assertIn("--auto-base", message)


class StatusLogicTests(_ProducerDirCase):
    def test_missing_plan_then_base_then_open(self) -> None:
        self.assertIn("author edit_plan.json", self._status_output())
        self._touch(self.paths.plan)
        self.assertIn("--skip-graphics", self._status_output())
        self._touch(self.paths.base)
        self.assertIn(f"open {self.paths.root}", self._status_output())

    def test_unsynced_edits_route_to_sync(self) -> None:
        self._touch(self.paths.plan)
        self._touch(self.paths.base)
        _seal_manifest(self.paths.studio_dir)
        self.assertIn("--auto-base", self._status_output())  # clean, no server
        _seal_manifest(self.paths.studio_dir, files={"index.html": "0" * 64})
        self._touch(os.path.join(self.paths.studio_dir, "index.html"))
        output = self._status_output()
        self.assertIn("1 unsynced", output)
        self.assertIn("sync", output)

    def test_additions_only_route_to_review_not_sync(self) -> None:
        self._touch(self.paths.plan)
        self._touch(self.paths.base)
        _seal_manifest(self.paths.studio_dir)
        self._touch(os.path.join(self.paths.studio_dir, "installed-comp.html"))
        output = self._status_output()
        self.assertIn("additions", output)   # sync can never adopt these
        self.assertIn("--force", output)

    def test_server_record_is_not_an_unsynced_edit(self) -> None:
        self._touch(self.paths.plan)
        self._touch(self.paths.base)
        _seal_manifest(self.paths.studio_dir)
        studio_server.write_record(self.paths.studio_dir, _record())
        self.assertIn("0 unsynced", self._status_output())


class OpenFlowTests(_ProducerDirCase):
    def setUp(self) -> None:
        super().setUp()
        self._touch(self.paths.plan)
        self._touch(self.paths.base)

    def test_unsynced_edits_refuse_without_force(self) -> None:
        _seal_manifest(self.paths.studio_dir)
        self._touch(os.path.join(self.paths.studio_dir, "studio-edit.html"))
        with mock.patch.object(studio_review, "generate_project") as generate:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(studio_review.cmd_open(self.paths), 2)
        generate.assert_not_called()
        self.assertIn("--force", err.getvalue())

    def test_generates_then_launches(self) -> None:
        result = {"status": "generated", "entries": 3, "tracks": 2,
                  "exitClamped": 1}
        with mock.patch.object(studio_review, "generate_project",
                               return_value=result) as generate, \
                mock.patch.object(studio_review, "open_preview",
                                  return_value=_record(port=3993)) as launch:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(studio_review.cmd_open(self.paths), 0)
        request = generate.call_args[0][0]
        self.assertEqual(request.out_dir, self.paths.studio_dir)
        self.assertFalse(request.force)
        launch.assert_called_once_with(self.paths.studio_dir)
        self.assertIn("http://localhost:3993/#project/studio", out.getvalue())

    def test_existing_server_is_resolved_through_shared_manager(self) -> None:
        result = {"status": "generated", "entries": 1, "tracks": 1,
                  "exitClamped": 0}
        os.makedirs(self.paths.studio_dir, exist_ok=True)
        studio_server.write_record(self.paths.studio_dir, _record())
        with mock.patch.object(studio_review, "generate_project",
                               return_value=result), \
                mock.patch.object(studio_review, "open_preview", return_value=_record()) as managed:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(studio_review.cmd_open(self.paths), 0)
        managed.assert_called_once_with(self.paths.studio_dir)
        self.assertIn("studio:", out.getvalue())


class StopTests(_ProducerDirCase):
    def test_stop_without_record_is_a_noop(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(studio_review.cmd_stop(self.paths), 0)
        self.assertIn("stale local pointer cleared", out.getvalue())

    def test_stop_refuses_to_kill_a_foreign_pid(self) -> None:
        os.makedirs(self.paths.studio_dir, exist_ok=True)
        studio_server.write_record(self.paths.studio_dir,
                                   _record(pid=os.getpid()))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(studio_review.cmd_stop(self.paths), 0)
        self.assertIn("stale local pointer cleared", out.getvalue())
        self.assertIsNone(studio_server.read_record(self.paths.studio_dir))

    def test_stop_does_not_forget_a_live_unmanaged_preview(self) -> None:
        """An old local pointer alone cannot bypass the managed identity registry."""
        os.makedirs(self.paths.studio_dir, exist_ok=True)
        record = _record(pid=2 ** 22 + 3)
        studio_server.write_record(self.paths.studio_dir, record)
        with mock.patch.object(studio_review, 'is_live_preview', return_value=True):
            with self.assertRaisesRegex(StudioServerError, 'outside the managed registry'):
                studio_review.cmd_stop(self.paths)
        self.assertEqual(studio_server.read_record(self.paths.studio_dir), record)


class ContextTests(_ProducerDirCase):
    def test_context_requires_a_live_server(self) -> None:
        with self.assertRaises(StudioServerError):
            studio_review.cmd_context(self.paths)

    def test_context_runs_bridge_from_inside_the_project(self) -> None:
        os.makedirs(self.paths.studio_dir, exist_ok=True)
        studio_server.write_record(self.paths.studio_dir, _record(port=3991))
        done = mock.Mock(returncode=0, stdout="{}", stderr="")
        with mock.patch.object(studio_review, "is_live_preview",
                               return_value=True), \
                mock.patch.object(studio_review.subprocess, "run",
                                  return_value=done) as run:
            code = studio_review.cmd_context(self.paths,
                                             fields="selection,lint")
        self.assertEqual(code, 0)
        args, kwargs = run.call_args
        self.assertEqual(args[0][2:], ["preview", "--context", "--json",
                                       "--port", "3991",
                                       "--context-fields", "selection,lint"])
        self.assertEqual(kwargs["cwd"], self.paths.studio_dir)


class SyncTests(_ProducerDirCase):
    def test_missing_sync_module_fails_loudly(self) -> None:
        with mock.patch.object(studio_review, "SYNC_CLI",
                               os.path.join(self.paths.root, "absent.py")):
            with self.assertRaises(StudioServerError):
                studio_review.cmd_sync(self.paths)

    def test_apply_passes_through_then_prints_assemble(self) -> None:
        sync_cli = os.path.join(self.paths.root, "studio_sync.py")
        self._touch(sync_cli)
        done = mock.Mock(returncode=0)
        with mock.patch.object(studio_review, "SYNC_CLI", sync_cli), \
                mock.patch.object(studio_review.subprocess, "run",
                                  return_value=done) as run:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = studio_review.cmd_sync(self.paths, apply=True)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args[0][0],
                         [sys.executable, sync_cli, self.paths.studio_dir,
                          "--apply"])
        self.assertIn("--auto-base", out.getvalue())

    def test_apply_with_assemble_chains_the_re_render(self) -> None:
        sync_cli = os.path.join(self.paths.root, "studio_sync.py")
        self._touch(sync_cli)
        done = mock.Mock(returncode=0)
        with mock.patch.object(studio_review, "SYNC_CLI", sync_cli), \
                mock.patch.object(studio_review.subprocess, "run",
                                  return_value=done) as run:
            code = studio_review.cmd_sync(self.paths, apply=True,
                                          assemble=True)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 2)
        assemble_args = run.call_args_list[1][0][0]
        self.assertIn("--auto-base", assemble_args)
        self.assertEqual(assemble_args[2:5],
                         [self.paths.base, self.paths.plan, self.paths.final])

    def _sync_args(self, paths: ProducerPaths, **kwargs) -> list:
        """The argv cmd_sync hands to studio_sync (subprocess mocked)."""
        sync_cli = os.path.join(self.paths.root, "studio_sync.py")
        self._touch(sync_cli)
        done = mock.Mock(returncode=0)
        with mock.patch.object(studio_review, "SYNC_CLI", sync_cli), \
                mock.patch.object(studio_review.subprocess, "run",
                                  return_value=done) as run:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    studio_review.cmd_sync(paths, **kwargs), 0)
        return run.call_args_list[0][0][0]

    def test_sync_forwards_the_workspace_source_manifest(self) -> None:
        """Producer-dir layout: asset_manifest.json lives at
        <project_root>/source/ — cmd_sync must locate and forward it, or
        apply is impossible on the standard layout."""
        producer = os.path.join(self.paths.root, "producer")
        source = os.path.join(self.paths.root, "source")
        os.makedirs(producer)
        os.makedirs(source)
        manifest = os.path.join(source, "asset_manifest.json")
        self._touch(manifest)
        args = self._sync_args(ProducerPaths.resolve(producer), apply=True)
        self.assertIn("--manifest", args)
        self.assertEqual(args[args.index("--manifest") + 1], manifest)

    def test_sync_manifest_beside_the_plan_wins(self) -> None:
        producer = os.path.join(self.paths.root, "producer")
        source = os.path.join(self.paths.root, "source")
        os.makedirs(producer)
        os.makedirs(source)
        self._touch(os.path.join(source, "asset_manifest.json"))
        beside = os.path.join(producer, "asset_manifest.json")
        self._touch(beside)
        args = self._sync_args(ProducerPaths.resolve(producer))
        self.assertEqual(args[args.index("--manifest") + 1], beside)

    def test_sync_explicit_manifest_flag_overrides(self) -> None:
        override = os.path.join(self.paths.root, "elsewhere.json")
        self._touch(override)
        args = self._sync_args(self.paths, manifest=override)
        self.assertEqual(args[args.index("--manifest") + 1], override)

    def test_dry_run_never_chains_assemble(self) -> None:
        sync_cli = os.path.join(self.paths.root, "studio_sync.py")
        self._touch(sync_cli)
        done = mock.Mock(returncode=0)
        with mock.patch.object(studio_review, "SYNC_CLI", sync_cli), \
                mock.patch.object(studio_review.subprocess, "run",
                                  return_value=done) as run:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = studio_review.cmd_sync(self.paths)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 1)
        self.assertNotIn("--apply", run.call_args[0][0])
        self.assertNotIn("--auto-base", out.getvalue())


if __name__ == "__main__":
    unittest.main()
