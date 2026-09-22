"""Studio source and packaged followups retain the exact manifest authority."""
from __future__ import annotations

import contextlib
import io
import os
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import *  # noqa: F401,F403
from studio import studio_review
from studio.studio_review import ProducerPaths
from studio.studio_server import StudioServerError


class ManifestHandoffTests(unittest.TestCase):
    """The gated manifest must remain the manifest used by reassembly."""

    def setUp(self) -> None:
        """Build only isolated path fixtures, including shell-sensitive names."""
        self.enterContext(mock.patch.dict(os.environ, {"SNIPER_STUDIO_COMMAND": ""}))
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

    def test_packaged_followup_preserves_wrapper_and_manifest_as_safe_argv(self) -> None:
        """Package users rebuild through installed settings, even in sensitive paths."""
        wrapper = str(self.root / "package's $(literal)" / "install" / "studio.command")
        override = self.root / "override's manifest.json"
        override.write_text("{}")
        with mock.patch.dict(os.environ, {"SNIPER_STUDIO_COMMAND": wrapper}):
            _, output = self._run(apply=True, manifest=str(override))
        args = shlex.split(output.splitlines()[-1].strip())
        self.assertEqual(args, [wrapper, "rebuild", self.paths.root,
                                "--manifest", str(override)])
