"""assemble lock tests — one re-render per dir, crash-safe.

Concurrent assemble.py runs on one output dir are destructive (both write
final.mp4, --auto-base promotes over the plan). The protocol under test:
<out dir>/.assemble.lock {pid, startedAt}; a LIVE holder blocks the second
run (exit 1, loud error, holder's lock untouched); a dead-pid or unreadable
lock is stale (replaced with a warning); the acquiring run removes the lock
in its finally — on success AND on failure.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403
import assemble_lock as alock


def _sleeper(case: unittest.TestCase) -> subprocess.Popen:
    """A live placeholder process (killed + reaped on test teardown)."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    case.addCleanup(proc.wait)
    case.addCleanup(proc.kill)
    return proc


def _dead_pid() -> int:
    """A pid that is definitely not running (spawned, exited, reaped)."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


class AcquireLockTests(unittest.TestCase):
    """acquire_lock: live holder blocks; stale/unreadable locks are replaced."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lock = os.path.join(self.tmp.name, ".assemble.lock")

    def _acquire(self) -> tuple[bool, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = alock.acquire_lock(self.lock)
        return ok, buf.getvalue()

    def test_live_pid_blocks_and_holder_lock_is_untouched(self) -> None:
        holder = _sleeper(self)
        with open(self.lock, "w") as f:
            json.dump({"pid": holder.pid, "startedAt": "2026-07-09T00:00:00+00:00"}, f)
        ok, out = self._acquire()
        self.assertFalse(ok)
        self.assertIn("another re-render is already running for this dir "
                      f"(pid {holder.pid})", out)
        with open(self.lock) as f:               # never clobber a live holder
            self.assertEqual(json.load(f)["pid"], holder.pid)

    def test_stale_dead_pid_lock_is_replaced_with_warning(self) -> None:
        with open(self.lock, "w") as f:
            json.dump({"pid": _dead_pid(), "startedAt": "x"}, f)
        ok, out = self._acquire()
        self.assertTrue(ok)
        self.assertIn("stale_lock_replaced", out)
        with open(self.lock) as f:
            rec = json.load(f)
        self.assertEqual(rec["pid"], os.getpid())
        self.assertIn("startedAt", rec)

    def test_unreadable_lock_is_stale_not_a_wedge(self) -> None:
        with open(self.lock, "w") as f:
            f.write("{half-written")             # a crashed run's partial write
        ok, out = self._acquire()
        self.assertTrue(ok)
        self.assertIn("stale_lock_replaced", out)

    def test_no_lock_acquires_silently(self) -> None:
        ok, out = self._acquire()
        self.assertTrue(ok)
        self.assertNotIn("stale_lock_replaced", out)
        self.assertTrue(os.path.exists(self.lock))

    def test_racing_acquirers_yield_exactly_one_winner(self) -> None:
        """The <lock>.mutex flock closes the check-then-write race: N
        processes acquiring the same lock at once → exactly 1 True."""
        script = (
            "import sys, time, json, os\n"
            "sys.path.insert(0, sys.argv[2])\n"
            "import assemble_lock as alock\n"
            "deadline = float(sys.argv[3])\n"
            "time.sleep(max(0.0, deadline - time.time()))  # start barrier\n"
            "ok = alock.acquire_lock(sys.argv[1])\n"
            "if ok:\n"
            "    time.sleep(0.5)  # hold while the others race\n"
            "sys.exit(0 if ok else 1)\n"
        )
        import time
        pkg_dir = os.path.dirname(os.path.abspath(alock.__file__))
        deadline = str(time.time() + 0.4)
        procs = [subprocess.Popen(
                     [sys.executable, "-c", script, self.lock, pkg_dir, deadline],
                     stdout=subprocess.DEVNULL)
                 for _ in range(8)]
        winners = sum(1 for p in procs if p.wait() == 0)
        self.assertEqual(winners, 1)


class MainLockLifecycleTests(unittest.TestCase):
    """main() wiring: blocked run exits 1; owner removes on success AND failure."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        self.plan_path = os.path.join(d, "edit_plan.json")
        with open(self.plan_path, "w") as f:
            json.dump({"cutTrack": [{"sourceId": "r", "start": 0.0, "end": 2.0}],
                       "graphicsTrack": [],
                       "target": {"mode": "longform", "scope": "light"}}, f)
        with open(os.path.join(d, "project.json"), "w") as f:
            json.dump({"origin": "raw", "history": [], "resolvedIntent": {
                "mode": "longform", "scope": "light", "lanes": {}}}, f)
        self.base = os.path.join(d, "base_final.mp4")
        self.out = os.path.join(d, "final.mp4")
        self.lock = os.path.join(d, ".assemble.lock")

    def _run_main(self, plan_path: str) -> tuple[int, str]:
        argv = [
            "assemble.py", self.base, plan_path, self.out,
            "--allow-legacy-unadmitted",
        ]
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                contextlib.redirect_stdout(buf), \
                self.assertRaises(SystemExit) as ctx:
            asm.main()
        return ctx.exception.code or 0, buf.getvalue()

    def test_blocked_run_exits_1_and_leaves_holders_lock(self) -> None:
        holder = _sleeper(self)
        with open(self.lock, "w") as f:
            json.dump({"pid": holder.pid, "startedAt": "x"}, f)
        code, out = self._run_main(self.plan_path)
        self.assertEqual(code, 1)
        self.assertIn("another re-render is already running", out)
        with open(self.lock) as f:               # the holder still owns the dir
            self.assertEqual(json.load(f)["pid"], holder.pid)

    def test_lock_removed_on_failure(self) -> None:
        code, out = self._run_main(os.path.join(self.tmp.name, "missing.json"))
        self.assertEqual(code, 1)
        self.assertIn("error", out)
        self.assertFalse(os.path.exists(self.lock))

    def test_lock_held_during_run_and_removed_on_success(self) -> None:
        seen: dict = {}

        def fake_assemble(job) -> dict:
            with open(self.lock) as f:           # lock is live mid-run, ours
                seen["pid"] = json.load(f)["pid"]
            return {"mocked": True}

        argv = [
            "assemble.py", self.base, self.plan_path, self.out,
            "--allow-legacy-unadmitted",
        ]
        buf = io.StringIO()
        with mock.patch.object(asm, "assemble", new=fake_assemble), \
                mock.patch.object(sys, "argv", argv), \
                contextlib.redirect_stdout(buf):
            asm.main()
        self.assertEqual(seen["pid"], os.getpid())
        self.assertIn("done", buf.getvalue())
        self.assertFalse(os.path.exists(self.lock))


if __name__ == "__main__":
    unittest.main(verbosity=2)
