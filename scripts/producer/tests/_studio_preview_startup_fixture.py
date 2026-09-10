"""Inert original-process/log/clock fixture shared by Studio startup regressions."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from studio import studio_server


class PreviewStartupFixture(unittest.TestCase):
    """Own startup files and replace only explicit process and clock leaves."""

    def setUp(self) -> None:
        """Own every startup file; never launch a process or listen on a port."""
        temporary = tempfile.TemporaryDirectory(prefix="sniper-studio-startup-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.studio = self.root / "studio with spaces"
        self.studio.mkdir()
        self.cli = self.root / "hyperframes-cli.js"
        self.cli.write_text("TEST inert CLI; never executed")
        self.cli.chmod(0o700)
        self.node = self.root / "opt/bin/node"
        self.node.parent.mkdir(parents=True)
        self.node.write_text("TEST inert node; never executed")
        self.node.chmod(0o700)
        self.tools = dict.fromkeys(("node", "browser", "ffmpeg", "ffprobe"), str(self.cli))
        self.tools["node"] = str(self.node)
        self.log = self.studio / ".hyperframes/preview-server.log"
        self.process = mock.Mock(pid=45678)
        self.process.poll.return_value = None
        self.process.wait.return_value = 0
        self.now, self.partial = 0.0, b""
        self.payload = self._ready()

    def _ready(self, **changes: object) -> bytes:
        """Match the actual installed SDK's foreground lifecycle data shape."""
        result = dict(state="started", mode="foreground", projectName=self.studio.name,
                      projectDir=str(self.studio), host="127.0.0.1", port=3990,
                      pid=45678, serverUrl="http://127.0.0.1:3990",
                      studioUrl="http://127.0.0.1:3990/#project/studio%20with%20spaces", ready=True)
        result.update(changes)
        return (json.dumps(dict(schemaVersion=1, operation="start", ok=True, result=result)) + "\n").encode()

    def _spawn(self, argv: list, **options: object) -> mock.Mock:
        """Emit only TEST bytes through the exact log descriptor supplied to Popen."""
        self.argv, self.options = argv, options
        self.descriptor = options["stdout"].fileno()
        os.write(self.descriptor, self.payload)
        return self.process

    def _sleep(self, delay: float) -> None:
        """Advance the original clock and optionally complete one partial line."""
        self.now += delay
        if self.partial:
            os.write(self.descriptor, self.partial)
            self.partial = b""

    def _launch(self) -> studio_server.ServerRecord:
        """Keep real record/log operations and replace only process/clock leaves."""
        with mock.patch.object(studio_server.subprocess, "Popen", side_effect=self._spawn), \
                mock.patch.object(studio_server, "resolve_tools", return_value=self.tools), \
                mock.patch.object(studio_server.time, "monotonic", side_effect=lambda: self.now), \
                mock.patch.object(studio_server.time, "sleep", side_effect=self._sleep):
            return studio_server.launch_preview(str(self.cli), str(self.studio), 3990)

    def _refused(self, pattern: str, stopped: bool = True) -> None:
        """Failure cannot publish readiness or signal an unrelated process."""
        with self.assertRaisesRegex((studio_server.StudioServerError, ValueError), pattern):
            self._launch()
        self.assertIsNone(studio_server.read_record(str(self.studio)))
        self.assertEqual(self.process.terminate.call_count, int(stopped))
        self.assertLessEqual(self.now, 10.0)
