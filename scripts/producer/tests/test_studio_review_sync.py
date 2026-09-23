"""Studio sync dispatch: source commands, apply gates and manifest handoff."""
from __future__ import annotations

import contextlib
import io
import os
import sys
from unittest import mock

from _common import *  # noqa: F401,F403
from studio import studio_review
from studio.studio_review import ProducerPaths
from studio.studio_server import StudioServerError
from test_studio_review import _ProducerDirCase


class SyncTests(_ProducerDirCase):
    """Exercise source-mode commands independently of the caller's package env."""

    def setUp(self) -> None:
        """Keep source argv expectations explicit; wrapper behavior has its own tests."""
        super().setUp()
        self.enterContext(mock.patch.dict(os.environ, {"SNIPER_STUDIO_COMMAND": ""}))

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
