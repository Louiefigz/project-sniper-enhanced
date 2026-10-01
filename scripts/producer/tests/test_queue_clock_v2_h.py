"""Short capacity clock v2, continued (the P1 fix round M-RP6 opens this module: X246).

ToleranceChainTests (m1): the settle tolerance applies only where the trail leaves an owner waiting, so edits just
under it cannot accumulate over links with no waiting owner (the reviewer's 20 x 29.9 s probe). The rest are the
reviewer's gap tests (``reviews/P1-RP6A-evidence/probes/gaps_rp6a.py``, m6): RecoveredDigestTests (N1, N4),
MixedFormatTests (legacy and compact settled lines in one trail), StatementRetryTests (N10), SpentCadenceTests (N11),
LegacyStatementTests (N9) and UnwrittenAbandonmentTests (N15). Private roots, fake clocks, TEST process tables; no
child process is started.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import os
import unittest
from unittest import mock

from _budget_fixture import table
from _production_task_flow_fixture import BATCH as FLOW_BATCH, held_batch, run_cli
from studio import native_budget_launch, native_budget_store
from studio.native_budget_binding import advance_clock
from studio.native_budget_store import BudgetAuthorityError, locked_batch, read_batch
from studio.production import api
from studio.production.approvals import trail_events
from studio.production.queue_audit import SETTLE_TOLERANCE, _audit_clip, capacity_audit, owner_digest
from studio.production.queue_authority import CHECKPOINT_SECONDS, record_observation
from studio.production.queue_clock_schema import MAX_CHECKPOINTS, new_clock
from studio.production.host_contract import encoded_length
from studio.production.reconcile import _change
from studio.production.tasks import TaskRefused
from test_budget_schema_shapes import ATTEMPT
from test_queue_clock_stall_c import BATCH as FULL_BATCH, FullTrailCase
from test_queue_clock_v2_c import BATCH, POOL, AuditCase

ME = {'type': 'process', 'pid': os.getpid(), 'pgid': os.getpgid(0), 'started': 'TEST start'}


def trail_rows(root: object, batch_id: str) -> list[dict]:
    """The batch's trail lines."""
    return [json.loads(line) for line in (root / 'batches' / batch_id / 'events.jsonl').read_text().splitlines()]


class ToleranceChainTests(AuditCase):
    """m1: one edit just under the settle tolerance before each of 20 owners' end lines is seen."""

    def chain(self, owners: int, step: float) -> str:
        """``owners`` short-lived working owners; before each one's end line, A's credit is raised by ``step``."""
        for index in range(owners):
            context = {**self.context, 'workerId': f'/TEST/owner-{index}.json'}
            record_observation(context, 'working', ('native-owner', 'preparation'))
            self.clock.advance(max(40.0, step + 10.0))
            with locked_batch(self.root, BATCH) as session:
                record = session.read()
                advance_clock(record)
                record['clips']['A']['capacityClock']['excludedSeconds'] += step
                session.commit(record, {'event': 'TEST-hand-edit'})
            self.clock.advance(10.0)
            record_observation(context, 'finished', ('native-owner', 'owner finished'))
        return capacity_audit(self.root, BATCH, read_batch(self.root, BATCH))['A']['status']

    def test_twenty_sub_tolerance_edits_are_seen(self) -> None:
        """20 edits of (tolerance - 0.1) s with no owner waiting: exceeds-trail (before X246 m1: consistent)."""
        self.assertEqual(self.chain(20, SETTLE_TOLERANCE - 0.1), 'exceeds-trail')

    def test_honest_working_owners_stay_consistent(self) -> None:
        """The same 20 owners with no edit: consistent."""
        self.assertEqual(self.chain(20, 0.0), 'consistent')


class ChangeReasonTests(unittest.TestCase):
    """X246 n1: a reconcile change's reason is clipped as the record's is, so its line stays within its count."""

    def test_a_long_reason_is_clipped(self) -> None:
        """A 512-byte reason plus a suffix (``_fenced_unacknowledged``'s shape) is cut to 512 encoded bytes."""
        task = {'id': 'TEST-task', 'state': 'abandoned', 'unresolved': True}
        suffix = '; its claim holder ended before any execution acknowledged it'
        change = _change(task, 'superseded', 'r' * 512 + suffix)
        self.assertEqual(encoded_length(change['reason']), 512)


class RecoveredDigestTests(AuditCase):
    """An owner's end that recovers a dead waiter: the compact line names both by digest; the audit is consistent."""

    def test_a_recovered_waiter_named_by_digest_is_explained(self) -> None:
        """W1 waits; W2 works; W1's supervisor vanishes; W2 ends and recovers W1 on its capacity-settled line."""
        w1 = {**self.context, 'workerId': '/TEST/w1.json'}
        w2 = {**self.context, 'workerId': '/TEST/w2.json'}
        with mock.patch.object(native_budget_launch, '_process_table', return_value=table(ME)):
            record_observation(w1, 'waiting', ('heavy-pool', '{}'), POOL)
            record_observation(w2, 'working', ('native-owner', 'preparation'))
        self.clock.advance(5.0)
        with mock.patch.object(native_budget_launch, '_process_table', return_value=table()):
            record_observation(w2, 'finished', ('native-owner', 'owner finished'))
        lines = [row for row in trail_rows(self.root, BATCH) if row['event'] == 'capacity-settled']
        self.assertEqual(lines[-1]['recoveredDigests'], [owner_digest('/TEST/w1.json')])
        record = read_batch(self.root, BATCH)
        self.assertEqual(record['clips']['A']['capacityClock']['workers'], {})
        self.assertEqual(capacity_audit(self.root, BATCH, record)['A']['status'], 'consistent')


class MixedFormatTests(unittest.TestCase):
    """Legacy settled lines (worker paths) and compact ones (digests) in one trail."""

    @staticmethod
    def clip(workers: dict, credit: float = 0.0) -> dict:
        """A v2 clip whose clock was observed at 100 s."""
        return {'output': {'format': 'short'}, 'capacityClock': {**new_clock(), 'observedElapsed': 100.0,
                                                                 'excludedSeconds': credit, 'workers': workers}}

    @staticmethod
    def observed(worker: str, state: str, at: float) -> dict:
        """One capacity-observed line of Short A with no credit."""
        return {'event': 'capacity-observed', 'clipId': 'A', 'worker': worker, 'state': state, 'elapsed': at,
                'excludedSeconds': 0.0, 'recoveredWorkers': [], 'orphanedWorkers': []}

    def test_legacy_then_compact_lines_audit_consistent(self) -> None:
        """W1 and W2 wait; a legacy line ends W1 and recovers W3; a compact line ends W2 and recovers W4."""
        trail = [self.observed('/w1', 'waiting', 1.0), self.observed('/w2', 'waiting', 2.0),
                 self.observed('/w3', 'waiting', 3.0), self.observed('/w4', 'waiting', 4.0),
                 {'event': 'capacity-settled', 'clipId': 'A', 'worker': '/w1', 'state': 'finished', 'elapsed': 5.0,
                  'excludedSeconds': 0.0, 'recoveredWorkers': ['/w3'], 'orphanedWorkers': []},
                 {'event': 'capacity-settled', 'clipId': 'A', 'workerDigest': owner_digest('/w2'),
                  'state': 'finished', 'elapsed': 6.0, 'excludedSeconds': 0.0,
                  'recoveredDigests': [owner_digest('/w4')], 'orphanedDigests': []}]
        self.assertEqual(_audit_clip(self.clip({}), trail)['status'], 'consistent')
        self.assertEqual(_audit_clip(self.clip({}), trail[:5])['status'], 'unexplained-removal')


class StatementRetryTests(unittest.TestCase):
    """m2b: one statement per task and phase counts only a committed statement."""

    def test_a_failed_statement_does_not_block_its_retry(self) -> None:
        """The first statement's record replace fails (line, then commit-failed); the retry is recorded."""
        batch = held_batch(self)
        with mock.patch.object(native_budget_store, 'write_pending_replace', side_effect=OSError('TEST replace')), \
                self.assertRaises(BudgetAuthorityError):
            api.settle_resource(batch.root, FLOW_BATCH, 'critic', 'TEST first statement')
        result = api.settle_resource(batch.root, FLOW_BATCH, 'critic', 'TEST retried statement')
        self.assertTrue(result['committed'])


class SpentCadenceTests(AuditCase):
    """N11: after MAX_CHECKPOINTS checkpoint lines the cadence no longer bounds the window (no false alarm)."""

    def test_an_honest_wait_past_the_last_checkpoint_is_consistent(self) -> None:
        """A capacity wait long enough for every checkpoint line, then 600 s more: still consistent."""
        self.observe('waiting', POOL)
        target = CHECKPOINT_SECONDS * (MAX_CHECKPOINTS + 2) + 600.0
        while self.clock_of()['excludedSeconds'] < target:
            self.clock.advance(25.0)
            self.observe('waiting', POOL)
        record = read_batch(self.root, BATCH)
        self.assertEqual(record['clips']['A']['capacityClock']['checkpoint']['count'], MAX_CHECKPOINTS)
        self.assertEqual(capacity_audit(self.root, BATCH, record)['A']['status'], 'consistent')


class LegacyStatementTests(unittest.TestCase):
    """N9: a statement line written before M-RP5 (no ``phase``) still counts as the task's statement."""

    def test_a_phaseless_statement_blocks_a_second(self) -> None:
        """A legacy line for critic on the trail: a new statement is refused by name."""
        batch = held_batch(self)
        trail = batch.root / 'batches' / FLOW_BATCH / 'events.jsonl'
        with trail.open('a') as handle:
            handle.write(json.dumps({'event': 'task-resource-settled', 'taskId': 'critic',
                                     'basis': 'operator-statement', 'statement': 'TEST legacy',
                                     'elapsed': 1.0}) + '\n')
        with self.assertRaisesRegex(TaskRefused, 'already has the operator'):
            api.settle_resource(batch.root, FLOW_BATCH, 'critic', 'TEST second')


class UnwrittenAbandonmentTests(FullTrailCase):
    """N15: an abandonment whose line never reached the trail stays owed."""

    def test_an_unwritable_trail_leaves_the_abandonment_owed(self) -> None:
        """The first status cannot append (exit 2); the next writes the abandoning line and commits it."""
        running = {**ATTEMPT, 'status': 'running', 'resultStatus': None, 'completedElapsed': None}
        self.commit(lambda record: record['clips']['A'].update(attempts=[running]))
        self.table.side_effect, self.table.return_value = None, table()
        with mock.patch.object(native_budget_store, 'write_all', side_effect=OSError('TEST unwritable')):
            self.assertEqual(run_cli('status', '--batch', FULL_BATCH)[0], 2)
        self.status()
        committed = trail_events(self.trail.read_bytes())
        self.assertTrue(any(row.get('event') == 'observed' and row.get('abandoned') for row in committed))


if __name__ == '__main__':
    unittest.main()
