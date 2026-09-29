"""M2 regression (P0 Step 3.2; CS2-REVIEW mi1): a real child process passes the audio worker's supervisor gate.

This test process is the supervisor. It starts the gate check as its own child with the real shared binding
(``native_export.worker_environment``), then publishes the receipt a live, admitted owner writes: this process as
``supervisorPid``, the child's pid as ``pid``. The child calls ``require_owned_audio_worker`` itself, so both
``os.getppid()`` comparisons are real, not modeled. A receipt that names another supervisor is refused.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from _native_audio_stage_fixture import launch_receipt, write_json
from studio import native_audio_seal as seal
from studio import native_audio_stage as stage
from studio.native_export import BINDING_ENV, worker_environment
from test_native_audio_owner import AudioStageCase

PRODUCER = Path(__file__).resolve().parents[1]
WORKER = ('import json, sys\nfrom pathlib import Path\nsys.path[:0] = [sys.argv[1]]\n'
          'from studio.native_audio_owner import NativeOwnerRefused, require_owned_audio_worker\n'
          'print("ready", flush=True)\nsys.stdin.readline()\n'
          'try:\n    request = require_owned_audio_worker(Path(sys.argv[2]))\n'
          'except NativeOwnerRefused as error:\n    print(json.dumps({"refused": str(error)}))\n    sys.exit(2)\n'
          'print(json.dumps({"accepted": request["scope"]}))\n')


class ChildSupervisorGateTests(AudioStageCase):
    """The gate runs in an actual child of this (supervising) process."""

    def setUp(self) -> None:
        """Freeze one stage's real request and owner settings; no owner runs."""
        super().setUp()
        self.settings = stage.stage_owner_settings(self.plan())
        self.request_file, self.owner_file = Path(self.settings.command[-1]), self.settings.root / seal.OWNER_NAME

    def gate_in_child(self, **changes: object) -> tuple[int, dict]:
        """Start the child, publish the owner receipt naming it, let it run the gate; (exit status, its result)."""
        binding = {key: value for key, value in worker_environment(self.settings, self.owner_file).items()
                   if key in BINDING_ENV}
        child = subprocess.Popen([sys.executable, '-B', '-c', WORKER, str(PRODUCER), str(self.request_file)],
                                 env={**os.environ, **binding}, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        self.assertEqual(child.stdout.readline().strip(), 'ready')
        write_json(self.owner_file, launch_receipt(self.settings, pid=child.pid, productionAllocation=None, **changes))
        output, _ = child.communicate('go\n', timeout=120)
        return child.returncode, json.loads(output.strip().splitlines()[-1])

    def test_attempt_mode_worker_accepts_its_own_supervisor(self) -> None:
        """The owner receipt names this process, the child's real parent: the gate accepts the exact request."""
        scope = json.loads(self.request_file.read_text())['scope']
        self.assertEqual(self.gate_in_child(), (0, {'accepted': scope}))

    def test_a_receipt_naming_another_supervisor_is_refused(self) -> None:
        """The same child and binding, but the receipt names another supervisor: refused, exit 2."""
        status, result = self.gate_in_child(supervisorPid=os.getpid() + 1)
        self.assertEqual(status, 2, result)
        self.assertIn('names another supervisor', result['refused'])


if __name__ == '__main__':
    unittest.main()
