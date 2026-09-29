"""The audio-stage worker's live-owner contract: the launch binding and the worker gate.

Launch tests exercise the closed audio command/request/pin contract that
``native_export.launch_binding`` applies before pool admission. Gate tests run the real
``native_audio_stage.worker`` in-process against explicit TEST owner receipts and the real
shared binding (``_native_audio_stage_fixture.supervised``); only DSP and PATH tool
resolution are TEST doubles. The real supervised lifecycle, with an actual worker child,
is in ``test_native_audio_owner_lifecycle.py``.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _budget_fixture import FakeClock, fake_clock
from _native_audio_stage_fixture import (AudioProjectFixture, fake_prepare_dialogue, launch_receipt, supervised,
                                         write_json)
from studio import native_audio_seal as seal
from studio import native_audio_stage as stage
from studio.native_audio_owner import NativeOwnerRefused
from studio.native_budget_clock import allocation, start_anchor
from studio.native_export import (AUDIO_REQUEST_ENV, OWNER_ENV, PID_ENV, REQUEST_ENV, launch_binding,
                                  worker_environment)
from studio.native_run_config import NativeRunConfig
from studio.native_runtime import digest


class AudioStageCase(unittest.TestCase):
    """One TEST project, runtime and closed tool environment per test."""

    def setUp(self) -> None:
        """Build the project; the closed child environment carries no tools or credentials."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.f = AudioProjectFixture(self.base)
        self.runtime = self.base / 'runtime'
        (self.runtime / 'dist').mkdir(parents=True)
        (self.runtime / 'dist/cli.js').write_text('TEST CLI, never executed')
        self.enterContext(mock.patch('studio.native_run_config.local_environment', return_value=(self.f.tools, {})))

    def plan(self, name: str = 'audio-v1') -> stage.AudioStagePlan:
        """A new standalone stage beside the project."""
        return stage.AudioStagePlan(self.f.project, self.base / name, runtime=self.runtime)


class AudioLaunchContractTests(AudioStageCase):
    """Only the exact audio worker command for its own pinned request receives a binding."""

    def setUp(self) -> None:
        """Freeze one real request and its real owner settings; no owner runs."""
        super().setUp()
        self.settings = stage.stage_owner_settings(self.plan())
        self.request_file = self.settings.root / seal.REQUEST_NAME

    def test_the_stage_command_binds_only_the_audio_request(self) -> None:
        """The child gets the audio request, owner and supervisor, never an export binding."""
        self.assertEqual(launch_binding(self.settings), (AUDIO_REQUEST_ENV, self.request_file))
        inherited = {REQUEST_ENV: '/TEST/forged-export', AUDIO_REQUEST_ENV: '/TEST/forged', OWNER_ENV: '/TEST/o',
                     PID_ENV: '1', 'TEST_KEEP': '1'}
        owner = self.settings.root / seal.OWNER_NAME
        environment = worker_environment(replace(self.settings, environment=inherited), owner)
        self.assertEqual(environment, {'TEST_KEEP': '1', AUDIO_REQUEST_ENV: str(self.request_file),
                                       OWNER_ENV: str(owner), PID_ENV: str(os.getpid())})

    def test_custom_wrapper_output_lane_or_unpinned_request_is_refused(self) -> None:
        """Every deviation from the command native_audio_stage builds fails before admission."""
        command = self.settings.command
        wrapper = [sys.executable, str(self.base / 'wrapper.py'), *command[4:]]
        (self.settings.root / 'other.json').write_text('{}')
        other_output = {**self.settings.admission, 'output': str(self.settings.root / 'other.json')}
        cases = (('custom wrapper', replace(self.settings, command=wrapper)),
                 ('custom wrapper', replace(self.settings, command=command[3:])),
                 ('custom wrapper', replace(self.settings, admission=other_output)),
                 ('pool class', replace(self.settings, lane='heavy')),
                 ('unpinned', replace(self.settings, additional_pins={str(self.request_file): digest(self.request_file)})))
        for message, settings in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                launch_binding(settings)

    def test_request_symlink_or_foreign_stage_root_project_or_scope_is_refused(self) -> None:
        """The request must be this stage's own regular file naming this root, project and scope."""
        original = self.request_file.read_bytes()
        request = json.loads(original)
        for field, value in (('stageRoot', str(self.base / 'elsewhere')), ('project', str(self.base / 'other')),
                             ('scope', 'TEST-other-scope')):
            self.request_file.write_text(json.dumps({**request, field: value}))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'does not bind this stage'):
                launch_binding(self.settings)
        moved = self.base / 'moved-request.json'
        moved.write_bytes(original)
        self.request_file.unlink()
        self.request_file.symlink_to(moved)
        with self.assertRaisesRegex(ValueError, 'requires its stage-request.json'):
            launch_binding(self.settings)
        self.request_file.unlink()
        with self.assertRaisesRegex(ValueError, 'requires its stage-request.json'):
            launch_binding(self.settings)

    def test_supporting_owner_gets_no_binding(self) -> None:
        """A utility owner that does not run the audio worker is unbound, whatever it inherits."""
        output = self.base / 'utility'
        output.mkdir()
        cli, sandbox = self.runtime / 'dist/cli.js', self.settings.sandbox
        utility = NativeRunConfig(self.f.project, output, cli, ['TEST-NO-LAUNCH'], {AUDIO_REQUEST_ENV: '/TEST/x'},
                                  {'output': str(output / 'result.bin'), 'sdkSha256': digest(cli),
                                   'sandboxSha256': digest(sandbox)}, sandbox=sandbox)
        self.assertIsNone(launch_binding(utility))
        self.assertEqual(worker_environment(utility, output / 'owner.json'), {})


class AudioOwnerGateTests(AudioStageCase):
    """The real worker starts DSP only for the live, admitted owner bound to its exact request."""

    def setUp(self) -> None:
        """Freeze one stage's real request and owner settings without running any owner."""
        super().setUp()
        self.tools = self.enterContext(mock.patch.object(stage, 'require_tool_resolution'))
        self.prepare = self.enterContext(mock.patch('studio.native_short_delivery.prepare_dialogue',
                                                    side_effect=fake_prepare_dialogue))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.settings = stage.stage_owner_settings(self.plan())
        self.request_file, self.owner_file = Path(self.settings.command[-1]), self.settings.root / seal.OWNER_NAME

    def run_worker(self, receipt: dict | None, environment: dict | None = None, parent: int | None = None) -> None:
        """Publish one TEST owner receipt (None: none at all) and run the real worker under its binding."""
        if receipt is not None:
            write_json(self.owner_file, receipt)
        with supervised(self.settings, self.owner_file, environment, parent):
            stage.worker(self.request_file)

    def assert_refused(self, message: str, receipt: dict | None, environment: dict | None = None,
                       parent: int | None = None) -> None:
        """A specific refusal before any input check or DSP; the stage gains no result or failure."""
        with self.assertRaisesRegex(NativeOwnerRefused, message):
            self.run_worker(receipt, environment, parent)
        self.prepare.assert_not_called()
        self.assert_unpublished()

    def assert_unpublished(self) -> None:
        """Neither a result nor a worker failure record exists in the stage."""
        self.assertFalse((self.settings.root / seal.RESULT_NAME).exists())
        self.assertFalse((self.settings.root / seal.WORKER_FAILURE).exists())

    def test_native_run_receipt_names_its_supervisor(self) -> None:
        """M2 regression (P0): the real NativeRun owner receipt records supervisorPid = the supervising process."""
        from studio.native_run import NativeRun
        owner = NativeRun('audio-stage', self.settings)
        owner.persist(initial=True)
        receipt = json.loads(owner.path.read_text())
        self.assertEqual(receipt.get('supervisorPid'), os.getpid())

    def test_the_real_receipt_passes_the_supervisor_gate(self) -> None:
        """M2 regression (P0): the gate that requires supervisorPid == getppid() admits a real NativeRun receipt."""
        from studio.native_run import NativeRun
        owner = NativeRun('audio-stage', self.settings)
        receipt = json.loads(json.dumps(owner.result, allow_nan=False))
        self.assertEqual(receipt.get('supervisorPid'), os.getpid())
        self.assertNotIn('names another supervisor', str(receipt))

    def test_missing_owner_starts_no_dsp(self) -> None:
        """No binding at all, or a binding to an owner receipt that does not exist, is refused."""
        with mock.patch.dict('os.environ', {}, clear=True), \
                self.assertRaisesRegex(NativeOwnerRefused, 'no live audio-stage owner started it'):
            stage.worker(self.request_file)
        self.assert_refused('its owner receipt is missing', None)

    def test_wrong_owner_or_changed_request_is_refused(self) -> None:
        """Another stage's live owner, an export binding, another command or project, changed bytes."""
        other = stage.stage_owner_settings(self.plan('audio-v2'))
        foreign = other.root / seal.OWNER_NAME
        write_json(foreign, launch_receipt(other))
        live = launch_receipt(self.settings)
        self.assert_refused("not this audio stage's own", live, {OWNER_ENV: str(foreign)})
        self.assert_refused('no live audio-stage owner', live,
                            {AUDIO_REQUEST_ENV: None, REQUEST_ENV: str(self.settings.root / 'export-request.json')})
        check = [*self.settings.command[:-2], 'check', str(self.request_file)]
        for changes in ({'args': check}, {'project': str(self.base / 'other')}, {'output': str(self.owner_file)}):
            with self.subTest(changes=list(changes)):
                self.assert_refused('does not bind this exact audio request', launch_receipt(self.settings, **changes))
        write_json(self.owner_file, live)
        with supervised(self.settings, self.owner_file):  # bound and pinned, then the request changes
            request = json.loads(self.request_file.read_text())
            self.request_file.write_text(json.dumps({**request, 'workSeconds': 1}))
            with self.assertRaisesRegex(NativeOwnerRefused, 'does not bind this exact audio request'):
                stage.worker(self.request_file)
        self.prepare.assert_not_called()

    def test_command_shape_interpreter_or_request_root_mismatch_is_refused(self) -> None:
        """The receipt names the sandbox launcher, this interpreter, and a request for this very root."""
        command = list(self.settings.command)
        shapes = {'launcher': ['/usr/bin/env', *command[1:]], 'flag': [command[0], '-p', *command[2:]],
                  'interpreter': [*command[:3], str(self.base / 'TEST-python'), *command[4:]],
                  'extra argument': [*command[:4], '-B', *command[4:]]}
        for name, args in shapes.items():
            with self.subTest(shape=name):
                self.assert_refused('does not bind this exact audio request', launch_receipt(self.settings, args=args))
        original = self.request_file.read_bytes()
        for field, value in (('stageRoot', str(self.base / 'elsewhere')), ('scope', 'TEST-other-scope')):
            with self.subTest(field=field), supervised(self.settings, self.owner_file):
                self.request_file.write_text(json.dumps({**json.loads(original), field: value}))
                write_json(self.owner_file, launch_receipt(self.settings))  # the owner pinned these bytes
                self.assertRaisesRegex(NativeOwnerRefused, 'does not bind', stage.worker, self.request_file)
                self.request_file.write_bytes(original)
        self.prepare.assert_not_called()
        self.assert_unpublished()

    def test_stale_dead_or_unadmitted_owner_is_refused(self) -> None:
        """A finished, aborted, waiting or superseded owner; a dead supervisor; no admission or time."""
        stale = ({'completedAt': 'TEST', 'status': seal.STATUS_PREPARED}, {'abortReason': 'TEST cancelled'},
                 {'status': 'waiting-for-capacity'}, {'pid': os.getpid() + 1})
        unadmitted = ({'pool': None}, {'pool': {'class': 'heavy'}}, {'queue': {'admitted': False}})
        cases = [('not the active owner', row) for row in stale] + [('not admitted', row) for row in unadmitted]
        for message, changes in cases:
            with self.subTest(changes=changes):
                self.assert_refused(message, launch_receipt(self.settings, **changes))
        self.assert_refused('not alive as its parent', launch_receipt(self.settings), parent=1)
        self.assert_refused('names another supervisor', launch_receipt(self.settings, supervisorPid=os.getpid() + 1))
        undated = launch_receipt(self.settings)
        del undated['productionAllocation']
        self.assert_refused('no inherited deadline', undated)
        with fake_clock(FakeClock()) as clock:
            grant = allocation(start_anchor(), 30, 5)
            clock.advance(31)
            with self.assertRaises(NativeOwnerRefused) as caught:
                self.run_worker(launch_receipt(self.settings, productionAllocation=grant))
        self.assertIn('inherited production deadline has passed', str(caught.exception))
        self.assertEqual(caught.exception.category, 'budget-exhausted')

    def test_orphaned_worker_publishes_nothing(self) -> None:
        """A supervisor that dies before or during DSP leaves no result and no failure record."""
        def orphan(*_args: object) -> None:
            """Model the SIGKILLed supervisor: the worker is reparented to launchd."""
            os.getppid.return_value = 1
        self.tools.side_effect = orphan  # after the gate, before DSP
        self.assert_refused('not alive as its parent', launch_receipt(self.settings))
        self.tools.side_effect = None
        self.prepare.side_effect = lambda *args: (fake_prepare_dialogue(*args), orphan())[0]  # during DSP
        with self.assertRaisesRegex(NativeOwnerRefused, 'not alive as its parent'):
            self.run_worker(launch_receipt(self.settings))
        self.prepare.assert_called_once()
        self.assert_unpublished()

    def test_live_admitted_owner_runs_the_worker_once(self) -> None:
        """The legitimate owner (admitted, in time, the worker's parent) gets exactly one preparation."""
        with fake_clock(FakeClock()):
            grant = allocation(start_anchor(), 300, 5)
            self.run_worker(launch_receipt(self.settings, productionAllocation=grant))
        self.prepare.assert_called_once()
        result = json.loads((self.settings.root / seal.RESULT_NAME).read_text())
        self.assertEqual(result['status'], seal.STATUS_PREPARED)

    def test_direct_cli_worker_is_refused_with_exit_2_and_writes_nothing(self) -> None:
        """The reproduced defect: a direct ``worker`` call no longer reaches preparation."""
        script = Path(stage.__file__).resolve()
        completed = subprocess.run([sys.executable, '-B', str(script), 'worker', str(self.request_file)],
                                   capture_output=True, text=True, timeout=120, env={'PATH': '/usr/bin:/bin'})
        self.assertEqual(completed.returncode, 2, completed.stderr)
        report = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual((report['status'], report['phase'], report['category']),
                         ('refused', 'audio-stage-worker', 'audio-owner-refused'))
        self.assertIn('no live audio-stage owner started it', report['error'])
        self.assertEqual(sorted(path.name for path in self.settings.root.iterdir()), ['stage-request.json', 'work'])
        self.assertEqual(list((self.settings.root / 'work').iterdir()), [])

    def test_stage_failure_names_the_logged_refusal_and_its_category(self) -> None:
        """Exit 2 plus the worker's refusal line become the failure reason and category; nothing else does."""
        log = self.settings.root / 'audio-stage.render.log'
        line = {'status': 'refused', 'phase': 'audio-stage-worker', 'category': 'budget-exhausted',
                'error': "Native audio worker refused: its owner's inherited production deadline has passed"}
        log.write_text('TEST noise\n' + json.dumps(line) + '\n')
        owner = {'status': 'failed', 'exitCode': 2, 'logPath': str(log), 'failureCategory': 'renderer-failure'}
        with mock.patch.object(stage, 'write_new'):  # read the record without publishing three variants
            record = stage.record_failure(self.settings.root, owner)
            generic = stage.record_failure(self.settings.root, {**owner, 'exitCode': 1})
            unknown = json.dumps({**line, 'category': 'TEST-unknown'})
            log.write_text(unknown + '\n')
            unrecognized = stage.record_failure(self.settings.root, owner)
        self.assertEqual((record['error'], record['failureCategory'], record['workerRefused'], record['errorType']),
                         (line['error'], 'budget-exhausted', True, 'NativeOwnerRefused'))
        self.assertEqual(stage.AudioStageFailure(record).category, 'budget-exhausted')
        for other in (generic, unrecognized):
            self.assertEqual((other['error'], other['failureCategory'], other['workerRefused']),
                             ('audio worker failed', 'renderer-failure', False))
            self.assertEqual(stage.AudioStageFailure(other).category, 'audio-stage-failure')


if __name__ == '__main__':
    unittest.main()
