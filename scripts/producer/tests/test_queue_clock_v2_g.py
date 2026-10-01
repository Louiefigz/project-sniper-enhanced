"""Short capacity clock v2, continued (the P1 fix round M-RP5 opens this module: X217).

CloseSettlementTests (M2): a close's reconcile writes the owners it settles on the close line, so an untouched closed
batch audits ``consistent``. CadenceCapTests (m1): the audit's waiting window is capped by the checkpoint cadence, so
an edit made while the waiter was silent stays visible after the watchdog's settlement. ReaderTests (n1): only the
settling lists are read. OwnerEndTests (M1): an owner's end names owners by digest and is a line only when it removes
a row. CommitGapTests (m6: R10, R7, R5) and AbandonmentOnceTests (m3): an unwritable trail fails status, a checkpoint
after a failed one is written, a heartbeat never needs settlement room, and an abandoning observation is written once
per attempt while its record cannot be replaced. On private authority roots and fake clocks; no child process.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import unittest
from unittest import mock

from _budget_fixture import CHILD, table
from _production_task_flow_fixture import BATCH as FLOW_BATCH, close, run_cli
from studio import native_budget_binding, native_budget_store
from studio.native_budget_store import BudgetAuthorityError, locked_batch
from studio.production import process_settle
from studio.production.approvals import trail_events
from studio.production.queue_audit import SETTLE_TOLERANCE, _capacity_rows, owner_digest
from studio.production.queue_authority import CHECKPOINT_SECONDS
from studio.production.queue_clock import SETTLED
from test_budget_schema_shapes import ATTEMPT
from test_queue_clock_stall_c import BATCH as FULL_BATCH, FullTrailCase
from test_queue_clock_v2_c import BATCH, POOL, AuditCase
import test_queue_clock_v2_f as v2_f   # its SettlementAuditTests.batch_waiting, called with this module's tests


def audit_status(test: unittest.TestCase, batch_id: str = FLOW_BATCH) -> str:
    """The status command's audit verdict for Short A."""
    code, result = run_cli('status', '--batch', batch_id)
    test.assertEqual(code, 0, result)
    return result['capacityAudit']['A']['status']


def trail_lines(root: object, batch_id: str) -> list[dict]:
    """The batch's trail lines."""
    return [json.loads(line) for line in (root / 'batches' / batch_id / 'events.jsonl').read_text().splitlines()]


def hand_edit(root: object, batch_id: str, seconds: float) -> None:
    """A record-only hand edit of A's credit, committed through the store."""
    with locked_batch(root, batch_id) as session:
        record = session.read()
        native_budget_binding.advance_clock(record)
        record['clips']['A']['capacityClock']['excludedSeconds'] += seconds
        session.commit(record, {'event': 'TEST-hand-edit'})


class CloseSettlementTests(unittest.TestCase):
    """M2: the owners a close's reconcile settles reach the close line (``reconciled``)."""

    def test_an_untouched_closed_batch_audits_consistent(self) -> None:
        """A survivor keeps media-a unresolved; 2500 s later close sees it gone, settles the owner and closes."""
        batch, claim = v2_f.SettlementAuditTests.batch_waiting(self)
        process_settle.settle(claim, process_settle.Ending(CHILD['pid'], None, (v2_f.SURVIVOR,), None))
        self.assertEqual(close(batch)['status'], 'closed')
        self.assertEqual(batch.record()['clips']['A']['capacityClock']['workers'], {})
        line = [row for row in batch.events() if row['event'] == 'batch-closed'][-1]
        self.assertEqual([change['taskId'] for change in line['reconciled']], ['media-a'])
        self.assertEqual(line['reconciled'][0][SETTLED]['A']['removedWorkers'], [owner_digest('/TEST/owner.json')])
        self.assertEqual(audit_status(self), 'consistent')


class CadenceCapTests(unittest.TestCase):
    """m1: credit cannot outgrow the last row by more than the checkpoint cadence without a line."""

    def test_an_edit_before_the_watchdog_settlement_stays_visible(self) -> None:
        """The waiter falls silent at 60 s of credit; 1200 s later an edit adds 1100; the settlement copies it."""
        batch, claim = v2_f.SettlementAuditTests.batch_waiting(self)
        batch.clock.advance(1200)
        hand_edit(batch.root, FLOW_BATCH, 1100.0)
        self.assertEqual(audit_status(self), 'exceeds-trail')
        self.assertTrue(process_settle.settle(claim, process_settle.Ending(CHILD['pid'], None, (), None))['settled'])
        self.assertEqual(audit_status(self), 'exceeds-trail')

    def edit_past_the_cadence(self, beyond: float) -> str:
        """X238: the waiter falls silent, and 1200 s later its credit is edited to ``beyond`` seconds past one
        cadence plus the tolerance above the last row; the audit's verdict."""
        batch, _claim = v2_f.SettlementAuditTests.batch_waiting(self)
        batch.clock.advance(1200)
        code, result = run_cli('status', '--batch', FLOW_BATCH)
        self.assertEqual(code, 0, result)
        row = result['capacityAudit']['A']
        bound = row['trailSeconds'] + CHECKPOINT_SECONDS + SETTLE_TOLERANCE
        hand_edit(batch.root, FLOW_BATCH, bound + beyond - row['recordedSeconds'])
        return audit_status(self)

    def test_an_edit_just_over_one_cadence_is_seen(self) -> None:
        """X238: one second past one cadence plus the tolerance is exceeds-trail."""
        self.assertEqual(self.edit_past_the_cadence(1.0), 'exceeds-trail')

    def test_an_edit_just_under_one_cadence_is_within_the_window(self) -> None:
        """X238: one second short of one cadence plus the tolerance stays consistent."""
        self.assertEqual(self.edit_past_the_cadence(-1.0), 'consistent')

    def test_an_honest_silent_waiter_stays_consistent(self) -> None:
        """A waiter silent for 1200 s, then settled by its watchdog, stays consistent."""
        batch, claim = v2_f.SettlementAuditTests.batch_waiting(self)
        batch.clock.advance(1200)
        self.assertEqual(audit_status(self), 'consistent')
        process_settle.settle(claim, process_settle.Ending(CHILD['pid'], None, (), None))
        self.assertEqual(audit_status(self), 'consistent')


class ReaderTests(unittest.TestCase):
    """n1: a settlement entry is read from the event, its ``changes`` and its ``reconciled``, never another list."""

    def test_only_the_settling_lists_are_read(self) -> None:
        """Entries in the event, its changes and its reconciled are read; one in receipts is not."""
        entry = {'A': {'elapsed': 10.0, 'excludedSeconds': 5.0, 'removedWorkers': [owner_digest('/TEST/w')]}}
        read = [{'event': 'tasks-reconciled', 'changes': [{'taskId': 't', SETTLED: entry}]},
                {'event': 'batch-closed', 'reconciled': [{'taskId': 't', SETTLED: entry}]},
                {'event': 'task-completed', SETTLED: entry}]
        self.assertEqual(len(_capacity_rows(read)), 3)
        self.assertEqual(_capacity_rows([{'event': 'task-completed', 'receipts': [{SETTLED: entry}]}]), [])


class OwnerEndTests(AuditCase):
    """M1: an owner's end is a compact settling line, and only when it removes an owner row."""

    def test_an_owner_end_names_owners_by_digest(self) -> None:
        """An owner's end writes the compact digest line, and the audit reads it as consistent."""
        self.observe('waiting', POOL)
        self.clock.advance(20.0)
        self.observe('waiting', POOL)
        self.observe('finished')
        line = trail_lines(self.root, BATCH)[-1]
        self.assertEqual((line['event'], line['workerDigest']),
                         ('capacity-settled', owner_digest('/TEST/owner-a.json')))
        self.assertFalse({'worker', 'resource', 'evidence', 'creditedSeconds'} & set(line))
        self.assertEqual(audit_status(self, BATCH), 'consistent')

    def test_the_end_of_an_owner_the_record_no_longer_holds_writes_no_line(self) -> None:
        """A finish of an owner with no row adds no trail line."""
        before = len(trail_lines(self.root, BATCH))
        self.observe('finished')
        self.assertEqual(len(trail_lines(self.root, BATCH)), before)


class CommitGapTests(AuditCase):
    """m6 (R10, R7, R5): reviewer gap tests (``reviews/P1-RP5A-evidence/gaps_rp5a.py``) and the room exemption."""

    def test_an_unwritable_trail_fails_status(self) -> None:
        """R10: with the trail unwritable, status fails (exit 2), never record-only."""
        with mock.patch.object(native_budget_store, 'write_all', side_effect=OSError('TEST unwritable')):
            code, result = run_cli('status', '--batch', BATCH)
        self.assertEqual(code, 2, result)

    def test_the_checkpoint_after_a_failed_one_is_written(self) -> None:
        """R7 and X246 m2: the failed checkpoint is committed once its record is, and the next one is written too."""
        self.observe('working')
        self.clock.advance(1000.0)
        self.observe('waiting', POOL)
        hand_edit(self.root, BATCH, 600.0)
        with mock.patch.object(native_budget_store, 'write_pending_replace', side_effect=OSError('TEST replace')):
            self.clock.advance(2.0)
            self.assertRaises(BudgetAuthorityError, self.observe, 'waiting', POOL)
        self.clock.advance(2.0)
        self.observe('waiting', POOL)                     # the failed one: record committed, then its line
        self.clock.advance(700.0)
        hand_edit(self.root, BATCH, 600.0)
        self.clock.advance(2.0)
        self.observe('waiting', POOL)                     # the next checkpoint: written
        raw = trail_lines(self.root, BATCH)
        committed = trail_events((self.root / 'batches' / BATCH / 'events.jsonl').read_bytes())
        self.assertEqual([row['event'] for row in raw].count('capacity-checkpoint'), 3)   # one failed, two committed
        self.assertEqual([row['event'] for row in committed].count('capacity-checkpoint'), 2)

    def test_a_heartbeat_needs_no_settlement_room(self) -> None:
        """R5: with no room left for settlements, new work is refused but a heartbeat still commits."""
        full = mock.patch.object(native_budget_store, 'settlement_reserve',
                                 return_value=native_budget_store.MAX_RECORD_BYTES)
        with full, locked_batch(self.root, BATCH) as session:
            record = session.read()
            with self.assertRaisesRegex(BudgetAuthorityError, 'no room left'):
                session.commit(record, {'event': 'TEST-new-work'})
            session.commit(record, {'event': 'capacity-heartbeat'})


class AbandonmentOnceTests(FullTrailCase):
    """X217 m3 as X246 m2 rules: at a full trail, while the record cannot be replaced, a dead launch's line is written
    once; once the record holds the abandonment its line is appended, so the committed trail names it exactly once.
    Nothing is kept between statuses (each CLI status is its own process): the writer reads the trail."""

    def test_status_writes_the_abandoned_line_once_while_the_record_cannot_be_replaced(self) -> None:
        """Three failing statuses write one observed line and one commit-failed; the next success commits the record
        and appends the committed line: two abandoning lines in all, one committed."""
        running = {**ATTEMPT, 'status': 'running', 'resultStatus': None, 'completedElapsed': None}
        self.commit(lambda record: record['clips']['A'].update(attempts=[running]))
        self.table.side_effect, self.table.return_value = None, table()     # the launch's supervisor is gone
        self.fill()
        with mock.patch.object(native_budget_store, 'write_pending_replace', side_effect=OSError('TEST replace')):
            codes = [run_cli('status', '--batch', FULL_BATCH)[0] for _ in range(3)]
        self.assertEqual(codes, [2, 2, 2])
        lines = [json.loads(line) for line in self.trail.read_text().splitlines()[-2:]]
        self.assertEqual([(row['event'], row.get('abandoned')) for row in lines],
                         [('observed', [ATTEMPT['id']]), ('commit-failed', None)])
        self.status()                                     # the record commits now, then its line follows it
        self.assertEqual(self.trail.read_text().count('"abandoned":["'), 2)
        committed = [row for row in trail_events(self.trail.read_bytes()) if row.get('abandoned')]
        self.assertEqual([row['abandoned'] for row in committed], [[ATTEMPT['id']]])
        self.status()                                     # nothing more is owed
        self.assertEqual(self.trail.read_text().count('"abandoned":["'), 2)


if __name__ == '__main__':
    unittest.main()
