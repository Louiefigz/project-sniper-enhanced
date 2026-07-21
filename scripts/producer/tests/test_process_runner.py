"""Owned process-group deadline and descendant-reap regressions."""
from __future__ import annotations

import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path

from _common import pl  # noqa: F401
from headless.process_runner import ProcessDeadlineError, ProcessRequest, run_text


def _environment() -> dict[str, str]:
    return {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin", "TZ": "UTC"}


def _exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _assert_gone(test: unittest.TestCase, pid: int, message: str) -> None:
    for _ in range(100):
        if not _exists(pid):
            return
        time.sleep(0.01)
    if _exists(pid):
        os.kill(pid, signal.SIGKILL)
        test.fail(message)


class ProcessRunnerTests(unittest.TestCase):
    def test_success_returns_exact_text_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            request = ProcessRequest(
                (sys.executable, "-c",
                 "import sys; data=sys.stdin.read(); print(data.upper())"),
                "closed input", root, _environment(), 5)
            result = run_text(request)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "CLOSED INPUT\n")

    def test_timeout_reaps_descendant_that_ignores_term(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            pid_path = str(Path(root) / "descendant.pid")
            descendant = "import time; time.sleep(30)"
            parent = (
                "import os,subprocess,sys,time; "
                f"p=subprocess.Popen([sys.executable,'-c',{descendant!r}]); "
                f"h=open({pid_path!r},'w'); h.write(str(p.pid)); h.flush(); "
                "os.fsync(h.fileno()); h.close(); time.sleep(30)")
            request = ProcessRequest(
                (sys.executable, "-c", parent), "", root, _environment(),
                0.2, termination_grace_seconds=0.2)
            with self.assertRaises(ProcessDeadlineError):
                run_text(request)
            pid = int(Path(pid_path).read_text())
            _assert_gone(self, pid, "deadline left a descendant process alive")

    def test_success_reaps_descendant_that_closed_inherited_stdio(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            pid_path = str(Path(root) / "detached.pid")
            descendant = ("import signal,time; "
                          "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                          "time.sleep(30)")
            parent = (
                "import os,subprocess,sys; "
                f"p=subprocess.Popen([sys.executable,'-c',{descendant!r}], "
                "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
                "stderr=subprocess.DEVNULL); "
                f"h=open({pid_path!r},'w'); h.write(str(p.pid)); h.flush(); "
                "os.fsync(h.fileno()); h.close()")
            request = ProcessRequest(
                (sys.executable, "-c", parent), "", root, _environment(),
                5, termination_grace_seconds=0.2)
            result = run_text(request)
            self.assertEqual(result.returncode, 0)
            pid = int(Path(pid_path).read_text())
            _assert_gone(self, pid, "successful child left a descendant alive")


if __name__ == "__main__":
    unittest.main(verbosity=2)
