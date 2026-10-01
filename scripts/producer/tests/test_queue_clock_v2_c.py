"""Short capacity clock v2, continued (M-047 opens this module: v2 is at 299 lines and v2_b near its bound, MA3).

AuditTests (P1 Step B4, C11): credit bound to pool evidence and to the registered supervisor, trail checkpoints and
the status audit; P1-RP3 (X183): the audit's window closes when no owner waits (m2), and a checkpoint event carries
only what the audit reads, within its share of the trail's terminal reserve (m5); status audits from its one trail
read (n3). Batches live on the test's private authority root (``_live_state_isolation``) on a fake clock, with one
Short, A, and no enrolled director, so a render wait is the only work; no child process is started.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import os
import sys
import unittest
from unittest import mock

from _budget_fixture import FakeClock, approval, fake_clock
from _production_task_flow_fixture import run_cli
from studio import native_budget_binding, native_budget_store
from studio.native_budget_batches import create_batch
from studio.native_budget_clock import ClockAnchor, start_anchor
from studio.native_budget_policy import BatchSpec, new_batch_record
from studio.native_budget_report import TrailViews, clip_status
from studio.native_budget_schema import validate_record
from studio.native_budget_schema_data import BOUNDS
from studio.native_budget_store import TERMINAL_EVENTS, canonical, locked_batch, read_batch
from studio.production import queue_authority, queue_clock
from studio.production.queue_audit import _audit_clip, capacity_audit
from studio.production.queue_authority import CHECKPOINT_EVENT_BYTES, PoolEvidence, record_observation
from studio.production.queue_clock_schema import MAX_CHECKPOINTS, new_clock

BATCH = 'clock-audit'
POOL = PoolEvidence(7, ('a' * 32,), 'capacity')   # a capacity-only refusal's ticket and live occupant


class AuditCase(unittest.TestCase):
    """One TEST batch with Short A and an owner context of this very process."""

    def setUp(self) -> None:
        """Create the batch at elapsed 0 on the private root; the owner is this process."""
        self.clock = self.enterContext(fake_clock(FakeClock()))
        self.root = native_budget_store.default_root()
        spec = BatchSpec(BATCH, ('A',), (), 1, approvals={'A': approval('A')})
        create_batch(self.root, new_batch_record(spec, start_anchor()))
        owner = {'pid': os.getpid(), 'pgid': os.getpgid(0), 'started': 'TEST start'}
        self.context = {'authority': str(self.root), 'batchId': BATCH, 'clipId': 'A', 'workerId': '/TEST/owner-a.json',
                        'supervisor': owner, 'boot': self.clock.boot, 'taskId': None, 'attemptId': None}

    def observe(self, state: str, pool: PoolEvidence | None = None) -> float:
        """One committed observation of the owner."""
        return record_observation(self.context, state, ('heavy-pool', '{}'), pool)

    def wait(self, seconds: float, pool: PoolEvidence | None) -> None:
        """Wait ``seconds`` for the pool, observed every 2 s, then be admitted (the last interval settles)."""
        self.observe('waiting', pool)
        for _ in range(int(seconds / 2)):
            self.clock.advance(2.0)
            self.observe('waiting', pool)
        self.observe('working')

    def clock_of(self) -> dict:
        """Short A's committed capacity clock."""
        return read_batch(self.root, BATCH)['clips']['A']['capacityClock']


class AuditTests(AuditCase):
    """C11: a wait earns credit only with its pool evidence and from its own supervisor; status audits the total."""

    def test_declared_wait_without_pool_evidence_earns_nothing(self) -> None:
        """A wait with no pool evidence is counted as uncertain; the same wait with a ticket and occupants is
        credited, and the waiting row keeps that evidence (X180 n5: nothing overwrites it)."""
        self.wait(60, None)
        self.assertEqual((self.clock_of()['excludedSeconds'], self.clock_of()['uncertainSeconds']), (0.0, 60.0))
        self.observe('waiting', POOL)
        row = self.clock_of()['workers']['/TEST/owner-a.json']
        self.assertEqual((row['ticket'], row['occupants'], row['waitClass']), (7, ['a' * 32], 'capacity'))
        self.wait(60, POOL)
        self.assertEqual((self.clock_of()['excludedSeconds'], self.clock_of()['uncertainSeconds']), (60.0, 60.0))

    def test_hand_edited_excluded_seconds_is_reported(self) -> None:
        """A total raised by 600 s through the store exceeds its trail: the audit, clip_status and the status
        command all say so; before the edit the same total is consistent."""
        self.wait(60, POOL)
        self.clock.advance(740.0)
        self.observe('finished')                       # a capacity-settled event at 800 s, with its 60 s
        record = read_batch(self.root, BATCH)
        self.assertEqual(capacity_audit(self.root, BATCH, record)['A']['status'], 'consistent')
        with locked_batch(self.root, BATCH) as session:
            edited = session.read()
            edited['clips']['A']['capacityClock']['excludedSeconds'] += 600.0
            session.commit(edited, {'event': 'TEST-hand-edit'})
        record = read_batch(self.root, BATCH)
        audit = capacity_audit(self.root, BATCH, record)
        self.assertEqual(audit['A'], {'status': 'exceeds-trail', 'recordedSeconds': 660.0, 'trailSeconds': 60.0,
                                      'trailElapsed': 800.0})
        self.assertIs(clip_status(record, 'A', 800.0, TrailViews(audit))['creditVerified'], False)
        self.assertIsNone(clip_status(record, 'A', 800.0)['creditVerified'])
        code, status = run_cli('status', '--batch', BATCH)
        self.assertEqual((code, status['capacityAudit']['A']['status'], status['clips']['A']['creditVerified']),
                         (0, 'exceeds-trail', False))

    def test_a_hand_edit_after_a_productive_stretch_exceeds_the_trail(self) -> None:
        """X183 m2: the owner works for 20 min after its last event and nothing waits, so no credit can have accrued
        since that event: a total raised by 1100 s exceeds the trail although 1200 s have passed."""
        self.observe('working')                        # a capacity-observed event at 0 s carrying 0
        self.clock.advance(1200.0)
        with locked_batch(self.root, BATCH) as session:
            edited = session.read()
            native_budget_binding.advance_clock(edited)
            edited['clips']['A']['capacityClock']['excludedSeconds'] += 1100.0
            session.commit(edited, {'event': 'TEST-hand-edit'})
        audit = capacity_audit(self.root, BATCH, read_batch(self.root, BATCH))['A']
        self.assertEqual((audit['status'], audit['recordedSeconds'], audit['trailSeconds']),
                         ('exceeds-trail', 1100.0, 0.0))

    def test_status_reads_the_trail_once(self) -> None:
        """X183 n3: status audits the credit from the trail it read under its observation lock, not a second read."""
        from headless import durable_files
        self.wait(60, POOL)
        reads, original = [], durable_files.read_private_file

        def counted(dir_fd: int, name: str, limit: int) -> bytes:
            """The real read, counting the trail's."""
            reads.append(name)
            return original(dir_fd, name, limit)

        with mock.patch.object(durable_files, 'read_private_file', counted):
            code, status = run_cli('status', '--batch', BATCH)
        self.assertEqual((code, status['capacityAudit']['A']['status'], reads.count(native_budget_store.EVENTS)),
                         (0, 'consistent', 1))

    def test_an_event_after_the_record_was_read_is_no_mismatch(self) -> None:
        """Only events at or before the record's observed time count: credit committed after this record was read
        (a later wait's admission) leaves the earlier record consistent, and the fresh record too."""
        self.wait(60, POOL)
        self.observe('waiting', POOL)
        earlier = read_batch(self.root, BATCH)
        for _ in range(5):
            self.clock.advance(2.0)
            self.observe('waiting', POOL)
        self.observe('working')                        # a capacity-observed event carrying 70 s
        self.assertEqual(capacity_audit(self.root, BATCH, earlier)['A']['status'], 'consistent')
        fresh = capacity_audit(self.root, BATCH, read_batch(self.root, BATCH))['A']
        self.assertEqual((fresh['status'], fresh['recordedSeconds'], fresh['trailSeconds']), ('consistent', 70.0, 70.0))

    def test_other_process_cannot_commit_for_the_supervisor(self) -> None:
        """A context naming another supervisor is refused before anything is read or written."""
        before = (self.root / 'batches' / BATCH / 'authority.json').read_bytes()
        other = {**self.context, 'supervisor': {**self.context['supervisor'], 'pid': os.getpid() + 1}}
        with self.assertRaisesRegex(ValueError, '^Only the registered supervisor commits its capacity observations$'):
            record_observation(other, 'waiting', ('heavy-pool', '{}'), POOL)
        self.assertEqual((self.root / 'batches' / BATCH / 'authority.json').read_bytes(), before)


class CadenceTests(AuditCase):
    """P2 (P1 Step B13, M-055): a waiting owner's observation gap is credited up to a bound derived from the admission
    loop's own bounds; a longer gap is counted, as uncertain."""

    def steps(self, seconds: float, count: int) -> dict:
        """Wait for the pool with ``count`` gaps of ``seconds`` between observations, then be admitted."""
        self.observe('waiting', POOL)
        for _ in range(count):
            self.clock.advance(seconds)
            self.observe('waiting', POOL)
        self.observe('working')
        return self.clock_of()

    def test_poll_bound_covers_the_loop_bounds(self) -> None:
        """The 2 s poll sleep (``native_run_admission.wait_capacity``), the ledger wait, three host inspections with
        their 0.5 s and 1 s backoff, and one process-table read: 27.5 s, within the 30 s bound."""
        from native_work_pool_policy import HOST_IDENTITY_TIMEOUT_SECONDS
        from native_work_pool_state import LEDGER_WAIT_SECONDS
        from studio.native_budget_launch import PS_TIMEOUT_SECONDS
        from studio.native_run_admission import INSPECTION_ATTEMPTS, INSPECTION_BACKOFF_SECONDS
        backoff = INSPECTION_BACKOFF_SECONDS * (2 ** (INSPECTION_ATTEMPTS - 1) - 1)
        loop = 2 + LEDGER_WAIT_SECONDS + INSPECTION_ATTEMPTS * HOST_IDENTITY_TIMEOUT_SECONDS + backoff + PS_TIMEOUT_SECONDS
        self.assertEqual(loop, 27.5)
        self.assertGreaterEqual(queue_clock.POLL_BOUND_SECONDS, loop)

    def test_25_second_steps_credit_fully(self) -> None:
        """Four 25 s gaps (each inside the bound) are credited in full."""
        clock = self.steps(25.0, 4)
        self.assertEqual((clock['excludedSeconds'], clock['uncertainSeconds']), (100.0, 0.0))

    def test_31_second_gap_is_uncertain(self) -> None:
        """One 31 s gap (past the bound: a sleep, a stopped process) is counted as uncertain, never credited."""
        clock = self.steps(31.0, 1)
        self.assertEqual((clock['excludedSeconds'], clock['uncertainSeconds']), (0.0, 31.0))


class MemorySession:
    """An in-memory stand-in for ``BatchSession``: validated commits, and a trail without heartbeats, as the store."""

    def __init__(self, record: dict) -> None:
        """Hold the record; the trail starts empty."""
        self.record, self.trail = record, []

    def read(self) -> dict:
        """A copy of the committed record."""
        return copy.deepcopy(self.record)

    def commit(self, record: dict, event: dict) -> None:
        """Validate and keep the record; append every event but a heartbeat."""
        validate_record(record)
        self.record = copy.deepcopy(record)
        if event['event'] != 'capacity-heartbeat':
            self.trail.append(event)

    def lines_naming(self, name: str) -> list[dict]:
        """The trail's lines naming ``name``, as ``BatchSession.lines_naming`` reads them (no commit fails here)."""
        return [row for row in self.trail if name in (row.get('event'), row.get('failedEvent'))]


class CheckpointTests(unittest.TestCase):
    """Trail checkpoints: one per 300 credited seconds, at most 32 per Short, never refused by a full trail; each only
    what the audit reads, within ``CHECKPOINT_EVENT_BYTES`` (X183 m5)."""

    def drive(self, windows: int, worker: str = '/TEST/owner-a.json') -> MemorySession:
        """``windows`` windows of 300 s of credited waiting by ``worker`` (a new occupant each window, observed every
        5 s) through the committing path; returns the in-memory session."""
        spec = BatchSpec(BATCH, ('A',), (), 1, approvals={'A': approval('A')})
        session = MemorySession(new_batch_record(spec, ClockAnchor('TEST-boot', 5000.0, 1_800_000_000.0, 0.0)))
        context = {'clipId': 'A', 'workerId': worker, 'taskId': None, 'attemptId': None,
                   'supervisor': {'pid': 7001, 'pgid': 7001, 'started': 'TEST start'}, 'boot': 'TEST-boot'}
        now = [0.0]

        def advance(record: dict) -> float:
            """The batch clock at ``now``, checkpointed as advance_clock does."""
            queue_clock.checkpoint(record, now[0])
            return now[0]

        self.enterContext(mock.patch.object(native_budget_binding, 'advance_clock', advance))
        for window in range(windows):
            evidence = {'ticket': window, 'occupants': [f'{window:032x}'], 'waitClass': 'capacity'}
            for _ in range(60):
                now[0] += 5.0
                observation = {'state': 'waiting', 'resource': 'heavy-pool', 'evidence': '{}', **evidence}
                queue_authority._observe_locked(session, context, observation, queue_authority.Recovery({}, {}))
        return session

    def test_checkpoint_every_300_credited_seconds_capped(self) -> None:
        """40 windows write exactly 32 capacity-checkpoint events; the checkpoint row names the last one."""
        session = self.drive(40)
        names = [event['event'] for event in session.trail]
        clock = session.record['clips']['A']['capacityClock']
        self.assertEqual((names.count('capacity-checkpoint'), clock['checkpoint']['count']), (32, 32))
        self.assertEqual(clock['checkpoint']['excludedSeconds'], 32 * 300.0)
        self.assertEqual(clock['excludedSeconds'], 40 * 300.0 - 5.0)   # the first observation starts the wait
        self.assertIn('capacity-checkpoint', TERMINAL_EVENTS)

    def test_a_checkpoint_carries_only_what_the_audit_reads(self) -> None:
        """m5: the checkpoint is the six fields ``queue_audit`` reads; the observation before it keeps its evidence."""
        trail = self.drive(2).trail
        self.assertEqual([event['event'] for event in trail], ['capacity-observed', 'capacity-checkpoint'])
        self.assertEqual(set(trail[1]), {'event', 'clipId', 'worker', 'state', 'elapsed', 'excludedSeconds'})
        self.assertEqual((trail[0]['resource'], trail[0]['evidence'], trail[1]['worker']),
                         ('heavy-pool', '{}', '/TEST/owner-a.json'))

    def test_the_worst_case_fits_its_share_of_the_terminal_reserve(self) -> None:
        """32 Shorts x 32 checkpoints of the largest event written (a 64-character clip id, the longest float
        spellings, an owner path filling the rest of ``CHECKPOINT_EVENT_BYTES``) fill at most 512 KiB, their row in
        ``test_trail_reserve_budget``; a path one byte longer, or shorter but escaped by JSON, is never written as a
        checkpoint."""
        mark = {'event': 'capacity-checkpoint', 'clipId': 'C' * 64, 'worker': '', 'state': 'waiting',
                'elapsed': sys.float_info.max, 'excludedSeconds': sys.float_info.max}
        room = CHECKPOINT_EVENT_BYTES - len(canonical(mark))
        widest = {**mark, 'worker': '/' + 'x' * (room - 1)}
        self.assertEqual(len(canonical(widest)), CHECKPOINT_EVENT_BYTES)
        self.assertLessEqual(BOUNDS['clips'] * MAX_CHECKPOINTS * len(canonical(widest)), 512 * 1024)
        clip = {'capacityClock': new_clock()}
        self.assertTrue(queue_authority._checkpoint_due(clip, widest))
        for worker in ('/' + 'x' * room, '/' + '\x01' * (room // 6 + 1)):
            clip = {'capacityClock': new_clock()}
            with self.subTest(characters=len(worker)):
                self.assertFalse(queue_authority._checkpoint_due(clip, {**mark, 'worker': worker}))
                self.assertEqual(clip['capacityClock']['checkpoint']['count'], 0)

    def test_an_owner_path_too_long_writes_no_checkpoint_and_the_audit_holds(self) -> None:
        """m5: a 600-character owner path writes no checkpoint; its credit still accrues, and the audit's window
        (the owner waits after its last event) still accounts for it."""
        session = self.drive(2, '/TEST/' + 'p' * 600)
        clip = session.record['clips']['A']
        self.assertEqual([event['event'] for event in session.trail], ['capacity-observed'])
        self.assertEqual(clip['capacityClock']['excludedSeconds'], 2 * 300.0 - 5.0)
        self.assertEqual(_audit_clip(clip, session.trail)['status'], 'consistent')


if __name__ == '__main__':
    unittest.main()
