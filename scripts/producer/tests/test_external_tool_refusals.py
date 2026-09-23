"""Reference features refuse clearly, with the exact install command, when their
external program is absent — exercised through the production entry points with
a PATH that has neither tesseract nor yt-dlp (as on a clean Mac)."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

PRODUCER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER))

from study import fetch_reference, study_deep  # noqa: E402


class MissingToolTests(unittest.TestCase):
    """Each case runs with PATH pointing at an empty folder."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="sniper-no-tools-"))
        self.empty_bin = self.tmp / "bin"
        self.empty_bin.mkdir()
        patcher = mock.patch.dict(os.environ, {"PATH": str(self.empty_bin)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_study_refuses_before_any_work_without_tesseract(self) -> None:
        out_dir, video = self.tmp / "study", self.tmp / "ref.mp4"
        video.write_bytes(b"never decoded")
        buffer = io.StringIO()
        with mock.patch.object(sys, "argv", ["study_deep.py", str(video), str(out_dir)]), \
                mock.patch.object(study_deep, "run_deep") as work, redirect_stdout(buffer):
            self.assertEqual(study_deep.main(), 1)
        work.assert_not_called()
        self.assertIn("run install/install.command", buffer.getvalue())
        self.assertFalse(out_dir.exists(), "the study started work before refusing")

    def test_study_cli_reports_the_refusal_as_its_error_event(self) -> None:
        video = self.tmp / "ref.mp4"
        video.write_bytes(b"not decoded: the refusal comes first")
        done = subprocess.run([sys.executable, str(PRODUCER / "study/study_deep.py"), str(video),
                               str(self.tmp / "out")], capture_output=True, text=True, timeout=120,
                              env={"PATH": str(self.empty_bin), "HOME": str(self.tmp)}, check=False)
        events = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
        self.assertEqual(done.returncode, 1)
        self.assertTrue(any("run install/install.command" in str(e.get("error", "")) for e in events), done.stdout)

    def test_reference_url_refuses_without_ytdlp(self) -> None:
        buffer = io.StringIO()
        with mock.patch.object(fetch_reference, "YTDLP_FALLBACKS", ()), redirect_stdout(buffer):
            code = fetch_reference.fetch("https://www.youtube.com/watch?v=abcdefghijk",
                                         str(self.tmp / "ref"), "chrome")
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.startswith("{")]
        self.assertEqual(code, 1)
        self.assertTrue(any(e.get("event") == "error" and "run install/install.command" in e.get("message", "")
                            for e in events), buffer.getvalue())
        self.assertFalse((self.tmp / "ref").exists(), "the fetch created output before refusing")


if __name__ == "__main__":
    unittest.main()
