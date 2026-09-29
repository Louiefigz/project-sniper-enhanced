"""M-043's tests: reconcile's rule (P1 A3), historical rows (A4), settlement and closure (X25, X29, X37).

``settle-resource`` records the operator's statement and never releases. Closure ends only the director's batch
assignment, revokes live AI work, lists every task still holding a slot or an unresolved resource in
``production.closure``, and appends those rows to the host record inside the closing transaction. Archive keeps
the charge in the host record. Batches are ``_production_task_flow_fixture.Batch`` (private roots, fake clocks,
TEST handles and a TEST process table); no test starts a child process.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest
from unittest.mock import Mock, patch

from _budget_fixture import CHILD, DISPATCHER, private_root, table
from _production_task_flow_fixture import (
    BATCH, Batch, close, closure_rows, finish, held_batch, host, rewrite, run_cli,
)
from studio import native_budget_launch, native_budget_store
from studio.native_budget_batches import BudgetRefused, archive_batch
from studio.native_budget_schema import validate_record
from studio.native_budget_store import BudgetAuthorityError, canonical
from studio.production import api, settlement
from studio.production.callbacks import TaskFailure
from studio.production.dependencies import refresh
from studio.production.production_optional import closure_problem
from studio.production.reconcile import host_key
from studio.production.task_schema import holds_slot, production_problem
from studio.production.tasks import active_ai
from studio.production.unresolved_executions import RECORD, open_rows, recorded_task_ids

STATEMENT = 'TEST operator: the turn ended on the host console'
ARCHIVE_REFUSAL = ('Batch batch-auth holds unresolved work not recorded at closure '
                   '(production.closure/unresolved-executions.jsonl)')


class ReconcileRuleTests(unittest.TestCase):
    """Reconcile reads evidence through the same rule (P1 A3)."""

    def test_observed_terminal_holds_on_both_hosts(self) -> None:
        """A host turn seen terminal is lost: abandoned with its slot held, on either host."""
        for kind in ('codex', 'claude-code'):
            with self.subTest(host=kind):
                batch, handle = Batch(self, root=private_root(self)), host('critic', kind)
                batch.enqueue(('critic', 'specialist', ()))
                batch.claim('critic', handle)
                api.reconcile(batch.root, BATCH, {host_key(handle): 'terminal'})
                task = batch.row('critic')
                self.assertEqual((task['state'], task['unresolved'], holds_slot(task)), ('abandoned', True, True))

    def test_host_lost_abandons_with_slot_held(self) -> None:
        """A host that no longer knows the turn: abandoned, slot held."""
        batch = Batch(self)
        batch.enqueue(('critic', 'specialist', ()))
        batch.host_event(batch.claim('critic', host('critic')), 'lost', host('critic'))
        self.assertEqual((batch.row('critic')['state'], batch.row('critic')['unresolved']), ('abandoned', True))

    def test_unreadable_process_table_changes_nothing(self) -> None:
        """No evidence means no change: an unreadable process table leaves a process-handle task running."""
        batch = Batch(self)
        batch.enqueue(('critic', 'review', ()))
        batch.claim('critic', CHILD)
        with patch.object(native_budget_launch, '_process_table', side_effect=OSError('TEST: ps unavailable')):
            result = api.reconcile(batch.root, BATCH)
        self.assertEqual(result['changes'], [])
        self.assertEqual(batch.row('critic')['state'], 'running')


class HistoricalRowTests(unittest.TestCase):
    """A pre-P1 completed-after-cancel row never satisfies its dependents (P1 A4)."""

    def test_completed_cancel_requested_prerequisite_fails_its_dependents(self) -> None:
        """The pre-P1 row reads valid; refresh fails its dependent as prerequisite-cancelled."""
        batch = Batch(self)
        batch.enqueue(('graphics', 'specialist', ()), ('synthesis', 'planning', ('graphics',)))
        finish(batch, 'graphics')
        # The row as a pre-P1 engine wrote it (F1 D01): completed, with its cancellation requested.
        rewrite(batch, lambda record: record['production']['tasks']['graphics'].update(cancelRequested=True))
        record = batch.record()
        self.assertIsNone(production_problem(record))
        self.assertEqual(record['production']['tasks']['synthesis']['state'], 'ready')
        refresh(record, 20.0)
        synthesis = record['production']['tasks']['synthesis']
        self.assertEqual((synthesis['state'], synthesis['failure']['category']), ('failed', 'prerequisite-cancelled'))


class SettlementTests(unittest.TestCase):
    """``settle-resource`` records the operator's statement and never releases anything (G9, X25)."""

    def test_settle_resource_cli_records_and_never_releases(self) -> None:
        """Active, then draining: the statement reaches the event and the reason; slot, charge and flags stay."""
        batch = Batch(self)
        batch.enqueue(('critic', 'specialist', ()), ('writer', 'specialist', ()))
        finish(batch, 'critic')
        finish(batch, 'writer')
        before = batch.record()
        settle = ('settle-resource', '--batch', BATCH, '--statement', STATEMENT, '--task')
        self.assertEqual(run_cli(*settle, 'critic')[0], 0)
        batch.clock.advance(2500)
        self.assertEqual(api.drain(batch.root, BATCH, 'TEST drain')['status'], 'draining')
        self.assertEqual(run_cli(*settle, 'writer')[0], 0)
        after = batch.record()
        for task_id in ('critic', 'writer'):
            task = after['production']['tasks'][task_id]
            self.assertTrue(task['unresolved'] and holds_slot(task))
            self.assertIn(f'operator statement (not evidence): {STATEMENT}', task['reason'])
        self.assertEqual(active_ai(after), active_ai(before))
        self.assertEqual(after['production']['ai'], before['production']['ai'])
        settled = [row for row in batch.events() if row['event'] == 'task-resource-settled']
        self.assertEqual([(row['taskId'], row['basis'], row['statement']) for row in settled],
                         [('critic', 'operator-statement', STATEMENT), ('writer', 'operator-statement', STATEMENT)])
        code, out = run_cli('settle-resource', '--batch', BATCH, '--statement', '  ', '--task', 'critic')
        self.assertEqual((code, out['error']), (2, "ValueError: Settling records the operator's statement"))


class ClosureTests(unittest.TestCase):
    """Closure in MASTER-PLAN M-043's order (1)-(7): only the director's batch assignment is released."""

    def test_close_ends_the_director_first_and_never_revokes_it(self) -> None:
        """The director's assignment ends with the closure (X29): completed and released, never frozen or revoked."""
        batch = Batch(self)
        batch.enqueue(('critic', 'specialist', ()))
        batch.claim('critic', host('critic'))
        result = close(batch)
        self.assertEqual((result['status'], result['directorEnded']), ('closed', 'director'))
        director = batch.row('director')
        self.assertEqual((director['state'], director['unresolved'], director['endConfirmed']),
                         ('completed', False, True))
        self.assertFalse(director['cancelRequested'] or director['revoked'])
        self.assertIn("director's batch assignment ended", director['reason'])
        self.assertEqual((batch.row('critic')['state'], batch.row('critic')['revoked']), ('cancel-requested', True))
        self.assertEqual(closure_rows(batch), [('critic', 'specialist', 'cancel-requested', 'codex')])

    def test_close_revokes_live_ai_tasks_and_lists_them(self) -> None:
        """Live AI work is revoked with its state and slot kept; a live check is frozen and listed; hosts per M3."""
        batch = Batch(self)
        batch.enqueue(('critic', 'specialist', ()), ('writer', 'specialist', ()), ('lint', 'check', ()),
                      ('later', 'specialist', ('critic',)))
        batch.claim('critic', host('critic'))    # running on a codex turn
        batch.claim('writer')                    # claimed by the codex director, never acknowledged
        batch.claim('lint', CHILD, DISPATCHER)   # a check task: process claimer and process handle
        batch.table = table(CHILD)               # the check's process is alive when the close reconciles
        self.assertEqual(close(batch)['revoked'], ['critic', 'writer'])
        states = {task_id: (batch.row(task_id)['state'], batch.row(task_id)['revoked'])
                  for task_id in ('critic', 'writer', 'lint', 'later')}
        self.assertEqual(states, {'critic': ('cancel-requested', True), 'writer': ('cancel-requested', True),
                                  'lint': ('cancel-requested', False), 'later': ('cancelled', False)})
        self.assertEqual(closure_rows(batch), [('critic', 'specialist', 'cancel-requested', 'codex'),   # id order
                                               ('lint', 'check', 'cancel-requested', None),
                                               ('writer', 'specialist', 'cancel-requested', 'codex')])
        self.assertEqual(active_ai(batch.record()), 2)
        # A null-host row counts against every host (gate M3, X85(4)).
        self.assertEqual([row['taskId'] for row in open_rows(batch.root, 'codex')], ['critic', 'lint', 'writer'])
        self.assertEqual([row['taskId'] for row in open_rows(batch.root, 'claude-code')], ['lint'])

    def test_close_lists_completed_residue_and_releases_nothing(self) -> None:
        """Ended work still holding its slot is listed and stays unresolved; charges and reservations stay."""
        batch = Batch(self)
        batch.enqueue(('critic', 'specialist', ()), ('writer', 'specialist', ()))
        finish(batch, 'critic')
        api.fail_task(batch.root, BATCH, batch.claim('writer'), TaskFailure('launch-failed', 'no launch error'))
        before = batch.record()
        close(batch)
        after = batch.record()
        self.assertEqual(closure_rows(batch), [('critic', 'specialist', 'completed', 'codex'),
                                               ('writer', 'specialist', 'failed', 'codex')])
        self.assertTrue(all(after['production']['tasks'][key]['unresolved'] for key in ('critic', 'writer')))
        self.assertEqual(after['production']['ai'], before['production']['ai'])
        self.assertEqual((active_ai(before), active_ai(after)), (3, 2))   # only the director's assignment ended

    def test_close_waits_for_live_media_tasks(self) -> None:
        """Live media drains the batch with no closure and no host rows; the close after its end records both."""
        batch = Batch(self)
        batch.enqueue(('critic', 'specialist', ()), ('export', 'media', ()))
        finish(batch, 'critic')
        media = batch.claim('export', claimer=DISPATCHER)
        batch.table = table(DISPATCHER)   # the dispatcher is alive: its claim is live media work, not a lost launch
        self.assertEqual(close(batch)['status'], 'draining')
        record = batch.record()
        self.assertEqual(record['production']['drain']['reason'], 'close requested with unsettled work')
        self.assertEqual(batch.row('director')['state'], 'running')
        self.assertNotIn('closure', record['production'])
        self.assertFalse((batch.root / RECORD).exists())
        api.release_claim(batch.root, BATCH, media)
        self.assertEqual(close(batch)['status'], 'closed')
        self.assertEqual(closure_rows(batch), [('critic', 'specialist', 'completed', 'codex')])
        self.assertEqual(recorded_task_ids(batch.root, BATCH), {'critic'})

    def test_close_fits_at_the_room_bound(self) -> None:
        """A batch filled to its room bound still closes; the reserve is the widest valid closure (256 rows)."""
        batch = Batch(self)
        batch.enqueue(*((f'turn-{index}', 'specialist', ()) for index in range(3)))
        for index in range(3):
            finish(batch, f'turn-{index}')
        record = batch.record()
        bound = len(canonical(record)) + settlement.settlement_reserve(record)
        self.assertGreaterEqual(settlement._lifecycle_room(record), settlement.CLOSURE_ENTRY_BYTES)
        with patch.object(native_budget_store, 'MAX_RECORD_BYTES', bound):
            self.assertEqual(close(batch)['status'], 'closed')
        widest = settlement.widest_closure()
        rows = [{**row, 'taskId': f'{index:03d}{row["taskId"][3:]}'}
                for index, row in enumerate(widest['unresolvedAtClose'])]
        probe = {'status': 'closed', 'closedAtElapsed': widest['closedElapsed'],
                 'production': {'closure': {**widest, 'unresolvedAtClose': rows},
                                'tasks': {row['taskId']: {'kind': row['kind']} for row in rows}}}
        self.assertIsNone(closure_problem(probe))
        self.assertEqual(settlement.encoded(probe['production']['closure']), settlement.encoded(widest))

    def test_closure_refused_on_an_open_batch(self) -> None:
        """``production.closure`` belongs to a closed batch, at its closing time, listing its own tasks once."""
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

    def test_close_appends_host_rows_inside_its_transaction(self) -> None:
        """The host record already holds the closure's rows when the closing commit runs (X79(1))."""
        batch, seen = held_batch(self), []
        close(batch, lambda: seen.append(recorded_task_ids(batch.root, BATCH)))
        self.assertEqual(seen, [{'critic'}])
        self.assertEqual(batch.record()['status'], 'closed')

    def test_a_refused_close_commit_overcharges_and_a_retry_appends_nothing_twice(self) -> None:
        """A refused close commit leaves the batch open with its rows charged; a retried close appends none again."""
        batch = held_batch(self)
        refused = Mock(side_effect=BudgetAuthorityError('TEST: the close commit failed (a full disk, say)'))
        with self.assertRaisesRegex(BudgetAuthorityError, 'TEST'):
            close(batch, refused)
        self.assertEqual(batch.record()['status'], 'active')
        self.assertEqual([row['taskId'] for row in open_rows(batch.root, 'codex')], ['critic'])
        self.assertEqual(close(batch)['status'], 'closed')
        self.assertEqual(len((batch.root / RECORD).read_text().splitlines()), 1)

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

    def test_archive_keeps_the_charge_in_the_host_record(self) -> None:
        """An archived batch's unresolved work stays open in the host record, charged against its host."""
        batch = held_batch(self)
        close(batch)
        archive_batch(batch.root, BATCH, 'TEST archive')
        self.assertFalse((batch.root / 'batches' / BATCH).exists())
        self.assertTrue((batch.root / 'archive' / BATCH).exists())
        self.assertEqual([row['taskId'] for row in open_rows(batch.root, 'codex')], ['critic'])

    def test_drain_leaves_the_director_running(self) -> None:
        """``drain`` freezes every task but the enrolled director; its assignment ends only at the closure."""
        batch = Batch(self)
        batch.enqueue(('critic', 'specialist', ()))
        batch.claim('critic', host('critic'))
        batch.clock.advance(2500)
        result = api.drain(batch.root, BATCH, 'TEST drain')
        self.assertEqual((result['frozen'], result['unsettled']), (['critic'], ['critic', 'director']))
        self.assertEqual((batch.row('director')['state'], batch.row('director')['cancelRequested']), ('running', False))
        close(batch)
        self.assertEqual((batch.row('director')['state'], batch.row('director')['cancelRequested']),
                         ('completed', False))


if __name__ == '__main__':
    unittest.main()
