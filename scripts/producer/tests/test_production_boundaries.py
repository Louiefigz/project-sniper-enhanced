"""Review round 3 regressions: supersession of uncertain claims, killed approval writes, staged starts,
the settlement room, transitive approval staleness and the pre-release schema 4.

Several cases are ports of the adversarial reviewer's probes (test_adv_a12_r2), kept as they were
written where the inputs are valid, so each asserts the guarantee the review named.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from _budget_fixture import CHANGE_REASON, CHILD, DISPATCHER, approval, host_turn, receipt, table, task_spec
from test_native_budget_registry import ns
from test_production_recovery import RecoveryCase
from test_production_tasks import BATCH, TaskCase
import native_batch
from studio import native_budget_batches as batches
from studio.native_budget_store import BudgetAuthorityError
from studio.production.approvals import ApprovalChange  # P0 adapt: src takes one typed change (WAVES:186)
from studio.production import api
from studio.production.reconcile import Observation
from studio.production.tasks import TaskRefused

AUTHORITY = 'batches/batch-auth/authority.json'


def observe(test: TaskCase, process_table: dict | None) -> dict:
    """Reconcile with a TEST process table and no host evidence."""
    with mock.patch('studio.production.api.current_observation', return_value=Observation(process_table, {})), \
            mock.patch('studio.production.api.reconcile_running', return_value=[]):
        return api.reconcile(test.root, BATCH)


def script_change(title: str) -> object:
    """Clip A's approval with its first cut shortened by one word (words 10-38, seconds [10, 39))."""
    texts = tuple(f'w{index}' for index in list(range(10, 39)) + list(range(50, 80)))
    return approval('A', title=title, word_ranges=((10, 38), (50, 79)), word_texts=texts,
                    ranges=((10.0, 39.0), (50.0, 80.0)))


class PortedApprovalChecks(TaskCase):
    """The reviewer's approval checks: exact re-records refused, typed changes, clock and counters untouched."""

    def test_unchanged_and_changed_approvals(self) -> None:
        before = self.record()
        with self.assertRaisesRegex(TaskRefused, 'already has this exact'):
            api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A'), CHANGE_REASON))
        self.enqueue(task_spec('author-a', 'author', parent='director'))
        claimed = self.claim('author-a', host_turn('author'))
        self.assertEqual(claimed['approval']['identity'], before['clips']['A']['approvals'][0]['identity'])
        self.assertEqual(claimed['approval']['title'], 'TEST title A')
        self.clock.advance(30)
        other = approval('A', title='TEST other title')
        changed = api.record_script_change(self.root, BATCH, 'A', ApprovalChange(other, CHANGE_REASON))
        self.assertEqual((changed['changed'], changed['material']), (['title'], True))
        after = self.record()
        self.assertEqual((after['startEpoch'], after['clips']['A']['counters']),
                         (before['startEpoch'], {**before['clips']['A']['counters'], 'author': 1}))
        changed = api.record_script_change(self.root, BATCH, 'A', ApprovalChange(script_change('TEST third title'), CHANGE_REASON))
        self.assertEqual((changed['changed'], changed['material']), (['title', 'script'], True))
        self.assertEqual(self.task('author-a')['claim']['approval'],
                         before['clips']['A']['approvals'][0]['identity'])


class SupersededUncertainClaims(TaskCase):
    """MAJOR 1: supersession never turns an uncertain AI claim back into a releasable one."""

    def test_supersede_then_release_of_an_abandoned_ai_claim_keeps_the_slot(self) -> None:
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'),
                     task_spec('after-critic', prerequisites=('critic',)))
        ref = self.ref(self.claim('critic', DISPATCHER))
        observe(self, table())                                    # claimer provably gone
        self.assertEqual((self.state('critic'), self.task('critic')['unresolved']), ('abandoned', True))
        api.supersede_task(self.root, BATCH, 'critic', 'plan v2')
        with self.assertRaisesRegex(TaskRefused, 'abandoned; releasing it cannot prove'):
            api.release_claim(self.root, BATCH, ref)
        self.assertEqual((self.state('critic'), self.task('critic')['unresolved']), ('abandoned', True))
        self.assertEqual(self.state('after-critic'), 'superseded')    # what was computed from it is revoked

    def test_superseded_unacknowledged_ai_claim_of_a_dead_holder_is_not_releasable(self) -> None:
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'))
        ref = self.ref(self.claim('critic', DISPATCHER))
        api.supersede_task(self.root, BATCH, 'critic', 'plan v2')
        self.assertEqual((self.state('critic'), self.task('critic')['unresolved']), ('superseded', True))
        observe(self, table())                                    # claimer provably gone; nothing recorded
        self.assertEqual((self.state('critic'), self.task('critic')['unresolved']), ('abandoned', True))
        with self.assertRaisesRegex(TaskRefused, 'abandoned'):
            api.release_claim(self.root, BATCH, ref)
        self.assertTrue(self.task('critic')['unresolved'])
        observe(self, table())                                    # evidence again changes nothing
        self.assertEqual(self.state('critic'), 'abandoned')

    def test_a_live_holder_may_still_release_a_superseded_claim(self) -> None:
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'))
        ref = self.ref(self.claim('critic', DISPATCHER))
        api.supersede_task(self.root, BATCH, 'critic', 'plan v2')
        api.release_claim(self.root, BATCH, ref, 'TEST: spawn critic ENOENT')   # its launch call failed
        self.assertEqual((self.state('critic'), self.task('critic')['unresolved']), ('superseded', False))


class ChangeReasons(TaskCase):
    """An operator's reason for a change to approved content is recorded in the row and its event."""

    def test_the_reason_is_recorded_and_bounded(self) -> None:
        change = approval('A', title='TEST retitled A')
        for bad, message in (('  ', "records the operator's reason"), ('\u00e9' * 100, 'at most 512 encoded bytes')):
            with self.assertRaisesRegex(ValueError, message):
                api.record_script_change(self.root, BATCH, 'A', ApprovalChange(change, bad))
        result = api.record_script_change(self.root, BATCH, 'A', ApprovalChange(change, ' operator asked for a new title '))
        self.assertEqual((result['reason'], result['approval']['reason']),
                         ('operator asked for a new title', 'operator asked for a new title'))
        current = api.read_approval(self.root, BATCH, 'A')['current']
        self.assertEqual(current['reason'], 'operator asked for a new title')
        trail = (self.root / 'batches/batch-auth/events.jsonl').read_bytes().splitlines()
        events = [json.loads(line) for line in trail if json.loads(line).get('event') == 'approval-changed']
        self.assertEqual([row['reason'] for row in events], ['operator asked for a new title'])

    def test_the_names_the_coordinator_commands_call(self) -> None:
        """A3 detects and calls these by name: record_script_change(..., reason), discard_staged, staged_starts."""
        import inspect
        self.assertEqual(list(inspect.signature(api.record_script_change).parameters),
                         ['root', 'batch_id', 'clip_id', 'change'])  # P0 adapt: src's typed change (WAVES:186)
        self.assertEqual(list(inspect.signature(api.discard_staged).parameters), ['root', 'name', 'reason'])
        self.assertEqual(list(inspect.signature(api.staged_starts).parameters), ['root'])


class OutputAuthorizedApprovals(TaskCase):
    """A derived Short authorized through D1's ``output-authorized`` event (clipId and approval, the shape of
    ``clip-added``) reads back its approval; a tampered identity in that event is corrupt authority."""

    def authorized_output(self, clip: str, identity: str | None = None) -> None:
        api.add_clip(self.root, BATCH, clip, api.AddedClip('TEST derived Short', approval(clip)))
        events = self.root / 'batches/batch-auth/events.jsonl'
        rows = [json.loads(line) for line in events.read_bytes().splitlines()]
        for row in rows:
            if row.get('event') == 'clip-added' and row['clipId'] == clip:
                row.update(event='output-authorized', approval=identity or row['approval'])
        events.write_text(''.join(json.dumps(row) + '\n' for row in rows))

    def test_a_derived_short_reads_back_its_approval(self) -> None:
        self.authorized_output('C')
        self.assertEqual(api.read_approval(self.root, BATCH, 'C')['current']['title'], 'TEST title C')
        api.record_script_change(self.root, BATCH, 'C', ApprovalChange(approval('C', title='TEST derived retitled'), CHANGE_REASON))
        self.assertEqual(api.read_approval(self.root, BATCH, 'C')['current']['title'], 'TEST derived retitled')

    def test_a_tampered_identity_in_the_event_is_refused(self) -> None:
        self.authorized_output('C', 'f' * 64)
        with self.assertRaisesRegex(BudgetAuthorityError, 'output-authorized event does not name its first approval'):
            api.read_approval(self.root, BATCH, 'C')


class RevokedNeverPublishes(TaskCase):
    """Round 4 MAJOR: revocation is carried independently of the state, in both orders (reviewer r3 probe)."""

    def late_completion(self, ref: object) -> dict:
        event = {'type': 'completed', 'taskId': 'critic', 'epoch': ref.epoch, 'token': ref.token,
                 'handle': host_turn('critic'), 'sequence': 9, 'receipts': [receipt('late')], 'failure': None,
                 'usage': None}
        return api.host_event(self.root, BATCH, event)

    def check(self) -> None:
        row = self.task('critic')
        self.assertEqual((row['state'], row['revoked'], row['unresolved'], row['receipts'][0]['path']),
                         ('superseded', True, True, receipt('late')['path']))   # kept as history; slot held (G9)
        self.assertEqual(self.state('earlier'), 'superseded')
        with self.assertRaisesRegex(TaskRefused, 'Prerequisite critic is superseded'):
            self.enqueue(task_spec('after', 'check', prerequisites=('critic',)))

    def begin(self) -> object:
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'),
                     task_spec('earlier', 'check', prerequisites=('critic',)))
        return self.ref(self.claim('critic', DISPATCHER))

    def test_supersede_then_holder_dies_then_late_completion(self) -> None:
        ref = self.begin()
        api.supersede_task(self.root, BATCH, 'critic', 'plan v2')
        observe(self, table())
        self.assertEqual((self.state('critic'), self.task('critic')['revoked']), ('abandoned', True))
        self.late_completion(ref)
        self.check()

    def test_holder_dies_then_supersede_then_late_completion(self) -> None:
        ref = self.begin()
        observe(self, table())
        api.supersede_task(self.root, BATCH, 'critic', 'plan v2')
        self.assertEqual((self.state('critic'), self.task('critic')['revoked']), ('abandoned', True))
        self.late_completion(ref)
        self.check()

    def test_the_completion_event_is_not_publishable(self) -> None:
        ref = self.begin()
        observe(self, table())
        api.supersede_task(self.root, BATCH, 'critic', 'plan v2')
        self.late_completion(ref)
        trail = (self.root / 'batches/batch-auth/events.jsonl').read_bytes().splitlines()
        completed = [json.loads(line) for line in trail if json.loads(line).get('event') == 'task-completed']
        self.assertEqual([row['publishable'] for row in completed], [False])

    def test_a_revoked_state_is_part_of_the_schema(self) -> None:
        self.enqueue(task_spec('a'))
        path = self.root / AUTHORITY
        record = json.loads(path.read_text())
        record['production']['tasks']['a'].update(state='superseded', terminalElapsed=1.0)   # revoked left False
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(BudgetAuthorityError, 'a superseded task is revoked'):
            self.record()


class ChainInference(TaskCase):
    """committed_changes against tamper, interleaved kills and reverts (reviewer r3 probe)."""

    def edit(self, change: object) -> None:
        path = self.root / AUTHORITY
        record = json.loads(path.read_text())
        change(record)
        path.write_text(json.dumps(record))

    def killed(self, clip: str, title: str) -> None:
        with mock.patch('studio.native_budget_store.write_pending_replace', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                api.record_script_change(self.root, BATCH, clip, ApprovalChange(approval(clip, title=title), CHANGE_REASON))

    def readable(self, clip: str) -> str:
        try:
            return api.read_approval(self.root, BATCH, clip)['current']['title']
        except BudgetAuthorityError as error:
            return f'CORRUPT: {str(error)[:80]}'

    def test_mid_chain_replacement_is_detected(self) -> None:
        from studio.native_budget_selection import approval_identity, title_identity
        for title in ('TEST two', 'TEST three'):
            api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A', title=title), CHANGE_REASON))

        def forge(record: dict) -> None:
            rows = record['clips']['A']['approvals']
            rows[1].update(title='FORGED middle', titleSha256=title_identity('FORGED middle'))
            rows[1]['identity'] = approval_identity('FORGED middle', rows[1]['script'])
            rows[2]['previous'] = rows[1]['identity']
        self.edit(forge)
        self.assertTrue(self.readable('A').startswith('CORRUPT'))

    def test_interleaved_kills_on_two_clips_heal(self) -> None:
        self.killed('A', 'TEST A1')
        api.record_script_change(self.root, BATCH, 'B', ApprovalChange(approval('B', title='TEST B1'), CHANGE_REASON))
        self.killed('B', 'TEST B2')
        api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A', title='TEST A1'), CHANGE_REASON))
        self.killed('A', 'TEST A2')
        api.record_script_change(self.root, BATCH, 'B', ApprovalChange(approval('B', title='TEST B3'), CHANGE_REASON))
        self.assertEqual((self.readable('A'), self.readable('B')), ('TEST A1', 'TEST B3'))

    def test_revert_then_killed_repeat_heals(self) -> None:
        api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A', title='TEST two'), CHANGE_REASON))
        api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A'), CHANGE_REASON))
        self.killed('A', 'TEST two')
        self.assertEqual(self.readable('A'), 'TEST title A')

    def test_dropping_the_two_latest_rows_is_detected(self) -> None:
        self.killed('A', 'TEST two')
        api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A', title='TEST two'), CHANGE_REASON))
        api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A', title='TEST three'), CHANGE_REASON))
        self.edit(lambda record: [record['clips']['A']['approvals'].pop() for _ in range(2)])
        self.assertTrue(self.readable('A').startswith('CORRUPT'))


class KilledApprovalWrites(TaskCase):
    """MAJOR 2: a process killed between the trail append and the record write never bricks a clip."""

    def kill(self, action: object) -> None:
        with mock.patch('studio.native_budget_store.write_pending_replace', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                action()

    def test_killed_change_then_retry_keeps_approvals_readable(self) -> None:
        change = approval('A', title='TEST retitled A')
        self.kill(lambda: api.record_script_change(self.root, BATCH, 'A', ApprovalChange(change, CHANGE_REASON)))
        self.assertEqual(len(api.read_approval(self.root, BATCH, 'A')['history']), 1)
        self.enqueue(task_spec('unrelated'))                     # later events of other kinds
        self.assertEqual(len(api.read_approval(self.root, BATCH, 'A')['history']), 1)
        api.record_script_change(self.root, BATCH, 'A', ApprovalChange(change, CHANGE_REASON))
        read = api.read_approval(self.root, BATCH, 'A')
        self.assertEqual((len(read['history']), read['current']['title']), (2, 'TEST retitled A'))
        third, fourth = (approval('A', title=title) for title in ('TEST third A', 'TEST fourth A'))
        self.kill(lambda: api.record_script_change(self.root, BATCH, 'A', ApprovalChange(third, CHANGE_REASON)))
        api.record_script_change(self.root, BATCH, 'A', ApprovalChange(fourth, CHANGE_REASON))            # a different retry
        self.assertEqual(api.read_approval(self.root, BATCH, 'A')['current']['title'], 'TEST fourth A')

    def test_killed_add_clip_then_retry_keeps_approvals_readable(self) -> None:
        self.kill(lambda: api.add_clip(self.root, BATCH, 'C', api.AddedClip('probe', approval('C'))))
        api.add_clip(self.root, BATCH, 'C', api.AddedClip('probe', approval('C')))
        self.assertEqual(len(api.read_approval(self.root, BATCH, 'C')['history']), 1)

    def test_a_mismatch_inside_the_chain_is_still_corrupt(self) -> None:
        api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A', title='TEST second A'), CHANGE_REASON))
        api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A', title='TEST third A'), CHANGE_REASON))
        events = self.root / 'batches/batch-auth/events.jsonl'
        rows = [json.loads(line) for line in events.read_bytes().splitlines()]
        first = next(row for row in rows if row.get('event') == 'approval-changed')
        first['toIdentity'] = 'f' * 64
        events.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaisesRegex(BudgetAuthorityError, 'do not match the approval chain'):
            api.read_approval(self.root, BATCH, 'A')


class StaleInputs(TaskCase):
    """approvalStale travels through every dependency, run-scoped tasks included."""

    def test_run_scoped_intermediary_does_not_launder_a_stale_input(self) -> None:
        self.enqueue(task_spec('author-a', 'author', parent='director'),
                     task_spec('mix', 'check', prerequisites=('author-a',)),          # run-scoped (no clip)
                     task_spec('draft-a', 'media', prerequisites=('mix',)))
        self.finish_task(self.start_task('author-a', host_turn('author')))
        ref = self.start_task('mix')
        api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A', title='TEST retitled A'), CHANGE_REASON))
        self.finish_task(ref, 'mix')
        self.assertEqual(self.state('draft-a'), 'blocked')
        self.assertIn('its input author-a was completed under an approval that is no longer current',
                      self.task('draft-a')['reason'])
        api.supersede_task(self.root, BATCH, 'author-a', 'retitled')                  # the operator's remedy
        self.assertEqual([self.state(name) for name in ('mix', 'draft-a')], ['superseded', 'superseded'])


    def test_a_prerequisite_cycle_is_corrupt_authority(self) -> None:
        self.enqueue(task_spec('a'), task_spec('b', prerequisites=('a',)))
        path = self.root / AUTHORITY
        record = json.loads(path.read_text())
        record['production']['tasks']['a']['prerequisites'] = ['b']
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(BudgetAuthorityError, 'form a cycle'):
            self.record()


class StaleLaunch(RecoveryCase):
    """A media claim made under an approval that then changed materially is refused before its charge."""

    def test_a_stale_media_claim_is_refused_before_its_charge(self) -> None:
        self.enqueue(task_spec('draft', 'media'))
        ref = self.ref(self.claim('draft', DISPATCHER))
        api.attach_task(self.root, BATCH, ref, CHILD)
        api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A', title='TEST retitled A'), CHANGE_REASON))
        before = self.record()['clips']['A']['counters']['exportAttempt']
        with self.assertRaisesRegex(TaskRefused, 'approval has since changed'):
            self.reserve_for(ref)
        self.assertEqual(self.record()['clips']['A']['counters']['exportAttempt'], before)


class SchemaFourTests(TaskCase):
    """The never-deployed pre-release schema 4 is refused by that name; a closed one still archives."""

    def test_schema_four_is_refused_by_name(self) -> None:
        path = self.root / AUTHORITY
        record = json.loads(path.read_text())
        path.write_text(json.dumps({**record, 'schemaVersion': 4}))
        with self.assertRaisesRegex(BudgetAuthorityError, 'pre-release schema 4'):
            native_batch.cmd_status(ns(batch=BATCH))
        path.write_text(json.dumps({**record, 'schemaVersion': 4, 'status': 'closed', 'closedAtElapsed': 5.0,
                                    'production': {**record['production'], 'tasks': {}}}))
        batches.archive_batch(self.root, BATCH, 'operator: pre-release schema')
        self.assertEqual(batches.list_batches(self.root), [])


if __name__ == '__main__':
    unittest.main()
