"""Media dispatch (unit A3): the single-instance dispatcher, its claims and launches, and a detached TEST run.

In-process cases drive ``Dispatcher.step`` against a private authority with a TEST process table
and a fake ``run-media`` child; nothing real is observed or signalled. The detached cases start the
real dispatcher, ``run-media`` and export watchdog as separate processes with the TEST exporter
child of ``_dispatch_fixture`` (the real exporter entry, claim and reservation; no render).
"""
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
from unittest import mock

from _budget_fixture import CHILD, DISPATCHER, SOURCE, approval, b3_stand_in, handoff_confirmation, make_project, table
from _dispatch_fixture import PRODUCER, approval_file, launcher, media_request, tasks_file, write_exporter
from test_native_budget_registry import ns
from test_production_tasks import BATCH, TaskCase
from studio import native_budget_launch as launch
from studio import native_budget_store as store
from studio.native_budget_store import BudgetAuthorityError
from studio.production import api, cli, dispatch, media, process
from studio.production.callbacks import TaskResult
from studio.production.claims import ClaimRef
from studio.production.tasks import TaskRefused

OTHER = {'type': 'process', 'pid': 7050, 'pgid': 7050, 'started': 'Sun Sep 27 10:20:00 2026'}


class FakeChild:
    """A TEST run-media process: ``code`` None while it runs."""

    def __init__(self, pid: int, code: int | None = None) -> None:
        self.pid, self.returncode = pid, code

    def poll(self) -> int | None:
        return self.returncode


class DispatchCase(TaskCase):
    """TaskCase (batch-auth: A and B, a director) with media requests and a dispatcher of TEST identity."""

    def setUp(self) -> None:
        super().setUp()
        self.spawned: list[list[str]] = []
        self.children: list[FakeChild] = []
        self.enterContext(mock.patch.object(process, 'spawn_detached', side_effect=self.spawn))
        self.rows = table(DISPATCHER)
        self.enterContext(mock.patch.object(launch, '_process_table', side_effect=lambda: self.rows))

    def spawn(self, command: list[str], _log: Path) -> FakeChild:
        self.spawned.append(command)
        child = FakeChild(8000 + len(self.spawned))
        self.children.append(child)
        return child

    def media(self, task_id: str, clip: str = 'A', deadline: float = 1800.0, route: str = 'draft') -> None:
        """Enqueue one media task through the command, which keeps its exact request."""
        fields = {'batchId': BATCH, 'taskId': task_id, 'clipId': clip, 'route': route, 'project': str(self.project),
                  'output': str(self.work / f'out-{task_id}')}
        request = media_request(self.work, fields)
        cli.cmd_enqueue(ns(batch=BATCH, tasks=tasks_file(self.work, task_id, [
            {'taskId': task_id, 'kind': 'media', 'version': 'v1', 'deadlineElapsed': deadline,
             'mediaRequest': str(request)}])))

    def dispatcher(self, identity: dict = DISPATCHER) -> dispatch.Dispatcher:
        directory = media.batch_state(self.root, BATCH)
        return dispatch.Dispatcher(self.root, BATCH, identity, dispatch.BoundedLog(directory / 'test.log'))

    def logged(self) -> list[dict]:
        return [json.loads(line) for line in (self.root / 'dispatch' / BATCH / 'test.log').read_text().splitlines()]


class LaunchTests(DispatchCase):
    """Least deadline first, at most the pool slots, only with the exact kept request."""

    def test_the_most_urgent_media_task_launches_first_within_the_pool_slots(self) -> None:
        self.media('draft-a', 'A', 1800.0)
        self.media('draft-b', 'B', 1700.0)
        runner = self.dispatcher()
        self.assertIsNone(runner.step())
        # P0 adapt (B-19): both claims launch at once, the most urgent first; the host pool orders capacity.
        self.assertEqual([command[command.index('--task') + 1] for command in self.spawned], ['draft-b', 'draft-a'])
        self.assertEqual(self.task('draft-b')['claim']['claimer'], DISPATCHER)
        self.assertIsNone(runner.step())                                   # every clip claimed: nothing more
        self.assertEqual(len(self.spawned), 2)
        # P0 adapt (B-19, B-1): no slot waits for draft-b's completion, and an acknowledged media task completes
        # only through its export watchdog (covered by test_production_recovery and test_production_settle).

    def test_least_deadline_is_the_only_order(self) -> None:
        # Minor 13: no forecast fallback on this branch; ready media launch least task deadline first.
        self.media('draft-a', 'A', 1700.0)
        self.media('draft-b', 'B', 1800.0)
        self.assertFalse(hasattr(dispatch, 'launch_order'))
        self.dispatcher().step()
        # P0 adapt (B-19): both launch at once; least task deadline first is still the only order.
        self.assertEqual([command[command.index('--task') + 1] for command in self.spawned], ['draft-a', 'draft-b'])

    def test_a_running_launch_no_task_owns_takes_a_pool_slot(self) -> None:
        # Plausible 17: a direct public export of clip A holds the batch's one pool slot.
        exporter = {key: OTHER[key] for key in ('pid', 'pgid', 'started')}
        self.rows = table(DISPATCHER, OTHER)
        with mock.patch.object(launch, 'own_identity', return_value=exporter), \
                mock.patch('studio.native_budget_binding.own_identity', return_value=exporter):
            self.reserve(self.project)
        self.media('draft-b', 'B')
        self.assertEqual(dispatch.busy_slots(self.record()), 1)
        self.dispatcher().step()
        # P0 adapt (B-19): an untasked launch no longer holds a claim slot; the host pool bounds capacity.
        self.assertEqual((self.state('draft-b'), [c[c.index('--task') + 1] for c in self.spawned]),
                         ('claimed', ['draft-b']))

    def test_an_existing_output_directory_is_refused_at_enqueue(self) -> None:
        # Probes p1/p1b (BLOCKER 1): a request naming an existing attempt directory (a stale delivery, or the
        # previous version's output) is refused before anything is kept or claimed.
        stale = self.work / 'out-draft-a'
        stale.mkdir()
        (stale / 'delivery.json').write_text(json.dumps({'output': '/TEST/older.mp4', 'sha256': 'ab' * 32}))
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.media('draft-a')
        self.assertNotIn('draft-a', self.record()['production']['tasks'])
        self.assertIsNone(media.stored_request(self.root, BATCH, 'draft-a'))

    def test_a_long_project_is_not_a_media_task_here(self) -> None:
        # D2 seam (fail closed until D1/D2 are integrated): the Short exporter and Short deadlines never take a Long.
        project = self.work / 'long-project'
        project.mkdir()
        (project / 'LONG-PROJECT.json').write_text('{}')
        fields = {'batchId': BATCH, 'taskId': 'long-a', 'clipId': 'A', 'route': 'final', 'project': str(project),
                  'output': str(self.work / 'out-long-a')}
        request = media_request(self.work, fields, {'previewReviews': '/TEST/reviews.json'})
        with self.assertRaisesRegex(ValueError, 'names a native-long project'):
            cli.cmd_enqueue(ns(batch=BATCH, tasks=tasks_file(self.work, 'long-a', [
                {'taskId': 'long-a', 'kind': 'media', 'version': 'v1', 'deadlineElapsed': 1800.0,
                 'mediaRequest': str(request)}])))
        self.assertNotIn('long-a', self.record()['production']['tasks'])

    def test_an_unexpected_error_fails_only_that_task_by_name(self) -> None:
        # Minor 12: the dispatcher keeps dispatching; the task it could not handle fails 'dispatcher-error'.
        self.media('draft-a', 'A', 1700.0)
        self.media('draft-b', 'B', 1800.0)
        real = media.check_request

        def check(task: dict, *kept: object) -> None:
            if task['id'] == 'draft-a':
                raise KeyError('TEST project')
            real(task, *kept)
        with mock.patch.object(media, 'check_request', side_effect=check):
            self.assertIsNone(self.dispatcher().step())
        self.assertEqual((self.task('draft-a')['state'], self.task('draft-a')['failure']['category']),
                         ('failed', dispatch.DISPATCHER_ERROR))
        self.assertIn('draft-a', self.task('draft-a')['failure']['detail'])
        self.assertEqual([command[command.index('--task') + 1] for command in self.spawned], ['draft-b'])
        self.assertIn(dispatch.DISPATCHER_ERROR, [row['event'] for row in self.logged()])

    def test_a_refused_release_after_a_failed_start_fails_the_task(self) -> None:
        self.media('draft-a')
        with mock.patch.object(process, 'spawn_detached', side_effect=OSError('TEST exec failure')), \
                mock.patch.object(api, 'release_claim', side_effect=TaskRefused('TEST fenced')):
            self.assertIsNone(self.dispatcher().step())
        self.assertEqual(self.task('draft-a')['failure']['category'], 'run-media-spawn-failed')

    def test_an_error_outside_any_task_ends_the_dispatcher_with_a_named_record(self) -> None:
        from studio.native_runtime import sniper_lock
        with mock.patch.object(api, 'reconcile', side_effect=KeyError('TEST authority shape')), \
                mock.patch.object(dispatch, 'APP_ROOT', self.root.parent / 'app'), \
                mock.patch.object(process, 'own_process', return_value=DISPATCHER), \
                mock.patch.object(sniper_lock, 'hold_for_process'):
            self.assertEqual(dispatch.run(self.root, BATCH), 0)
        exit_record = dispatch.status(self.root, BATCH)['exit']
        self.assertTrue(exit_record['reason'].startswith(f'{dispatch.DISPATCHER_ERROR}: KeyError'), exit_record)

    def test_another_engine_never_dispatches(self) -> None:
        # Probe p13 / minor 11: a dispatcher from another checkout refuses; the task is never claimed or burned.
        from studio import native_budget_engine
        from studio.native_runtime import sniper_lock
        self.media('draft-a')
        store_engine = {'root': '/TEST', 'identity': 'a' * 64, 'files': 1}
        other = {'root': '/other-checkout', 'identity': '9' * 64, 'files': 1}
        self.mutate('batch-auth', lambda record: record.update(engine=store_engine))
        with mock.patch.object(native_budget_engine, 'engine_identity', return_value=other):
            with self.assertRaisesRegex(TaskRefused, 'is not the engine batch batch-auth froze'):
                dispatch.start(self.root, BATCH)
            with mock.patch.object(dispatch, 'APP_ROOT', self.root.parent / 'app'), \
                    mock.patch.object(process, 'own_process', return_value=DISPATCHER), \
                    mock.patch.object(sniper_lock, 'hold_for_process'):
                self.assertEqual(dispatch.run(self.root, BATCH), dispatch.REFUSED_EXIT)
        self.assertIn('is not the engine', dispatch.status(self.root, BATCH)['exit']['reason'])
        self.assertEqual((self.state('draft-a'), self.spawned), ('ready', []))

    def test_a_missing_or_foreign_request_is_never_claimed(self) -> None:
        self.media('draft-a')
        kept = self.root / 'dispatch' / BATCH / 'requests' / 'draft-a.json'
        kept.write_bytes(kept.read_bytes().replace(b'out-draft-a', b'out-elsewhere'))
        self.dispatcher().step()
        self.assertEqual((self.state('draft-a'), self.spawned), ('ready', []))
        kept.unlink()
        runner = self.dispatcher()
        runner.step()
        self.assertEqual(self.state('draft-a'), 'ready')
        self.assertIn('waiting-for-media-request', [row['event'] for row in self.logged()])

    def test_a_failed_start_releases_the_claim_and_charges_nothing(self) -> None:
        self.media('draft-a')
        with mock.patch.object(process, 'spawn_detached', side_effect=OSError('TEST exec failure')):
            self.dispatcher().step()
        self.assertEqual((self.state('draft-a'), self.task('draft-a')['epochs']), ('ready', 1))
        self.assertEqual(self.record()['clips']['A']['counters']['exportAttempt'], 0)

    def test_run_media_that_never_acknowledged_fails_the_task_without_a_retry(self) -> None:
        self.media('draft-a')
        runner = self.dispatcher()
        runner.step()
        self.children[0].returncode = 2                                   # refused before its exporter attached
        runner.step()
        self.assertEqual(self.task('draft-a')['failure']['category'], 'launch-not-acknowledged')
        runner.step()
        self.assertEqual(len(self.spawned), 1)

    def test_ai_work_is_never_launched_by_the_dispatcher(self) -> None:
        from _budget_fixture import task_spec
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'))
        self.dispatcher().step()
        self.assertEqual((self.state('critic'), self.spawned), ('ready', []))

    def test_the_dispatcher_takes_no_pool_lease(self) -> None:
        import native_work_lease
        self.media('draft-a')
        with mock.patch.object(native_work_lease.NativeWorkLease, 'acquire',
                               side_effect=AssertionError('the dispatcher must not lease')) as acquire:
            self.dispatcher().step()
        acquire.assert_not_called()
        self.assertEqual(len(self.spawned), 1)


class RecoveryAndExitTests(DispatchCase):
    """Parent loss, restart, a full trail, the deadline and the clock."""

    def test_a_restarted_dispatcher_never_relaunches_an_uncertain_claim(self) -> None:
        self.media('draft-a')
        self.dispatcher().step()                                          # claimed, then this dispatcher died
        self.rows = table(OTHER)
        self.dispatcher(OTHER).step()                                     # the replacement reconciles first
        self.assertEqual((self.state('draft-a'), self.task('draft-a')['unresolved']), ('abandoned', False))
        self.assertEqual(len(self.spawned), 1)
        claim = self.task('draft-a')['claim']
        with self.assertRaisesRegex(TaskRefused, 'fenced before acknowledgement'):
            api.attach_task(self.root, BATCH, ClaimRef('draft-a', claim['epoch'], claim['token']), CHILD)

    def test_an_export_acknowledged_before_the_dispatcher_died_keeps_running(self) -> None:
        self.media('draft-a')
        self.dispatcher().step()
        claim = self.task('draft-a')['claim']
        api.attach_task(self.root, BATCH, ClaimRef('draft-a', claim['epoch'], claim['token']), CHILD)
        self.rows = table(OTHER, CHILD)                                   # dispatcher gone, exporter alive
        self.dispatcher(OTHER).step()
        self.assertEqual(self.state('draft-a'), 'running')

    def test_a_full_trail_stops_new_claims_but_still_reconciles(self) -> None:
        self.media('draft-a')
        self.media('draft-b', 'B')
        self.dispatcher().step()
        with (self.root / 'batches/batch-auth/events.jsonl').open('ab') as handle:
            handle.truncate(store.MAX_EVENT_BYTES - 10)
        self.rows = table(OTHER)
        runner = self.dispatcher(OTHER)
        self.assertIsNone(runner.step())
        self.assertEqual(self.state('draft-a'), 'abandoned')             # the dead claimer's claim is fenced
        self.assertEqual(self.state('draft-b'), 'ready')                 # but nothing new is claimed
        self.assertIn('trail is full', json.dumps(self.logged()))

    def test_exit_after_hand_off_the_deadline_or_draining(self) -> None:
        runner = self.dispatcher()
        record = self.record()
        for clip in record['clips'].values():
            clip['state'] = 'handed-off'
        self.assertEqual(runner.exit_reason(record, 100.0), 'every clip is handed off')
        self.assertEqual(runner.exit_reason(self.record(), 2400.0), 'the delivery deadline passed')
        runner.children['x'] = (FakeChild(1), ClaimRef('x', 1, 'a' * 32))
        self.assertIsNone(runner.exit_reason(self.record(), 2400.0))       # its launches get the cleanup window
        late = 2400.0 + dispatch.CLEANUP_WINDOW_SECONDS
        self.assertEqual(runner.exit_reason(self.record(), late), 'the cleanup window after the delivery deadline ended')
        self.clock.advance(2400)
        api.drain(self.root, BATCH, 'operator stopped the run')
        self.assertEqual(self.dispatcher().step(), 'the batch is draining')

    def test_reconcile_reads_the_process_table_under_the_batch_lock(self) -> None:
        # Plausible 16 (in-process probe): an acknowledgement that lands while reconcile observes waits for the
        # lock, so a table read before it can never abandon the live export.
        import threading
        from studio.production import reconcile
        self.media('draft-a')
        self.dispatcher().step()
        claim = self.task('draft-a')['claim']
        ref = ClaimRef('draft-a', claim['epoch'], claim['token'])
        acknowledged = threading.Thread(target=api.attach_task, args=(self.root, BATCH, ref, CHILD))

        def observe_then_let_the_child_acknowledge(host: object = None) -> reconcile.Observation:
            acknowledged.start()
            acknowledged.join(0.5)                       # blocks on the batch lock this reconcile holds
            return reconcile.Observation(table(DISPATCHER))
        with mock.patch.object(api, 'current_observation', side_effect=observe_then_let_the_child_acknowledge):
            api.reconcile(self.root, BATCH)
        acknowledged.join(10)
        self.assertEqual((self.state('draft-a'), self.task('draft-a')['handle']), ('running', CHILD))

    def test_a_clock_that_cannot_be_established_stops_the_dispatcher(self) -> None:
        self.clock.advance(100)
        api.task_status(self.root, BATCH)
        self.clock.reboot(downtime=-2000)
        self.assertIn('authority is unavailable', self.dispatcher().step())

    def test_one_dispatcher_per_batch(self) -> None:
        directory = media.batch_state(self.root, BATCH)
        holder = subprocess.Popen([
            sys.executable, '-c', 'import fcntl, os, sys, time\n'
            'fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600); fcntl.flock(fd, fcntl.LOCK_EX)\n'
            'print("held", flush=True); time.sleep(30)', str(directory / dispatch.LOCK)],
            stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), 'held')
        with mock.patch.object(dispatch, 'APP_ROOT', self.root.parent / 'app'):
            self.assertEqual(dispatch.run(self.root, BATCH), dispatch.BUSY_EXIT)


class DetachedDispatchTests(unittest.TestCase):
    """The real detached dispatcher, run-media and watchdog with the TEST exporter child."""

    def setUp(self) -> None:
        base = Path(tempfile.mkdtemp(prefix='sniper-dispatch-')).resolve()
        self.addCleanup(lambda: subprocess.run(['rm', '-rf', str(base)], check=False))
        os.chmod(base, 0o700)
        self.root, self.testdir, self.work = base / 'budgets', base / 'test', base / 'work'
        for directory in (self.testdir, self.work):
            directory.mkdir()
        write_exporter(self.root, self.testdir)
        self.addCleanup(self.stop_dispatcher)
        self.addCleanup(lambda: (self.testdir / 'release').write_text('release'))  # never leave an export held
        recording = base / 'recording.mov'
        recording.write_bytes(SOURCE)
        started = self.cli('start', '--clips', 'A', '--approval', f'A={approval_file(self.work, "A", approval("A"))}',
                           '--source', str(recording), '--pool-slots', '1')
        self.assertTrue(started['approvalsBound'])
        self.project = make_project(self.work, 'native-v1')
        self.cli('bind', '--clip', 'A', str(self.project))
        fields = {'batchId': 'batch-e2e', 'taskId': 'draft-a', 'clipId': 'A', 'route': 'draft',
                  'project': str(self.project), 'output': str(self.work / 'attempt-draft-a')}
        self.cli('enqueue', '--tasks', str(tasks_file(self.work, 'draft', [
            {'taskId': 'draft-a', 'kind': 'media', 'version': 'v1', 'deadlineElapsed': 2000.0,
             'mediaRequest': str(media_request(self.work, fields))}])))

    def cli(self, *args: str, expect: int = 0) -> dict:
        command = [*launcher('cli', self.root, self.testdir), args[0], '--batch', 'batch-e2e', *args[1:]]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def record(self) -> dict:
        return store.read_batch(self.root, 'batch-e2e')

    def wait_for(self, predicate: object, seconds: float = 60.0) -> None:
        until = time.monotonic() + seconds
        while not predicate():
            self.assertLess(time.monotonic(), until, 'condition not reached in time')
            time.sleep(0.1)

    def stop_dispatcher(self) -> None:
        """Stop only a dispatcher this test started, by its exact recorded identity."""
        current = dispatch.status(self.root, 'batch-e2e') if self.root.exists() else {'running': False}
        if current['running']:
            os.kill(current['identity']['pid'], signal.SIGKILL)

    def hand_off(self) -> dict:
        """Hand off in this process with the TEST stand-in as B3's verifier (the CLI refuses without B3's)."""
        from studio.production import commands
        delivery = self.record()['clips']['A']['deliveries'][-1]
        confirmation = handoff_confirmation(self.work / 'handoff', (delivery['output'], delivery['sha256']))
        refused = self.cli('handoff', '--clip', 'A', '--confirmation', str(confirmation), expect=3)
        self.assertIn("B3's verifier refused the confirmation", refused['reason'])  # P0 adapt: B3 in src
        with b3_stand_in(), mock.patch.object(store, 'default_root', return_value=self.root):
            return commands.cmd_handoff(ns(batch='batch-e2e', clip='A', confirmation=confirmation))

    def test_a_detached_dispatcher_delivers_and_exits_after_the_hand_off(self) -> None:
        started = self.cli('dispatch')
        self.assertEqual(started['status'], 'started')
        identity = started['identity']
        self.assertEqual(identity['pgid'], identity['pid'])               # its own session: it outlived the command
        self.assertNotEqual(identity['pgid'], os.getpgid(0))
        self.assertEqual(self.cli('dispatch')['status'], 'already-running')
        self.wait_for(lambda: self.record()['production']['tasks']['draft-a']['state'] == 'completed')
        task, clip = self.record()['production']['tasks']['draft-a'], self.record()['clips']['A']
        self.assertEqual(task['claim']['claimer'], identity)
        self.assertNotEqual(task['handle']['pid'], identity['pid'])        # the exporter child acknowledged
        self.assertEqual(clip['attempts'][-1]['supervisor']['pid'], task['handle']['pid'])
        self.assertEqual(task['attempt'], clip['attempts'][-1]['id'])     # the one launch is the task's
        self.assertEqual((clip['counters']['exportAttempt'], task['receipts'][0]['path']),
                         (1, str(self.work / 'attempt-draft-a/review-draft.mp4')))
        self.assertFalse((self.root.parent / 'pool-state').exists())      # no pool lease anywhere on this route
        self.assertIsNotNone(self.hand_off()['handoff']['visibleHandoffAt'])
        self.wait_for(lambda: dispatch.status(self.root, 'batch-e2e')['exit'] is not None, 15)
        self.assertEqual(dispatch.status(self.root, 'batch-e2e')['exit']['reason'], 'every clip is handed off')

    def test_concurrent_starts_leave_exactly_one_dispatcher(self) -> None:
        (self.testdir / 'hold').write_text('hold')
        command = [*launcher('cli', self.root, self.testdir), 'dispatch', '--batch', 'batch-e2e']
        starters = [subprocess.Popen(command, stdout=subprocess.PIPE, text=True) for _ in range(3)]
        results = [json.loads(starter.communicate(timeout=120)[0]) for starter in starters]
        self.assertEqual(sorted(row['status'] for row in results).count('started'), 1, results)
        self.assertEqual(len({row['identity']['pid'] for row in results}), 1)   # every starter names the winner
        self.wait_for(lambda: self.record()['production']['tasks']['draft-a']['state'] == 'running')
        self.assertEqual(self.record()['production']['tasks']['draft-a']['epochs'], 1)    # claimed once
        (self.testdir / 'release').write_text('release')
        self.wait_for(lambda: self.record()['production']['tasks']['draft-a']['state'] == 'completed')

    def test_dispatcher_loss_keeps_the_export_and_a_restart_reconciles(self) -> None:
        (self.testdir / 'hold').write_text('hold')
        first = self.cli('dispatch')['identity']
        self.wait_for(lambda: self.record()['production']['tasks']['draft-a']['state'] == 'running')
        self.assertTrue(process.alive(first))
        os.kill(first['pid'], signal.SIGKILL)                             # the dispatcher this test started
        self.wait_for(lambda: process.alive(first) is False, 10)
        self.assertFalse(dispatch.status(self.root, 'batch-e2e')['running'])
        self.assertEqual(self.record()['production']['tasks']['draft-a']['state'], 'running')
        (self.testdir / 'release').write_text('release')
        self.wait_for(lambda: self.record()['production']['tasks']['draft-a']['state'] == 'completed')
        restarted = self.cli('dispatch')
        self.assertEqual(restarted['status'], 'started')
        self.assertNotEqual(restarted['identity']['pid'], first['pid'])
        self.hand_off()
        self.wait_for(lambda: dispatch.status(self.root, 'batch-e2e')['exit'] is not None, 15)
        self.assertEqual(self.record()['clips']['A']['counters']['exportAttempt'], 1)

    def test_a_helper_left_in_the_exporters_group_is_ended_before_the_task_settles(self) -> None:
        # Probe p3 (major 3): the exporter leaves a same-group helper and exits normally; the watchdog ends
        # the group (waitid WNOWAIT, killpg, reap) and only then confirms the end.
        pidfile = self.work / 'helper.pid'
        (self.testdir / 'test_exporter.py').write_text(
            f'import subprocess, sys\nsys.path[:0] = [{str(PRODUCER)!r}, {str(PRODUCER / "tests")!r}]\n'
            'import _dispatch_fixture as fixture\n'
            'real = fixture.FakePipeline.execute\n'
            'def execute(self, render_only, invocation):\n'
            '    helper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
            f'    open({str(pidfile)!r}, "w").write(str(helper.pid))\n'
            '    return real(self, render_only, invocation)\n'
            'fixture.FakePipeline.execute = execute\n'
            f'fixture.test_exporter({str(self.root)!r}, {str(self.testdir)!r})\n')
        self.cli('dispatch')
        self.wait_for(lambda: self.record()['production']['tasks']['draft-a']['state'] == 'completed')
        helper = int(pidfile.read_text())
        self.addCleanup(lambda: subprocess.run(['kill', '-9', str(helper)], capture_output=True))
        state = subprocess.run(['ps', '-o', 'stat=', '-p', str(helper)], capture_output=True, text=True).stdout.strip()
        self.assertTrue(state == '' or state.startswith('Z'), f'helper {helper} outlived the export: {state}')
        self.assertTrue(self.record()['production']['tasks']['draft-a']['endConfirmed'])

    def test_an_exporter_that_never_acknowledges_is_stopped_and_frees_its_slot(self) -> None:
        # Probe p7 (major 6): no acknowledgement within ACK_SECONDS; the watchdog stops the child and fails the
        # task 'launch-not-acknowledged' after the confirmed end, instead of holding the slot to the deadline.
        (self.testdir / 'test_exporter.py').write_text('import time\ntime.sleep(600)\n')
        self.cli('dispatch')
        self.wait_for(lambda: self.record()['production']['tasks']['draft-a']['state'] == 'failed', 60)
        task = self.record()['production']['tasks']['draft-a']
        self.assertEqual((task['failure']['category'], task['endConfirmed'], task['handle']),
                         ('launch-not-acknowledged', True, None))
        self.assertEqual(self.record()['clips']['A']['counters']['exportAttempt'], 0)


if __name__ == '__main__':
    unittest.main()
