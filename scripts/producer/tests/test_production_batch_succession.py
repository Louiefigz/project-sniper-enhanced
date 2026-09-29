"""M-043: a new batch waits for its predecessor (X25, X114).

A draining batch (an explicit drain, or a close while media is live) refuses a new batch, its own archive, every
reservation and new tasks, by name. A closed batch whose closure lists unresolved AI work refuses a new batch by
name until termination evidence resolves that work (X114 M4): until M-100 counts the host record's open rows at
admission, creation fails closed, archived or not. Code work left at closure does not hold a new batch.
Registry batches (``RegistryCase``) on private roots and fake clocks; no child process is started.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest
from unittest import mock

import native_batch
from _budget_fixture import DIRECTOR, DISPATCHER, FINGERPRINT, host_turn, receipt, table, task_spec
from test_native_budget_registry import RegistryCase, ns
from studio import native_budget_batches as batches
from studio import native_budget_launch as launch
from studio import native_budget_registry as registry
from studio.production import api
from studio.production.callbacks import TaskResult
from studio.production.claims import ClaimRef, Enrollment
from studio.production.unresolved_executions import Execution, open_rows, resolve

BATCH = 'batch-auth'
AI_REFUSAL = ('Batch batch-auth closed with unresolved AI work (batch-auth/critic) still charged in '
              'unresolved-executions.jsonl; a new batch waits until termination evidence resolves it (fail closed '
              'until admission counts it, M-100)')


class SuccessionCase(RegistryCase):
    """``batch-auth`` with its enrolled codex director and one clip-A review task, ``critic``."""

    def setUp(self) -> None:
        """RegistryCase's batch, with the director enrolled and the critic enqueued under it."""
        super().setUp()
        api.enroll_director(self.root, BATCH, Enrollment('director', DIRECTOR, 'v1', FINGERPRINT))
        api.enqueue_tasks(self.root, BATCH, (task_spec('critic', 'review', clip_id='A', parent='director'),))

    def archive(self) -> dict:
        """Archive ``batch-auth`` through the coordinator CLI."""
        return native_batch.cmd_archive(ns(batch=BATCH, reason='TEST operator released it'))


class DrainingSuccessionTests(SuccessionCase):
    """A draining batch keeps its unresolved work until it settles, and nothing new starts beside it (M3)."""

    def test_a_drained_batch_refuses_a_successor_its_archive_reservations_and_new_tasks(self) -> None:
        """After an explicit drain: a new batch, the archive, a reservation for an unbound project or the batch's own
        project, and a new task are each refused by name; the batch stays draining."""
        self.clock.advance(2400)
        self.assertEqual(api.drain(self.root, BATCH, 'TEST operator stopped the run')['status'], 'draining')
        with self.assertRaisesRegex(batches.PredecessorCurrent, 'Batch batch-auth is still draining'):
            self.start('batch-next', ('A',))
        with self.assertRaisesRegex(registry.BudgetRefused, 'Only a closed batch'):
            self.archive()
        for project in (self.unrelated(), self.project):   # an unbound project, then the batch's own
            with self.subTest(project.name), self.assertRaisesRegex(registry.BudgetRefused, 'is draining'):
                self.reserve(project)
        with self.assertRaisesRegex(registry.BudgetRefused, 'draining'):
            api.enqueue_tasks(self.root, BATCH, (task_spec('late', parent='director'),))
        self.assertEqual(self.record()['status'], 'draining')
        self.assertNotIn('batch-next', batches.list_batches(self.root))


class ClosedSuccessionTests(SuccessionCase):
    """X114 M4: a closure's unresolved AI work holds every new batch until termination evidence resolves it."""

    def held_critic(self) -> None:
        """The critic completes on a codex turn: ended, with its slot held (G9: no host end evidence)."""
        claimed = api.claim_task(self.root, BATCH, 'critic', host_turn('critic'))
        ref = ClaimRef('critic', claimed['epoch'], claimed['token'])
        api.attach_task(self.root, BATCH, ref, host_turn('critic'))
        api.complete_task(self.root, BATCH, ref, TaskResult((receipt('critic'),)))

    def test_unresolved_ai_work_at_closure_refuses_a_new_batch_by_name(self) -> None:
        """Closed, then archived: the new batch is refused by name each time and nothing is created."""
        self.held_critic()
        self.close_batch()
        self.assertEqual(self.record()['status'], 'closed')
        with self.assertRaises(batches.PredecessorCurrent) as refused:
            self.start('batch-next', ('A',))
        self.assertEqual(str(refused.exception), AI_REFUSAL)
        self.archive()                                      # archived: the host record keeps the charge
        with self.assertRaises(batches.PredecessorCurrent) as refused:
            self.start('batch-next', ('A',))
        self.assertEqual(str(refused.exception), AI_REFUSAL)
        self.assertNotIn('batch-next', batches.list_batches(self.root))
        self.assertEqual([row['taskId'] for row in open_rows(self.root, 'codex')], ['critic'])

    def test_termination_evidence_lets_the_next_batch_start(self) -> None:
        """Once the host record resolves the row (G9 evidence, M-102's caller), the next batch starts."""
        self.held_critic()
        self.close_batch()
        with self.assertRaises(batches.PredecessorCurrent):
            self.start('batch-next', ('A',))
        self.assertTrue(resolve(self.root, Execution(BATCH, 'critic'),
                                {'basis': 'host-end', 'detail': 'TEST host end event for critic'}))
        self.start('batch-next', ('A',))
        self.assertIn('batch-next', batches.list_batches(self.root))

    def test_code_work_left_at_closure_does_not_hold_a_new_batch(self) -> None:
        """A check still claimed by a live dispatcher is listed with a null host, yet it is not AI work (X114)."""
        api.enqueue_tasks(self.root, BATCH, (task_spec('lint', 'check', parent='director'),))
        api.claim_task(self.root, BATCH, 'lint', DISPATCHER)
        with mock.patch.object(launch, '_process_table', return_value=table(DISPATCHER)):
            self.close_batch()
        rows = self.record()['production']['closure']['unresolvedAtClose']
        self.assertEqual([(row['taskId'], row['kind'], row['host']) for row in rows], [('lint', 'check', None)])
        self.start('batch-next', ('A',))
        self.assertIn('batch-next', batches.list_batches(self.root))


if __name__ == '__main__':
    unittest.main()
