"""Real tiny process groups only; no transcription, models, media or network."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS))

import local_asr_worker as worker
from producer.headless.process_runner import ProcessDeadlineError, ProcessRequest, run_text


def _environment() -> dict[str, str]:
    """Minimal deterministic child environment; no model or provider controls."""
    return {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(SCRIPTS),
            "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}


def _request(root: str, script: str, timeout: float = 5) -> ProcessRequest:
    """One bounded live parent-owned Python group."""
    return ProcessRequest((sys.executable, "-c", script), "", root,
                          _environment(), timeout, 0.3, 1024 * 1024)


def _leaf(root: str, action: str) -> str:
    """Record exact TEST pids, including a TERM-resistant same-group descendant."""
    child = "import time; time.sleep(30)"
    return ("import json,os,signal,subprocess,sys,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}],stdin=subprocess.DEVNULL,"
        "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        f"Path({str(Path(root) / 'leaf.json')!r}).write_text(json.dumps("
        "{'leaf':os.getpid(),'descendant':p.pid,'group':os.getpgrp()})); " + action)


def _script(root: str, action: str, leaf_timeout: float = 3) -> str:
    """Exercise the exact explicit worker context and actual shared leaf adapter."""
    return f"""
import os,sys
from pathlib import Path
from local_asr_worker import run_local_asr_leaf,use_local_asr_worker_group
from producer.headless.process_runner import ProcessRequest
Path({str(Path(root) / 'worker.pid')!r}).write_text(str(os.getpid()))
with use_local_asr_worker_group():
    request=ProcessRequest((sys.executable,'-c',{_leaf(root, action)!r}),'',
        {root!r},dict(os.environ),{leaf_timeout!r},0.2,4096)
    result=run_local_asr_leaf(request)
    print('leaf-return',result.returncode)
"""


def _assert_absent(test: unittest.TestCase, pid: int, group: bool = False) -> None:
    """Observe only exact TEST-owned IDs; remove a leaking fixture before failing."""
    observe = os.killpg if group else os.kill
    for _ in range(100):
        try:
            observe(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.01)
    observe(pid, signal.SIGKILL)
    test.fail(f"TEST owned {'group' if group else 'pid'} {pid} survived parent return")


def _assert_group_closed(test: unittest.TestCase, root: str) -> None:
    """The leaf and its descendant must share the now-absent outer worker group."""
    pid = int(Path(root, "worker.pid").read_text())
    rows = json.loads(Path(root, "leaf.json").read_text())
    test.assertEqual(rows["group"], pid)
    _assert_absent(test, pid, True)
    for key in ("leaf", "descendant"):
        _assert_absent(test, rows[key])


def _enter_scope() -> None:
    """Exercise context entry without exceeding the tests' control-depth bound."""
    with worker.use_local_asr_worker_group():
        pass


class LocalAsrWorkerTests(unittest.TestCase):
    """Private opt-in, terminal cleanup and unchanged ordinary default behavior."""

    def test_default_and_ambient_environment_delegate_to_ordinary_runner(self) -> None:
        """An env flag alone cannot enable shared process ownership."""
        request = _request(tempfile.gettempdir(), "pass")
        expected = subprocess.CompletedProcess(request.command, 0, "ok", "")
        with patch.dict(os.environ, {"SNIPER_LOCAL_ASR_OWNED_WORKER": "1"}), \
                patch.object(worker, "run_text", return_value=expected) as run:
            self.assertIs(worker.run_local_asr_leaf(request), expected)
        run.assert_called_once_with(request)

    def test_non_leader_cannot_enter_private_mode(self) -> None:
        """Reject before spawning when the caller is not its own session leader."""
        with patch.object(worker.os, "getpid", return_value=50), \
                patch.object(worker.os, "getpgrp", return_value=51), \
                patch.object(worker.os, "getsid", return_value=50):
            with self.assertRaisesRegex(RuntimeError, "session and group leader"):
                _enter_scope()

    def test_nested_inherited_and_unbounded_modes_fail_before_spawn(self) -> None:
        """Context authority is exact, non-nesting and bounded-output only."""
        request = _request(tempfile.gettempdir(), "pass")
        with patch.object(worker, "_worker_identity", return_value=50), \
                patch.object(worker.subprocess, "Popen") as spawn:
            with worker.use_local_asr_worker_group():
                self._reject_private_modes(request)
            spawn.assert_not_called()

    def _reject_private_modes(self, request: ProcessRequest) -> None:
        """Apply malformed mode requests within the already-entered TEST context."""
        with self.assertRaisesRegex(RuntimeError, "cannot be nested"):
            with worker.use_local_asr_worker_group():
                self.fail("nested context entered")
        with patch.object(worker, "_worker_identity", return_value=51):
            with self.assertRaisesRegex(RuntimeError, "ownership changed"):
                worker.run_local_asr_leaf(request)
        unbounded = ProcessRequest(request.command, "", request.cwd, request.environment, 1)
        with self.assertRaisesRegex(RuntimeError, "bounded output"):
            worker.run_local_asr_leaf(unbounded)

    def test_outer_timeout_removes_term_resistant_leaf_and_descendant(self) -> None:
        """Hard parent cancellation owns the entire shared group, not a guessed PID."""
        with tempfile.TemporaryDirectory(prefix="sniper-asr-outer-timeout-") as root:
            request = _request(root, _script(root, "time.sleep(30)", 10), 0.8)
            started = time.monotonic()
            with self.assertRaises(ProcessDeadlineError):
                run_text(request)
            self.assertLess(time.monotonic() - started, 5)
            _assert_group_closed(self, root)

    def test_success_closes_descendant_that_released_stdio(self) -> None:
        """A successful transcript-shaped worker cannot leave background children."""
        with tempfile.TemporaryDirectory(prefix="sniper-asr-success-cleanup-") as root:
            result = run_text(_request(root, _script(root, "pass")))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "leaf-return 0\n")
            _assert_group_closed(self, root)

    def test_leaf_timeout_and_output_overflow_propagate_then_parent_cleans(self) -> None:
        """Terminal leaf errors never call a second provider or claim group cleanup."""
        for action in ("time.sleep(30)", "print('x'*8192,flush=True); time.sleep(30)"):
            with tempfile.TemporaryDirectory(prefix="sniper-asr-leaf-failure-") as root:
                result = run_text(_request(root, _script(root, action, 0.25)))
                self.assertNotEqual(result.returncode, 0)
                expected = "deadline" if action.startswith("time.sleep") else "output byte bound"
                self.assertIn(expected, result.stderr)
                _assert_group_closed(self, root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
