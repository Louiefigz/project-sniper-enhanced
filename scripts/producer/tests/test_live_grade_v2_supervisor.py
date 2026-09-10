"""Tiny actual POSIX processes only; no grade worker, source, daemon or media."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import live_grade_v2_supervisor as supervisor


class V2SupervisorTests(unittest.TestCase):
    """Exercise pre-fork EOF/timeout and real group absence after bounded return."""

    def setUp(self) -> None:
        """Use one fresh scratch tree and actual current helper imports."""
        self.tmp = tempfile.TemporaryDirectory(prefix="TEST-v2-process-", dir="/private/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.imports = f"import sys;sys.path[:0]={sys.path!r};"

    def run_blocked(self, payload: str | None) -> subprocess.CompletedProcess:
        """Actual child cannot touch the fork marker before a complete permit."""
        marker = str(self.root / "forked")
        code = self.imports + "import os,time;from pathlib import Path;from live_grade_v2_supervisor import read_permit;" \
            + f"read_permit(os.getppid(),time.monotonic()+.12);Path({marker!r}).touch()"
        child = subprocess.Popen([sys.executable, "-B", "-c", code], start_new_session=True,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if payload is None:
            time.sleep(.2)
        stdout, stderr = child.communicate(payload or "", timeout=2)
        with self.assertRaises(ProcessLookupError):
            os.killpg(child.pid, 0)
        self.assertFalse(Path(marker).exists())
        return subprocess.CompletedProcess(child.args, child.returncode, stdout, stderr)

    def test_owner_pipe_eof_before_claim_and_after_claim(self) -> None:
        """No claim metadata can turn EOF into permission to fork later."""
        for claimed in [False, True]:
            if claimed:
                (self.root / "TEST-active.json").write_text('{"TEST":"claimed but not activated"}')
            self.assertNotEqual(self.run_blocked("").returncode, 0)

    def test_wait_timeout_and_malformed_permit(self) -> None:
        """Bounded startup failure and oversized/nonobject payload never fork."""
        for payload in [None, "[1]\n", "malformed\n", "x" * 4097]:
            self.assertNotEqual(self.run_blocked(payload).returncode, 0)

    def test_real_owner_death_before_handshake(self) -> None:
        """An actual killed parent closes the activation pipe; no delayed fork."""
        marker = str(self.root / "orphan-fork")
        leaf = self.imports + "import os,time;from pathlib import Path;from live_grade_v2_supervisor import read_permit;" \
            + f"read_permit(os.getppid(),time.monotonic()+1);Path({marker!r}).touch()"
        parent_code = "import subprocess,sys,os;" + f"p=subprocess.Popen([sys.executable,'-B','-c',{leaf!r}],stdin=subprocess.PIPE);" \
            + "print(p.pid,flush=True);os._exit(7)"
        parent = subprocess.Popen([sys.executable, "-B", "-c", parent_code], start_new_session=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        parent.communicate(timeout=3)
        self.assertEqual(parent.returncode, 7)
        self.assertFalse(Path(marker).exists())
        with self.assertRaises(ProcessLookupError):
            os.killpg(parent.pid, 0)

    def test_actual_supervisor_reaps_normal_inner_worker(self) -> None:
        """Only the outside observer tests complete process-group absence."""
        code = self.imports + "import os,time;from live_grade_v2_supervisor import supervise;" \
            + f"raise SystemExit(supervise([{sys.executable!r},'-c','print(\"TEST leaf\")'],os.getppid(),time.monotonic()+1))"
        child = subprocess.Popen([sys.executable, "-B", "-c", code], start_new_session=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = child.communicate(timeout=3)
        self.assertEqual((child.returncode, stdout.strip(), stderr), (0, "TEST leaf", ""))
        with self.assertRaises(ProcessLookupError):
            os.killpg(child.pid, 0)

    def test_term_and_cancel_resistant_child_is_reaped_by_bounded_supervisor(self) -> None:
        """The TEST shortened cleanup allowance never changes the CLI's100s cap."""
        leaf = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);signal.signal(signal.SIGUSR1,signal.SIG_IGN);time.sleep(5)"
        code = self.imports + "import os,time;from live_grade_v2_supervisor import supervise;" \
            + f"raise SystemExit(supervise([{sys.executable!r},'-c',{leaf!r}],os.getppid(),time.monotonic()+.15,.15))"
        started = time.monotonic()
        child = subprocess.Popen([sys.executable, "-B", "-c", code], start_new_session=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        child.communicate(timeout=3)
        self.assertNotEqual(child.returncode, 0)
        self.assertLess(time.monotonic() - started, 2)
        with self.assertRaises(ProcessLookupError):
            os.killpg(child.pid, 0)

    def test_owner_death_after_actual_fork_cancels_and_reaps_inner_worker(self) -> None:
        """The supervisor detects actual parent loss after a child-ready marker."""
        marker = str(self.root / "inner-ready")
        leaf = "import signal,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);" \
            + f"signal.signal(signal.SIGUSR1,lambda *_:exit(0));Path({marker!r}).touch();time.sleep(3)"
        owned = self.imports + "import os,time;from live_grade_v2_supervisor import supervise;" \
            + f"raise SystemExit(supervise([{sys.executable!r},'-c',{leaf!r}],os.getppid(),time.monotonic()+2,.3))"
        parent_code = "import subprocess,sys,os,time;from pathlib import Path;" \
            + f"p=subprocess.Popen([sys.executable,'-B','-c',{owned!r}],start_new_session=True);print(p.pid,flush=True)\n" \
            + f"while not Path({marker!r}).exists():time.sleep(.01)\nos._exit(7)"
        parent = subprocess.run([sys.executable, "-B", "-c", parent_code], capture_output=True, text=True, timeout=4)
        self.assertEqual(parent.returncode, 7)
        self.assertTrue(Path(marker).exists())
        with self.assertRaises(ProcessLookupError):
            os.killpg(int(parent.stdout.strip()), 0)


if __name__ == "__main__":
    unittest.main()
