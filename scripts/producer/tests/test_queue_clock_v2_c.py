"""Short capacity clock v2, continued (M-047 opens this module: v2 is at 299 lines and v2_b near its bound, MA3).

AuditTests (P1 Step B4, C11): credit bound to pool evidence and to the registered supervisor, trail checkpoints and
the status audit. Batches live on the test's private authority root (``_live_state_isolation``) on a fake clock,
with one Short, A, and no enrolled director, so a render wait is the only work; no child process is started.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import os
import unittest
from unittest import mock

from _budget_fixture import FakeClock, approval, fake_clock
from _production_task_flow_fixture import run_cli
from studio import native_budget_binding, native_budget_store
from studio.native_budget_batches import create_batch
from studio.native_budget_clock import ClockAnchor, start_anchor
from studio.native_budget_policy import BatchSpec, new_batch_record
from studio.native_budget_report import clip_status
from studio.native_budget_schema import validate_record
from studio.native_budget_store import TERMINAL_EVENTS, locked_batch, read_batch
from studio.production import queue_authority, queue_clock
from studio.production.queue_audit import capacity_audit
from studio.production.queue_authority import PoolEvidence, record_observation

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
        self.assertIs(clip_status(record, 'A', 800.0, audit)['creditVerified'], False)
        self.assertIsNone(clip_status(record, 'A', 800.0)['creditVerified'])
        code, status = run_cli('status', '--batch', BATCH)
        self.assertEqual((code, status['capacityAudit']['A']['status'], status['clips']['A']['creditVerified']),
                         (0, 'exceeds-trail', False))

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


class CheckpointTests(unittest.TestCase):
    """Trail checkpoints: one per 300 credited seconds, at most 32 per Short, never refused by a full trail."""

    def test_checkpoint_every_300_credited_seconds_capped(self) -> None:
        """40 windows of 300 s of credited waiting (a new occupant each window, observed every 5 s) write exactly
        32 capacity-checkpoint events; the checkpoint row names the last one."""
        spec = BatchSpec(BATCH, ('A',), (), 1, approvals={'A': approval('A')})
        session = MemorySession(new_batch_record(spec, ClockAnchor('TEST-boot', 5000.0, 1_800_000_000.0, 0.0)))
        context = {'clipId': 'A', 'workerId': '/TEST/owner-a.json', 'taskId': None, 'attemptId': None,
                   'supervisor': {'pid': 7001, 'pgid': 7001, 'started': 'TEST start'}, 'boot': 'TEST-boot'}
        now = [0.0]

        def advance(record: dict) -> float:
            """The batch clock at ``now``, checkpointed as advance_clock does."""
            queue_clock.checkpoint(record, now[0])
            return now[0]

        self.enterContext(mock.patch.object(native_budget_binding, 'advance_clock', advance))
        for window in range(40):
            evidence = {'ticket': window, 'occupants': [f'{window:032x}'], 'waitClass': 'capacity'}
            for _ in range(60):
                now[0] += 5.0
                observation = {'state': 'waiting', 'resource': 'heavy-pool', 'evidence': '{}', **evidence}
                queue_authority._observe_locked(session, context, observation, queue_authority.Recovery({}, {}))
        names = [event['event'] for event in session.trail]
        clock = session.record['clips']['A']['capacityClock']
        self.assertEqual((names.count('capacity-checkpoint'), clock['checkpoint']['count']), (32, 32))
        self.assertEqual(clock['checkpoint']['excludedSeconds'], 32 * 300.0)
        self.assertEqual(clock['excludedSeconds'], 40 * 300.0 - 5.0)   # the first observation starts the wait
        self.assertIn('capacity-checkpoint', TERMINAL_EVENTS)


if __name__ == '__main__':
    unittest.main()
