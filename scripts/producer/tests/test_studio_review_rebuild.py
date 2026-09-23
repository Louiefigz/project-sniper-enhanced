"""install/studio.command support in studio_review: the `rebuild` subcommand, and the
rebuild instruction printed after `sync --apply` naming the wrapper when run under it."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from studio import studio_review  # noqa: E402
from studio.review_commands import ProducerPaths  # noqa: E402


class RebuildCommand(unittest.TestCase):
    """What a buyer is told to run, and what `rebuild` runs."""

    def setUp(self) -> None:
        self.paths = ProducerPaths(root="/work/demo/producer")

    def test_without_the_wrapper_the_assemble_command_is_printed(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SNIPER_STUDIO_COMMAND", None)
            with mock.patch.object(studio_review, "_assemble_args", return_value=["py", "assemble.py"]):
                self.assertEqual(studio_review._rebuild_command(self.paths, None), ["py", "assemble.py"])

    def test_under_the_wrapper_the_wrapper_rebuild_is_printed(self) -> None:
        with mock.patch.dict(os.environ, {"SNIPER_STUDIO_COMMAND": "/pkg/install/studio.command"}):
            self.assertEqual(studio_review._rebuild_command(self.paths, "/m.json"),
                             ["/pkg/install/studio.command", "rebuild", "/work/demo/producer", "--manifest", "/m.json"])

    def test_rebuild_runs_the_same_assemble_command_sync_would(self) -> None:
        with mock.patch.object(ProducerPaths, "resolve", return_value=self.paths), \
                mock.patch.object(studio_review, "resolve_manifest", return_value="/m.json") as manifest, \
                mock.patch.object(studio_review, "_assemble_args", return_value=["py", "assemble.py"]) as assemble, \
                mock.patch.object(studio_review.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertEqual(studio_review.main(["rebuild", "/work/demo/producer", "--manifest", "/m.json"]), 0)
        manifest.assert_called_once_with(self.paths, "/m.json")
        assemble.assert_called_once_with(self.paths, "/m.json")
        self.assertEqual(run.call_args.args[0], ["py", "assemble.py"])


if __name__ == "__main__":
    unittest.main()
