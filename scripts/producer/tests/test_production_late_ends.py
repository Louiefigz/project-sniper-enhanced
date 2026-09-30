"""P1 review point 2 (X181): AI ends that must go through the one end rule and keep their slot until evidence (G9).

MA1: an execution that attaches after its claim's deadline is refused, yet it exists, so its handle is bound and its
end is settled through ``task_end`` with the slot held; a process handle is freed once reconcile sees it gone. Media
and check claims keep the plain expiry. C05: releasing a claim superseded before launch records its end fields. G02:
reconcile frees a completed process-handle AI task once its exact process is gone. Batches are
``_production_task_flow_fixture.Batch`` (private roots, fake clocks, TEST handles and a TEST process table); no test
starts a child process.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest

from _budget_fixture import CHILD, DISPATCHER, private_root, receipt, table
from _production_task_flow_fixture import BATCH, Batch, host
from studio.production import api
from studio.production.callbacks import TaskResult
from studio.production.claims import ClaimRef
from studio.production.task_schema import holds_slot
from studio.production.tasks import TaskRefused, active_ai

LATE = 1790   # inside the cleanup reserve (45 s) plus the minimum stage (1 s) before the tasks' 1800 s deadline
LAUNCH_ERROR = 'TEST launch tool: spawn failed (ENOENT)'
END_KEYS = ('event', 'category', 'handle', 'unresolved', 'endCause', 'slotReleased')


class LateAttachTests(unittest.TestCase):
    """MA1: a late attach is still refused, but the attaching AI execution is bound and its slot stays held."""

    def late(self, batch: Batch, task_id: str, handle: dict, claimer: dict | None = None) -> ClaimRef:
        """Claim ``task_id`` (for the director unless ``claimer`` is given), then attach ``handle`` after the deadline;
        the attach is refused by name."""
        ref = batch.claim(task_id, claimer=claimer)
        batch.clock.advance(LATE)
        with self.assertRaisesRegex(TaskRefused, rf'^Task {task_id} reached its deadline \(1800s\) before launch$'):
            api.attach_task(batch.root, BATCH, ref, handle)
        return ref

    def test_a_host_turn_attaching_late_is_bound_and_held(self) -> None:
        """Codex and Claude Code: the task fails with the turn bound and its slot held (no active AI slot frees),
        and the ``task-failed`` event records the handle and the rule's end fields."""
        for kind in ('codex', 'claude-code'):
            with self.subTest(kind):
                batch = Batch(self, root=private_root(self))
                batch.enqueue(('critic', 'specialist', ()))
                turn = host('critic', kind)
                before = active_ai(batch.record()) + 1          # the claim below takes one slot
                self.late(batch, 'critic', turn)
                row = batch.row('critic')
                self.assertEqual((row['state'], row['unresolved'], row['endConfirmed'], row['handle']),
                                 ('failed', True, True, turn))
                self.assertTrue(holds_slot(row))
                self.assertEqual(active_ai(batch.record()), before)
                event = batch.events()[-1]
                self.assertEqual({key: event.get(key) for key in END_KEYS},
                                 {'event': 'task-failed', 'category': 'deadline-expired', 'handle': turn,
                                  'unresolved': True, 'endCause': 'host-ended', 'slotReleased': False})
                self.assertIn(event['toolCleanup'], ('proved', 'unproven'))

    def test_a_process_attaching_late_is_held_until_reconcile_sees_it_gone(self) -> None:
        """A process handle: bound and held at the late attach; freed once reconcile sees the exact process gone."""
        batch = Batch(self)
        batch.enqueue(('critic', 'specialist', ()))
        batch.table = table(CHILD)                              # the attaching process is alive
        before = active_ai(batch.record()) + 1
        self.late(batch, 'critic', CHILD)
        row = batch.row('critic')
        self.assertEqual((row['state'], row['unresolved'], row['handle'], active_ai(batch.record())),
                         ('failed', True, CHILD, before))
        batch.table = table()                                   # it exited and its process group is empty
        api.reconcile(batch.root, BATCH)
        row = batch.row('critic')
        self.assertEqual((row['state'], row['unresolved'], active_ai(batch.record())), ('failed', False, before - 1))

    def test_a_check_claim_attaching_late_keeps_the_plain_expiry(self) -> None:
        """Check work holds no AI slot: the late attach fails the task as before, with no handle bound, nothing held
        and no end fields."""
        batch = Batch(self)
        batch.enqueue(('lint', 'check', ()))
        batch.table = table(DISPATCHER, CHILD)
        self.late(batch, 'lint', CHILD, DISPATCHER)
        row = batch.row('lint')
        self.assertEqual((row['state'], row['unresolved'], row['handle']), ('failed', False, None))
        self.assertEqual(batch.events()[-1]['event'], 'task-failed')
        self.assertNotIn('endCause', batch.events()[-1])


class ReleaseAndReconcileEndTests(unittest.TestCase):
    """C05 and G02: the release of a superseded claim, and reconcile's end of a completed process handle."""

    def test_a_superseded_unlaunched_release_records_its_end(self) -> None:
        """A claim superseded before launch, then released with the launch tool's error: the end is confirmed with
        cause ``unlaunched`` and its slot released, in the record and in the ``task-released`` event."""
        batch = Batch(self)
        batch.enqueue(('writer', 'specialist', ()))
        ref = batch.claim('writer')
        api.supersede_task(batch.root, BATCH, 'writer', 'TEST replaced before launch')
        self.assertEqual((batch.row('writer')['state'], batch.row('writer')['unresolved']), ('superseded', True))
        before = active_ai(batch.record())
        api.release_claim(batch.root, BATCH, ref, LAUNCH_ERROR)
        row = batch.row('writer')
        self.assertEqual((row['state'], row['unresolved'], row['endConfirmed']), ('superseded', False, True))
        self.assertEqual(active_ai(batch.record()), before - 1)
        event = batch.events()[-1]
        self.assertEqual({key: event.get(key) for key in ('event', 'endCause', 'slotReleased', 'launchError')},
                         {'event': 'task-released', 'endCause': 'unlaunched', 'slotReleased': True,
                          'launchError': LAUNCH_ERROR})

    def test_a_completed_process_handle_is_freed_once_reconcile_sees_it_gone(self) -> None:
        """M-042's reconcile hunk: the completion holds the slot while the process runs; reconcile frees it once
        the exact process is gone (a TEST process table)."""
        batch = Batch(self)
        batch.enqueue(('critic', 'specialist', ()))
        batch.table = table(CHILD)
        ref = batch.claim('critic', CHILD)
        api.complete_task(batch.root, BATCH, ref, TaskResult((receipt('critic'),)))
        held = (batch.row('critic')['state'], batch.row('critic')['unresolved'], active_ai(batch.record()))
        batch.table = table()
        api.reconcile(batch.root, BATCH)
        after = (batch.row('critic')['state'], batch.row('critic')['unresolved'], active_ai(batch.record()))
        self.assertEqual((held, after), (('completed', True, 2), ('completed', False, 1)))


if __name__ == '__main__':
    unittest.main()
