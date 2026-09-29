"""Durable task contract (unit A1): DAG checks, dependency outcomes, claims, AI reservations, fencing."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from _budget_fixture import (
    CHILD, DIRECTOR, DISPATCHER, FINGERPRINT, host_turn, receipt, task_spec,
)
from test_native_budget_registry import RegistryCase
from studio import native_budget_schema as schema
from studio.native_budget_clock import BudgetClockError
from studio.native_budget_store import BudgetAuthorityError
from studio.production import api
from studio.production.callbacks import TaskFailure, TaskResult
from studio.production.claims import ClaimRef, Enrollment
from studio.production.task_schema import TASK_FIELDS, authorization_identity
from studio.production.tasks import StaleClaim, TaskConflict, TaskRefused

HERE = Path(__file__).resolve().parents[1]
BATCH = 'batch-auth'
RACE = '''
import json, sys, time
from pathlib import Path
sys.path[:0] = [sys.argv[1], str(Path(sys.argv[1]) / "tests")]
from _budget_fixture import FakeClock, fake_clock
from studio.production import api
from studio.production.tasks import TaskRefused
wall, continuous, boot = json.loads(sys.argv[3])
claimer = {"type": "process", "pid": 7100 + int(sys.argv[6]), "pgid": 7100, "started": "Sun Sep 27 10:00:00 2026"}
with fake_clock(FakeClock(wall, continuous, boot)):
    while time.monotonic() < float(sys.argv[5]):
        time.sleep(0.001)
    try:
        claimed = api.claim_task(Path(sys.argv[2]), "batch-auth", sys.argv[4], claimer)
        print(json.dumps({"result": "claimed", "epoch": claimed["epoch"]}))
    except TaskRefused as error:
        print(json.dumps({"result": "refused", "reason": str(error)}))
'''


class TaskCase(RegistryCase):
    """RegistryCase (batch-auth: clips A and B, one project bound to A) with an enrolled director."""

    def setUp(self) -> None:
        super().setUp()
        self.director = api.enroll_director(self.root, BATCH, Enrollment('director', DIRECTOR, 'v1', FINGERPRINT))

    def enqueue(self, *specs: object) -> dict:
        return api.enqueue_tasks(self.root, BATCH, specs)

    def claim(self, task_id: str, claimer: dict = DISPATCHER) -> dict:
        return api.claim_task(self.root, BATCH, task_id, claimer)

    @staticmethod
    def ref(claimed: dict) -> ClaimRef:
        return ClaimRef(claimed['taskId'], claimed['epoch'], claimed['token'])

    def start_task(self, task_id: str, handle: dict = CHILD) -> ClaimRef:
        ref = self.ref(self.claim(task_id))
        api.attach_task(self.root, BATCH, ref, handle)
        return ref

    def finish_task(self, ref: ClaimRef, name: str = 'out') -> dict:
        return api.complete_task(self.root, BATCH, ref, TaskResult((receipt(name),)))

    def task(self, task_id: str) -> dict:
        return self.record()['production']['tasks'][task_id]

    def state(self, task_id: str) -> str:
        return self.task(task_id)['state']

    def ai(self) -> dict:
        return self.record()['production']['ai']

    def use_claude_director(self) -> None:
        """Replace the Codex director with a Claude Code one (its governance replaces the run's)."""
        api.complete_task(self.root, BATCH, ClaimRef('director', 1, self.director['token']), TaskResult(()))
        claude = {'type': 'host', 'host': 'claude-code', 'thread': 'TEST-session', 'turn': None}
        api.enroll_director(self.root, BATCH, Enrollment('director-claude', claude, 'v1', FINGERPRINT))


class EnqueueTests(TaskCase):
    """Bounded DAG checks: missing, cross-run and cyclic prerequisites; atomic, idempotent submissions."""

    def test_missing_prerequisite_is_refused(self) -> None:
        with self.assertRaisesRegex(TaskRefused, 'missing prerequisite ghost'):
            self.enqueue(task_spec('a', prerequisites=('ghost',)))
        self.assertNotIn('a', self.record()['production']['tasks'])

    def test_cross_run_prerequisites_and_specs_are_refused(self) -> None:
        self.enqueue(task_spec('a'))
        with self.assertRaisesRegex(TaskRefused, 'of another run'):
            self.enqueue(task_spec('b', prerequisites=('batch-other/a',)))
        with self.assertRaisesRegex(TaskRefused, 'belongs to run batch-other'):
            self.enqueue(task_spec('c', run_id='batch-other'))
        self.enqueue(task_spec('d', prerequisites=(f'{BATCH}/a',)))           # own run, qualified
        self.assertEqual(self.task('d')['prerequisites'], ['a'])

    def test_cycles_and_self_dependencies_are_refused_atomically(self) -> None:
        cycle = (task_spec('a', prerequisites=('c',)), task_spec('b', prerequisites=('a',)),
                 task_spec('c', prerequisites=('b',)), task_spec('free'))
        with self.assertRaisesRegex(TaskRefused, 'cycle'):
            self.enqueue(*cycle)
        with self.assertRaisesRegex(TaskRefused, 'none of them itself'):
            self.enqueue(task_spec('self', prerequisites=('self',)))
        self.assertEqual(set(self.record()['production']['tasks']), {'director'})

    def test_a_parent_cycle_or_a_missing_ancestor_is_refused(self) -> None:
        with self.assertRaisesRegex(TaskRefused, 'parent chain is cyclic'):
            self.enqueue(task_spec('p', parent='q'), task_spec('q', parent='p'))
        with self.assertRaisesRegex(TaskRefused, 'missing parent ghost'):
            self.enqueue(task_spec('child', parent='mid'), task_spec('mid', parent='ghost'))

    def test_a_cross_run_replay_of_an_existing_id_is_refused(self) -> None:
        self.enqueue(task_spec('a'))
        with self.assertRaisesRegex(TaskRefused, 'belongs to run batch-other'):
            self.enqueue(task_spec('a', run_id='batch-other'))

    def test_identical_replay_is_a_noop_and_a_changed_definition_conflicts(self) -> None:
        first = self.enqueue(task_spec('a'), task_spec('b', prerequisites=('a',)))
        trail = (self.root / 'batches/batch-auth/events.jsonl').read_text()
        self.clock.advance(60)
        replay = self.enqueue(task_spec('a'), task_spec('b', prerequisites=('a',)))
        self.assertEqual((first['enqueued'], replay['enqueued'], replay['replayed']), (['a', 'b'], [], ['a', 'b']))
        self.assertFalse(replay['committed'])
        self.assertEqual((self.root / 'batches/batch-auth/events.jsonl').read_text(), trail)
        with self.assertRaisesRegex(TaskConflict, 'different definition'):
            self.enqueue(task_spec('b', version='v2', prerequisites=('a',)))

    def test_rows_are_bounded(self) -> None:
        with self.assertRaisesRegex(TaskRefused, 'at most 16'):
            self.enqueue(*[task_spec(f'p{index}') for index in range(17)],
                         task_spec('wide', prerequisites=tuple(f'p{index}' for index in range(17))))
        with mock.patch.dict(schema.BOUNDS, tasks=3):
            self.enqueue(task_spec('one'), task_spec('two'))
            with self.assertRaisesRegex(TaskRefused, 'holds 3 of 3 tasks'):
                self.enqueue(task_spec('three'))
        from studio.production import settlement
        with mock.patch.object(settlement, 'MAX_TASK_ENTRY_BYTES', 4 * 1024 ** 2):
            with self.assertRaisesRegex(TaskRefused, 'no room left to settle'):
                self.enqueue(task_spec('crowded'))

    def test_deadlines_nest_inside_the_parent_and_the_delivery_deadline(self) -> None:
        with self.assertRaisesRegex(TaskRefused, 'no later than the delivery deadline'):
            self.enqueue(task_spec('late', deadline_elapsed=2401.0))
        self.enqueue(task_spec('author-a', 'author', parent='director', deadline_elapsed=900.0))
        with self.assertRaisesRegex(TaskRefused, 'later than its parent'):
            self.enqueue(task_spec('child', 'specialist', parent='author-a', deadline_elapsed=901.0))

    def test_nesting_depth_is_bounded(self) -> None:
        self.enqueue(task_spec('l1', 'planning', parent='director'), task_spec('l2', 'specialist', parent='l1'),
                     task_spec('l3', 'specialist', parent='l2'))
        with self.assertRaisesRegex(TaskRefused, 'deeper than 3'):
            self.enqueue(task_spec('l4', 'specialist', parent='l3'))

    def test_no_row_field_can_hold_a_command(self) -> None:
        self.assertFalse({'command', 'argv', 'args', 'shell', 'environment', 'env'} & set(TASK_FIELDS))
        self.enqueue(task_spec('a'))
        path = self.root / 'batches/batch-auth/authority.json'
        record = json.loads(path.read_text())
        record['production']['tasks']['a']['command'] = 'rm -rf /'
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(BudgetAuthorityError, 'task a fields'):
            self.record()


class DependencyTests(TaskCase):
    """Readiness, failure/cancel propagation with a retained reason, supersession and replacement."""

    def test_a_dependent_is_ready_only_after_its_prerequisites_complete(self) -> None:
        self.enqueue(task_spec('a'), task_spec('b'), task_spec('c', prerequisites=('a', 'b')))
        self.assertEqual(self.state('c'), 'blocked')
        self.finish_task(self.start_task('a'))
        self.assertIn('waiting for b (ready)', self.task('c')['reason'])
        self.finish_task(self.start_task('b'), 'b')
        self.assertEqual(self.state('c'), 'ready')

    def test_failure_propagates_transitively_with_a_retained_reason(self) -> None:
        self.enqueue(task_spec('a'), task_spec('b', prerequisites=('a',)), task_spec('c', prerequisites=('b',)))
        api.fail_task(self.root, BATCH, self.start_task('a'), TaskFailure('renderer-failure', 'TEST failure'))
        for task_id, cause in (('b', 'prerequisite a is failed'), ('c', 'prerequisite b is failed')):
            row = self.task(task_id)
            self.assertEqual((row['state'], row['failure']['category']), ('failed', 'prerequisite-failed'))
            self.assertEqual(row['reason'], cause)

    def test_cancellation_propagates_and_dead_prerequisites_are_refused(self) -> None:
        self.enqueue(task_spec('a'), task_spec('b', prerequisites=('a',)))
        api.request_cancel(self.root, BATCH, 'a', 'operator changed scope')
        self.assertEqual(self.task('b')['failure']['category'], 'prerequisite-cancelled')
        with self.assertRaisesRegex(TaskRefused, 'prerequisite a is cancelled|Prerequisite a is cancelled'):
            self.enqueue(task_spec('c', prerequisites=('a',)))

    def test_a_replacement_names_a_new_version_and_dependency_set(self) -> None:
        self.enqueue(task_spec('cut'), task_spec('audio', prerequisites=('cut',)))
        self.finish_task(self.start_task('cut'))
        self.finish_task(self.start_task('audio'), 'audio')
        with self.assertRaisesRegex(TaskRefused, 'new input version'):
            self.enqueue(task_spec('cut-2', replaces='cut'))
        self.enqueue(task_spec('cut-2', version='v2', replaces='cut'), task_spec('audio-2', prerequisites=('cut-2',)))
        self.assertEqual((self.state('cut'), self.state('audio')), ('superseded', 'superseded'))
        self.assertEqual(self.task('cut')['supersededBy'], 'cut-2')
        with self.assertRaisesRegex(TaskRefused, 'superseded'):
            self.enqueue(task_spec('review', prerequisites=('audio',)))
        self.assertEqual(self.state('audio-2'), 'blocked')
        with self.assertRaisesRegex(TaskRefused, 'depend on a task it replaces'):
            self.enqueue(task_spec('cut-3', version='v3', replaces='cut-2'),
                         task_spec('audio-3', prerequisites=('cut-2',)))

    def test_a_superseded_result_never_satisfies_a_dependency(self) -> None:
        self.enqueue(task_spec('graphic'), task_spec('picture', prerequisites=('graphic',)))
        self.finish_task(self.start_task('graphic'))
        self.assertEqual(self.state('picture'), 'ready')
        api.supersede_task(self.root, BATCH, 'graphic', 'graphic words changed')
        self.assertEqual(self.state('picture'), 'superseded')
        with self.assertRaises(TaskRefused):
            self.claim('picture')

    def test_superseding_running_work_revokes_publishing_but_keeps_its_slot(self) -> None:
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'))
        ref = self.start_task('critic', host_turn('critic'))
        api.supersede_task(self.root, BATCH, 'critic', 'plan v2 replaced the reviewed plan')
        row = self.task('critic')
        self.assertEqual((row['state'], row['unresolved']), ('superseded', True))
        self.assertEqual(self.ai()['charged'], 2)
        result = self.finish_task(ref, 'late-findings')
        self.assertEqual((result['state'], result['unresolved']), ('superseded', False))
        trail = (self.root / 'batches/batch-auth/events.jsonl').read_text().splitlines()
        self.assertFalse(json.loads(trail[-1])['publishable'])

    def test_a_superseded_interrupted_turn_never_regains_publishing(self) -> None:
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'))
        ref = self.start_task('critic', host_turn('critic'))
        api.supersede_task(self.root, BATCH, 'critic', 'plan v2')
        api.confirm_cancelled(self.root, BATCH, ref)                    # Codex: tools may survive
        row = self.task('critic')
        self.assertEqual((row['state'], row['unresolved']), ('superseded', True))
        with self.assertRaisesRegex(TaskConflict, 'already ended as superseded'):
            self.finish_task(ref, 'late')                               # its end was already reported
        self.assertTrue(self.task('critic')['unresolved'])

    def test_unlaunched_ai_work_of_an_ended_parent_is_cancelled(self) -> None:
        self.enqueue(task_spec('author-a', 'author', parent='director'),
                     task_spec('art', 'specialist', clip_id='A', parent='author-a'))
        ref = self.start_task('author-a', host_turn('author'))
        self.finish_task(ref)
        self.assertEqual(self.state('art'), 'cancelled')
        self.assertIn('parent author-a ended', self.task('art')['reason'])


class ClaimTests(TaskCase):
    """Reserve before dispatch; enrollment, host slots, run and per-clip reservations; fencing."""

    def test_ai_work_needs_an_enrolled_live_parent(self) -> None:
        with self.assertRaisesRegex(TaskRefused, 'names no parent'):
            self.enqueue(task_spec('stray', 'review', clip_id='A'))
        self.enqueue(task_spec('plan', 'planning', parent='director'),
                     task_spec('spec', 'specialist', clip_id='A', parent='plan'))
        with self.assertRaisesRegex(TaskRefused, 'no live parent \\(plan is ready\\)'):
            self.claim('spec')
        with self.assertRaisesRegex(TaskRefused, 'must descend from AI work'):
            self.enqueue(task_spec('mech'), task_spec('ai-child', 'specialist', clip_id='A', parent='mech'))

    def test_enrollment_records_supervised_governance_and_its_limits(self) -> None:
        status = api.task_status(self.root, BATCH)
        governance = status['governance']
        self.assertEqual((governance['host'], governance['mode']), ('codex', 'supervised'))
        self.assertEqual(set(governance), {'host', 'version', 'mode', 'unsupported', 'unproven', 'source'})
        self.assertTrue({'absoluteAiExpiry', 'directorEnrollment'} <= set(governance['unsupported']))
        self.assertTrue(status['limitations'][0].startswith('AI deadlines are enforced only while the coordinator'))
        self.assertTrue(any('self-declared' in row for row in status['limitations']))
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'))
        rules = self.claim('critic', host_turn('critic'))['hostRules']
        self.assertEqual(rules['deadlineEnforcement'], 'supervised')
        self.assertEqual(rules['cleanEnvironment'], ['HOME', 'USER', 'LOGNAME', 'SHELL', 'TMPDIR', 'LANG', 'PATH'])
        self.clock.advance(1800)
        self.assertEqual(api.task_status(self.root, BATCH)['overdue'], ['critic'])

    def test_one_director_at_a_time_and_enrollment_replays(self) -> None:
        again = api.enroll_director(self.root, BATCH, Enrollment('director', DIRECTOR, 'v1', FINGERPRINT))
        self.assertEqual((again['token'], again['committed']), (self.director['token'], False))
        with self.assertRaisesRegex(TaskRefused, 'already enrolled'):
            api.enroll_director(self.root, BATCH, Enrollment('director-2', host_turn('x'), 'v1', FINGERPRINT))

    def test_slots_include_the_director_and_free_only_on_confirmed_termination(self) -> None:
        self.enqueue(*[task_spec(f'r{index}', 'review', clip_id='A', parent='director') for index in range(4)])
        refs = [self.start_task(f'r{index}', host_turn(f'r{index}')) for index in range(3)]
        with self.assertRaisesRegex(TaskRefused, 'All 4 AI slots are held'):
            self.claim('r3')
        api.request_cancel(self.root, BATCH, 'r0', 'deadline')
        with self.assertRaisesRegex(TaskRefused, 'All 4 AI slots'):
            self.claim('r3')                                       # cancellation requested is not complete
        confirmed = api.confirm_cancelled(self.root, BATCH, refs[0])
        self.assertEqual((confirmed['state'], confirmed['unresolved']), ('cancelled', True))
        with self.assertRaisesRegex(TaskRefused, 'All 4 AI slots'):
            self.claim('r3')                                       # Codex: an interrupt may leave its tools
        self.finish_task(refs[1], 'findings')
        self.assertEqual(self.claim('r3')['epoch'], 1)

    def test_a_host_that_ends_tools_on_interrupt_frees_the_slot_on_confirmation(self) -> None:
        self.use_claude_director()
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director-claude'))
        ref = self.start_task('critic', {'type': 'host', 'host': 'claude-code', 'thread': 'TEST-c', 'turn': None})
        api.request_cancel(self.root, BATCH, 'critic', 'deadline')
        self.assertEqual(api.confirm_cancelled(self.root, BATCH, ref)['state'], 'cancelled')
        self.assertEqual(api.task_status(self.root, BATCH)['ai']['active'], 1)

    def test_charges_are_per_task_never_refunded_and_counted_with_admit(self) -> None:
        import native_batch
        from test_native_budget_registry import ns
        native_batch.cmd_admit(ns(batch=BATCH, clip='A', kind='author', label='manual'))
        self.enqueue(*[task_spec(f'author-{index}', 'author', parent='director') for index in range(3)])
        first = self.claim('author-0')
        api.release_claim(self.root, BATCH, self.ref(first))          # definitely not launched
        second = self.claim('author-0')
        self.assertEqual((first['epoch'], second['epoch']), (1, 2))
        self.claim('author-1')
        with self.assertRaisesRegex(TaskRefused, 'author limit reached'):
            self.claim('author-2')
        record = self.record()
        self.assertEqual(record['clips']['A']['counters']['author'], 3)
        self.assertEqual(record['production']['ai']['charged'], 3)   # director + two authors
        self.assertIn('task author-0', [row['label'] for row in record['clips']['A']['dispatches']])

    def test_run_reservations_are_a_ceiling(self) -> None:
        path = self.root / 'batches/batch-auth/authority.json'
        record = json.loads(path.read_text())
        record['production']['ai']['reservations'] = 2
        record['production']['authorization']['identity'] = authorization_identity(record)   # part of the go
        path.write_text(json.dumps(record))
        self.enqueue(task_spec('plan-1', 'planning', parent='director'), task_spec('plan-2', 'planning',
                                                                                  parent='director'))
        self.claim('plan-1')
        with self.assertRaisesRegex(TaskRefused, 'all 2 of its AI reservations'):
            self.claim('plan-2')

    def test_minute_25_refuses_creative_claims_but_not_reviews(self) -> None:
        self.enqueue(task_spec('author-a', 'author', parent='director'),
                     task_spec('critic', 'review', clip_id='A', parent='director'))
        self.clock.advance(1500)
        with self.assertRaisesRegex(TaskRefused, 'Minute 25'):
            self.claim('author-a')
        self.claim('critic', host_turn('critic'))

    def test_an_expired_task_fails_at_claim_and_its_dependents_follow(self) -> None:
        self.enqueue(task_spec('a', deadline_elapsed=600.0), task_spec('b', prerequisites=('a',)))
        self.clock.advance(560)
        with self.assertRaisesRegex(TaskRefused, 'reached its deadline'):
            self.claim('a')
        self.assertEqual(self.task('a')['failure']['category'], 'deadline-expired')
        self.assertEqual(self.task('b')['failure']['category'], 'prerequisite-failed')

    def test_one_live_media_task_per_clip_and_family(self) -> None:
        self.enqueue(task_spec('draft', 'media'), task_spec('final', 'media', route='final'),
                     task_spec('preview', 'media', route='preview'))
        self.claim('draft')
        with self.assertRaisesRegex(TaskRefused, r'already has live exportAttempt work \(draft\); it waits'):
            self.claim('final')
        self.claim('preview')

    def test_a_running_launch_no_task_owns_holds_its_family(self) -> None:
        # Fix-round item 17: a direct public export of clip A is running; the media claim waits for it.
        self.enqueue(task_spec('final', 'media', route='final'))
        self.reserve(self.project)
        with self.assertRaisesRegex(TaskRefused, 'already has live exportAttempt work .*; it waits for its end'):
            self.claim('final')


class FencingTests(TaskCase):
    """Stale epochs are refused; duplicate callbacks are idempotent only for the identical outcome."""

    def test_stale_epoch_and_wrong_token_callbacks_are_refused(self) -> None:
        self.enqueue(task_spec('a'))
        old = self.ref(self.claim('a'))
        api.release_claim(self.root, BATCH, old)
        new = self.ref(self.claim('a'))
        for stale in (old, ClaimRef('a', new.epoch, '0' * 32)):
            with self.assertRaises(StaleClaim):
                api.attach_task(self.root, BATCH, stale, CHILD)
        api.attach_task(self.root, BATCH, new, CHILD)
        with self.assertRaises(StaleClaim):
            api.complete_task(self.root, BATCH, old, TaskResult((receipt('x'),)))
        self.assertEqual(self.state('a'), 'running')

    def test_duplicate_completion_is_idempotent_only_for_the_same_artifacts(self) -> None:
        self.enqueue(task_spec('a'))
        ref = self.start_task('a')
        self.assertTrue(self.finish_task(ref)['committed'])
        self.assertFalse(self.finish_task(ref)['committed'])
        with self.assertRaisesRegex(TaskConflict, 'different artifacts'):
            self.finish_task(ref, 'other')
        with self.assertRaisesRegex(TaskConflict, 'already ended as completed'):
            api.fail_task(self.root, BATCH, ref, TaskFailure('renderer-failure', 'late'))

    def test_a_second_execution_cannot_attach_to_a_claim(self) -> None:
        self.enqueue(task_spec('a'))
        ref = self.start_task('a')
        self.assertFalse(api.attach_task(self.root, BATCH, ref, CHILD)['committed'])
        with self.assertRaisesRegex(TaskConflict, 'another execution'):
            api.attach_task(self.root, BATCH, ref, {**CHILD, 'pid': 7003})

    def test_completion_needs_an_acknowledged_execution_and_receipts(self) -> None:
        self.enqueue(task_spec('a'))
        ref = self.ref(self.claim('a'))
        with self.assertRaisesRegex(TaskRefused, 'never acknowledged'):
            self.finish_task(ref)
        api.attach_task(self.root, BATCH, ref, CHILD)
        with self.assertRaisesRegex(ValueError, 'binds its artifacts'):
            api.complete_task(self.root, BATCH, ref, TaskResult(()))


class UsageTests(TaskCase):
    """Missing usage is unknown, never zero; cumulative reports never lower a count."""

    def usage(self, total: int | None, cached: int | None = None) -> dict:
        return {'inputTokens': total, 'outputTokens': None, 'cachedInputTokens': cached, 'reasoningTokens': None}

    def test_unknown_usage_stays_unknown_and_counts_never_decrease(self) -> None:
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'))
        ref = self.start_task('critic', host_turn('critic'))
        api.record_usage(self.root, BATCH, ref, self.usage(1000, 400))
        self.assertFalse(api.record_usage(self.root, BATCH, ref, self.usage(900, 100))['committed'])
        self.finish_task(ref)
        self.assertEqual(self.task('critic')['usage']['inputTokens'], 1000)
        status = api.task_status(self.root, BATCH)['ai']['usage']
        self.assertEqual(status['known']['inputTokens'], 1000)
        self.assertEqual(status['unknownTasks']['inputTokens'], 1)          # the director reported nothing
        self.assertEqual(status['unknownTasks']['outputTokens'], 2)
        with self.assertRaisesRegex(ValueError, 'cached input'):
            api.record_usage(self.root, BATCH, ref, self.usage(10, 20))

    def test_a_lowered_charge_is_corrupt_authority(self) -> None:
        path = self.root / 'batches/batch-auth/authority.json'
        record = json.loads(path.read_text())
        record['production']['ai']['charged'] = 0
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(BudgetAuthorityError, 'charges disagree'):
            self.record()


class ClockTests(TaskCase):
    """A wall-clock rollback never extends a task deadline; after a reboot it refuses the claim."""

    def test_rollback_does_not_reopen_an_expired_task(self) -> None:
        self.enqueue(task_spec('a', deadline_elapsed=600.0))
        self.clock.advance(600, wall=-3000)                  # ten minutes passed, wall set back 50 minutes
        with self.assertRaisesRegex(TaskRefused, 'reached its deadline'):
            self.claim('a')

    def test_rollback_across_a_reboot_refuses_new_claims(self) -> None:
        self.enqueue(task_spec('a'))
        self.claim('a')                                       # records the anchor
        self.clock.reboot(downtime=-100)
        with self.assertRaises(BudgetClockError):
            self.enqueue(task_spec('b'))


class ClaimRaceTests(TaskCase):
    """Two real processes race for the same claim or the last slot under the kernel lock."""

    def race(self, task_ids: tuple[str, str]) -> list[dict]:
        clock = json.dumps([self.clock.wall, self.clock.continuous, self.clock.boot])
        go = time.monotonic() + 1.5
        processes = [subprocess.Popen([sys.executable, '-c', RACE, str(HERE), str(self.root), clock, task_id,
                                       str(go), str(index)], stdout=subprocess.PIPE, text=True)
                     for index, task_id in enumerate(task_ids)]
        return [json.loads(process.communicate(timeout=60)[0]) for process in processes]

    def test_two_processes_claim_one_task_once(self) -> None:
        self.enqueue(task_spec('a'))
        results = self.race(('a', 'a'))
        self.assertEqual(sorted(row['result'] for row in results), ['claimed', 'refused'])
        self.assertIn('is claimed', next(row['reason'] for row in results if row['result'] == 'refused'))
        self.assertEqual(self.task('a')['epochs'], 1)

    def test_two_processes_race_for_the_last_ai_slot(self) -> None:
        self.enqueue(*[task_spec(f'r{index}', 'review', clip_id='A', parent='director') for index in range(4)])
        self.claim('r0', host_turn('r0'))
        self.claim('r1', host_turn('r1'))
        results = self.race(('r2', 'r3'))
        self.assertEqual(sorted(row['result'] for row in results), ['claimed', 'refused'])
        self.assertEqual(self.ai()['charged'], 4)


if __name__ == '__main__':
    unittest.main()
