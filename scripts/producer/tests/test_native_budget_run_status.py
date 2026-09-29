"""Run status (AI, media by class, CPU, memory, disk, cleanup) and the assembled production status.

The host pool is read from a private temporary state root (``native_work_lease.state_root`` is
patched) holding TEST pool files whose liveness locks this test holds or leaves free; the process
table and host memory are TEST values (``RealLockTests`` records a ``/bin/sleep`` it starts); owner
receipts are TEST files; the one-lock observation uses a private TEST authority. Nothing live is read.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
import unittest
from unittest import mock

import native_work_lease
import native_work_pool_policy
import native_work_pool_recovery
from _budget_fixture import ENGINE, FakeClock, fake_clock, host_turn, private_root
from _status_fixture import (
    BATCH, START, attempt, batch_record, deliver, enroll, handed_off, handoff_summary, mp4, observe, packet_resolved,
    run_task, temporary_directory,
)
import native_work_pool_state
from native_render_processes import process_table
from native_work_pool_observe import observe as admission_observe
from studio import native_budget_run_status as run_status_module
from studio.native_budget_pool import pool_snapshot
from studio.native_budget_batches import create_batch
from studio.native_budget_status import StatusInputs, production_status, status_observation
from studio.native_budget_store import locked_batch
from studio.production import callbacks
from test_stage_timing_v2 import _row

GIB = 1024 ** 3
HOST = {'memsizeBytes': 64 * GIB}
LIVE = {'pid': 5001, 'pgid': 5001, 'started': 'Sun Sep 27 09:00:00 2026'}
OTHER_ZONE = {**LIVE, 'started': 'Sun Sep 27 14:00:00 2026'}   # the same supervisor recorded under TZ=UTC
GONE = {'pid': 5002, 'pgid': 5002, 'started': 'Sun Sep 27 09:00:00 2026'}


def cpu_summary(owned: float, busy: float) -> dict:
    """An E1 owner CPU summary."""
    return {'schema': 'native-owned-cpu-v1', 'observedOwnedCpuSeconds': owned, 'measuredOwnedCpuSeconds': owned,
            'peakHostBusyFraction': busy, 'meanHostBusyFraction': busy / 2}


def private_file(path: object, value: dict | None = None) -> None:
    """A private (0600, single-link) pool record as the pool writes it (an empty lock file without a value)."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.write(fd, b'' if value is None else json.dumps(value).encode())
    os.close(fd)


def hold(case: unittest.TestCase, path: object) -> None:
    """Hold an exclusive flock on the file for the test, as a supervisor or waiter does."""
    fd = os.open(path, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    case.addCleanup(os.close, fd)


class Case(unittest.TestCase):
    """A TEST batch and a private pool: a live member (lock held; identity recorded under another zone), a member
    closed without completing (lock free, supervisor still in the process table), a waiting and a stale ticket."""

    def setUp(self) -> None:
        self.dir = temporary_directory(self)
        self.state = self.dir / 'pool-state'
        self.state.mkdir(mode=0o700)
        pool = self.state / 'pool-v1'
        pool.mkdir(mode=0o700)
        heavy = {'class': 'heavy', 'reservationBytes': 6 * GIB, 'diskReservationBytes': 3 * GIB, 'diskDevice': 7}
        private_file(pool / f'm-{"a" * 32}.json', {**heavy, 'supervisor': OTHER_ZONE})
        private_file(pool / f'm-{"b" * 32}.json', {**heavy, 'class': 'audio', 'reservationBytes': GIB,
                                                   'supervisor': LIVE})
        for name in (f'm-{"a" * 32}.lock', f'm-{"b" * 32}.lock'):
            private_file(pool / name)
        private_file(pool / f't-000000000001-{"c" * 32}.json', {'class': 'heavy', 'supervisor': LIVE})
        private_file(pool / f't-000000000002-{"d" * 32}.json', {'class': 'heavy', 'supervisor': GONE})
        hold(self, pool / f'm-{"a" * 32}.lock')
        hold(self, pool / f't-000000000001-{"c" * 32}.json')
        patches = (mock.patch.object(native_work_lease, 'state_root', return_value=self.state),
                   mock.patch.object(native_work_pool_recovery, 'process_snapshot',
                                     return_value={LIVE['pid']: (1, LIVE['pgid'], LIVE['started'])}),
                   mock.patch.object(native_work_pool_policy, 'host_identity', return_value=HOST))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.record = observe(batch_record(), 2500.0)
        self.attempt_dir = self.dir / 'A-final'
        self.attempt_dir.mkdir()
        self.running = attempt('final', 900.0, status='running', output=str(self.attempt_dir))
        self.record['clips']['A']['attempts'].append(self.running)

    def pool_files(self) -> list[tuple[str, float]]:
        return sorted((path.name, path.stat().st_mtime) for path in self.state.rglob('*'))


class RunStatusTests(Case):
    """What the run section reports, what it leaves unknown, and that it never writes the pool."""

    def test_pool_by_class_memory_headroom_and_disk_reservations_read_only(self) -> None:
        before = self.pool_files()
        run = run_status_module.run_status(self.record, 1000.0)
        pool = run['media']['hostPool']
        self.assertEqual(pool['byClass']['heavy'], {'live': 1, 'quarantined': 0, 'waiting': 1})
        self.assertEqual(pool['byClass']['audio'], {'live': 0, 'quarantined': 1, 'waiting': 0})
        self.assertEqual((pool['staleTickets'], pool['liveWithoutProcessTableMatch']), (1, 1))
        self.assertEqual(run['memory']['reservations']['headroomBytes'], 32 * GIB - 7 * GIB)
        self.assertEqual(run['disk']['reservedBytesByDevice'], {'7': 6 * GIB})
        self.assertEqual(run['cleanup']['quarantinedPoolMembers'], [
            {'nonce': 'b' * 32, 'class': 'audio', 'lock': 'free', 'supervisorInProcessTable': True,
             'recover': f'native_work_recovery.py {"b" * 32}'}])
        self.assertEqual(self.pool_files(), before)               # nothing created, pruned or touched

    def test_a_ticket_being_enqueued_is_not_probed(self) -> None:
        pool = self.state / 'pool-v1'
        private_file(pool / f't-000000000003-{"e" * 32}.json', None)   # created, not yet locked or written
        with mock.patch.object(native_work_pool_state, 'probe', wraps=native_work_pool_state.probe) as probe:
            found = pool_snapshot()
        self.assertNotIn(f't-000000000003-{"e" * 32}.json', [call.args[1] for call in probe.call_args_list])
        self.assertEqual(found['staleTickets'], 2)

    def test_a_host_without_pool_state_reports_it_and_creates_nothing(self) -> None:
        missing = self.dir / 'never-used'
        with mock.patch.object(native_work_lease, 'state_root', return_value=missing):
            pool = run_status_module.run_status(self.record, 1000.0)['media']['hostPool']
        self.assertEqual(pool['status'], 'no-pool-state')
        self.assertFalse(missing.exists())

    def test_the_task_summary_is_folded_into_run_ai(self) -> None:
        enroll(self.record)
        ai = run_status_module.run_status(self.record, 1000.0, {'running': False})['ai']
        self.assertEqual((ai['slots'], ai['active'], ai['charged'], ai['enrolledDirector']), (4, 1, 1, 'director'))
        self.assertNotIn('usage', ai)

    def test_cpu_and_pressure_come_from_owner_receipts_or_stay_unknown(self) -> None:
        unknown = run_status_module.run_status(self.record, 1000.0)
        self.assertEqual((unknown['cpu']['status'], unknown['memory']['pressure']['status']), ('unknown', 'unknown'))
        snapshot = {'measured_at': START + 950, 'kernel_pressure_level': 2, 'unused_physical_bytes': 5 * GIB,
                    'free_percent': 30.0}
        (self.attempt_dir / 'pipeline.render.json').write_text(json.dumps(
            {'cpu': cpu_summary(40.0, 0.9), 'latestResourceSnapshot': snapshot}))
        (self.attempt_dir / 'capture.render.json').write_text(json.dumps({'cpu': cpu_summary(20.0, 0.5)}))
        (self.attempt_dir / 'broken.render.json').write_text('{')
        run = run_status_module.run_status(self.record, 1000.0)
        self.assertEqual((run['cpu']['owners'], run['cpu']['observedOwnedCpuSeconds']), (2, 60.0))
        self.assertEqual(run['memory']['pressure']['kernelPressure'], 'warning')
        self.assertEqual(run['unreadableOwnerReceipts'], [str(self.attempt_dir / 'broken.render.json')])

    def test_cleanup_names_stopping_tasks_and_launches_after_hand_off(self) -> None:
        enroll(self.record)
        run_task(self.record, ('author-A', 'author', {}), host_turn('A'), (10.0, None))
        callbacks.request_cancel(self.record, 'author-A', 'TEST stop', 20.0)
        self.record['clips']['A']['state'] = 'handed-off'
        cleanup = run_status_module.run_status(self.record, 1000.0)['cleanup']
        self.assertEqual((cleanup['cancelRequested'], cleanup['launchesRunningAfterHandoff']),
                         (['author-A'], [self.running['id']]))
        self.assertFalse(cleanup['settled'])


class ProductionStatusTests(Case):
    """The status report: earlier fields kept, a compact summary by default, the whole block with --full."""

    def status(self, full: bool, **inputs: object) -> dict:
        video = mp4('B-draft')
        deliver(self.record, 'B', attempt('draft', 600.0, completed=900.0), video)
        handed = handed_off('B', handoff_summary(video, (950.0, 1000.0)), 1001.0)
        return production_status(self.record, 2500.0, StatusInputs(events=(handed,), full=full, **inputs))

    def test_the_full_report_separates_encoded_from_visible(self) -> None:
        journal = self.dir / 'stage_timings.jsonl'
        common = {'stage': 'm', 'metadata': {'activity': 'model'}, 'runId': BATCH}
        journal.write_text('\n'.join(json.dumps(row) for row in (
            _row('m', 'start', 10.0, ts=START + 10, **common),
            _row('m', 'end', 70.0, ts=START + 70, elapsedMs=60000.0, **common))) + '\n')
        status = self.status(True, timing=(journal,))
        self.assertEqual((status['slaMisses'], status['production']['visibleSlaMisses']), (['A'], ['A']))
        clip_b = status['clips']['B']['production']
        self.assertEqual((clip_b['state'], clip_b['milestones']['slaMiss']['status']), ('visible', 'met'))
        self.assertEqual(status['production']['elapsedBreakdown']['categories']['model']['unionSeconds'], 60.0)
        self.assertEqual(clip_b['forecast']['status'], 'unknown')
        approval = self.record['clips']['B']['approvals'][0]
        self.assertEqual(clip_b['versions']['approvedContent']['identity'], approval['identity'])
        self.assertEqual((clip_b['milestones']['timestamps']['authorizedAt'], clip_b['versions']['approvalChanges']),
                         (0.0, 0))  # approved-content-production-2026-09-27: the clock starts at the hand-over

    def test_the_default_report_is_a_compact_summary(self) -> None:
        full, compact = json.dumps(self.status(True)), self.status(False)
        clip_b = compact['clips']['B']['production']
        self.assertEqual(sorted(clip_b), ['blockers', 'forecast', 'milestones', 'nextActions', 'state'])
        self.assertEqual((clip_b['milestones']['visibleMp4'], clip_b['milestones']['timestamps']['visibleHandoffAt']),
                         ('visible', 1001.0))
        self.assertEqual((compact['production']['full'], compact['production']['visibleSlaMisses']), (False, ['A']))
        self.assertLess(len(json.dumps(compact)), len(full) / 2)
        self.assertEqual(compact['clips']['A']['counters']['author'], '0/3')   # the earlier fields are unchanged


class RealLockTests(unittest.TestCase):
    """probe_pool2: a real supervisor stand-in this test starts, its identity recorded under TZ=UTC with its lock held,
    and a member closed without completing (lock released, supervisor alive). Status agrees with admission."""

    def identity(self, pid: int, environment: dict) -> dict:
        out = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'pid=,ppid=,pgid=,lstart='], capture_output=True,
                             text=True, env=environment, check=True).stdout
        _parent, group, started = process_table(out)[pid]
        return {'pid': pid, 'pgid': group, 'started': started}

    def test_status_liveness_is_the_admissions_lock_view(self) -> None:
        state = temporary_directory(self) / 'state'
        (state / native_work_pool_state.POOL_DIR).mkdir(parents=True, mode=0o700)
        os.chmod(state, 0o700)
        helper = subprocess.Popen(['/bin/sleep', '47.321'])
        self.addCleanup(helper.wait)
        self.addCleanup(helper.kill)
        pool, record = state / native_work_pool_state.POOL_DIR, {'class': 'heavy', 'reservationBytes': GIB,
                                                               'diskReservationBytes': 0, 'diskDevice': 1}
        members = (('a' * 32, {**os.environ, 'TZ': 'UTC'}), ('b' * 32, dict(os.environ)))
        for nonce, environment in members:
            private_file(pool / f'm-{nonce}.json', {**record, 'supervisor': self.identity(helper.pid, environment)})
            private_file(pool / f'm-{nonce}.lock')
        hold(self, pool / f'm-{"a" * 32}.lock')
        with mock.patch.object(native_work_lease, 'state_root', return_value=state), \
                mock.patch.object(native_work_pool_policy, 'host_identity', return_value=HOST):
            status = pool_snapshot()
            with native_work_pool_state.ledger(time.monotonic() + 5) as namespace:
                admission = {row['nonce']: row['state'] for row in admission_observe(namespace).members}
        self.assertEqual(admission, {'a' * 32: 'live', 'b' * 32: 'quarantined'})
        self.assertEqual(status['byClass']['heavy'], {'live': 1, 'quarantined': 1, 'waiting': 0})
        self.assertEqual([(row['nonce'], row['lock'], row['supervisorInProcessTable'], row['recover'])
                          for row in status['quarantinedMembers']],
                         [('b' * 32, 'free', True, f'native_work_recovery.py {"b" * 32}')])


class ObservationTests(unittest.TestCase):
    """The record and its trail's hand-off, claim, release and review-timing events come from one batch-lock session."""

    def test_the_trail_is_read_with_the_record(self) -> None:
        root, record = private_root(self), batch_record()
        record['engine'] = dict(ENGINE)
        create_batch(root, record)
        with locked_batch(root, BATCH) as session:
            current = session.read()
            session.commit(current, handed_off('A', {'record': None}, 5.0))
            session.commit(current, {'event': 'task-released', 'taskId': 'x', 'epoch': 1, 'elapsed': 6.0})
            session.commit(current, {'event': 'dispatch-admitted', 'clipId': 'A', 'elapsed': 7.0})
            session.commit(current, packet_resolved('A', 8.0))
        with fake_clock(FakeClock()), mock.patch('studio.native_budget_launch._process_table', return_value={}):
            _record, _elapsed, events = status_observation(root, BATCH)
        self.assertEqual([row['event'] for row in events], ['clip-handed-off', 'task-released', 'packet-resolved'])


if __name__ == '__main__':
    unittest.main()
