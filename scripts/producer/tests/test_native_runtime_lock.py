"""Render-runtime construction under the install's maintenance and build locks.

Builds the real runtime from the real patch set over a copy of the installed stock
SDK in a temporary tree, with the lock contenders played by separate processes
running ``scripts/infra/sniper_lock.py hold`` (the same helper the installer uses).
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from studio import native_runtime  # noqa: E402
from studio.native_runtime import install_runtime  # noqa: E402

import sniper_lock  # noqa: E402  (native_runtime put scripts/infra on sys.path)

LOCK_CLI = native_runtime.REPO / "scripts/infra/sniper_lock.py"
STOCK = native_runtime.REPO / "templates/motion/node_modules/hyperframes"


@unittest.skipUnless((STOCK / "dist/cli.js").is_file(), "stock HyperFrames SDK not installed")
class RuntimeLockTests(unittest.TestCase):
    """Each test gets a fresh tree holding a copy of the stock SDK."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.base = Path(tempfile.mkdtemp(prefix="sniper-runtime-lock-"))
        stock = cls.base / "seed/templates/motion/node_modules/hyperframes"
        stock.mkdir(parents=True)
        shutil.copyfile(STOCK / "package.json", stock / "package.json")
        shutil.copytree(STOCK / "dist", stock / "dist")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.base, ignore_errors=True)

    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(dir=self.base))
        shutil.copytree(self.base / "seed/templates", self.repo / "templates", copy_function=os.link)
        self.state = sniper_lock.state_dir(self.repo)
        self.holders: list[subprocess.Popen] = []
        patcher = mock.patch.dict(sniper_lock._PROCESS_HOLD, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._release_process_holds)
        os.environ.pop(sniper_lock.ENV_FD, None)

    def tearDown(self) -> None:
        for proc in self.holders:
            proc.kill()
            proc.wait()
            if proc.stdout:
                proc.stdout.close()

    def _release_process_holds(self) -> None:
        for fd in sniper_lock._PROCESS_HOLD.values():
            os.close(fd)

    def _hold(self, name: str, mode: str) -> subprocess.Popen:
        """Start a separate process holding a lock; return once it holds it."""
        proc = subprocess.Popen([sys.executable, str(LOCK_CLI), "hold", "--state-dir", str(self.state),
                                 "--name", name, "--mode", mode, "--label", f"test {name}"],
                                stdout=subprocess.PIPE, text=True)
        self.holders.append(proc)
        self.assertTrue(proc.stdout.readline().startswith("held"), "holder did not take the lock")
        return proc

    def _runtime(self) -> Path:
        _, identity = native_runtime._runtime_manifest()
        return self.repo / "templates/motion/.sniper-native-runtime" / identity

    def test_interrupted_staging_is_rebuilt_under_the_build_lock(self) -> None:
        staging = self._runtime() / "installing"
        (staging / "dist").mkdir(parents=True)
        (staging / "dist/cli.js").write_text("half-written")
        built = install_runtime(repo=self.repo)
        self.assertEqual(built, self._runtime() / "hyperframes")
        self.assertFalse(staging.exists())
        native_runtime.verify_runtime(built, native_runtime._runtime_manifest()[0])

    def test_construction_waits_for_another_builder_then_gives_up(self) -> None:
        self._hold(sniper_lock.RUNTIME_BUILD, "exclusive")
        with mock.patch.object(native_runtime, "BUILD_WAIT_SECONDS", 0.5):
            with self.assertRaises(sniper_lock.LockBusy):
                install_runtime(repo=self.repo)
        self.assertFalse((self._runtime() / "hyperframes").exists())

    def test_refuses_while_a_maintenance_step_holds_the_install(self) -> None:
        self._hold(sniper_lock.MAINTENANCE, "exclusive")
        with self.assertRaises(sniper_lock.LockBusy) as caught:
            install_runtime(repo=self.repo)
        self.assertIn("test maintenance", str(caught.exception))
        self.assertFalse(self._runtime().exists())

    def test_stale_lock_after_kill_9_does_not_block(self) -> None:
        holder = self._hold(sniper_lock.MAINTENANCE, "exclusive")
        holder.send_signal(signal.SIGKILL)
        holder.wait()
        self.assertTrue(install_runtime(repo=self.repo).is_dir())

    def test_changed_runtime_refuses_unless_repairing(self) -> None:
        built = install_runtime(repo=self.repo)
        (built / "dist/frame-source-transport.mjs").write_text("tampered")
        with self.assertRaises(ValueError):
            install_runtime(repo=self.repo)
        repaired = install_runtime(repair=True, repo=self.repo)
        native_runtime.verify_runtime(repaired, native_runtime._runtime_manifest()[0])

    def test_a_process_using_the_runtime_blocks_exclusive_maintenance(self) -> None:
        code = textwrap.dedent(f"""
            import sys, time
            sys.path.insert(0, {str(native_runtime.REPO / 'scripts/producer')!r})
            from pathlib import Path
            from studio.native_runtime import install_runtime
            install_runtime(repo=Path({str(self.repo)!r}))
            print("ready", flush=True)
            time.sleep(60)
        """)
        user = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        self.holders.append(user)
        self.assertEqual(user.stdout.readline().strip(), "ready")
        status = [sys.executable, str(LOCK_CLI), "status", "--state-dir", str(self.state)]
        busy = subprocess.run(status, capture_output=True, text=True, check=False)
        self.assertEqual(busy.returncode, 1, busy.stdout)
        self.assertIn("render runtime user", busy.stdout)
        user.kill()
        user.wait()
        time.sleep(0.2)
        self.assertEqual(subprocess.run(status, capture_output=True, check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
