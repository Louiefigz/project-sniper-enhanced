"""Recovery (unit A2): every crash boundary around claim/spawn/attach/charge/complete, host replay, full trail."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from contextlib import ExitStack
from unittest import mock

from _budget_fixture import (
    CHILD, DISPATCHER, b3_stand_in, handoff_confirmation, host_turn, receipt, table, task_spec, test_mp4,
)
from test_native_budget_registry import ns
from test_production_tasks import BATCH, HERE, TaskCase
import native_batch
from studio import native_budget_binding as binding
from studio import native_budget_launch as launch
from studio import native_budget_store as store
from studio.native_budget_store import BudgetAuthorityError
from studio.production import api
from studio.production.callbacks import TaskResult
from studio.production.claims import ClaimRef
from studio.production.tasks import StaleClaim, TaskConflict, TaskRefused

REPLAY = '''
import json, sys
from pathlib import Path
sys.path[:0] = [sys.argv[1], str(Path(sys.argv[1]) / "tests")]
from _budget_fixture import FakeClock, fake_clock
from studio.production import api
from studio.production.callbacks import TaskResult
from studio.production.claims import ClaimRef
wall, continuous, boot = json.loads(sys.argv[3])
ref = ClaimRef(*json.loads(sys.argv[4]))
with fake_clock(FakeClock(wall, continuous, boot)):
    print(json.dumps(api.complete_task(Path(sys.argv[2]), "batch-auth", ref, TaskResult(tuple(json.loads(sys.argv[5]))))))
'''


class RecoveryCase(TaskCase):
    """Process-table evidence is a TEST table; nothing real is signalled or observed."""

    def claimed(self, ref: ClaimRef) -> object:
        """The export watchdog's claim of one task (TEST request SHA-256)."""
        from studio.production.process import TaskClaim
        return TaskClaim(BATCH, ref.task_id, ref.epoch, ref.token, 'e' * 64)

    def settle(self, ref: ClaimRef, reason: tuple | None = None) -> dict:
        """Settle the claim as the export watchdog does once its child has ended."""
        from studio.production.process_settle import Ending, settle
        return settle(self.claimed(ref), Ending(CHILD['pid'], reason, (), None))

    def reconcile(self, rows: dict, host: dict | None = None) -> dict:
        with mock.patch.object(launch, '_process_table', return_value=rows):
            return api.reconcile(self.root, BATCH, host)

    def events(self, last: int = 2) -> list[str]:
        lines = (self.root / 'batches/batch-auth/events.jsonl').read_bytes().splitlines()[-last:]
        return [json.loads(line)['event'] for line in lines]

    def as_child(self, stack: ExitStack, identity: dict = CHILD) -> None:
        """The exporter process is the child that acknowledged the claim."""
        own = {key: identity[key] for key in ('pid', 'pgid', 'started')}
        for target in (binding, launch):
            stack.enter_context(mock.patch.object(target, 'own_identity', return_value=own))
        stack.enter_context(mock.patch.object(launch, '_process_table', return_value=table(identity)))

    def reserve_for(self, ref: ClaimRef, identity: dict = CHILD) -> dict:
        """The acknowledged child's launch (TEST: its request and inputs reproduce the task's fingerprint)."""
        with ExitStack() as stack:
            self.as_child(stack, identity)
            stack.enter_context(mock.patch.object(binding, 'launch_fingerprint',
                                                  return_value=self.task(ref.task_id)['inputFingerprint']))
            return binding.reserve_task_launch(binding.TaskLaunch(self.project, self.work / f'out-{ref.epoch}', 'draft',
                                                                  {}, BATCH, ref, 'e' * 64))


class ClaimBoundaryTests(RecoveryCase):
    """Crash while claiming, after claiming (before spawn) and after spawning (before acknowledgement)."""

    def test_a_failed_claim_commit_leaves_the_task_ready_and_uncharged(self) -> None:
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'))
        with mock.patch.object(store, 'write_pending_replace', side_effect=OSError('TEST disk full')):
            with self.assertRaises(BudgetAuthorityError):
                self.claim('critic', host_turn('critic'))
        self.assertEqual((self.state('critic'), self.ai()['charged']), ('ready', 1))
        self.assertEqual(self.events()[-2:], ['task-claimed', 'commit-failed'])
        self.assertEqual(self.claim('critic', host_turn('critic'))['epoch'], 1)

    def test_a_dead_claimer_leaves_an_uncertain_launch_charged_and_never_retried(self) -> None:
        self.enqueue(task_spec('draft', 'media'), task_spec('critic', 'review', clip_id='A', parent='director'))
        self.claim('draft')
        self.claim('critic')
        changes = self.reconcile(table())                                   # the dispatcher is gone
        self.assertEqual({row['taskId']: row['unresolved'] for row in changes['changes']},
                         {'draft': False, 'critic': True})
        self.assertEqual((self.state('draft'), self.state('critic')), ('abandoned', 'abandoned'))
        status = api.task_status(self.root, BATCH)
        self.assertEqual((status['ai']['active'], status['ai']['charged']), (2, 2))   # critic keeps its slot
        self.assertEqual(self.record()['clips']['A']['counters']['review'], 1)
        self.assertEqual(api.next_ready(self.root, BATCH), [])
        with self.assertRaisesRegex(TaskRefused, 'is abandoned'):
            self.claim('critic')

    def test_a_late_child_is_fenced_for_media_and_recorded_for_ai(self) -> None:
        self.enqueue(task_spec('draft', 'media'), task_spec('critic', 'review', clip_id='A', parent='director'))
        media, critic = self.ref(self.claim('draft')), self.ref(self.claim('critic'))
        self.reconcile(table())
        with self.assertRaisesRegex(TaskRefused, 'fenced before acknowledgement'):
            api.attach_task(self.root, BATCH, media, CHILD)
        attached = api.attach_task(self.root, BATCH, critic, host_turn('critic'))
        self.assertEqual((attached['state'], attached['proceed']), ('abandoned', False))
        self.finish_task(critic, 'findings')                               # the real outcome replaces the mark
        self.assertEqual((self.state('critic'), self.task('critic')['unresolved']), ('completed', True))   # G9
        self.assertEqual(api.task_status(self.root, BATCH)['ai']['active'], 2)

    def test_a_live_claimer_keeps_its_claim(self) -> None:
        self.enqueue(task_spec('draft', 'media'))
        self.claim('draft')
        self.assertEqual(self.reconcile(table(DISPATCHER))['changes'], [])
        self.assertEqual(self.state('draft'), 'claimed')
        self.assertEqual(self.reconcile(None)['changes'], [])              # an unreadable table is no evidence


class AttachAndChargeBoundaryTests(RecoveryCase):
    """Crash after acknowledgement, the atomic charge-and-bind, and a lost completion."""

    def test_a_child_gone_before_its_charge_is_abandoned_without_a_charge(self) -> None:
        self.enqueue(task_spec('draft', 'media'), task_spec('preview', 'media', route='preview'))
        self.start_task('draft', CHILD)
        other = {**CHILD, 'pid': 7005, 'pgid': 7005}
        self.start_task('preview', other)
        self.reconcile(table(survivors=(7005,)))                            # preview left a live descendant
        # P0 adapt (M-030): acknowledged media stays unresolved until its watchdog confirms cleanup (reconcile.py:
        # 172-178; B-26; G9): no owners were recorded, so nothing proves the draft's cleanup either.
        self.assertEqual((self.state('draft'), self.task('draft')['unresolved']), ('abandoned', True))
        self.assertEqual((self.state('preview'), self.task('preview')['unresolved']), ('abandoned', True))
        self.assertEqual(self.record()['clips']['A']['counters']['exportAttempt'], 0)
        self.reconcile(table())                                             # the descendant ended
        self.assertTrue(self.task('preview')['unresolved'])                 # P0 adapt: no watchdog evidence (G9)

    def test_the_launch_charge_and_the_task_binding_commit_together_once(self) -> None:
        self.enqueue(task_spec('draft', 'media'))
        ref = self.start_task('draft', CHILD)
        grant = self.reserve_for(ref)
        self.assertEqual(self.task('draft')['attempt'], grant['attemptId'])
        with self.assertRaisesRegex(TaskRefused, 'a claim launches once'):
            self.reserve_for(ref)
        self.assertEqual(self.record()['clips']['A']['counters']['exportAttempt'], 1)

    def test_a_refused_task_launch_charges_nothing(self) -> None:
        self.enqueue(task_spec('draft', 'media'))
        ref = self.start_task('draft', CHILD)
        with self.assertRaisesRegex(TaskRefused, 'Only the process that acknowledged'):
            self.reserve_for(ref, {**CHILD, 'pid': 7009})
        with mock.patch.object(store, 'write_pending_replace', side_effect=OSError('TEST disk full')):
            with self.assertRaises(BudgetAuthorityError):
                self.reserve_for(ref)
        self.assertIsNone(self.task('draft')['attempt'])
        api.request_cancel(self.root, BATCH, 'draft', 'operator stopped it')
        with self.assertRaisesRegex(TaskRefused, 'cancel-requested; no launch'):
            self.reserve_for(ref)
        self.assertEqual(self.record()['clips']['A']['counters']['exportAttempt'], 0)

    def test_an_exact_exporter_delivery_recovers_a_lost_completion(self) -> None:
        self.enqueue(task_spec('draft', 'media'), task_spec('review-draft', prerequisites=('draft',)))
        ref = self.start_task('draft', CHILD)
        grant = self.reserve_for(ref)
        binding.record_request_outcome({'productionBudget': grant}, {
            'status': 'native-short-review-draft', 'output': '/TEST/out/review-draft.mp4', 'sha256': 'a' * 64})
        self.settle(ref)                  # P0 adapt (B-1, B-26): the watchdog settles; the child died before completing
        self.assertEqual(self.state('draft'), 'completed')
        self.assertEqual(self.task('draft')['receipts'][0]['path'], '/TEST/out/review-draft.mp4')
        self.assertEqual(self.state('review-draft'), 'ready')

    def test_a_child_gone_after_its_charge_without_an_outcome_is_abandoned_and_charged(self) -> None:
        self.enqueue(task_spec('draft', 'media'))
        grant = self.reserve_for(self.start_task('draft', CHILD))
        changes = self.reconcile(table())                       # exporter and child died mid-launch
        self.assertEqual(changes['abandonedLaunches'], [grant['attemptId']])
        # P0 adapt (M-030): unresolved until the watchdog's cleanup evidence (reconcile.py:172-178; B-26; G9).
        self.assertEqual((self.state('draft'), self.task('draft')['unresolved']), ('abandoned', True))
        self.assertEqual(self.record()['clips']['A']['counters']['exportAttempt'], 1)
        with self.assertRaisesRegex(TaskRefused, 'is abandoned'):
            self.claim('draft')

    def test_an_exact_exporter_failure_fails_the_task(self) -> None:
        self.enqueue(task_spec('draft', 'media'))
        ref = self.start_task('draft', CHILD)
        grant = self.reserve_for(ref)
        binding.record_request_outcome({'productionBudget': grant}, {
            'status': 'failed', 'failureCategory': 'host-memory-pressure', 'error': 'TEST'})
        self.settle(ref)                  # P0 adapt (B-1): the watchdog settles the exact failure
        self.assertEqual(self.task('draft')['failure']['category'], 'host-memory-pressure')

    def test_a_failed_completion_commit_keeps_the_task_running(self) -> None:
        self.enqueue(task_spec('a'))
        ref = self.start_task('a')
        with mock.patch.object(store, 'write_pending_replace', side_effect=OSError('TEST disk full')):
            with self.assertRaises(BudgetAuthorityError):
                self.finish_task(ref)
        self.assertEqual(self.state('a'), 'running')
        self.assertTrue(self.finish_task(ref)['committed'])

    def test_a_terminal_result_replays_idempotently_from_another_process(self) -> None:
        self.enqueue(task_spec('a'))
        ref = self.start_task('a')
        self.finish_task(ref)
        clock = json.dumps([self.clock.wall, self.clock.continuous, self.clock.boot])
        arguments = [sys.executable, '-c', REPLAY, str(HERE), str(self.root), clock,
                     json.dumps([ref.task_id, ref.epoch, ref.token])]
        same = subprocess.run([*arguments, json.dumps([receipt('out')])], capture_output=True, text=True, timeout=60)
        self.assertEqual(json.loads(same.stdout)['committed'], False, same.stderr)
        other = subprocess.run([*arguments, json.dumps([receipt('other')])], capture_output=True, text=True, timeout=60)
        self.assertIn('TaskConflict', other.stderr)

    def test_pid_reuse_is_not_the_same_execution(self) -> None:
        self.enqueue(task_spec('a'))
        self.start_task('a', CHILD)
        api.request_cancel(self.root, BATCH, 'a', 'deadline')
        reused = {CHILD['pid']: (1, 4444, 'Sun Sep 27 11:59:00 2026'), 1: (0, 1, 'boot')}
        self.reconcile(reused)
        self.assertEqual((self.state('a'), self.task('a')['reason']), ('cancelled',
                                                                        'termination confirmed: the exact execution is gone'))


class HostEventTests(RecoveryCase):
    """Host events use the same fenced callbacks; acknowledgement of a cancel is not termination."""

    def event(self, kind: str, ref: ClaimRef, **values: object) -> dict:
        row = {'type': kind, 'taskId': ref.task_id, 'epoch': ref.epoch, 'token': ref.token,
               'handle': host_turn('critic'), 'sequence': 1, 'receipts': [], 'failure': None, 'usage': None}
        return {**row, **values}

    def critic(self) -> ClaimRef:
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'))
        return self.ref(self.claim('critic'))

    def test_a_lost_acceptance_is_recovered_by_the_completion_event(self) -> None:
        ref = self.critic()
        api.host_event(self.root, BATCH, self.event('completed', ref, receipts=[receipt('findings')]))
        self.assertEqual((self.state('critic'), self.task('critic')['handle']), ('completed', host_turn('critic')))
        replay = api.host_event(self.root, BATCH, self.event('completed', ref, receipts=[receipt('findings')]))
        self.assertFalse(replay['committed'])

    def test_cancel_acknowledgement_keeps_the_slot_until_the_interrupt_completes(self) -> None:
        ref = self.critic()
        api.host_event(self.root, BATCH, self.event('accepted', ref))
        api.request_cancel(self.root, BATCH, 'critic', 'visible delivery reached')
        acknowledged = api.host_event(self.root, BATCH, self.event('cancel-acknowledged', ref))
        self.assertEqual((acknowledged['state'], acknowledged['terminationPending']), ('cancel-requested', True))
        self.assertEqual(api.task_status(self.root, BATCH)['ai']['active'], 2)
        api.host_event(self.root, BATCH, self.event('interrupted', ref))
        self.assertEqual((self.state('critic'), self.task('critic')['unresolved']), ('cancelled', True))
        self.assertEqual(api.task_status(self.root, BATCH)['ai']['active'], 2)   # Codex tools may outlive it

    def test_an_interrupt_on_a_host_that_ends_tools_cancels_and_frees_the_slot(self) -> None:
        self.use_claude_director()
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director-claude'))
        ref = self.ref(self.claim('critic'))
        claude = {'type': 'host', 'host': 'claude-code', 'thread': 'TEST-c', 'turn': None}
        api.host_event(self.root, BATCH, self.event('accepted', ref, handle=claude))
        api.host_event(self.root, BATCH, self.event('interrupted', ref, handle=claude))
        self.assertEqual((self.state('critic'), api.task_status(self.root, BATCH)['ai']['active']), ('cancelled', 2))

    def test_stale_foreign_and_lost_events(self) -> None:
        ref = self.critic()
        api.host_event(self.root, BATCH, self.event('accepted', ref))
        with self.assertRaises(StaleClaim):
            api.host_event(self.root, BATCH, self.event('completed', ClaimRef('critic', 9, ref.token),
                                                        receipts=[receipt('x')]))
        with self.assertRaisesRegex(TaskConflict, 'names another execution'):
            api.host_event(self.root, BATCH, self.event('failed', ref, handle=host_turn('other'),
                                                        failure={'category': 'host-failure', 'detail': ''}))
        api.host_event(self.root, BATCH, self.event('lost', ref))
        self.assertEqual((self.state('critic'), self.task('critic')['unresolved']), ('abandoned', True))
        self.reconcile(table(), host={'codex:TEST-thread-critic:TEST-turn-critic': 'terminal'})
        self.assertTrue(self.task('critic')['unresolved'])       # a seen end does not prove its tools ended


class ExportChildBoundaryTests(RecoveryCase):
    """The exporter child's crash boundaries as the export watchdog settles them, once (units A3/A4)."""

    def test_a_child_gone_before_its_charge_fails_uncharged_and_is_never_relaunched(self) -> None:
        self.enqueue(task_spec('draft', 'media'))
        ref = self.start_task('draft', CHILD)
        self.settle(ref)
        task = self.task('draft')
        self.assertEqual((task['state'], task['unresolved'], task['failure']['category']),
                         ('failed', False, 'export-exited-without-outcome'))
        self.assertEqual(self.record()['clips']['A']['counters']['exportAttempt'], 0)
        with self.assertRaisesRegex(TaskRefused, 'is failed'):
            self.claim('draft')

    def test_a_child_gone_after_its_charge_without_an_outcome_stays_charged(self) -> None:
        self.enqueue(task_spec('draft', 'media'))
        grant = self.reserve_for(self.start_task('draft', CHILD))
        self.settle(ClaimRef('draft', 1, self.task('draft')['claim']['token']))
        attempt = self.record()['clips']['A']['attempts'][-1]
        self.assertEqual((attempt['id'], attempt['status'], attempt['failure']['category']),
                         (grant['attemptId'], 'failed', 'export-exited-without-outcome'))
        self.assertEqual((self.state('draft'), self.record()['clips']['A']['counters']['exportAttempt']),
                         ('failed', 1))

    def test_a_lost_settlement_is_recovered_from_the_exporters_own_receipt_and_replays_idempotently(self) -> None:
        self.enqueue(task_spec('draft', 'media'))
        ref = self.start_task('draft', CHILD)
        grant = self.reserve_for(ref)
        result = {'status': 'native-short-review-draft', 'output': str(self.work / 'out/review-draft.mp4'),
                  'sha256': 'c' * 64}
        binding.record_request_outcome({'productionBudget': grant}, result)
        with mock.patch.object(store, 'write_pending_replace', side_effect=OSError('TEST disk full')):
            with self.assertRaises(BudgetAuthorityError):
                self.settle(ref)                                  # the watchdog's settlement did not commit
        self.assertEqual(self.state('draft'), 'running')
        # P0 adapt (M-030): reconcile never completes acknowledged media from the receipt; only the watchdog confirms
        # cleanup (reconcile.py:172-178; B-1, B-26; G9). The delivery is kept on its attempt, the slot stays held
        # (closure records it, M-043), and a generic completion is refused (callbacks.py:77-81).
        self.reconcile(table())
        task = self.task('draft')
        self.assertEqual((task['state'], task['unresolved']), ('abandoned', True))
        attempt = self.record()['clips']['A']['attempts'][-1]
        self.assertEqual((attempt['id'], attempt['status'], attempt['resultStatus']),
                         (grant['attemptId'], 'succeeded', 'native-short-review-draft'))
        with self.assertRaisesRegex(TaskRefused, 'acknowledged media|abandoned'):
            api.complete_task(self.root, BATCH, ref, TaskResult(({'path': result['output'], 'sha256': 'c' * 64,
                                                                  'bytes': None},)))

    def test_a_child_of_a_released_claim_is_fenced(self) -> None:
        self.enqueue(task_spec('draft', 'media'))
        first = self.ref(self.claim('draft'))
        api.release_claim(self.root, BATCH, first)                # its run-media failed to start: nothing ran
        second = self.ref(self.claim('draft'))
        self.assertEqual(second.epoch, first.epoch + 1)
        with self.assertRaises(StaleClaim):
            api.attach_task(self.root, BATCH, first, CHILD)
        self.assertFalse(self.settle(first)['settled'])
        self.assertEqual(self.state('draft'), 'claimed')


class FullTrailTests(RecoveryCase):
    """A full trail refuses new work but still records an active critic's cancellation, hand-off and close."""

    def test_full_trail_with_an_active_critic_still_settles_and_closes(self) -> None:
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'), task_spec('extra'))
        ref = self.start_task('critic', host_turn('critic'))
        grant = self.reserve(self.project)
        mp4 = test_mp4(self.work / 'attempt')
        binding.record_request_outcome({'productionBudget': grant}, {
            'status': 'native-short-review-draft', 'output': mp4[0], 'sha256': mp4[1]})
        with (self.root / 'batches/batch-auth/events.jsonl').open('ab') as handle:
            handle.truncate(store.MAX_EVENT_BYTES - 10)
        with self.assertRaisesRegex(BudgetAuthorityError, 'trail is full'):
            self.enqueue(task_spec('more'))
        with self.assertRaisesRegex(BudgetAuthorityError, 'trail is full'):
            self.claim('extra')
        confirmation = handoff_confirmation(self.work / 'handoff', mp4, at=self.clock.wall)
        with b3_stand_in():
            handed = native_batch.cmd_handoff(ns(batch=BATCH, clip='A', confirmation=confirmation))  # visible first
        self.assertEqual(handed['frozenTasks'], ['critic'])
        api.confirm_cancelled(self.root, BATCH, ref)                       # Codex: slot stays unresolved
        api.complete_task(self.root, BATCH, ClaimRef('director', 1, self.director['token']), TaskResult(()))
        api.settle_resource(self.root, BATCH, 'critic', 'operator saw no tool process left')   # M-043: while active
        self.clock.advance(2400)
        self.assertEqual(native_batch.cmd_close(ns(batch=BATCH))['status'], 'closed')   # M-043: lists, never drains
        self.assertEqual(self.events(4), ['task-cancelled', 'task-completed', 'task-resource-settled', 'batch-closed'])
        self.assertEqual([row['taskId'] for row in self.record()['production']['closure']['unresolvedAtClose']],
                         ['critic'])


if __name__ == '__main__':
    unittest.main()
