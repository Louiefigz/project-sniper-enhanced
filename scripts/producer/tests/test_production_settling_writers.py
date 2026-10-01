"""Settling writers are bounded (X217 M1, m2): what a full trail may still owe is counted, never repeated.

DrainingCloseTests (m2a): a close that leaves a draining batch draining records nothing. StatementTests (m2b): one
operator statement per task and phase; a second is refused by name and writes nothing. ContinuationLineTests (M1):
a review continuation's outcome line is bounded. CommitLineTests (M1): a failed commit's error is escaped and cut,
and past the stop an unsynced commit stands without its ``commit-unsynced`` line. Private roots, fake clocks and
TEST process tables; no child process is started.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import unittest
from unittest import mock

from _budget_fixture import CHILD, DISPATCHER, table
from _production_task_flow_fixture import BATCH, Batch, close, held_batch, host, rewrite
from studio import native_budget_continuation as continuation, native_budget_store as store
from studio.native_budget_binding import advance_clock
from studio.native_budget_store import BudgetAuthorityError, locked_batch
from studio.native_budget_trail import ERROR_TEXT_CHARS, error_text
from studio.production import api
from studio.production.settlement import RESULT_TEXT_BYTES
from studio.production.tasks import TaskRefused
import test_native_section_budget_continuation as continuation_tests   # its fixture setUp and reserve
from test_queue_clock_stall_c import FullTrailCase

STATEMENT = 'TEST operator: the turn ended on the host console'


class DrainingCloseTests(unittest.TestCase):
    """m2a: ``close`` on a draining batch with live media writes nothing until it closes."""

    def test_close_while_draining_writes_once(self) -> None:
        """Five closes of a draining batch change nothing; the close after the media ends closes it."""
        batch = Batch(self)
        batch.table = table(CHILD, DISPATCHER)                     # media stays live
        batch.enqueue(('media-a', 'media', ()))
        batch.claim('media-a', CHILD, DISPATCHER)
        self.assertEqual(close(batch)['status'], 'draining')
        authority = batch.root / 'batches' / BATCH / 'authority.json'
        before = (authority.read_bytes(), len(batch.events()))
        for _ in range(5):
            result = api.close(batch.root, BATCH)
            self.assertEqual((result['status'], result['committed'], result['reconciled']), ('draining', False, []))
        self.assertEqual((authority.read_bytes(), len(batch.events())), before)
        batch.table = table()
        self.assertEqual(api.close(batch.root, BATCH)['status'], 'closed')
        self.assertEqual([row['event'] for row in batch.events()].count('batch-draining'), 1)


class StatementTests(unittest.TestCase):
    """m2b: ``settle-resource`` records one statement per task and phase."""

    def test_a_second_statement_on_an_unresolved_resource_is_refused_by_name(self) -> None:
        """The second statement on an unresolved slot is refused by name and nothing is written."""
        batch = held_batch(self)
        api.settle_resource(batch.root, BATCH, 'critic', STATEMENT)
        authority = batch.root / 'batches' / BATCH / 'authority.json'
        before = (authority.read_bytes(), len(batch.events()))
        with self.assertRaisesRegex(TaskRefused, "^Task critic already has the operator's statement on its unresolved "
                                                 'resource; one statement is recorded per task and phase$'):
            api.settle_resource(batch.root, BATCH, 'critic', 'TEST a second statement')
        self.assertEqual((authority.read_bytes(), len(batch.events())), before)
        line = [row for row in batch.events() if row['event'] == 'task-resource-settled'][-1]
        self.assertEqual(line['phase'], 'unresolved resource')

    def test_revoked_live_work_takes_one_statement_on_its_revocation(self) -> None:
        """Revoked live work takes one statement, recorded with its revocation phase."""
        batch = Batch(self)
        batch.enqueue(('critic', 'specialist', ()))
        batch.claim('critic', host('critic'))
        rewrite(batch, lambda record: record['production']['tasks']['critic'].update(revoked=True))
        api.settle_resource(batch.root, BATCH, 'critic', STATEMENT)
        with self.assertRaisesRegex(TaskRefused, 'statement on its revocation; one statement is recorded'):
            api.settle_resource(batch.root, BATCH, 'critic', STATEMENT)
        lines = [row for row in batch.events() if row['event'] == 'task-resource-settled']
        self.assertEqual([row['phase'] for row in lines], ['revocation'])


class ContinuationLineTests(unittest.TestCase):
    """M1: a review continuation's outcome line cuts its status and leaves the output path to its start line."""

    def setUp(self) -> None:
        """The continuation fixture: a settled render attempt with its launch charge intact."""
        continuation_tests.ReviewContinuationTests.setUp(self)

    def test_the_outcome_line_is_bounded(self) -> None:
        """A 10,000-character result status is cut to RESULT_TEXT_BYTES and the output path is not repeated."""
        budget = continuation_tests.ReviewContinuationTests.reserve(self)
        request = {**self.fixture.request, 'productionBudget': budget}
        event = continuation.apply_review_outcome(self.fixture.record(), request, {'status': 'x' * 10_000}, 0)
        self.assertEqual((event['event'], event['status']), ('launch-completed', 'x' * RESULT_TEXT_BYTES))
        self.assertNotIn('output', event)


class CommitLineTests(FullTrailCase):
    """M1: what a failed or unsynced commit adds to the trail is bounded, and past the stop nothing for unsynced."""

    def commit_with(self, failure: object) -> None:
        """Commit a settling TEST line (the clock advanced, so the record changes) while the record replace behaves
        as ``failure`` makes it."""
        self.clock.advance(1.0)
        with mock.patch.object(store, 'write_pending_replace', side_effect=failure):
            with locked_batch(self.root, 'batch-auth') as session:
                record = session.read()
                advance_clock(record)
                session.commit(record, {'event': 'task-superseded', 'taskIds': [], 'reason': 'TEST'})

    def test_a_failed_commit_line_carries_the_escaped_cut_error(self) -> None:
        """A failed replace's commit-failed line carries error_text of the error, 96 characters."""
        error = OSError('\U0001F600\n' * 1000)
        with self.assertRaises(BudgetAuthorityError):
            self.commit_with(error)
        line = json.loads(self.trail.read_text().splitlines()[-1])
        self.assertEqual((line['event'], line['error']), ('commit-failed', error_text(error)))
        self.assertEqual(len(line['error']), ERROR_TEXT_CHARS)

    def test_past_the_stop_an_unsynced_commit_stands_without_its_line(self) -> None:
        """At a full trail a replaced but unsynced commit stands and its commit-unsynced line is not written."""
        real = store.write_pending_replace

        def replace_then_fail(dir_fd: int, names: tuple, data: bytes) -> None:
            """Replace the record, then fail as a lost directory sync would."""
            real(dir_fd, names, data)
            raise OSError('TEST directory fsync failed')
        self.fill()
        self.commit_with(replace_then_fail)
        self.assertEqual(json.loads(self.trail.read_text().splitlines()[-1])['event'], 'task-superseded')


if __name__ == '__main__':
    unittest.main()
