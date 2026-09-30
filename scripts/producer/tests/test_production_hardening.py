"""A12 review round: slots, per-task host cleanup, headroom, approvals, staged starts, schema-3 lift.

Several cases are the reviewer's adversarial probes (scratchpad a12/test_adv_a12.py and
test_adv_headroom_257.py), adapted only where approvals must now match their transcript.
"""
from __future__ import annotations

import json
import random
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _budget_fixture import (
    CHANGE_REASON, CHILD, DISPATCHER, FINGERPRINT, approval, host_turn, make_project, receipt, table, task_spec,
    write_transcript,
)
from _dispatch_fixture import start_args
from test_native_budget_registry import ns
from test_production_tasks import BATCH, TaskCase
import native_batch
from studio import native_budget_batches as batches
from studio import native_budget_forecast as forecast
from studio import native_budget_owner as owner_budget
from studio import native_budget_registry as registry
from studio.native_budget_store import BudgetAuthorityError
from studio.production.approvals import ApprovalChange  # P0 adapt: src takes one typed change (WAVES:186)
from _pending import pending
from studio.production import api, task_schema
from studio.production.callbacks import TaskFailure, TaskResult
from studio.production.claims import ClaimRef, Enrollment
from studio.production.reconcile import Observation
from studio.production.tasks import TaskRefused

CLAUDE = {'type': 'host', 'host': 'claude-code', 'thread': 'TEST-claude', 'turn': None}


def observe(test: TaskCase, process_table: dict | None, host: dict | None = None) -> dict:
    """Reconcile against an explicit process table and host turn states."""
    with mock.patch('studio.production.api.current_observation', return_value=Observation(process_table, host or {})), \
            mock.patch('studio.production.api.reconcile_running', return_value=[]):
        return api.reconcile(test.root, BATCH)


class SlotTests(TaskCase):
    """MAJOR 1 and 2: a slot frees only on a confirmed end, judged by the task's own host."""

    def abandoned_unacknowledged(self) -> ClaimRef:
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'))
        ref = self.ref(self.claim('critic', DISPATCHER))
        observe(self, table())                                    # the claim holder is gone
        self.assertEqual((self.state('critic'), self.task('critic')['unresolved']), ('abandoned', True))
        return ref

    def test_an_abandoned_claim_cannot_be_released(self) -> None:
        ref = self.abandoned_unacknowledged()
        with self.assertRaisesRegex(TaskRefused, 'cannot prove that nothing launched'):
            api.release_claim(self.root, BATCH, ref)
        self.assertEqual(api.task_status(self.root, BATCH)['ai']['active'], 2)

    def test_confirming_ai_work_with_no_bound_execution_keeps_its_slot(self) -> None:
        ref = self.abandoned_unacknowledged()
        api.confirm_cancelled(self.root, BATCH, ref)
        self.assertTrue(self.task('critic')['unresolved'])
        self.enqueue(task_spec('plan', 'planning', parent='director'))
        claimed = self.ref(self.claim('plan', DISPATCHER))
        confirmed = api.confirm_cancelled(self.root, BATCH, claimed)  # claimed, never attached
        self.assertEqual((confirmed['state'], confirmed['unresolved']), ('cancelled', True))

    def test_a_codex_turn_under_a_claude_director_keeps_its_slot(self) -> None:
        self.use_claude_director()
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director-claude'))
        ref = self.start_task('critic', host_turn('critic'))           # a Codex turn
        api.request_cancel(self.root, BATCH, 'critic', 'deadline')
        self.assertTrue(api.confirm_cancelled(self.root, BATCH, ref)['unresolved'])

    def test_a_claude_turn_under_a_codex_director_frees_on_its_interrupt(self) -> None:
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'))
        ref = self.start_task('critic', CLAUDE)
        api.request_cancel(self.root, BATCH, 'critic', 'deadline')
        self.assertEqual(api.confirm_cancelled(self.root, BATCH, ref)['unresolved'], True)   # G9: held until M-102

    def test_enrollment_accepts_a_self_declared_handle(self) -> None:
        api.complete_task(self.root, BATCH, ClaimRef('director', 1, self.director['token']), TaskResult(()))
        fake = {'type': 'host', 'host': 'codex', 'thread': 'TEST-never-existed', 'turn': 'TEST-none'}
        self.assertTrue(api.enroll_director(self.root, BATCH, Enrollment('director-2', fake, 'v1', FINGERPRINT))
                        ['committed'])                            # documented limit: nothing verifies it

    def test_an_abandoned_director_cancels_its_unlaunched_ai_work(self) -> None:
        self.enqueue(task_spec('plan', 'planning', parent='director'))
        observe(self, None, {'codex:TEST-thread-director:TEST-turn-1': 'unknown'})
        self.assertEqual((self.state('director'), self.state('plan')), ('abandoned', 'cancelled'))

    def test_a_superseded_unacknowledged_media_claim_of_a_dead_holder_is_fenced(self) -> None:
        self.enqueue(task_spec('draft', 'media'))
        self.claim('draft', DISPATCHER)
        api.supersede_task(self.root, BATCH, 'draft', 'cut changed')
        observe(self, table())
        self.assertEqual((self.state('draft'), self.task('draft')['unresolved']), ('superseded', False))

    def test_charges_never_decrease_under_a_random_walk(self) -> None:
        rng = random.Random(1234)
        kinds = ('review', 'planning', 'check', 'author')
        specs = []
        for index in range(24):
            kind = rng.choice(kinds)
            specs.append(task_spec(f't{index}', kind) if kind == 'check' else
                         task_spec(f't{index}', kind, clip_id='A' if kind == 'author' or index % 2 else None,
                                   parent='director'))
        self.enqueue(*specs)
        refs, history = {}, []
        for step in range(300):
            record = self.record()
            history.append((record['production']['ai']['charged'], dict(record['clips']['A']['counters']),
                            record['startEpoch']))
            self.random_step(rng, refs, step)
            self.clock.advance(1)
        for before, after in zip(history, history[1:]):
            self.assertLessEqual(before[0], after[0])
            self.assertTrue(all(after[1][key] >= before[1][key] for key in before[1]))
            self.assertEqual(before[2], after[2])
        status = api.task_status(self.root, BATCH)
        self.assertLessEqual(status['ai']['active'], status['ai']['slots'])

    def random_step(self, rng: random.Random, refs: dict, step: int) -> None:
        task_id = f't{rng.randrange(24)}'
        actions = {'claim': lambda: refs.__setitem__(task_id, self.ref(self.claim(task_id, host_turn(f'c{step}')))),
                   'release': lambda: api.release_claim(self.root, BATCH, refs[task_id], 'TEST: spawn failed'),
                   'attach': lambda: api.attach_task(self.root, BATCH, refs[task_id], CHILD if self.task(task_id)
                                                     ['kind'] == 'check' else host_turn(task_id)),
                   'complete': lambda: self.finish_task(refs[task_id], f'{task_id}-{step}'),
                   'fail': lambda: api.fail_task(self.root, BATCH, refs[task_id], TaskFailure('renderer-failure', 'x')),
                   'cancel': lambda: api.request_cancel(self.root, BATCH, task_id, 'probe'),
                   'confirm': lambda: api.confirm_cancelled(self.root, BATCH, refs[task_id]),
                   'supersede': lambda: api.supersede_task(self.root, BATCH, task_id, 'probe'),
                   'reconcile': lambda: observe(self, table(CHILD) if rng.random() < 0.5 else table(), {
                       f'codex:TEST-thread-{task_id}:TEST-turn-{task_id}': rng.choice(('running', 'terminal', 'unknown'))})}
        name = rng.choice(sorted(actions))
        if name in ('release', 'attach', 'complete', 'fail', 'confirm') and task_id not in refs:
            return
        try:
            actions[name]()
        except (TaskRefused, ValueError):
            pass


class HeadroomTests(TaskCase):
    """Minor 3: new work always leaves every open task room for its widest outcome."""

    def test_the_widest_row_is_a_valid_row(self) -> None:
        from studio.production import settlement
        self.assertTrue(task_schema._fields_ok(settlement.widest_task_row()))
        self.assertGreater(settlement.MAX_TASK_ENTRY_BYTES, 12 * 1024)

    def test_filling_the_record_with_approvals_never_blocks_a_task_outcome(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        words = [{'word': f'{index:04d}' + 'W' * 60, 'start': index * 0.5, 'end': index * 0.5 + 0.4}
                 for index in range(2000)]
        path = Path(temp.name) / 'long.json'
        sha = write_transcript(path, words)
        self.enqueue(task_spec('critic', 'review', clip_id='A', parent='director'))
        ref = self.start_task('critic', host_turn('critic'))
        filled = self.fill(words, (path, sha))
        self.assertGreater(filled, 0)
        big = tuple(dict(receipt(f'{"p" * 1000}{index}')) for index in range(8))
        self.assertTrue(api.complete_task(self.root, BATCH, ref, TaskResult(big))['committed'])

    def fill(self, words: list, transcript: tuple) -> int:
        """The reviewer's fill: add clips and change approvals, largest first, until the record refuses."""
        capacity, version = {}, 0
        for count in (1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1):
            while self.fill_once(capacity, (words, transcript, count, version)):
                version += 1
        return version

    def fill_once(self, capacity: dict, context: tuple) -> bool:
        words, (path, sha), count, version = context
        ranges = tuple((index, index) for index in range(min(count, 128)))
        if count > len(ranges):
            ranges = ranges[:-1] + ((ranges[-1][0], ranges[-1][0] + count - len(ranges)),)
        kept = [index for first, last in ranges for index in range(first, last + 1)]
        open_clips = [clip for clip, left in capacity.items() if left > 0]
        clip = open_clips[0] if open_clips else f'X{len(capacity)}'
        value = approval(clip, title=f'T{version}-{count}', word_ranges=ranges, transcript_words=2000,
                         word_texts=tuple(words[index]['word'] for index in kept), transcript_path=str(path),
                         transcript_sha256=sha, ranges=tuple((first * 0.5, last * 0.5 + 0.4) for first, last in ranges))
        try:
            if open_clips:
                api.record_script_change(self.root, BATCH, clip, ApprovalChange(value, CHANGE_REASON))
                capacity[clip] -= 1
            elif len(capacity) < 30:
                api.add_clip(self.root, BATCH, clip, api.AddedClip('probe', value))
                capacity[clip] = 2
            else:
                return False
        except BudgetAuthorityError:
            return False
        return True


class ApprovalTests(TaskCase):
    """Minors 4, 5 and 12 and required change 10."""

    def test_a_missing_title_is_refused(self) -> None:
        from dataclasses import replace
        from studio.native_budget_policy import approval_row
        with self.assertRaisesRegex(ValueError, 'a title is always given'):
            approval_row(replace(approval('A'), title=None), 0.0, 0.0, 'probe')

    def test_a_rehashed_later_approval_is_refused_by_the_reader(self) -> None:
        from studio.native_budget_selection import approval_identity, title_identity
        api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A', title='TEST second title'), CHANGE_REASON))
        path = self.root / 'batches/batch-auth/authority.json'
        record = json.loads(path.read_text())
        row = record['clips']['A']['approvals'][-1]
        row['title'] = 'FORGED title never approved'
        row.update(titleSha256=title_identity(row['title']), identity=approval_identity(row['title'], row['script']))
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(BudgetAuthorityError, 'approval-changed events do not match'):
            api.read_approval(self.root, BATCH, 'A')

    def test_a_broken_chain_is_corrupt_authority(self) -> None:
        api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A', title='TEST second title'), CHANGE_REASON))
        path = self.root / 'batches/batch-auth/authority.json'
        record = json.loads(path.read_text())
        record['clips']['A']['approvals'][-1]['previous'] = 'f' * 64
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(BudgetAuthorityError, 'approval chain'):
            self.record()

    def test_a_normalization_only_change_is_not_material(self) -> None:
        changed = api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A', title='TEST  title A'), CHANGE_REASON))
        self.assertEqual((changed['changed'], changed['material']), (['title-normalization'], False))

    def test_a_material_change_mid_claim_stales_the_completion(self) -> None:
        self.enqueue(task_spec('author-a', 'author', parent='director'),
                     task_spec('check-a', 'check', clip_id='A', prerequisites=('author-a',)))
        ref = self.start_task('author-a', host_turn('author'))
        self.assertIsNotNone(self.task('author-a')['claim']['approval'])
        api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A', title='TEST retitled A'), CHANGE_REASON))
        self.finish_task(ref)
        self.assertEqual((self.state('author-a'), self.task('author-a')['approvalStale']), ('completed', True))
        self.assertEqual(self.state('check-a'), 'blocked')
        self.assertIn('no longer current', self.task('check-a')['reason'])
        self.enqueue(task_spec('author-a2', 'author', parent='director', version='v2', replaces='author-a'))
        self.assertEqual(self.state('check-a'), 'superseded')

    def test_a_normalization_only_change_mid_claim_does_not_stale(self) -> None:
        self.enqueue(task_spec('author-a', 'author', parent='director'),
                     task_spec('check-a', 'check', clip_id='A', prerequisites=('author-a',)))
        ref = self.start_task('author-a', host_turn('author'))
        api.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A', title='TEST  title A'), CHANGE_REASON))
        self.finish_task(ref)
        self.assertEqual((self.task('author-a')['approvalStale'], self.state('check-a')), (False, 'ready'))

    def test_approval_seconds_follow_the_writers_cut_rule(self) -> None:
        for ranges, reason in ((((10000.0, 40000.0), (50000.0, 80000.0)), 'outside the source'),
                               (((10.0, 41.0), (50.0, 80.0)), 'keeps words 10-40, not the approved words 10-39'),
                               (((10.5, 40.0), (50.0, 80.0)), None)):
            if reason is None:
                ok = approval('A', title='TEST ok', ranges=ranges)
                api.record_script_change(self.root, BATCH, 'A', ApprovalChange(ok, CHANGE_REASON))
                continue
            with self.assertRaisesRegex(ValueError, reason):
                bad = approval('A', title='TEST x', ranges=ranges)
                api.record_script_change(self.root, BATCH, 'A', ApprovalChange(bad, CHANGE_REASON))


class StagedStartTests(TaskCase):
    """Minor 8 and required change 11: a staged authorization is adopted with its go-time anchor."""

    def start_cli(self, batch_id: str, clips: str = 'A') -> dict:
        with mock.patch.object(forecast, 'heavy_lane_capacity', return_value=1):
            return native_batch.cmd_start(start_args(self.work, batch_id, clips))

    def close_auth(self, advance: float = 2400) -> None:
        api.complete_task(self.root, BATCH, ClaimRef('director', 1, self.director['token']), TaskResult(()))
        self.clock.advance(advance)
        native_batch.cmd_close(ns(batch=BATCH))

    def test_an_interrupted_rename_is_adopted(self) -> None:
        self.close_auth()
        handover = self.clock.wall
        with mock.patch.object(batches.os, 'rename', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.start_cli('batch-next')
        self.clock.advance(300)
        started = self.start_cli('batch-next')
        self.assertEqual((started['resumed'], started['authorizedAtEpoch']), (True, handover))

    @pending('P3b', "A12 R4-12: studio/production/commands.py:96-99 cmd_start drops authorize()'s "
                    "discardedStagings and priorAuthorizations (P0 Step 4.4, owner P3b)")
    def test_a_refused_start_is_recorded_and_adopted_after_the_predecessor_closes(self) -> None:
        self.clock.advance(300)
        with self.assertRaisesRegex(batches.PredecessorCurrent, 'is recorded'):
            self.start_cli('batch-next')
        first = next(entry.name for entry in (self.root / 'batches').iterdir() if entry.name.startswith('.creating'))
        self.clock.advance(1200)                                 # handed over again 25 minutes into batch-auth
        handover = self.clock.wall
        with self.assertRaisesRegex(batches.PredecessorCurrent, f'replaces the earlier hand-over {first}'):
            self.start_cli('batch-next', 'A,B')                   # other approved content: a new hand-over
        self.assertEqual(batches.list_batches(self.root), ['batch-auth'])           # staged, ignored by resolution
        self.close_auth(900)                                     # batch-auth closes at its minute 40
        started = self.start_cli('batch-next', 'A,B')
        self.assertEqual((started['resumed'], started['authorizedAtEpoch']), (True, handover))
        self.assertAlmostEqual(started['setupElapsed'], 900.0)                 # the clock ran from the go time
        self.assertEqual([(row['name'], row['cause']) for row in started['priorAuthorizations']],
                         [(first, 'replaced')])

    def test_refused_starts_are_bounded(self) -> None:
        from studio.production import authorization
        with mock.patch.object(authorization, 'MAX_STAGED', 2):
            for index in range(2):
                with self.assertRaisesRegex(batches.PredecessorCurrent, 'is recorded'):
                    self.start_cli(f'batch-wait-{index}')
            with self.assertRaisesRegex(batches.BudgetRefused, 'already recorded'):
                self.start_cli('batch-wait-9')


class LegacyLiftTests(TaskCase):
    """Rollout: a closed schema-3 batch is lifted read-only for resolution; nothing else is."""

    def as_v3(self, change: object = None) -> dict:
        api.complete_task(self.root, BATCH, ClaimRef('director', 1, self.director['token']), TaskResult(()))
        self.clock.advance(2400)
        native_batch.cmd_close(ns(batch=BATCH))
        path = self.root / 'batches/batch-auth/authority.json'
        record = json.loads(path.read_text())
        del record['production']
        for clip in record['clips'].values():
            del clip['approvals']
        record['schemaVersion'] = 3
        if change:
            change(record)
        path.write_text(json.dumps(record))
        return record

    @pending('P4', 'E-007: D2 (5f99f8da) studio/native_budget_owner.py:89-90 reads each served output with the strict '
             'production/outputs.py:208 read_any_batch, which refuses the lifted closed schema-3 batch as another '
             'engine version before _utility_grant refuses it by name; M-121a skips the read for inactive bindings')
    def test_a_closed_v3_batch_resolves_read_only(self) -> None:
        raw = self.as_v3()
        before = (self.root / 'batches/batch-auth/authority.json').read_bytes()
        self.assertIsNone(registry.resolve_binding(self.root, make_project(self.work, 'free', source=b'other')))
        copy_of_a = make_project(self.work, 'copy-of-a')
        (copy_of_a / 'PROJECT-MANIFEST.json').write_text(json.dumps(
            {'projectHash': raw['clips']['A']['projects'][0]['projectHash'], 'files': []}))
        with self.assertRaisesRegex(registry.BudgetRefused, 'clip A of closed batch batch-auth'):
            registry.resolve_binding(self.root, copy_of_a)
        self.assertIsNone(registry.owner_binding(self.root, make_project(self.work, 'free-2', source=b'other')))
        owner = SimpleNamespace(hard_deadline=None, project=self.project, label='audio', deadline=600,
                                settings=SimpleNamespace(serves=None))
        with self.assertRaisesRegex(registry.BudgetRefused, 'closed batch batch-auth'):
            owner_budget.apply_budget_to_owner(owner)              # documented side effect until archived
        with mock.patch.object(forecast, 'heavy_lane_capacity', return_value=1):
            self.assertEqual(native_batch.cmd_start(start_args(self.work, 'batch-next', 'A'))['status'],
                             'batch-started')
        with self.assertRaisesRegex(BudgetAuthorityError, 'another engine version'):
            native_batch.cmd_status(ns(batch='batch-auth'))
        self.assertEqual((self.root / 'batches/batch-auth/authority.json').read_bytes(), before)

    def test_only_an_exactly_closed_v3_record_is_lifted(self) -> None:
        raw = self.as_v3()
        self.assertIsNotNone(batches.legacy_closed(raw))
        attempt = dict(raw['clips']['A']['projects'][0])
        controls = {'active': {**raw, 'status': 'active', 'closedAtElapsed': None},
                    'production block': {**raw, 'production': {'tasks': {}}}, 'v4': {**raw, 'schemaVersion': 4},
                    'v5': {**raw, 'schemaVersion': 5},
                    'raised limit': {**raw, 'limits': {**raw['limits'], 'author': 9}}, 'extra key': {**raw, 'x': 1}}
        for name, value in controls.items():
            self.assertIsNone(batches.legacy_closed(value), name)
        running = json.loads(json.dumps(raw))
        running['clips']['A']['attempts'].append({'status': 'running', 'project': attempt['path']})
        self.assertIsNone(batches.legacy_closed(running))

    def test_an_unliftable_foreign_record_still_refuses_resolution(self) -> None:
        self.as_v3(lambda record: record.update(status='active', closedAtElapsed=None))
        with self.assertRaisesRegex(BudgetAuthorityError, 'another engine version'):
            registry.resolve_binding(self.root, make_project(self.work, 'free', source=b'other'))
