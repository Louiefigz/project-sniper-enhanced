"""M-043's reconcile and historical-row tests: reconcile reads evidence through the one end rule (P1 A3), and a
pre-P1 completed-after-cancel row never satisfies its dependents (P1 A4).

Split from ``test_production_task_settlement`` (the 300-line cap). Batches are
``_production_task_flow_fixture.Batch`` (private roots, fake clocks, TEST handles and a TEST process table); no
test starts a child process.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest
from unittest.mock import patch

from _budget_fixture import CHILD, private_root
from _production_task_flow_fixture import BATCH, Batch, finish, host, rewrite
from studio import native_budget_launch
from studio.production import api
from studio.production.dependencies import refresh
from studio.production.reconcile import host_key
from studio.production.task_schema import holds_slot, production_problem


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


if __name__ == '__main__':
    unittest.main()
