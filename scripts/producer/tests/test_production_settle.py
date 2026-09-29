"""The export watchdog settles its task once (fix round of units A3/A4), and the exporter entries it runs.

In process against a private authority: the watchdog's settlement (``process_settle.settle``) from
exact evidence only, the acknowledgement deadline with a TEST sleeper child this test starts, the
exporter entry that only supervises, and ``resume_final_qc.py`` under the same watchdog. No render,
host or real exporter runs here.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from _budget_fixture import CHILD, table, task_spec
from test_production_tasks import BATCH, TaskCase
from studio import native_budget_binding as binding
from studio import native_budget_launch as launch
from studio.native_budget_clock import allocation, start_anchor
from studio.production import api, process, process_group, process_watch
from studio.production.claims import ClaimRef
from studio.production.process import ExportLaunch, TaskClaim
from studio.production.process_settle import STOP_REQUESTED, UNACKNOWLEDGED, Ending, settle
from studio.production.process_watch import DEADLINE, ExportWatch, OutputRelay
from studio.production.reconcile import Observation
from studio.production.task_schema import holds_slot

REQUEST_SHA = 'e' * 64
IDENTITY = {key: CHILD[key] for key in ('pid', 'pgid', 'started')}
SURVIVOR = {'type': 'process', 'pid': 7301, 'pgid': 7301, 'started': 'Sun Sep 27 09:10:00 2026'}


class SettlementTests(TaskCase):
    """One locked settlement after the group is gone: exact evidence, the watchdog's reason, nothing else."""

    def setUp(self) -> None:
        super().setUp()
        self.enqueue(task_spec('draft', 'media'))
        claimed = self.claim('draft')
        self.ref = ClaimRef('draft', claimed['epoch'], claimed['token'])
        self.claimed = TaskClaim(BATCH, 'draft', claimed['epoch'], claimed['token'], REQUEST_SHA)

    def attach(self) -> None:
        api.attach_task(self.root, BATCH, self.ref, CHILD)

    def reserve(self) -> dict:
        """The acknowledged child's one launch of this task (TEST fingerprint check bypassed: A3 claims)."""
        with mock.patch.object(binding, 'own_identity', return_value=IDENTITY), \
                mock.patch.object(launch, 'own_identity', return_value=IDENTITY), \
                mock.patch.object(launch, '_process_table', return_value=table(CHILD)), \
                mock.patch('studio.native_budget_binding.launch_fingerprint', return_value=self.task('draft')[
                    'inputFingerprint']):
            return binding.reserve_task_launch(binding.TaskLaunch(self.project, self.work / 'out', 'draft', {}, BATCH,
                                                                  self.ref, REQUEST_SHA))

    def settle(self, reason: tuple | None = None, survivors: tuple = (), refusal: str | None = None) -> dict:
        return settle(self.claimed, Ending(CHILD['pid'], reason, survivors, refusal))

    def test_an_unacknowledged_claim_fails_and_nothing_ran(self) -> None:
        settle(self.claimed, Ending(7002, None, (), None))
        task = self.task('draft')
        self.assertEqual((task['state'], task['failure']['category'], task['endConfirmed']),
                         ('failed', UNACKNOWLEDGED, True))

    def test_a_stop_of_an_unacknowledged_claim_is_cancelled(self) -> None:
        # Probe p11 / minor 8: a cancel of a claim no child acknowledged ends cancelled, once, in the watchdog.
        api.request_cancel(self.root, BATCH, 'draft', 'operator stop')
        self.assertEqual(self.state('draft'), 'cancel-requested')
        settle(self.claimed, Ending(7002, (STOP_REQUESTED, 'TEST stop'), (), None))
        self.assertEqual((self.state('draft'), self.task('draft')['failure']), ('cancelled', None))
        self.assertFalse(settle(self.claimed, Ending(7002, None, (), None))['settled'])

    def test_a_child_that_could_not_start_fails_its_task(self) -> None:
        settle(self.claimed, Ending(None, ('export-spawn-failed', 'TEST exec failure'), (), None))
        self.assertEqual(self.task('draft')['failure']['category'], 'export-spawn-failed')

    def test_a_deadline_stop_fails_the_task_and_its_launch_with_the_watchdogs_category(self) -> None:
        # Probe p5 / minor 8: the watchdog's reason wins over whatever the interrupted exporter recorded.
        self.attach()
        attempt = self.reserve()['attemptId']
        self.settle((DEADLINE, 'TEST past the grant'))
        task, row = self.task('draft'), self.record()['clips']['A']['attempts'][-1]
        self.assertEqual((task['state'], task['failure']), ('failed', {'category': DEADLINE,
                                                                       'detail': 'TEST past the grant'}))
        self.assertEqual((row['id'], row['status'], row['failure']['category']), (attempt, 'failed', DEADLINE))
        self.assertTrue(task['endConfirmed'])
        self.assertEqual(self.record()['clips']['A']['counters']['exportAttempt'], 1)

    def test_a_requested_stop_of_a_running_launch_is_cancelled(self) -> None:
        self.attach()
        self.reserve()
        api.request_cancel(self.root, BATCH, 'draft', 'operator stop')
        self.settle((STOP_REQUESTED, 'TEST'))
        self.assertEqual(self.state('draft'), 'cancelled')
        self.assertEqual(self.record()['clips']['A']['attempts'][-1]['status'], 'failed')

    def test_completion_comes_only_from_the_authoritys_delivery_row(self) -> None:
        # Probe p1 (BLOCKER 1): a delivery.json in the attempt folder is never evidence; no bound attempt, no receipt.
        self.attach()
        output = self.work / 'out'
        output.mkdir()
        stale = {'status': 'native-short-review-draft', 'output': '/TEST/older/review-draft.mp4', 'sha256': 'ab' * 32}
        (output / 'delivery.json').write_text(json.dumps(stale))
        self.settle()
        task = self.task('draft')
        self.assertEqual((task['state'], task['receipts'], task['failure']['category']),
                         ('failed', [], 'export-exited-without-outcome'))

    def test_the_exporters_recorded_delivery_completes_the_task(self) -> None:
        self.attach()
        grant = self.reserve()
        binding.record_request_outcome({'productionBudget': grant}, {
            'status': 'native-short-review-draft', 'output': '/TEST/out/review-draft.mp4', 'sha256': 'a' * 64})
        self.settle()
        task = self.task('draft')
        self.assertEqual((task['state'], task['receipts'][0]['path'], task['endConfirmed']),
                         ('completed', '/TEST/out/review-draft.mp4', True))

    def test_a_refused_reservation_fails_with_the_childs_reason(self) -> None:
        self.attach()
        self.settle(refusal='BudgetRefused: TEST forecast')
        self.assertEqual(self.task('draft')['failure'], {'category': 'launch-refused',
                                                         'detail': 'BudgetRefused: TEST forecast'})

    def test_survivors_keep_the_slot_until_they_are_gone(self) -> None:
        # Probe p10 (major 4): processes that outlived the group kill hold the slot as owners; reconcile
        # settles once they are gone, never before.
        self.attach()
        self.reserve()
        self.settle((DEADLINE, 'TEST past the grant'), (SURVIVOR,))
        task = self.task('draft')
        # P0 adapt (M-030): survivors leave the task abandoned and unresolved as their owner (process_settle.py:
        # 111-133; B-8), still holding the slot.
        self.assertEqual((task['state'], task['owners'], task['endConfirmed'], holds_slot(task)),
                         ('abandoned', [SURVIVOR], False, True))
        with mock.patch('studio.production.api.current_observation', return_value=Observation(table(SURVIVOR))), \
                mock.patch('studio.production.api.reconcile_running', return_value=[]):
            api.reconcile(self.root, BATCH)
        self.assertTrue(holds_slot(self.task('draft')))
        with mock.patch('studio.production.api.current_observation', return_value=Observation(table())), \
                mock.patch('studio.production.api.reconcile_running', return_value=[]):
            api.reconcile(self.root, BATCH)
        task = self.task('draft')
        # P0 adapt (M-030): once the survivors are gone the slot is released; the watchdog's deadline stop had
        # superseded the task (B-8), and its launch keeps the deadline category (process_settle.py:124-133).
        self.assertEqual((task['state'], holds_slot(task), task['unresolved']), ('superseded', False, False))
        self.assertEqual(self.record()['clips']['A']['attempts'][-1]['failure']['category'], DEADLINE)

    def test_a_settled_or_foreign_task_is_left_alone(self) -> None:
        self.attach()
        self.assertFalse(settle(self.claimed, Ending(9999, (DEADLINE, 'TEST'), (), None))['settled'])
        self.assertEqual(self.state('draft'), 'running')

    def test_the_acknowledgement_deadline_stops_a_silent_child(self) -> None:
        # Probe p7 (major 6): no acknowledgement ACK_SECONDS after the start; the watchdog stops the child,
        # ends its group and only then fails the task (the slot frees after the confirmed end).
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: child.poll() is None and (child.kill() or child.wait()))
        directory = self.work / 'claim'
        directory.mkdir()
        watch = ExportWatch(self.claimed, directory, allocation(start_anchor(), 3600.0, 0.0), time.monotonic(),
                            time.time())
        with mock.patch.object(process_watch, 'ACK_SECONDS', 0.5), mock.patch.object(process, 'POLL_SECONDS', 0.1), \
                mock.patch.object(process, 'STOP_GRACE_SECONDS', 2.0), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            relay = OutputRelay(child)
            reason = process_watch.watch_child(child, watch, process._Stops(), relay)
            self.assertTrue(holds_slot(self.task('draft')))
            survivors = process_group.end_group(child, directory, watch.since)
            relay.drain()
        self.assertEqual((reason[0], survivors), (UNACKNOWLEDGED, []))
        settle(self.claimed, Ending(child.pid, reason, tuple(survivors), None))
        task = self.task('draft')
        self.assertEqual((task['state'], task['failure']['category'], holds_slot(task)),
                         ('failed', UNACKNOWLEDGED, False))


class ExporterEntryTests(TaskCase):
    """The public entry only supervises; the supervised child alone exports and never settles its task."""

    def arguments(self) -> list[str]:
        return [str(self.project), str(self.work / 'out'), '--review-draft']

    def claimed(self) -> TaskClaim:
        self.enqueue(task_spec('draft', 'media'))
        claimed = self.claim('draft')
        return TaskClaim(BATCH, 'draft', claimed['epoch'], claimed['token'], REQUEST_SHA)

    def test_the_parsing_process_only_supervises(self) -> None:
        from studio import native_short_export as export
        with mock.patch.object(sys, 'argv', ['native_short_export.py', *self.arguments()]), \
                mock.patch.object(process_watch, 'supervise_export', return_value=0) as supervise, \
                mock.patch.object(export, 'execute', side_effect=AssertionError('the parent never exports')), \
                self.assertRaises(SystemExit) as exited:
            export.main()
        self.assertEqual(exited.exception.code, 0)
        supervise.assert_called_once_with(ExportLaunch(tuple(self.arguments()), self.project))

    def test_a_forged_claim_is_refused_before_any_work(self) -> None:
        from studio import native_short_export as export
        out = io.StringIO()
        with mock.patch.object(sys, 'argv', ['native_short_export.py', *self.arguments()]), \
                mock.patch.dict(os.environ, {process.CLAIM_ENV: '/nonexistent/claim.json'}), \
                mock.patch.object(export, 'execute', side_effect=AssertionError('no work')), \
                contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as exited:
            export.main()
        self.assertEqual(exited.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())['status'], 'refused-supervision')

    def test_the_child_acknowledges_before_any_preparation_and_never_settles(self) -> None:
        from studio import native_short_export as export
        task, seen = self.claimed(), []
        with mock.patch.object(export, 'execute', side_effect=lambda args, claim: seen.append(
                (self.state('draft'), self.task('draft')['handle'] == process.own_process())) or False), \
                mock.patch.object(process_watch, 'supervise_export', side_effect=AssertionError('never wraps twice')), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(export.run_supervised(export.parser().parse_args(self.arguments()), task))
        self.assertEqual(seen, [('running', True)])
        self.assertEqual((self.state('draft'), self.task('draft')['failure']), ('running', None))   # watchdog settles

    def test_a_stop_requested_before_the_acknowledgement_runs_nothing(self) -> None:
        from studio import native_short_export as export
        task = self.claimed()
        api.request_cancel(self.root, BATCH, 'draft', 'operator stopped it')
        with mock.patch.object(export, 'execute', side_effect=AssertionError('nothing runs')):
            self.assertFalse(export.run_supervised(export.parser().parse_args(self.arguments()), task))
        self.assertEqual(self.state('draft'), 'cancel-requested')
        settle(task, Ending(os.getpid(), None, (), None))
        self.assertEqual(self.state('draft'), 'cancelled')

    def test_read_only_inspection_is_not_supervised_and_exports_are(self) -> None:
        from studio import native_export
        out = io.StringIO()
        with mock.patch.object(sys, 'argv', ['native_export.py', 'source-input', str(self.project)]), \
                mock.patch('graphics.visual_source_project.describe_project', return_value={'TEST': True}), \
                mock.patch.object(process_watch, 'supervise_export', side_effect=AssertionError('inspection')), \
                contextlib.redirect_stdout(out):
            native_export.main()
        self.assertEqual(json.loads(out.getvalue()), {'TEST': True})
        with mock.patch.object(sys, 'argv', ['native_export.py', *self.arguments()]), \
                mock.patch.object(process_watch, 'supervise_export', return_value=3) as supervise, \
                self.assertRaises(SystemExit) as exited:
            native_export.main()
        self.assertEqual(exited.exception.code, 3)
        self.assertEqual(supervise.call_args.args[0].arguments, tuple(self.arguments()))

    def test_resume_final_qc_runs_under_the_watchdog(self) -> None:
        # Plausible 14: the legacy command is a declared one-output run through the same watchdog.
        from studio import resume_final_qc
        argv = ['resume_final_qc.py', str(self.work / 'render-stage.json'), str(self.work / 'capture'),
                str(self.work / 'qc-out')]
        with mock.patch.object(sys, 'argv', argv), \
                mock.patch.object(process_watch, 'supervise_export', return_value=0) as supervise, \
                mock.patch.object(resume_final_qc, 'execute', side_effect=AssertionError('the parent never runs QC')), \
                self.assertRaises(SystemExit) as exited:
            resume_final_qc.main()
        self.assertEqual(exited.exception.code, 0)
        launch_spec = supervise.call_args.args[0]
        self.assertEqual((launch_spec.arguments, launch_spec.project, launch_spec.script),
                         (tuple(argv[1:]), None, Path(resume_final_qc.__file__).resolve()))
        with mock.patch.object(sys, 'argv', argv), mock.patch.dict(os.environ, {process.CLAIM_ENV: '/nonexistent/c'}), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as refused:
            resume_final_qc.main()
        self.assertEqual(refused.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
