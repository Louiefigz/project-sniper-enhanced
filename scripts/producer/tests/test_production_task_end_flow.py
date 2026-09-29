"""M-042's flows of the one end rule through the locked production API (P1 A2).

Split from ``test_production_task_end`` (MASTER-PLAN M-042, X35(k)); M-043's flows are in
``test_production_task_{settlement,reconcile}``, ``test_production_closure_record`` and
``test_production_batch_succession``. The batches are ``_production_task_flow_fixture.Batch``: private roots,
fake clocks, TEST handles and a TEST process table. Only
``test_process_handle_ai_completion_holds_until_reconcile_sees_exit`` starts a child (a TEST ``time.sleep``,
W2-D2) and reads the real process table to see it end.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import subprocess
import sys
import unittest
from unittest.mock import patch

from _budget_fixture import private_root, receipt
from _production_task_flow_fixture import BATCH, D02, REAL_TABLE, Batch, d02_end, host
from studio import native_budget_milestones
from studio.production import api, section_results
from studio.production.callbacks import TaskFailure, TaskResult
from studio.production.claims import ClaimRef
from studio.production.task_schema import holds_slot, production_problem
from studio.production.tasks import TaskConflict, TaskRefused, active_ai

LAUNCH_ERROR = 'TEST: spawn codex ENOENT'
RELEASE_REFUSAL = r"^Releasing an unlaunched claim records the launch tool's failure verbatim \(--launch-error\)$"


def launch_failure(launch_error: str | None = LAUNCH_ERROR) -> TaskFailure:
    """A launch-failed report, with the launch tool's verbatim error unless None."""
    return TaskFailure('launch-failed', 'spawn failed', None, launch_error)


class CancelWinsTests(unittest.TestCase):
    """Cancellation wins over a later reported end (D01): the result is kept as history, never published."""

    def cancelled(self, late: bool = False) -> tuple[Batch, ClaimRef]:
        """D01: graphics runs on a codex turn, synthesis depends on it, and the director cancels graphics.

        With ``late``, graphics' completion then arrives.
        """
        batch = Batch(self)
        batch.enqueue(('graphics', 'specialist', ()), ('synthesis', 'planning', ('graphics',)))
        ref = batch.claim('graphics', host('graphics'))
        batch.clock.advance(5)
        api.request_cancel(batch.root, BATCH, 'graphics', 'director cancelled the graphics proposal')
        batch.clock.advance(5)
        if late:
            api.complete_task(batch.root, BATCH, ref, TaskResult((receipt('graphics'),)))
        return batch, ref

    def assert_history(self, batch: Batch, receipts: list[dict]) -> None:
        """Graphics ended cancelled with its slot held and its receipts kept; synthesis failed with it."""
        graphics, synthesis = batch.row('graphics'), batch.row('synthesis')
        self.assertEqual(graphics['state'], 'cancelled')
        self.assertEqual(graphics['receipts'], receipts)
        self.assertTrue(graphics['cancelRequested'] and graphics['endConfirmed'] and graphics['unresolved'])
        self.assertIsNone(graphics['failure'])
        self.assertEqual(synthesis['state'], 'failed')
        self.assertEqual(synthesis['failure']['category'], 'prerequisite-cancelled')

    def test_completion_after_cancel_request_ends_cancelled_with_history(self) -> None:
        """The D01 sequence: no dependent becomes ready, the record validates, the trail ends task-cancelled."""
        batch, _ = self.cancelled(late=True)
        self.assert_history(batch, [receipt('graphics')])
        self.assertNotIn('synthesis', [row['taskId'] for row in api.next_ready(batch.root, BATCH)])
        self.assertIsNone(production_problem(batch.record()))
        events = batch.events()
        self.assertEqual([row['event'] for row in events[-4:]],
                         ['task-claimed', 'task-attached', 'task-cancel-requested', 'task-cancelled'])
        self.assertFalse(events[-1]['publishable'])

    def test_duplicate_late_completion_is_a_replay(self) -> None:
        """The same late completion again commits nothing."""
        batch, ref = self.cancelled(late=True)
        replay = api.complete_task(batch.root, BATCH, ref, TaskResult((receipt('graphics'),)))
        self.assertTrue(replay['replayed'])
        self.assertFalse(replay['committed'])

    def test_late_completion_with_other_receipts_conflicts(self) -> None:
        """A different late result is a conflict, named as a cancelled end."""
        batch, ref = self.cancelled(late=True)
        with self.assertRaisesRegex(TaskConflict, 'already ended as cancelled'):
            api.complete_task(batch.root, BATCH, ref, TaskResult((receipt('other'),)))

    def test_confirm_cancelled_after_late_completion_is_a_replay(self) -> None:
        """The host's cancellation confirmation after the late completion changes nothing."""
        batch, ref = self.cancelled(late=True)
        self.assertTrue(api.confirm_cancelled(batch.root, BATCH, ref)['replayed'])

    def test_host_event_completion_after_cancel_ends_cancelled(self) -> None:
        """The same sequence through the host bridge (``probe_d01_d02.py:117-130``)."""
        batch, ref = self.cancelled()
        self.assertEqual(batch.host_event(ref, 'completed', host('graphics'))['state'], 'cancelled')
        self.assert_history(batch, [receipt('graphics')])

    def test_failure_after_cancel_request_ends_cancelled(self) -> None:
        """A late failure ends cancelled with no failure row and its category in the reason; a repeat replays."""
        batch, ref = self.cancelled()
        api.fail_task(batch.root, BATCH, ref, TaskFailure('host-failure', 'the turn errored'))
        self.assert_history(batch, [])
        self.assertIn('host-failure', batch.row('graphics')['reason'])
        repeat = api.fail_task(batch.root, BATCH, ref, TaskFailure('host-failure', 'the turn errored again'))
        self.assertTrue(repeat['replayed'])

    def test_cancel_precedes_deadline_expiry(self) -> None:
        """A completion after the cancel request and after the task deadline ends cancelled, not deadline-expired."""
        batch, ref = self.cancelled()
        batch.clock.advance(1900)   # past the task's 1800 s deadline
        api.complete_task(batch.root, BATCH, ref, TaskResult((receipt('graphics'),)))
        self.assert_history(batch, [receipt('graphics')])

    def test_section_current_refuses_cancel_requested_and_accepts_completed_residue(self) -> None:
        """``current``: a cancel request refuses; a completed result holding its slot passes; other residue refuses."""
        section_results.current({'state': 'completed', 'unresolved': True}, ('completed',))
        refused = [{'state': 'running', 'cancelRequested': True}, {'state': 'superseded', 'unresolved': True}]
        for task in refused:
            with self.subTest(task=task), self.assertRaisesRegex(ValueError, 'not current'):
                section_results.current(task, (task['state'],))

    def test_section_result_after_cancel_settles_as_history(self) -> None:
        """A section author's result after a cancel request is rehashed as history and never read as current."""
        import test_production_sections as sections
        harness = sections.ProductionSectionsTests('test_authors_are_idempotent_and_integrated_outputs_are_required')
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        author = harness.context['assignments'][0]['authorTaskId']
        attach = api.attach_task

        def attach_then_cancel(root: object, batch_id: str, ref: ClaimRef, handle: dict) -> dict:
            """The author attaches; the director then cancels it before its result arrives."""
            attached = attach(root, batch_id, ref, handle)
            api.request_cancel(root, batch_id, ref.task_id, 'TEST director cancelled the author')
            return attached

        # validate_result would refuse this completion (the task is not current); only the settlement reader passes.
        with patch.object(api, 'attach_task', attach_then_cancel):
            harness.complete(author)
        record = harness.budget.record()
        task = record['production']['tasks'][author]
        self.assertEqual((task['state'], len(task['receipts']), task['unresolved']), ('cancelled', 1, True))
        with self.assertRaisesRegex(ValueError, 'not current'):
            section_results.read_completed_result(record, author, task['sectionBinding'])


class OneCleanupRuleTests(unittest.TestCase):
    """Every end goes through ``task_end``: host turns hold their slot until evidence (G9); charges never move."""

    def test_d02_matrix(self) -> None:
        """(state, unresolved, holds_slot, active AI, charged) after each D02 end."""
        for outcome, kind, state in D02:
            with self.subTest(outcome=outcome, host=kind):
                batch, handle = Batch(self, root=private_root(self)), host('critic', kind)
                batch.enqueue(('critic', 'specialist', ()))
                d02_end(batch, batch.claim('critic', handle), handle, outcome)
                record, task = batch.record(), batch.row('critic')
                observed = (task['state'], task['unresolved'], holds_slot(task), active_ai(record),
                            record['production']['ai']['charged'])
                self.assertEqual(observed, (state, True, True, 2, 2))

    def test_rule_reads_the_task_handle_host_not_the_directors(self) -> None:
        """Gate M4: both completions hold their slot; tool cleanup follows the task's own host."""
        cases = [('claude-code', 'codex', 'unproven'), ('codex', 'claude-code', 'proved')]
        for director, worker, cleanup in cases:
            with self.subTest(director=director, task=worker):
                batch = Batch(self, director, root=private_root(self))
                batch.enqueue(('critic', 'specialist', ()))
                ref = batch.claim('critic', host('critic', worker))
                api.complete_task(batch.root, BATCH, ref, TaskResult((receipt('critic'),)))
                event = batch.events()[-1]
                self.assertEqual((event['unresolved'], event['endCause'], event['toolCleanup']),
                                 (True, 'host-ended', cleanup))
                self.assertTrue(holds_slot(batch.row('critic')))

    def test_process_handle_ai_completion_holds_until_reconcile_sees_exit(self) -> None:
        """G9 (b): a process-handle completion holds until reconcile sees the exact child gone (W2-D2's child)."""
        batch = Batch(self)
        batch.table = None   # this test's child is real, so reconcile reads the real process table
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        _, pgid, started = REAL_TABLE()[child.pid]
        batch.enqueue(('critic', 'review', ()))
        ref = batch.claim('critic', {'type': 'process', 'pid': child.pid, 'pgid': pgid, 'started': started})
        api.complete_task(batch.root, BATCH, ref, TaskResult((receipt('critic'),)))
        api.reconcile(batch.root, BATCH)
        self.assertEqual((batch.row('critic')['state'], batch.row('critic')['unresolved']), ('completed', True))
        child.kill()
        child.wait()
        api.reconcile(batch.root, BATCH)
        self.assertEqual((batch.row('critic')['state'], batch.row('critic')['unresolved']), ('completed', False))
        self.assertEqual(active_ai(batch.record()), 1)

    def test_director_end_frees_its_slot_on_both_hosts(self) -> None:
        """A director's own end ends its batch assignment (X29) on either host; a live child keeps its slot."""
        for kind in ('codex', 'claude-code'):
            with self.subTest(director=kind):
                batch = Batch(self, kind, root=private_root(self))
                batch.enqueue(('critic', 'specialist', ()))
                batch.claim('critic', host('critic'))
                api.complete_task(batch.root, BATCH, batch.director, TaskResult(()))
                director = batch.row('director')
                self.assertEqual((director['state'], director['unresolved']), ('completed', False))
                self.assertEqual(active_ai(batch.record()), 1)

    def test_unlaunched_failure_with_launch_error_frees_the_slot(self) -> None:
        """Only the launch tool's verbatim error frees a failed claim; a bare failure holds it (M-041, G9)."""
        batch = Batch(self)
        batch.enqueue(('critic', 'specialist', ()), ('writer', 'specialist', ()))
        ref, bare = batch.claim('critic'), batch.claim('writer')
        api.fail_task(batch.root, BATCH, ref, launch_failure())
        event = batch.events()[-1]
        api.fail_task(batch.root, BATCH, bare, launch_failure(None))
        self.assertEqual((batch.row('critic')['state'], batch.row('critic')['unresolved']), ('failed', False))
        self.assertEqual((batch.row('writer')['state'], batch.row('writer')['unresolved']), ('failed', True))
        self.assertEqual((event['endCause'], event['slotReleased'], event['launchError']),
                         ('unlaunched', True, LAUNCH_ERROR))
        self.assertEqual(active_ai(batch.record()), 2)

    def test_release_without_launch_error_refused(self) -> None:
        """An AI release needs the launch tool's error; check work does not (its release is unchanged)."""
        batch = Batch(self)
        batch.enqueue(('critic', 'specialist', ()), ('lint', 'check', ()))
        ref = batch.claim('critic')
        with self.assertRaisesRegex(TaskRefused, RELEASE_REFUSAL):
            api.release_claim(batch.root, BATCH, ref)
        self.assertEqual(api.release_claim(batch.root, BATCH, ref, LAUNCH_ERROR)['state'], 'ready')
        self.assertEqual(batch.events()[-1]['launchError'], LAUNCH_ERROR)
        self.assertEqual(api.release_claim(batch.root, BATCH, batch.claim('lint'))['state'], 'ready')

    def test_a_stopped_claim_whose_launch_failed_ends_alike_on_fail_and_release(self) -> None:
        """X88: fail --launch-error and release --launch-error end a cancel-requested claim the same way."""
        batch = Batch(self)
        batch.enqueue(('critic', 'specialist', ()), ('writer', 'specialist', ()))
        ends = {'critic': lambda ref: api.fail_task(batch.root, BATCH, ref, launch_failure()),
                'writer': lambda ref: api.release_claim(batch.root, BATCH, ref, LAUNCH_ERROR)}
        for task_id, end in ends.items():
            with self.subTest(task=task_id):
                ref = batch.claim(task_id)
                api.request_cancel(batch.root, BATCH, task_id, 'TEST stop')
                end(ref)
                row, event = batch.row(task_id), batch.events()[-1]
                self.assertEqual((row['state'], row['unresolved'], row['endConfirmed']), ('cancelled', False, True))
                self.assertEqual((event['endCause'], event['slotReleased'], event['launchError']),
                                 ('unlaunched', True, LAUNCH_ERROR))

    def test_a_held_completion_keeps_its_outputs_cleanup_pending(self) -> None:
        """X114 M2, X125 N6: an output's cleanup milestone names every ended turn that still holds its slot (G9),
        a completed one and a failed one alike."""
        batch = Batch(self)
        batch.enqueue(('author-A', 'author', ()), ('author-A2', 'author', ()))
        ref = batch.claim('author-A', host('author-A'))
        api.complete_task(batch.root, BATCH, ref, TaskResult((receipt('author-A'),)))
        batch.host_event(batch.claim('author-A2', host('author-A2')), 'failed', host('author-A2'))
        record = batch.record()
        self.assertTrue(all(holds_slot(record['production']['tasks'][key]) for key in ('author-A', 'author-A2')))
        milestone = native_budget_milestones.cleanup(record, 'A')
        self.assertEqual((milestone['status'], milestone['unresolvedTasks']),
                         ('pending', [{'taskId': 'author-A', 'state': 'completed'},
                                      {'taskId': 'author-A2', 'state': 'failed'}]))

    def test_codex_turns_exhaust_four_slots_with_a_named_refusal(self) -> None:
        """X80: codex completions hold their slots, so the claim after the last free slot is refused by name."""
        batch = Batch(self)
        batch.enqueue(*((f'turn-{index}', 'specialist', ()) for index in range(4)))
        for index in range(3):
            ref = batch.claim(f'turn-{index}', host(f'turn-{index}'))
            api.complete_task(batch.root, BATCH, ref, TaskResult((receipt(f'turn-{index}'),)))
        self.assertEqual(active_ai(batch.record()), 4)
        ready = {row['taskId']: row['refusal'] for row in api.next_ready(batch.root, BATCH)}
        self.assertRegex(ready['turn-3'], '^All 4 AI slots are held')
        with self.assertRaisesRegex(TaskRefused, '^All 4 AI slots are held'):
            batch.claim('turn-3')


if __name__ == '__main__':
    unittest.main()
