"""M-050's named stall, continued (P1-RP3b fixes, X184, open this module: ``test_queue_clock_stall`` is at 299 lines).

FullTrailTests (MAJOR, heartbeat ruling (b)): at a full event trail the operator's cancel is still written and the
batch then closes, and a waiting owner's heartbeat that names a stall commits record-only instead of failing its
render; on the test's private authority root, the process table unreadable (no ``ps``). StaleStallTests (m1, m2,
m3, QS12): the close text, stalls that outlive their waits, and a cancelled Short's credit. UnionTests (QS2, QS3,
QC2): which waits the stall's union reads and what clears it. ForgedStallTests (n3): three forged stall rows that
version 8 now refuses. The last two run in memory through
``queue_authority._observe_locked`` (``test_queue_clock_stall.Waiter``). No child process is started.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import os
import unittest
from unittest import mock

from _budget_fixture import FakeClock, approval, fake_clock
from _production_task_flow_fixture import run_cli
from studio import native_budget_launch, native_budget_store as store
from studio.native_budget_batches import create_batch
from studio.native_budget_clock import start_anchor
from studio.native_budget_policy import BatchSpec, close_refusal, new_batch_record, phase_refusal
from studio.native_budget_report import clip_status
from studio.native_budget_store import locked_batch, read_batch
from studio.production import api, queue_clock, queue_stall
from studio.production.queue_authority import PoolEvidence, record_observation
from studio.production.queue_stall import StallDecision
from studio.production import queue_clock_schema as schema
from test_queue_clock_stall import A, B, BOUND, INCONSISTENT, Waiter
from test_queue_clock_v2 import short_record

BATCH = 'batch-auth'
CANCEL = ('capacity-stall', '--batch', BATCH, '--clip', 'A', '--decision', 'cancel', '--reason', 'TEST give A up')


class FullTrailTests(unittest.TestCase):
    """The trail's reserve never strands a stalled Short, and never fails the render that waits behind it."""

    def setUp(self) -> None:
        """Batch ``batch-auth`` with Short A on the private root; the process table reads as unreadable."""
        self.clock = self.enterContext(fake_clock(FakeClock()))
        self.enterContext(mock.patch.object(native_budget_launch, '_process_table', side_effect=OSError('TEST')))
        self.root = store.default_root()
        spec = BatchSpec(BATCH, ('A',), (), 3, approvals={'A': approval('A')})
        create_batch(self.root, new_batch_record(spec, start_anchor()))
        self.trail = self.root / 'batches' / BATCH / 'events.jsonl'

    def fill_trail(self) -> None:
        """Bring the trail to 10 bytes below the point where new work stops."""
        with self.trail.open('ab') as handle:
            handle.truncate(store.MAX_EVENT_BYTES - store.TERMINAL_RESERVE_BYTES - 10)

    def stall(self, handed_off: bool = False) -> None:
        """Short A stalled (as ``track`` writes it), optionally handed off, then past its deadline, at a full trail."""
        with locked_batch(self.root, BATCH) as session:
            record = session.read()
            record['clips']['A']['capacityClock']['stall'].update(state='capacity-stalled', sinceElapsed=0.0,
                                                                  occupants=['a' * 32])
            if handed_off:
                record['clips']['A']['state'] = 'handed-off'
            session.commit(record, {'event': 'TEST-stalled'})
        self.clock.advance(3000.0)
        self.fill_trail()

    def test_a_stalled_short_is_cancelled_and_the_batch_closes_at_a_full_trail(self) -> None:
        """MAJOR: the cancel is written although the trail is full (``capacity-stall-decided`` is terminal, at most
        one per Short), and the batch then closes, so no later batch on the host is held up."""
        self.stall()
        code, out = run_cli(*CANCEL)
        self.assertEqual((code, out['state']), (0, 'cancelled'))
        self.assertIn('capacity-stall-decided', store.TERMINAL_EVENTS)
        self.assertEqual(api.close(self.root, BATCH)['status'], 'closed')

    def test_a_handed_off_stale_stall_does_not_hold_the_batch(self) -> None:
        """m2: a handed-off Short's stall protects nothing: close succeeds at a full trail and the next batch starts."""
        self.stall(handed_off=True)
        self.assertEqual(api.close(self.root, BATCH)['status'], 'closed')
        spec = BatchSpec('batch-next', ('B',), (), 3, approvals={'B': approval('B')})
        create_batch(self.root, new_batch_record(spec, start_anchor()))

    def test_a_heartbeat_naming_the_stall_commits_record_only_at_a_full_trail(self) -> None:
        """Ruling (b): the waiting owner's heartbeat that names the stall cannot append its line; it commits the
        record as the heartbeat it was, so the render does not fail and the record and status name the stall."""
        context = {'authority': str(self.root), 'batchId': BATCH, 'clipId': 'A', 'workerId': '/TEST/owner-a.json',
                   'supervisor': {'pid': os.getpid(), 'pgid': os.getpgid(0), 'started': 'TEST start'},
                   'boot': self.clock.boot, 'taskId': None, 'attemptId': None}
        evidence = PoolEvidence(4, ('a' * 32,), 'capacity')
        for _ in range(2):
            self.clock.advance(5.0)
            record_observation(context, 'waiting', ('heavy-pool', '{}'), evidence)
        with locked_batch(self.root, BATCH) as session:          # the window has held for the bound
            record = session.read()
            record['clips']['A']['capacityClock']['occupancy']['sinceElapsed'] = 0.0
            session.commit(record, {'event': 'TEST-window'})
        self.fill_trail()
        size = self.trail.stat().st_size
        self.clock.advance(BOUND)
        record_observation(context, 'waiting', ('heavy-pool', '{}'), evidence)
        clip = read_batch(self.root, BATCH)['clips']['A']
        self.assertEqual((queue_stall.state(clip), self.trail.stat().st_size), ('capacity-stalled', size))
        self.assertEqual(queue_clock.status(clip, BOUND)['capacityState'], 'capacity-stalled')


class StaleStallTests(unittest.TestCase):
    """m1: the close text names the stall first; m2: a stall ends with its waits; m3 and QS12: after a cancel."""

    def stalled(self) -> Waiter:
        """A waiter whose occupants have not changed for the bound (and one more poll)."""
        waiter = Waiter(self)
        waiter.wait(BOUND + 10.0)
        self.assertEqual(waiter.clock['stall']['state'], 'capacity-stalled')
        return waiter

    def test_close_names_the_stall_before_the_deadline(self) -> None:
        """m1: a credited stall never reaches its deadline, so the stall's text comes before the open-clips text."""
        waiter = self.stalled()
        refusal = close_refusal(waiter.session.record, waiter.now[0])
        self.assertRegex(refusal, r'^Short A is capacity-stalled .* while its owner waits.* cancel')

    def test_settling_the_waiters_task_clears_its_stall(self) -> None:
        """m2: the watchdog settles the waiting owner's task; the stall it named clears and no longer holds close."""
        waiter = self.stalled()
        record = copy.deepcopy(waiter.session.record)
        record['clips']['A']['capacityClock']['workers']['/TEST/owner-a.json']['taskId'] = 'media-a'   # TEST: its task
        self.assertEqual(queue_clock.settle_task_workers(record, 'media-a'), ['/TEST/owner-a.json'])
        self.assertIsNone(record['clips']['A']['capacityClock']['stall']['state'])
        self.assertIsNone(close_refusal(record, waiter.now[0] + 5000.0))

    def test_a_handed_off_short_is_not_stalled(self) -> None:
        """m2: after hand-off the stall protects nothing: close is not refused and status shows no stall action."""
        waiter = self.stalled()
        record = waiter.session.record
        record['clips']['A']['state'] = 'handed-off'
        self.assertIsNone(close_refusal(record, waiter.now[0] + 5000.0))
        self.assertFalse(any('Capacity stalled' in text for text in clip_status(record, 'A', waiter.now[0])['actions']))

    def test_a_cancelled_short_earns_no_credit_and_shows_no_stall_action(self) -> None:
        """m3 (X184): after the cancel, truncated or not, the waits are counted as uncertain, never credited; the
        refusal names the Short (n1); QS12: no stall action is shown."""
        waiter = self.stalled()
        record = waiter.session.read()
        queue_stall.decide(record, 'A', StallDecision('cancel', 'TEST'), waiter.now[0])
        waiter.session.record = record
        before = (waiter.clock['excludedSeconds'], waiter.clock['uncertainSeconds'])
        waiter.wait(10.0)
        self.assertEqual((waiter.clock['excludedSeconds'], waiter.clock['uncertainSeconds']),
                         (before[0], before[1] + 10.0))
        self.assertFalse(any('Capacity stalled' in text for text in clip_status(record, 'A', waiter.now[0])['actions']))
        self.assertRegex(phase_refusal(record, record['clips']['A'], waiter.now[0]),
                         "^Short A's stalled capacity wait was cancelled")


class UnionTests(unittest.TestCase):
    """QS2, QS3, QC2: the union is every verified wait's occupants, all of them, and a finished waiter ends it."""

    def test_a_change_beyond_the_first_64_names_clears_the_stall(self) -> None:
        """QS2: nine owners with eight occupants each (72 names) stall truncated at 64; one name past the cut
        changes, and the stall clears (the fingerprint hashes the whole union, X98)."""
        waiter = Waiter(self)
        keys = [f'/TEST/owner-{index}.json' for index in range(9)]
        rows = {key: {**A, 'occupants': [f'{index}{slot}' for slot in range(8)]} for index, key in enumerate(keys)}
        waiter.now[0] = BOUND + 5.0
        self.poll(waiter, rows)
        waiter.clock['occupancy']['sinceElapsed'] = 0.0
        self.poll(waiter, rows)
        stall = waiter.clock['stall']
        self.assertEqual((stall['state'], stall['truncated']), ('capacity-stalled', True))
        self.assertNotIn('87', stall['occupants'])
        rows[keys[8]] = {**A, 'occupants': [*rows[keys[8]]['occupants'][:7], '89']}
        self.poll(waiter, rows)
        self.assertIsNone(waiter.clock['stall']['state'])

    def test_an_unverified_wait_is_not_in_the_union(self) -> None:
        """QS3: a second owner waits without its ticket (unverified): its occupant is not a holder of the stall."""
        waiter = Waiter(self)
        rows = {'/TEST/owner-a.json': A, '/TEST/owner-b.json': {**B, 'ticket': None}}
        end = BOUND + 10.0
        while waiter.now[0] < end:
            self.poll(waiter, rows)
        self.assertEqual((waiter.clock['stall']['state'], waiter.clock['stall']['occupants']),
                         ('capacity-stalled', ['a' * 32]))

    def test_a_finished_waiter_clears_the_stall(self) -> None:
        """QC2: the only waiter's ``finished`` observation ends the verified wait, and with it the stall."""
        waiter = Waiter(self)
        waiter.wait(BOUND + 10.0)
        waiter.now[0] += 5.0
        waiter.observe('finished')
        self.assertIsNone(waiter.clock['stall']['state'])

    @staticmethod
    def poll(waiter: Waiter, rows: dict) -> None:
        """One 5 s round in which every owner reports its evidence."""
        waiter.now[0] += 5.0
        for key, evidence in rows.items():
            waiter.observe('waiting', evidence, key)


class ForgedStallTests(unittest.TestCase):
    """X184 n3: shapes ``track`` and ``decide`` never write are refused under version 8."""

    def test_three_forged_stall_rows_are_refused(self) -> None:
        """A stall naming no occupant, one dated after the clock's observed time, and a cancel dated before its
        stall are refused; a stall with its holder, one dated at the observed time, and a cancel at the stall's own
        time are accepted."""
        clip = short_record()['clips']['A']
        clip['capacityClock']['observedElapsed'] = 100.0
        named = {'state': 'capacity-stalled', 'sinceElapsed': 40.0, 'occupants': ['a'], 'truncated': False,
                 'decisions': []}
        cancel = {'kind': 'cancel', 'reason': 'TEST', 'elapsed': 40.0}
        cancelled = {**named, 'state': 'cancelled', 'decisions': [cancel]}
        forged = ({**named, 'occupants': []}, {**named, 'sinceElapsed': 100.5},
                  {**cancelled, 'decisions': [{**cancel, 'elapsed': 39.5}]})
        accepted = (named, {**named, 'sinceElapsed': 100.0}, cancelled)
        rows = [(stall, INCONSISTENT) for stall in forged] + [(stall, None) for stall in accepted]
        for index, (stall, expected) in enumerate(rows):
            clock = {**copy.deepcopy(clip['capacityClock']), 'stall': stall}
            with self.subTest(index, forged=expected is not None):
                self.assertEqual(schema.problem({**clip, 'capacityClock': clock}), expected)


if __name__ == '__main__':
    unittest.main()
