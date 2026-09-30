"""Short capacity clock v2, continued (M-045 opens this module: test_queue_clock_v2.py is at 299 lines, X102 n5).

ProductiveTests (P1 Step B2, C4; X99(2), X176): which work withholds render-queue credit, and the enrolled
director's declared activity. In-memory TEST records only (no authority root is written): Shorts A and B, a
Codex-hosted enrolled director, and a media task per Short whose owner waits 60 s for render capacity, reporting a
capacity-only refusal every 2 s after a checkpoint, as the owner loop does.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import unittest

from _budget_fixture import FINGERPRINT, approval, receipt, table, task_spec
from _production_task_flow_fixture import BATCH, Batch, run_cli
from studio.native_budget_clock import ClockAnchor
from studio.native_budget_policy import BatchSpec, new_batch_record
from studio.production import api, callbacks, claims, queue_clock
from studio.production.claims import ClaimRef, Enrollment
from studio.production.director_activity import DirectorActivity, declare
from studio.production.reconcile import Observation, reconcile_tasks
from studio.production.tasks import StaleClaim, TaskRefused, enqueue

DIRECTOR = {'type': 'host', 'host': 'codex', 'thread': 'TEST-thread-director', 'turn': 'TEST-turn-director'}
OWNER = {'pid': 7101, 'pgid': 7101, 'started': 'Sun Sep 27 10:00:00 2026'}
PROCESS = {'type': 'process', 'pid': 7201, 'pgid': 7201, 'started': 'Sun Sep 27 10:00:10 2026'}
# A capacity-only wait with its pool evidence (ticket, live occupants: C11, M-047), as the owner loop reports it.
WAITING = {'state': 'waiting', 'resource': 'heavy-pool', 'evidence': '{}', 'ticket': 7, 'occupants': ['a' * 32],
           'waitClass': 'capacity'}


def turn(name: str) -> dict:
    """A TEST Codex host turn."""
    return {'type': 'host', 'host': 'codex', 'thread': f'TEST-thread-{name}', 'turn': f'TEST-turn-{name}'}


class Run:
    """An in-memory TEST batch: Shorts A and B, an enrolled Codex director, a dispatched media task per Short."""

    def __init__(self, ai_slots: int = 6) -> None:
        """Create the record at elapsed 0 and enroll the director (its clocks start with ``directorWorking``)."""
        spec = BatchSpec(BATCH, ('A', 'B'), (), 3, ai_slots=ai_slots,
                         approvals={'A': approval('A'), 'B': approval('B')})
        self.record, self.elapsed = new_batch_record(spec, ClockAnchor('TEST-boot', 5000.0, 1_800_000_000.0, 0.0)), 0.0
        enrolled = claims.enroll_director(self.record, Enrollment('director', DIRECTOR, 'v1', FINGERPRINT), 0.0)
        self.director = ClaimRef('director', enrolled.detail['epoch'], enrolled.detail['token'])
        # Each Short's media task; its owner is the waiting worker (excluded as the waited work, whatever its state).
        self.enqueue(('media-a', 'media', 'A', ()), ('media-b', 'media', 'B', ()))

    def enqueue(self, *rows: tuple[str, str, str | None, tuple[str, ...]]) -> None:
        """Enqueue (id, kind, clip, prerequisites) tasks under the director."""
        specs = tuple(task_spec(task_id, kind, clip_id=clip, prerequisites=prerequisites, parent='director')
                      for task_id, kind, clip, prerequisites in rows)
        enqueue(self.record, specs, self.elapsed)

    def claim(self, task_id: str, handle: dict) -> ClaimRef:
        """Claim a ready task for the director and attach ``handle``."""
        detail = claims.claim(self.record, task_id, DIRECTOR, self.elapsed).detail
        ref = ClaimRef(task_id, detail['epoch'], detail['token'])
        claims.attach(self.record, ref, handle, self.elapsed)
        return ref

    def declare(self, working: bool, clips: tuple[str, ...] | None = None) -> None:
        """The director's own declaration."""
        declare(self.record, self.director, DirectorActivity(clips, working), self.elapsed)

    def wait(self, clip: str, seconds: float = 60.0) -> float:
        """The clip's owner waits ``seconds`` for render capacity; return the credit this wait settled."""
        context = {'clipId': clip, 'workerId': f'/TEST/owner-{clip}.json', 'taskId': f'media-{clip.lower()}',
                   'attemptId': None, 'supervisor': OWNER, 'boot': 'TEST-boot'}
        before, end = queue_clock.excluded(self.record['clips'][clip]), self.elapsed + seconds
        while True:
            queue_clock.checkpoint(self.record, self.elapsed)
            queue_clock.observe_worker(self.record, context, dict(WAITING), self.elapsed)
            if self.elapsed >= end:
                break
            self.elapsed += 2.0
        queue_clock.observe_worker(self.record, context, {**WAITING, 'state': 'finished'}, self.elapsed)
        return queue_clock.excluded(self.record['clips'][clip]) - before


class ProductiveTests(unittest.TestCase):
    """C4: only a capacity-only wait with no other work of the Short is credited (X99(2): a completed turn is not
    work, even while its slot evidence is missing; any other unresolved end still is)."""

    def test_only_the_render_waits_is_credited(self) -> None:
        """With the director declared idle, the render is the only work: the whole wait is credited."""
        run = Run()
        run.declare(False)
        self.assertEqual(run.wait('A'), 60.0)

    def test_enrolled_director_without_declaration_blocks_credit(self) -> None:
        """Undeclared director work counts; idle credits; working for A alone blocks only A."""
        run = Run()
        self.assertEqual(run.wait('A'), 0.0)
        run.declare(False)
        self.assertEqual(run.wait('A'), 60.0)
        run.declare(True, ('A',))
        self.assertEqual((run.wait('A'), run.wait('B')), (0.0, 60.0))

    def test_claimed_author_blocks_credit(self) -> None:
        """Control: registered AI work of the Short is useful work."""
        run = Run()
        run.declare(False)
        run.enqueue(('author-a', 'author', 'A', ()))
        run.claim('author-a', turn('author-a'))
        self.assertEqual(run.wait('A'), 0.0)

    def test_ready_review_waiting_for_an_ai_slot_blocks_credit(self) -> None:
        """Report C p1 case d: a ready review that only waits for an AI slot is still the Short's work."""
        run = Run(ai_slots=2)
        run.declare(False)
        run.enqueue(('author-b', 'author', 'B', ()), ('review-a', 'review', 'A', ()))
        run.claim('author-b', turn('author-b'))   # the director and author-b hold both AI slots
        self.assertEqual(run.record['production']['tasks']['review-a']['state'], 'ready')
        self.assertEqual(run.wait('A'), 0.0)

    def test_ready_check_task_blocks_credit(self) -> None:
        """A ready check task of the Short blocks credit."""
        run = Run()
        run.declare(False)
        run.enqueue(('check-a', 'check', 'A', ()))
        self.assertEqual(run.wait('A'), 0.0)

    def test_blocked_review_waiting_for_the_render_does_not_block(self) -> None:
        """Work that waits for the render itself is not concurrent work."""
        run = Run()
        run.declare(False)
        run.enqueue(('review-a', 'review', 'A', ('media-a',)))
        self.assertEqual(run.record['production']['tasks']['review-a']['state'], 'blocked')
        self.assertEqual(run.wait('A'), 60.0)

    def test_ready_run_scoped_ai_blocks_every_short(self) -> None:
        """The documented conservative rule (report C P5): run-scoped AI work withholds every Short's credit."""
        run = Run()
        run.declare(False)
        run.enqueue(('shared-plan', 'planning', None, ()))
        self.assertEqual((run.wait('A'), run.wait('B')), (0.0, 0.0))

    def test_completed_ai_with_residue_does_not_block_credit(self) -> None:
        """X99(2), X176: a completed host turn holding its slot does no work; a statement changes nothing."""
        run = Run()
        run.declare(False)
        run.enqueue(('author-a', 'author', 'A', ()))
        ref = run.claim('author-a', turn('author-a'))
        callbacks.complete(run.record, ref, callbacks.TaskResult((receipt('author-a'),)), run.elapsed)
        row = run.record['production']['tasks']['author-a']
        self.assertEqual((row['state'], row['unresolved']), ('completed', True))   # G9: no host end evidence
        self.assertEqual(run.wait('A'), 60.0)
        callbacks.settle_resource(run.record, 'author-a', 'TEST operator statement', run.elapsed)
        self.assertEqual((row['unresolved'], run.wait('A')), (True, 60.0))

    def test_unresolved_ended_ai_blocks_credit_until_evidence_resolves_it(self) -> None:
        """A failed turn may still run: it blocks credit, a statement changes nothing, termination evidence does."""
        failure = callbacks.TaskFailure('host-failure', 'TEST turn errored')
        for handle, resolved in ((turn('author-a'), False), (dict(PROCESS), True)):
            with self.subTest(handle=handle['type']):
                run = Run()
                run.declare(False)
                run.enqueue(('author-a', 'author', 'A', ()))
                callbacks.fail(run.record, run.claim('author-a', handle), failure, run.elapsed)
                row = run.record['production']['tasks']['author-a']
                self.assertEqual((row['state'], row['unresolved'], run.wait('A')), ('failed', True, 0.0))
                callbacks.settle_resource(run.record, 'author-a', 'TEST operator statement', run.elapsed)
                self.assertEqual((row['unresolved'], run.wait('A')), (True, 0.0))
                reconcile_tasks(run.record, Observation(table()), run.elapsed)   # the TEST table holds pid 1 only
                # Reconcile proves a process handle's end (pid 7201 gone, empty group); a host turn's end is
                # not proven before M-102, so it keeps blocking.
                self.assertEqual((row['unresolved'], run.wait('A')), (not resolved, 60.0 if resolved else 0.0))


class DirectorActivityTests(unittest.TestCase):
    """The declaration is the enrolled director's own, fenced, recorded as declared, and refused by name."""

    def test_director_activity_refusals(self) -> None:
        """A non-director, a stale claim, an unknown Short, a handed-off Short and a v1 clock are refused."""
        run = Run()
        run.enqueue(('author-a', 'author', 'A', ()))
        author = run.claim('author-a', turn('author-a'))
        run.record['clips']['B']['capacityClock']['policy'] = 'short-render-capacity-v1'
        cases = [(author, ('A',), TaskRefused, 'Only the enrolled director declares its own activity'),
                 (ClaimRef('director', run.director.epoch, 'TEST-stale'), ('A',), StaleClaim, 'stale or foreign'),
                 (run.director, ('Z',), TaskRefused, 'Clip Z has no v2 Short capacity clock'),
                 (run.director, ('B',), TaskRefused, 'Clip B has no v2 Short capacity clock')]
        for ref, clips, error, text in cases:
            with self.subTest(text), self.assertRaisesRegex(error, text):
                declare(run.record, ref, DirectorActivity(clips, False), 0.0)
        run.record['clips']['A']['state'] = 'handed-off'
        with self.assertRaisesRegex(TaskRefused, 'Clip A was handed off'):
            declare(run.record, run.director, DirectorActivity(('A',), False), 0.0)
        self.assertTrue(run.record['clips']['A']['capacityClock']['directorWorking'])

    def test_all_covers_open_v2_shorts_and_a_repeat_changes_nothing(self) -> None:
        """``--all`` skips a handed-off Short; the event says declared; a repeated declaration commits nothing."""
        run = Run()
        run.record['clips']['B']['state'] = 'handed-off'
        first = declare(run.record, run.director, DirectorActivity(None, False), 0.0)
        self.assertEqual((first.changed, first.event), (True, {
            'event': 'director-activity', 'clips': ['A'], 'changed': ['A'], 'working': False,
            'declaredBy': 'director', 'declared': True}))
        self.assertFalse(declare(run.record, run.director, DirectorActivity(None, False), 0.0).changed)
        self.assertTrue(run.record['clips']['B']['capacityClock']['directorWorking'])

    def test_the_command_records_the_declaration_in_the_trail(self) -> None:
        """``native_batch.py director-activity`` commits the event through the locked API."""
        batch = Batch(self)
        code, out = run_cli('director-activity', '--batch', BATCH, '--task', 'director', '--epoch',
                            str(batch.director.epoch), '--token', batch.director.token, '--all', '--state', 'idle')
        self.assertEqual((code, out['changed'], out['committed']), (0, ['A'], True))
        self.assertFalse(batch.record()['clips']['A']['capacityClock']['directorWorking'])
        event = batch.events()[-1]
        self.assertEqual((event['event'], event['declared'], event['working']), ('director-activity', True, False))
        again = api.declare_director_activity(batch.root, BATCH, batch.director, DirectorActivity(('A',), False))
        self.assertFalse(again['committed'])
        self.assertEqual(copy.deepcopy(batch.events()[-1]), event)


if __name__ == '__main__':
    unittest.main()
