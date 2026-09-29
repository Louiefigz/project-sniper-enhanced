"""M-043's closure record: its room (X104), its validator, and the archive that keeps its charge (X37, X79).

A batch reserves one widest closure row for each task that can still be listed, so its close fits at the room
bound; ``production.closure`` belongs to a closed batch only; archive appends the rows the host record lacks,
refuses unresolved work the closure or the host record does not list, and keeps the charge in the host record.
Batches are ``_production_task_flow_fixture.Batch`` (private roots, fake clocks, TEST handles and a TEST process
table); no test starts a child process.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest
from unittest.mock import patch

from _budget_fixture import DISPATCHER, table
from _production_task_flow_fixture import BATCH, Batch, close, closure_rows, finish, held_batch, rewrite
from studio import native_budget_store
from studio.native_budget_batches import BudgetRefused, archive_batch
from studio.native_budget_schema import validate_record
from studio.native_budget_store import BudgetAuthorityError, canonical
from studio.production import lifecycle, settlement
from studio.production.host_contract import HOSTS, MAX_PID
from studio.production.production_optional import closure_problem
from studio.production.task_schema import TASK_KINDS, TASK_STATES
from studio.production.unresolved_executions import RECORD, open_rows, recorded_task_ids, row_problem

ARCHIVE_REFUSAL = ('Batch batch-auth holds unresolved work not recorded at closure '
                   '(production.closure/unresolved-executions.jsonl)')


def widest_valid_row(task_id: str = 'T' * 64) -> dict:
    """A closure row at every bound ``row_problem`` admits, built from the validator's own limits (X114 m1).

    Each ``"`` encodes as two bytes, so the reason and ``started`` sit at their encoded-byte bounds (512, 64).
    """
    return {'taskId': task_id, 'kind': max(TASK_KINDS, key=len), 'state': max(TASK_STATES, key=len),
            'host': max(HOSTS, key=len), 'hostProcess': {'pid': MAX_PID, 'pgid': MAX_PID, 'started': '"' * 32},
            'reason': '"' * 256}


class ClosureRoomTests(unittest.TestCase):
    """X104: the closure a batch can still write is reserved before the claim that makes a task listable."""

    def test_the_widest_valid_row_fits_the_row_reserved_for_it(self) -> None:
        """The widest row the validator admits fits ``CLOSURE_ROW_BYTES``; each field one step wider is refused."""
        widest = widest_valid_row()
        self.assertIsNone(row_problem(widest))
        self.assertLessEqual(settlement.encoded(widest) + 1, settlement.CLOSURE_ROW_BYTES)   # the row and its comma
        wider = {
            'taskId': {'taskId': 'T' * 65},
            'pid': {'hostProcess': {**widest['hostProcess'], 'pid': MAX_PID + 1}},
            'started': {'hostProcess': {**widest['hostProcess'], 'started': '"' * 32 + 's'}},
            'reason': {'reason': '"' * 256 + 'r'},
        }
        for field, change in wider.items():
            with self.subTest(field):
                self.assertIsNotNone(row_problem({**widest, **change}))

    def test_close_fits_at_the_room_bound(self) -> None:
        """A batch filled to its room bound still closes; each listable task reserves one widest closure row."""
        batch = Batch(self)
        batch.enqueue(*((f'turn-{index}', 'specialist', ()) for index in range(3)), ('spare', 'check', ()))
        for index in range(3):
            finish(batch, f'turn-{index}')   # three held completions; the unclaimed spare will be cancelled
        record = batch.record()
        # Four listable tasks: the three completions and the live director (the close releases its assignment).
        closure_room = settlement.CLOSURE_BASE_BYTES + 4 * settlement.CLOSURE_ROW_BYTES
        self.assertEqual(settlement._closure_room(record), closure_room)
        self.assertGreaterEqual(settlement._lifecycle_room(record), closure_room)
        bound = len(canonical(record)) + settlement.settlement_reserve(record)
        with patch.object(native_budget_store, 'MAX_RECORD_BYTES', bound):
            self.assertEqual(close(batch)['status'], 'closed')
        self.assertEqual(len(closure_rows(batch)), 3)
        # The widest valid closure (the task bound, every row at the validator's bounds) fits the reserved rows.
        rows = [widest_valid_row(f'{index:03d}' + 'T' * 61) for index in range(256)]
        closure = {'closedElapsed': 1.2345678901234567e-300, 'unresolvedAtClose': rows}
        probe = {'status': 'closed', 'closedAtElapsed': closure['closedElapsed'],
                 'production': {'closure': closure, 'tasks': {row['taskId']: {'kind': row['kind']} for row in rows}}}
        self.assertIsNone(closure_problem(probe))
        widest = settlement.encoded({'closure': closure}) - 1   # the closure's key and value, plus its comma
        self.assertLessEqual(widest, settlement.CLOSURE_BASE_BYTES + 256 * settlement.CLOSURE_ROW_BYTES)

    def test_a_claim_past_the_room_is_refused_and_the_fullest_batch_still_closes(self) -> None:
        """X104: a claim that would need another closure row past the room is refused before it commits; the batch
        filled to its room bound with every claimed-unsettled task it admits still closes."""
        batch = Batch(self)
        batch.enqueue(*((f'lint-{index:02d}', 'check', ()) for index in range(11)))
        for index in range(10):
            batch.claim(f'lint-{index:02d}', claimer=DISPATCHER)   # ten live claims, each a listable task
        batch.table = table(DISPATCHER)                            # their claimer is alive when the close reconciles
        record = batch.record()
        bound = len(canonical(record)) + settlement.settlement_reserve(record) + settlement.CLOSURE_ROW_BYTES // 2
        with patch.object(native_budget_store, 'MAX_RECORD_BYTES', bound):
            with self.assertRaisesRegex(BudgetAuthorityError, 'no room left'):
                batch.claim('lint-10', claimer=DISPATCHER)         # its closure row would not fit
            self.assertEqual(batch.record(), record)               # nothing was committed
            self.assertEqual(close(batch)['status'], 'closed')
        self.assertEqual(len(closure_rows(batch)), 10)
        self.assertEqual(batch.row('lint-10')['state'], 'cancelled')   # the unclaimed one was frozen, not listed


class ClosureValidatorTests(unittest.TestCase):
    """``production.closure`` belongs to a closed batch, at its closing time, listing its own tasks once."""

    def test_closure_refused_on_an_open_batch(self) -> None:
        """Each malformed closure is refused by name when the record is validated."""
        record = Batch(self).record()
        row = {'taskId': 'director', 'kind': 'director', 'state': 'running', 'host': 'codex', 'hostProcess': None,
               'reason': None}
        cases = [
            ('active', {'closedElapsed': 0.0, 'unresolvedAtClose': []}, 'belongs to a closed batch only'),
            ('closed', {'closedElapsed': 9.0, 'unresolvedAtClose': []}, 'closedElapsed must equal the batch'),
            ('closed', {'closedElapsed': 5.0}, 'must hold exactly closedElapsed and unresolvedAtClose'),
            ('closed', {'closedElapsed': 5.0, 'unresolvedAtClose': [{**row, 'host': 'other'}]},
             "row: a row's host is a known host or null"),
            ('closed', {'closedElapsed': 5.0, 'unresolvedAtClose': [row, row]}, 'lists each task of this batch once'),
            ('closed', {'closedElapsed': 5.0, 'unresolvedAtClose': [{**row, 'kind': 'author'}]},
             'lists each task of this batch once, with its kind'),
        ]
        for status, closure, text in cases:
            closed = {**record, 'status': status, 'closedAtElapsed': 5.0 if status == 'closed' else None,
                      'production': {**record['production'], 'closure': closure}}
            with self.subTest(text), self.assertRaisesRegex(ValueError, f'production.closure {text}'):
                validate_record(closed)


class ArchiveTests(unittest.TestCase):
    """Archive needs every unsettled task in the closure and the host record, and keeps the host record's charge."""

    def test_missing_host_rows_are_appended_before_archive_checks(self) -> None:
        """Archive appends the closure rows the host record lacks before it checks (a no-op normally)."""
        batch = held_batch(self)
        close(batch)
        (batch.root / RECORD).unlink()   # the host record lost the rows (restored from an older copy, say)
        archive_batch(batch.root, BATCH, 'TEST archive')
        self.assertEqual(recorded_task_ids(batch.root, BATCH), {'critic'})

    def test_archive_refuses_unresolved_work_missing_from_the_closure(self) -> None:
        """Unsettled work its closure does not list keeps the batch from archiving, refused by name."""
        batch = held_batch(self)
        close(batch)
        rewrite(batch, lambda record: record['production']['closure'].update(unresolvedAtClose=[]))
        with self.assertRaises(BudgetRefused) as refused:
            archive_batch(batch.root, BATCH, 'TEST archive')
        self.assertEqual(str(refused.exception), ARCHIVE_REFUSAL)

    def test_archive_refusal_needs_the_host_record_rows_too(self) -> None:
        """X114 m5: a closure that lists the work is not enough; the host record must hold its rows as well."""
        batch = held_batch(self)
        close(batch)
        record = batch.record()
        self.assertIsNone(lifecycle.archive_refusal(record, batch.root))
        (batch.root / RECORD).unlink()   # the closure still lists critic; the host record does not
        self.assertEqual(lifecycle.archive_refusal(record, batch.root), ARCHIVE_REFUSAL)

    def test_archive_keeps_the_charge_in_the_host_record(self) -> None:
        """An archived batch's unresolved work stays open in the host record, charged against its host."""
        batch = held_batch(self)
        close(batch)
        archive_batch(batch.root, BATCH, 'TEST archive')
        self.assertFalse((batch.root / 'batches' / BATCH).exists())
        self.assertTrue((batch.root / 'archive' / BATCH).exists())
        self.assertEqual([row['taskId'] for row in open_rows(batch.root, 'codex')], ['critic'])


if __name__ == '__main__':
    unittest.main()
