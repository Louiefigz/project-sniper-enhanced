"""The real supervisor admits, binds and supervises an actual audio worker child.

Runs the real NativeRun lifecycle (private budget root, private pool namespace, real
owner receipts, binding and log) and launches the real audio worker entry as an actual
child process of this test, writing to the owner's real log. Only resource telemetry,
the descendant registry and the child's DSP/tool resolution are TEST doubles; no FFmpeg,
media or listening happens.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _budget_fixture import private_root
from _native_pool_fixture import isolate_pool, members
from native_render_processes import ProcessRequest
from native_render_resources import GIB, parse_snapshot
from studio import native_audio_seal as seal
from studio import native_audio_stage as stage
from studio.native_audio_import import bind_audio_stage
from studio.native_budget_clock import allocation, start_anchor
from studio.native_export import AUDIO_REQUEST_ENV, OWNER_ENV
from studio.native_run import NativeRun
from studio.native_runtime import digest
from test_native_audio_owner import AudioStageCase
from test_native_render_resources import START, raw_sample

PRODUCER = Path(__file__).resolve().parents[1]
# The real worker entry, run in an actual child; only DSP and PATH tool resolution are TEST doubles.
CHILD = f'''
import sys
sys.path[:0] = [{str(PRODUCER)!r}, {str(PRODUCER / 'tests')!r}]
from unittest import mock
from _native_audio_stage_fixture import fake_prepare_dialogue
from studio import native_audio_stage as stage
with mock.patch('studio.native_short_delivery.prepare_dialogue', fake_prepare_dialogue), \\
        mock.patch.object(stage, 'require_tool_resolution'):
    sys.argv = [stage.__file__, 'worker', sys.argv[1]]
    stage.main()
'''


class SupervisedAudioStageTests(AudioStageCase):
    """The real owner admits, binds and supervises an actual worker child before sealing."""

    def setUp(self) -> None:
        """Private budget root and pool; real receipts; telemetry/registry doubles only."""
        super().setUp()
        self.pool = isolate_pool(self)
        self.enterContext(mock.patch('studio.native_budget_owner.default_root', return_value=private_root(self)))
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            self.addCleanup(signal.signal, number, signal.getsignal(number))
        snapshot = parse_snapshot(raw_sample(), ProcessRequest(), 40 * GIB)
        registry = mock.Mock(known={100: SimpleNamespace(pid=100, started=START, pgid=100)})
        registry.identities.return_value = [{'pid': 100, 'started': START, 'pgid': 100}]
        registry.cleanup.return_value = {'verified': True, 'survivors': [], 'TEST': 'child already exited'}
        self.popen = mock.Mock(side_effect=self.launch_child)
        process = SimpleNamespace(Popen=self.popen, DEVNULL=subprocess.DEVNULL, STDOUT=subprocess.STDOUT,
                                  TimeoutExpired=subprocess.TimeoutExpired)
        self.enterContext(mock.patch('studio.native_measurement_retry.read_snapshot', return_value=snapshot))
        self.enterContext(mock.patch('studio.native_run.OwnedRegistry', return_value=registry))
        self.enterContext(mock.patch('studio.native_run.subprocess', process))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.exits: list[int] = []

    def launch_child(self, args: list[str], **options: object) -> mock.Mock:
        """Run the real worker entry as an actual child of this supervisor, logging to the owner's log."""
        self.assertEqual(args[4:6], [str(Path(stage.__file__).resolve()), 'worker'])
        self.at_spawn = json.loads(Path(options['env'][OWNER_ENV]).read_text())  # what the child will read
        completed = subprocess.run([sys.executable, '-B', '-c', CHILD, args[-1]], env=options['env'],
                                   cwd=options['cwd'], stdout=options['stdout'], stderr=options['stderr'],
                                   timeout=120)
        self.exits.append(completed.returncode)
        child = mock.Mock(pid=100, returncode=completed.returncode)
        child.poll.return_value = completed.returncode
        return child

    def log_lines(self, root: Path) -> list[str]:
        """The owner log the child wrote."""
        return (root / 'audio-stage.render.log').read_text().strip().splitlines()

    def test_admitted_owner_launches_the_bound_worker_and_the_stage_is_reusable(self) -> None:
        """The real child passes the owner gate at 'preparing'; seal, discovery and binding follow."""
        plan = self.plan()
        record = stage.prepare_stage(plan)
        self.assertEqual(json.loads(self.log_lines(plan.root)[-1]), {'status': seal.STATUS_PREPARED})
        self.assertEqual((self.at_spawn['status'], 'pid' in self.at_spawn, self.at_spawn['queue']['admitted']),
                         ('preparing', False, True))
        owner = json.loads((plan.root / seal.OWNER_NAME).read_text())
        self.assertEqual((owner['supervisorPid'], owner['pool']['class'], owner['productionAllocation']),
                         (os.getpid(), 'audio', None))
        self.assertEqual(owner['additionalFilePinsBefore'][str(plan.root / seal.REQUEST_NAME)],
                         digest(plan.root / seal.REQUEST_NAME))
        self.assertEqual(record['status'], seal.SEAL_STATUS)
        self.assertEqual(seal.discover_stage(self.base, record['audioInputSha256'])[0], plan.root / seal.SEAL_NAME)
        request = {'project': str(self.f.project), 'output': str(self.base / 'final-v1'), 'tools': self.f.tools,
                   'runtime': str(self.runtime), 'audioProfile': 'native-short-v1', 'pins': {}}
        with mock.patch('studio.native_export_history.history_directory', return_value=self.base / 'history'):
            self.assertEqual(bind_audio_stage(request, None)['audioStage']['mode'], 'discovered')
        self.assertEqual(members(self.pool), [])  # the admitted member was released after verified cleanup

    def test_budgeted_owner_hands_its_inherited_deadline_to_the_worker(self) -> None:
        """Inside a budgeted export the real child re-checks the same grant on the real clocks."""
        grant = allocation(start_anchor(), 700, 45)
        plan = replace(self.plan(), export_request={'productionBudget': {'allocation': grant}})
        self.assertEqual(stage.prepare_stage(plan)['status'], seal.SEAL_STATUS, self.log_lines(plan.root))
        self.assertEqual(self.at_spawn['productionAllocation'], grant)
        owner = json.loads((plan.root / seal.OWNER_NAME).read_text())
        self.assertEqual((owner['productionAllocation'], owner['status']), (grant, seal.STATUS_PREPARED))

    def test_unbound_child_fails_the_stage_with_its_refusal_as_the_cause(self) -> None:
        """A child without the owner's binding is refused; the stage failure carries that exact reason."""
        def unbound(args: list[str], **options: object) -> mock.Mock:
            """Drop the binding the real supervisor supplied, as a direct CLI caller would have none."""
            options['env'] = {key: value for key, value in options['env'].items() if key != AUDIO_REQUEST_ENV}
            return self.launch_child(args, **options)
        self.popen.side_effect = unbound
        plan = self.plan()
        with self.assertRaises(stage.AudioStageFailure) as caught:
            stage.prepare_stage(plan)
        self.assertEqual(self.exits, [2], self.log_lines(plan.root))
        failed = json.loads((plan.root / seal.FAILED_NAME).read_text())
        self.assertEqual((caught.exception.category, failed['failureCategory'], failed['workerRefused']),
                         ('audio-owner-refused', 'audio-owner-refused', True))
        self.assertIn('no live audio-stage owner started it', failed['error'])
        self.assertIn('no live audio-stage owner started it', str(caught.exception))
        self.assertFalse((plan.root / seal.SEAL_NAME).exists() or (plan.root / seal.RESULT_NAME).exists())
        self.assertEqual(list((plan.root / 'work').iterdir()), [])

    def test_custom_wrapper_never_reaches_admission_or_launch(self) -> None:
        """A NativeRun built around another command is refused before any pool member or child."""
        settings = stage.stage_owner_settings(self.plan())
        wrapper = [sys.executable, str(self.base / 'wrapper.py'), *settings.command[4:]]
        owner = NativeRun('audio-stage', replace(settings, command=wrapper))
        self.assertFalse(owner.execute())
        self.assertIn('custom wrapper', owner.result['abortReason'])
        self.assertNotIn('pool', owner.result)
        self.popen.assert_not_called()
        self.assertEqual(members(self.pool), [])


if __name__ == '__main__':
    unittest.main()
