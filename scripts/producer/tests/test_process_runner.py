"""Owned process-group deadline and descendant-reap regressions."""
from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from _common import pl  # noqa: F401
from headless.process_runner import ProcessDeadlineError, ProcessRequest, run_text
from headless import process_runner


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
    def test_failed_spawn_record_reaps_the_actual_detached_child(self) -> None:
        """No append failure after fork may leave an unowned running process."""
        spawned = []
        original = process_runner._ledger_note

        def fail_spawn(event, proc, command):
            if event == "spawned":
                spawned.append(proc.pid)
                raise OSError("TEST ledger write failed after actual fork")
            return original(event, proc, command)

        with tempfile.TemporaryDirectory() as root:
            request = ProcessRequest((sys.executable, "-c", "import time; time.sleep(30)"),
                                     "", root, _environment(), 3)
            with patch.object(process_runner, "_ledger_note", side_effect=fail_spawn):
                with self.assertRaisesRegex(OSError, "after actual fork"):
                    run_text(request)
            self.assertEqual(len(spawned), 1)
            _assert_gone(self, spawned[0], "failed ledger record leaked child")

    def test_ledger_rejects_fifo_and_link_without_spawning(self) -> None:
        """Type-first nonblocking writes cannot hang at a hostile ledger path."""
        with tempfile.TemporaryDirectory() as root:
            fifo, target, link = (Path(root) / name for name in ("fifo", "target", "link"))
            os.mkfifo(fifo)
            target.write_text("unchanged")
            link.symlink_to(target)
            request = ProcessRequest((sys.executable, "-c", "raise SystemExit('must not run')"),
                                     "", root, _environment(), 3)
            for ledger in (fifo, link):
                with patch.dict(os.environ, {process_runner.LEDGER_ENV: str(ledger)}):
                    with self.assertRaises(OSError):
                        run_text(request)
            self.assertEqual(target.read_text(), "unchanged")

    def test_success_returns_exact_text_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            request = ProcessRequest(
                (sys.executable, "-c",
                 "import sys; data=sys.stdin.read(); print(data.upper())"),
                "closed input", root, _environment(), 5)
            result = run_text(request)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "CLOSED INPUT\n")

    def test_declared_ledger_records_exact_spawned_and_reaped_rows(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            ledger = os.path.join(root, "owned.jsonl")
            quick = ProcessRequest((sys.executable, "-c", "print('ok')"), "", root, _environment(), 5)
            slow = ProcessRequest((sys.executable, "-c", "import time; time.sleep(30)"), "", root,
                                  _environment(), 0.2)
            with patch.dict(os.environ, {"SNIPER_OWNED_PROCESS_LEDGER": ledger}):
                self.assertEqual(run_text(quick).returncode, 0)
                with self.assertRaises(ProcessDeadlineError):
                    run_text(slow)
            rows = [json.loads(line) for line in Path(ledger).read_text().splitlines()]
            self.assertEqual([row["event"] for row in rows],
                             ["intent", "spawned", "reaped", "intent", "spawned", "reaped"])
            self.assertIsNone(rows[0]["pid"])
            self.assertEqual(rows[1]["pid"], rows[2]["pid"])
            self.assertEqual(rows[0]["argv0"], sys.executable)
            self.assertEqual(rows[2]["returncode"], 0)
            self.assertLessEqual(rows[0]["at"], rows[1]["at"])
            self.assertLessEqual(rows[1]["at"], rows[2]["at"])
            self.assertNotEqual(rows[5]["returncode"], 0)
            self.assertEqual(os.stat(ledger).st_mode & 0o777, 0o600)
            _assert_gone(self, rows[4]["pid"], "reaped row must describe a dead process")
        with tempfile.TemporaryDirectory() as root:   # nothing is written without a declared ledger
            run_text(ProcessRequest((sys.executable, "-c", "pass"), "", root, _environment(), 5))
            self.assertEqual(os.listdir(root), [])

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
