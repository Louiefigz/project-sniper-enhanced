"""Short capacity clock v2, continued (P1-RP3 fixes, X183, open this module: ``_b`` is at 293 lines, MA3).

ReenrollmentTests (MAJOR, m7): each enrollment starts over, so a second director that declares nothing earns its
Shorts no credit, and ``enroll`` tells the director to declare; driven through the CLI and the locked API on the
test's private authority root (``test_queue_clock_v2_c.AuditCase``). DeadReadyWorkTests (m6): a ready creative task
whose claim is refused for good is not the Short's work. EvidenceGapTests (m8, n1, n5): which tasks, rows and evidence
the credit rule reads, each pinning a behaviour a surviving mutant changed. The last two use the in-memory TEST
records of ``test_queue_clock_v2_b.Run``; no child process is started.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import unittest
from unittest import mock

from _budget_fixture import FINGERPRINT
from _production_task_flow_fixture import run_cli
from studio.production import api, callbacks, queue_clock
from studio.production.claim_admission import authoring_closed, claim_refusal
from studio.production.claims import ClaimRef
from studio.production.director_activity import ENROLL_HINT, DirectorActivity, declare
from studio.production.formats import clip_deadlines
from studio.production.queue_clock_schema import new_clock
from studio.production.tasks import TaskRefused
from test_queue_clock_v2 import short_record
from test_queue_clock_v2_b import DIRECTOR, OWNER, WAITING, Run
from test_queue_clock_v2_c import BATCH, POOL, AuditCase
from test_queue_clock_v2_d import DEAD, POOL_ROW, ROW


class ReenrollmentTests(AuditCase):
    """MAJOR: an earlier director's ``idle`` never carries over; m7: the enrollment output names the declaration."""

    def enroll(self, task_id: str) -> ClaimRef:
        """Enroll a TEST Codex director through the CLI; its output carries the declaration hint."""
        handle = {**DIRECTOR, 'thread': f'TEST-thread-{task_id}', 'turn': f'TEST-turn-{task_id}'}
        code, enrolled = run_cli('enroll', '--batch', BATCH, '--task', task_id, '--handle', json.dumps(handle),
                                 '--version', 'v1', '--fingerprint', FINGERPRINT)
        self.assertEqual((code, enrolled['declare']), (0, ENROLL_HINT))
        return ClaimRef(task_id, enrolled['epoch'], enrolled['token'])

    def test_a_second_director_declaring_nothing_earns_no_credit(self) -> None:
        """The first director declares idle and A's wait is credited; once its assignment ends, a second director
        enrolls and declares nothing, so it counts as working on A and the same wait earns nothing."""
        first = self.enroll('director')
        api.declare_director_activity(self.root, BATCH, first, DirectorActivity(None, False))
        self.wait(60, POOL)
        self.assertEqual(self.clock_of()['excludedSeconds'], 60.0)
        api.complete_task(self.root, BATCH, first, callbacks.TaskResult(()))
        self.enroll('director-2')
        self.assertIs(self.clock_of()['directorWorking'], True)
        self.wait(60, POOL)
        self.assertEqual(self.clock_of()['excludedSeconds'], 60.0)


class DeadReadyWorkTests(unittest.TestCase):
    """m6: a ready authoring, planning, review or repair task past its output's preparation deadline is not work."""

    def test_a_ready_plan_review_stops_blocking_credit_at_preparation(self) -> None:
        """Before A's preparation deadline its ready plan review is work (no credit). A wait from 10 s before the
        deadline earns only the 50 s after it: each interval is judged at its start, by the claim refusal's own
        rule (``authoring_closed``), which never reopens."""
        run = Run()
        run.declare(False)
        run.enqueue(('plan-a', 'planReview', 'A', ()))
        self.assertEqual(run.wait('A'), 0.0)
        preparation = clip_deadlines(run.record, run.record['clips']['A'])['preparationSeconds']
        run.elapsed = preparation - 10.0
        self.assertEqual(run.wait('A'), 50.0)
        task = run.record['production']['tasks']['plan-a']
        self.assertTrue(authoring_closed(run.record, task, run.elapsed))
        self.assertIn('no further authoring', claim_refusal(run.record, task, run.elapsed))
        self.assertEqual(task['state'], 'ready')

    def test_a_ready_review_of_an_ended_director_is_cancelled_control(self) -> None:
        """Control: the director's end cancels its ready children, so they withhold nothing either."""
        run = Run()
        run.declare(False)
        run.enqueue(('review-a', 'review', 'A', ()))
        callbacks.complete(run.record, run.director, callbacks.TaskResult(()), run.elapsed)
        task = run.record['production']['tasks']['review-a']
        self.assertEqual((task['state'], run.wait('A')), ('cancelled', 60.0))


class EvidenceGapTests(unittest.TestCase):
    """m8 (P3, C1, C5), n1 and n5 (C2, C3, C4, D1): the tasks, rows and evidence the credit rule reads."""

    def test_a_ready_media_task_of_the_short_does_not_block(self) -> None:
        """P3: only ready AI or check work withholds credit; a ready media task waits for the render too."""
        run = Run()
        run.declare(False)
        run.enqueue(('media-a2', 'media', 'A', ()))
        self.assertEqual(run.record['production']['tasks']['media-a2']['state'], 'ready')
        self.assertEqual(run.wait('A'), 60.0)

    def test_a_wait_missing_any_evidence_earns_nothing(self) -> None:
        """C1-C3 (C11): a wait naming no occupant, no ticket, or no capacity class is counted, as uncertain."""
        for change in ({'occupants': []}, {'ticket': None}, {'waitClass': None}, {'waitClass': 'other'}):
            run = Run()
            run.declare(False)
            with self.subTest(change), mock.patch.dict(WAITING, change):
                self.assertEqual(run.wait('A'), 0.0)
                self.assertEqual(run.record['clips']['A']['capacityClock']['uncertainSeconds'], 60.0)

    def test_the_interval_is_judged_by_the_row_that_waited_through_it(self) -> None:
        """C4: a wait observed without its ticket, then with it: the first interval stays uncertain (its row was
        unverified), the second is credited (its row was verified)."""
        run = Run()
        run.declare(False)
        context = {'clipId': 'A', 'workerId': '/TEST/owner-A.json', 'taskId': 'media-a', 'attemptId': None,
                   'supervisor': OWNER, 'boot': 'TEST-boot'}
        for elapsed, evidence in ((0.0, {'ticket': None}), (2.0, {}), (4.0, {})):
            queue_clock.checkpoint(run.record, elapsed)
            queue_clock.observe_worker(run.record, context, {**WAITING, **evidence}, elapsed)
        clock = run.record['clips']['A']['capacityClock']
        self.assertEqual((clock['excludedSeconds'], clock['uncertainSeconds']), (2.0, 2.0))

    def test_a_finishing_owner_leaves_its_last_interval_uncertain(self) -> None:
        """C5: a ``finished`` observation cannot confirm the interval before it (uncertain); a ``working`` one after
        the same verified wait credits it (control)."""
        for state, expected in (('finished', (0.0, 10.0)), ('working', (10.0, 0.0))):
            waiting = {**ROW, 'state': 'waiting', 'supervisor': DEAD, 'boot': 'TEST-boot', **POOL_ROW}
            record = short_record({**new_clock(), 'observedElapsed': 10.0, 'pendingSeconds': 10.0,
                                   'workers': {'/TEST/owner-1.json': waiting}})
            context = {'clipId': 'A', 'workerId': '/TEST/owner-1.json', 'taskId': None, 'attemptId': None}
            queue_clock.observe_worker(record, context, {'state': state, 'resource': 'heavy-pool', 'evidence': ''},
                                       10.0)
            clock = record['clips']['A']['capacityClock']
            with self.subTest(state):
                self.assertEqual((clock['excludedSeconds'], clock['uncertainSeconds']), expected)

    def test_a_short_named_twice_is_one_short(self) -> None:
        """n1: ``--clip A --clip A`` declares, and reports, A once."""
        run = Run()
        outcome = declare(run.record, run.director, DirectorActivity(('A', 'A'), False), run.elapsed)
        self.assertEqual((outcome.event['clips'], outcome.event['changed']), (['A'], ['A']))

    def test_a_revoked_director_may_not_declare(self) -> None:
        """D1: a director whose task is revoked declares nothing, though it still holds its slot (TEST: the flag is
        set directly)."""
        run = Run()
        run.record['production']['tasks']['director']['revoked'] = True
        with self.assertRaisesRegex(TaskRefused, '^Only the enrolled director declares its own activity$'):
            run.declare(False)


if __name__ == '__main__':
    unittest.main()
