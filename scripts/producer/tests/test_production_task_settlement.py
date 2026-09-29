"""M-043's settlement and closure tests (X25, X29, X37); its reconcile and historical-row tests are in
``test_production_task_reconcile``, its closure room, validator and archive tests in
``test_production_closure_record``, and a batch's successor in ``test_production_batch_succession``.

``settle-resource`` records the operator's statement and never releases. Closure ends only the director's batch
assignment, revokes live AI work, lists every task still holding a slot or an unresolved resource in
``production.closure``, and appends those rows to the host record inside the closing transaction; while media
work is live or a media launch is running it drains instead. Batches are ``_production_task_flow_fixture.Batch``
(private roots, fake clocks, TEST handles and a TEST process table); no test starts a child process.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest
from unittest.mock import Mock

from _budget_fixture import CHILD, DISPATCHER, table
from _production_task_flow_fixture import BATCH, Batch, close, closure_rows, finish, held_batch, host, rewrite, run_cli
from _status_fixture import ALIVE, attempt
from studio.native_budget_store import BudgetAuthorityError
from studio.production import api
from studio.production.callbacks import TaskFailure
from studio.production.task_schema import holds_slot
from studio.production.tasks import active_ai
from studio.production.unresolved_executions import RECORD, open_rows, recorded_task_ids

STATEMENT = 'TEST operator: the turn ended on the host console'
DIRECTOR_END = {'taskId': 'director', 'endCause': 'closure', 'slotReleased': True, 'toolCleanup': 'unproven'}


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
        self.assertEqual((result['status'], result['directorEnd'], result['revoked']),
                         ('closed', DIRECTOR_END, ['critic']))
        director = batch.row('director')
        self.assertEqual((director['state'], director['unresolved'], director['endConfirmed']),
                         ('completed', False, True))
        self.assertFalse(director['cancelRequested'] or director['revoked'])
        self.assertIn("director's batch assignment ended", director['reason'])
        self.assertEqual((batch.row('critic')['state'], batch.row('critic')['revoked']), ('cancel-requested', True))
        self.assertEqual(closure_rows(batch), [('critic', 'specialist', 'cancel-requested', 'codex')])
        # X114 m4: the trail records the director's end (its end fields, M-041) and the revocations.
        event = batch.events()[-1]
        self.assertEqual((event['event'], event['directorEnd'], event['revoked']),
                         ('batch-closed', DIRECTOR_END, ['critic']))

    def test_a_cancel_requested_director_ends_cancelled_at_close(self) -> None:
        """X114 m3: a director already asked to stop ends ``cancelled`` at closure, its assignment released (X29)."""
        batch = Batch(self)
        api.request_cancel(batch.root, BATCH, 'director', 'TEST operator stop')
        self.assertEqual(close(batch)['directorEnd'], DIRECTOR_END)
        director = batch.row('director')
        self.assertEqual((director['state'], director['unresolved'], director['endConfirmed'], director['revoked']),
                         ('cancelled', False, True, False))
        self.assertIn("director's batch assignment ended", director['reason'])
        self.assertFalse(holds_slot(director))
        self.assertEqual(closure_rows(batch), [])

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

    def test_an_ai_task_on_a_process_handle_is_listed_with_a_null_host(self) -> None:
        """X114 m9: an AI execution acknowledged by a process handle is a process, not its claimer's host turn: its
        row's host is null, so it counts against every host (fail closed, X85)."""
        batch = Batch(self)
        batch.enqueue(('writer', 'specialist', ()))
        batch.claim('writer', CHILD)             # claimed by the codex director, acknowledged by a process
        batch.table = table(CHILD)               # the process is alive when the close reconciles
        self.assertEqual(close(batch)['revoked'], ['writer'])
        self.assertEqual(closure_rows(batch), [('writer', 'specialist', 'cancel-requested', None)])
        for name in ('codex', 'claude-code'):
            self.assertEqual([row['taskId'] for row in open_rows(batch.root, name)], ['writer'])

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
        # X125: each row carries its task's reason (the failure's detail, or the G9 note of a held slot).
        rows = after['production']['closure']['unresolvedAtClose']
        self.assertEqual([row['reason'] for row in rows],
                         [after['production']['tasks'][key]['reason'] for key in ('critic', 'writer')])
        self.assertIn('no launch error', rows[1]['reason'])
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

    def test_close_waits_for_a_running_media_launch(self) -> None:
        """X114 m2: a running launch with no live media task (a watchdog stop keeps its attempt running) drains the
        batch with no closure; once its supervisor is provably gone, the close abandons it and closes."""
        batch = held_batch(self)
        launch = attempt('final', 10.0, status='running')
        rewrite(batch, lambda record: record['clips']['A']['attempts'].append(launch))
        batch.table = table({'type': 'process', **ALIVE})   # the launch's supervisor is alive
        result = close(batch)
        self.assertEqual((result['status'], result['runningAttempts']), ('draining', [launch['id']]))
        self.assertNotIn('closure', batch.record()['production'])
        self.assertFalse((batch.root / RECORD).exists())
        batch.table = table()                                # the supervisor exited without an outcome
        self.assertEqual(close(batch)['status'], 'closed')
        self.assertEqual(batch.record()['clips']['A']['attempts'][-1]['status'], 'abandoned')
        self.assertEqual(closure_rows(batch), [('critic', 'specialist', 'completed', 'codex')])

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
