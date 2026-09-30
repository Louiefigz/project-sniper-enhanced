"""Lifecycle regressions: versions, hand-off windows, unsynced commits, staging names, trims, audio stage,
draining, and the release of batches holding production tasks."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _budget_fixture import b3_stand_in, handoff_confirmation, host_turn, make_project, task_spec, test_mp4
from _dispatch_fixture import added_approval, start_args
from test_native_budget_registry import RegistryCase, ns
import native_batch
from studio.production import api as production_api
from studio.production.callbacks import TaskResult
from studio.production.claims import ClaimRef
from studio import native_budget_batches as batches
from studio import native_budget_binding as binding
from studio import native_budget_owner as owner_budget
from studio import native_budget_registry as registry
from studio import native_budget_store as store
from studio.native_budget_store import BudgetAuthorityError


class StagingNameTests(RegistryCase):
    """Only an untouched interrupted start may hide under a staging name."""

    def test_a_live_batch_renamed_to_a_staging_name_is_named(self) -> None:
        os.rename(self.root / 'batches/batch-auth', self.root / 'batches/.creating-batch-auth-0123456789ab')
        with self.assertRaisesRegex(BudgetAuthorityError, 'creating-batch-auth'):
            registry.resolve_binding(self.root, self.unrelated())

    def test_an_untouched_interrupted_start_is_ignored(self) -> None:
        self.close_batch()
        staged = self.root / 'batches/.creating-batch-next-0123456789ab'
        self.start('batch-next', ('A',))
        os.rename(self.root / 'batches/batch-next', staged)   # as if the rename never happened
        self.assertEqual(batches.list_batches(self.root), ['batch-auth'])


class OlderEngineTests(RegistryCase):
    """A batch of another engine version is released once closed or past its deadline."""

    def older(self, change: object = None) -> None:
        path = self.root / 'batches/batch-auth/authority.json'
        record = json.loads(path.read_text())
        record['schemaVersion'] = 1
        for clip in record['clips'].values():   # P0 adapt: a v1 record predates capacityClock
            clip.pop('capacityClock', None)
        if change:
            change(record)
        path.write_text(json.dumps(record))

    def test_an_expired_active_batch_of_an_older_engine_can_be_archived(self) -> None:
        self.older()
        with self.assertRaisesRegex(BudgetAuthorityError, 'another engine version'):
            batches.archive_batch(self.root, 'batch-auth', 'migration')      # its deadline has not passed
        self.older(lambda record: record.update(startEpoch=time.time() - 2401))
        batches.archive_batch(self.root, 'batch-auth', 'migration')
        self.assertIsNone(registry.resolve_binding(self.root, self.unrelated()))

    def test_archived_older_history_counts_as_present(self) -> None:
        attempt = self.work / 'old-attempt'
        attempt.mkdir()
        budget = self.reserve(self.project, name='old-attempt')
        self.close(budget)
        (attempt / 'export-request.json').write_text(json.dumps({'project': str(self.project),
                                                                 'productionBudget': budget}))
        self.close_batch()
        self.older()
        batches.archive_batch(self.root, 'batch-auth', 'migration')
        request = {'project': str(self.project), 'output': str(self.work / 'next'), 'runtime': str(self.work / 'rt')}
        with mock.patch('studio.native_export_history.candidate_attempts', return_value=[attempt]):
            binding.require_budget_continuity(request)


class SelectionTests(RegistryCase):
    """Trims and extensions of a Short stay with its clip."""

    def test_a_trim_to_under_half_stays_with_its_clip(self) -> None:
        native_batch.cmd_add_clip(ns(batch='batch-auth', clip='A-trim', reason='tightened',
                                     approval=added_approval(self.work, 'A-trim')))
        trim = make_project(self.work, 'native-trim', cuts=((12.0, 40.0),))       # 28 s of A's 60 s
        with self.assertRaisesRegex(registry.BudgetRefused, 're-cuts clip A'):
            binding.bind_project(self.root, 'batch-auth', 'A-trim', trim)


class AddedClipTests(RegistryCase):
    """In-process probe: an added clip binds its approval before minute 25, and none is added after it."""

    def test_add_clip_at_the_minute_25_boundary(self) -> None:
        self.clock.advance(1499)
        added = native_batch.cmd_add_clip(ns(batch='batch-auth', clip='E', reason='probe',
                                             approval=added_approval(self.work, 'E')))
        self.assertEqual((added['status'], added['approval']['title']), ('clip-added', 'TEST title E'))
        self.clock.advance(1)
        for file in (added_approval(self.work, 'F'), None):
            with self.subTest(approval=file is not None), self.assertRaises(registry.BudgetRefused):
                native_batch.cmd_add_clip(ns(batch='batch-auth', clip='F', reason='probe', approval=file))
        self.assertNotIn('F', self.record()['clips'])


class HandoffBundleTests(RegistryCase):
    """A multi-clip hand-off bundle runs while any served clip admits it."""

    def test_one_undelivered_clip_does_not_block_the_bundle(self) -> None:
        other = make_project(self.work, 'clip-b', cuts=((300.0, 340.0),))
        binding.bind_project(self.root, 'batch-auth', 'B', other)
        budget = self.reserve(self.project)
        binding.record_request_outcome({'productionBudget': budget}, {
            'status': 'native-short-checked-for-review', 'output': '/x/review.mp4', 'sha256': 'a' * 64})
        self.clock.advance(2300)
        bundle = SimpleNamespace(hard_deadline=None, project=self.work, label='native-review', deadline=600,
                                 settings=SimpleNamespace(serves=(self.project, other)))
        owner_budget.apply_budget_to_owner(bundle)
        self.assertIsNotNone(bundle.hard_deadline)


class AudioStageCategoryTests(unittest.TestCase):
    """A host condition in the audio stage stays transient; a failed check does not."""

    def test_categories(self) -> None:
        from studio.native_audio_stage import AudioStageFailure
        self.assertEqual(AudioStageFailure({'failureCategory': 'capacity-timeout'}).category, 'capacity-timeout')
        self.assertEqual(AudioStageFailure({'failureCategory': 'renderer-failure'}).category, 'audio-stage-failure')
        self.assertEqual(AudioStageFailure({}).category, 'audio-stage-failure')


class RoundThreeTests(RegistryCase):
    """Versions, hand-off window, unsynced commits, hidden batches, disk category."""

    def write_raw(self, change: object) -> None:
        path = self.root / 'batches/batch-auth/authority.json'
        record = json.loads(path.read_text())
        change(record)
        path.write_text(json.dumps(record))

    def test_another_engine_version_is_named_and_a_closed_one_archives(self) -> None:
        self.write_raw(lambda record: record.update(schemaVersion=1))
        with self.assertRaisesRegex(BudgetAuthorityError, 'another engine version'):
            self.reserve(self.project)
        with self.assertRaisesRegex(BudgetAuthorityError, 'archive it once it is closed'):
            batches.archive_batch(self.root, 'batch-auth', 'operator migrated')  # still active there
        self.write_raw(lambda record: record.update(status='closed', closedAtElapsed=5.0))
        batches.archive_batch(self.root, 'batch-auth', 'operator migrated')
        self.assertIsNone(registry.resolve_binding(self.root, self.unrelated()))

    def test_policy_changes_need_a_new_schema_version(self) -> None:
        from studio import native_budget_schema as schema
        # Version 5 (production tasks, run-scoped AI reservations, draining) digests AI_POLICY too; the
        # never-deployed pre-release schema 4 had the Short policy and a different record shape. Version 5 also
        # carries the output formats (the Long policy); its Short part is version 4's, unchanged.
        pinned = {2: 'f5150bcd966084ad685c27bc47fb3d4198fde64f4b131a76b793f7f55af3fb68',
                  3: '6550905eb8e0bf5685090b42150133d01223515f94cd86e894346ff56e572f65',
                  4: '3f94e36e174e2a2af8cc2e386fe60ddf00c67f99f70553e898600a57229eb171',
                  5: '0de2cc57a5bc0e0f5bbb65fa04e8a308825f4b29ca4f250e5a163da51ce8d140',
                  # P0 adapt: schema 7 changed the record shape, not the policy; so does M-044's schema 8 (X7).
                  **dict.fromkeys((7, 8), '0de2cc57a5bc0e0f5bbb65fa04e8a308825f4b29ca4f250e5a163da51ce8d140')}
        self.assertIn(schema.SCHEMA_VERSION, pinned, 'record the new version\'s policy digest here')
        self.assertEqual(schema.policy_digest(), pinned[schema.SCHEMA_VERSION],
                         'limits, deadlines or rates changed: bump SCHEMA_VERSION and pin its digest')
        short = json.dumps([schema.LIMITS, schema.DEADLINES, schema.PROVISIONAL_RATES, schema.AI_POLICY],
                           sort_keys=True, separators=(',', ':'))
        self.assertEqual(hashlib.sha256(short.encode()).hexdigest(), pinned[4], 'the Short policy must not change')

    def test_delivered_clip_keeps_its_hand_off_window(self) -> None:
        budget = self.reserve(self.project)
        binding.record_request_outcome({'productionBudget': budget}, {
            'status': 'native-short-checked-for-review', 'output': '/x/review.mp4', 'sha256': 'a' * 64})
        self.clock.advance(2300)                                   # 38:20, inside the hand-off reserve
        self.assertGreater(self.utility('review-bundle')['allocation']['grantedSeconds'], 90)
        with self.assertRaisesRegex(registry.BudgetRefused, 'cleanup reserve'):
            self.utility('review-bundle', clip='B')

    def test_replaced_but_unsynced_record_stands(self) -> None:
        real = store.write_pending_replace

        def replace_then_fail(dir_fd: int, names: tuple, data: bytes) -> None:
            real(dir_fd, names, data)
            raise OSError('directory fsync failed')
        with mock.patch.object(store, 'write_pending_replace', side_effect=replace_then_fail):
            budget = self.reserve(self.project)
        self.assertEqual(self.record()['clips']['A']['attempts'][-1]['id'], budget['attemptId'])
        trail = (self.root / 'batches/batch-auth/events.jsonl').read_text().splitlines()
        self.assertEqual(json.loads(trail[-1])['event'], 'commit-unsynced')

    def test_a_renamed_hidden_batch_is_named(self) -> None:
        self.close_batch()
        shutil.copytree(self.root / 'batches/batch-auth', self.root / 'batches/.batch-hidden')
        with self.assertRaisesRegex(BudgetAuthorityError, '.batch-hidden'):
            registry.resolve_binding(self.root, self.unrelated())

    def test_disk_refusal_is_its_own_retryable_category(self) -> None:
        from studio.native_budget_launch import TRANSIENT
        from studio.native_run_lifecycle import failure_category
        result = {'status': 'failed', 'cleanup': {'verified': True},
                  'abortReason': 'RuntimeError: Disk admission refused: free disk is below the reserve'}
        self.assertEqual(failure_category(result), 'disk-space')
        self.assertIn('disk-space', TRANSIENT)



class DrainingTests(RegistryCase):
    """Closing with unsettled work drains; a draining batch is neither archivable nor replaceable."""

    def setUp(self) -> None:
        super().setUp()
        from _budget_fixture import DIRECTOR, FINGERPRINT
        from studio.production.claims import Enrollment
        self.director = production_api.enroll_director(self.root, 'batch-auth',
                                                       Enrollment('director', DIRECTOR, 'v1', FINGERPRINT))
        production_api.enqueue_tasks(self.root, 'batch-auth', (task_spec('critic', 'review', clip_id='A',
                                                                         parent='director'),))

    def director_done(self) -> None:
        production_api.complete_task(self.root, 'batch-auth', ClaimRef('director', 1, self.director['token']),
                                     TaskResult(()))

    def test_a_running_critic_drains_the_batch_until_it_settles(self) -> None:
        claimed = production_api.claim_task(self.root, 'batch-auth', 'critic', host_turn('critic'))
        ref = ClaimRef('critic', claimed['epoch'], claimed['token'])
        production_api.attach_task(self.root, 'batch-auth', ref, host_turn('critic'))
        self.director_done()
        self.clock.advance(2400)
        closing = native_batch.cmd_close(ns(batch='batch-auth'))
        self.assertEqual((closing['status'], closing['unsettledTasks']), ('draining', ['critic']))
        with self.assertRaisesRegex(registry.BudgetRefused, 'still draining'):
            self.start('batch-next', ('A',))
        with self.assertRaisesRegex(registry.BudgetRefused, 'Only a closed batch'):
            native_batch.cmd_archive(ns(batch='batch-auth', reason='operator released it'))
        with self.assertRaisesRegex(registry.BudgetRefused, 'is draining'):
            self.reserve(self.unrelated())
        with self.assertRaisesRegex(registry.BudgetRefused, 'is draining'):
            self.reserve(self.project)
        with self.assertRaisesRegex(registry.BudgetRefused, 'draining'):
            production_api.enqueue_tasks(self.root, 'batch-auth', (task_spec('late'),))
        production_api.confirm_cancelled(self.root, 'batch-auth', ref)       # Codex: tools may survive
        self.assertEqual(native_batch.cmd_close(ns(batch='batch-auth'))['status'], 'draining')
        production_api.settle_resource(self.root, 'batch-auth', 'critic', 'operator saw no tool process left')
        self.assertEqual(native_batch.cmd_close(ns(batch='batch-auth'))['status'], 'closed')
        native_batch.cmd_archive(ns(batch='batch-auth', reason='operator released it'))
        self.start('batch-next', ('A',))

    def test_an_unresolved_slot_is_settled_only_while_draining_and_with_evidence(self) -> None:
        from _budget_fixture import DISPATCHER, table
        from studio import native_budget_launch as launch
        production_api.claim_task(self.root, 'batch-auth', 'critic', DISPATCHER)
        with mock.patch.object(launch, '_process_table', return_value=table()):
            production_api.reconcile(self.root, 'batch-auth')              # dispatcher died: uncertain launch
        with self.assertRaisesRegex(registry.BudgetRefused, 'only while the run drains'):
            production_api.settle_resource(self.root, 'batch-auth', 'critic', 'checked the host')
        self.director_done()
        self.clock.advance(2400)
        self.assertEqual(native_batch.cmd_close(ns(batch='batch-auth'))['status'], 'draining')
        production_api.settle_resource(self.root, 'batch-auth', 'critic', 'operator confirmed no host turn runs')
        record = self.record()
        self.assertEqual((record['production']['tasks']['critic']['state'], record['production']['ai']['charged']),
                         ('abandoned', 2))                                    # still charged, never retried
        self.assertEqual(native_batch.cmd_close(ns(batch='batch-auth'))['status'], 'closed')

    def test_an_explicit_drain_waits_for_the_close_conditions_and_freezes_everything(self) -> None:
        with self.assertRaisesRegex(registry.BudgetRefused, 'not handed off'):
            production_api.drain(self.root, 'batch-auth', 'operator stopped the run')
        self.clock.advance(2400)
        drained = production_api.drain(self.root, 'batch-auth', 'operator stopped the run')
        self.assertEqual((drained['status'], drained['frozen']), ('draining', ['critic', 'director']))
        self.assertEqual(drained['unsettled'], ['director'])
        self.assertEqual(self.record()['production']['drain']['reason'], 'operator stopped the run')

    def test_a_clean_close_never_drains(self) -> None:
        self.director_done()
        self.clock.advance(2400)
        closed = native_batch.cmd_close(ns(batch='batch-auth'))
        self.assertEqual(closed['status'], 'closed')
        record = self.record()
        self.assertIsNone(record['production']['drain'])
        self.assertEqual(record['production']['tasks']['critic']['state'], 'cancelled')

    def test_a_hand_off_freezes_only_that_clips_work(self) -> None:
        production_api.enqueue_tasks(self.root, 'batch-auth', (task_spec('author-b', 'author', clip_id='B',
                                                                         parent='director'),))
        budget = self.reserve(self.project)
        mp4 = test_mp4(self.work / 'attempt')
        binding.record_request_outcome({'productionBudget': budget}, {
            'status': 'native-short-review-draft', 'output': mp4[0], 'sha256': mp4[1]})
        confirmation = handoff_confirmation(self.work / 'handoff', mp4, at=self.clock.wall)
        with b3_stand_in():
            handed = native_batch.cmd_handoff(ns(batch='batch-auth', clip='A', confirmation=confirmation))
        self.assertEqual(handed['frozenTasks'], ['critic'])
        tasks = self.record()['production']['tasks']
        self.assertEqual((tasks['critic']['state'], tasks['author-b']['state']), ('cancelled', 'ready'))

    def test_a_renamed_batch_with_tasks_is_not_an_interrupted_start(self) -> None:
        self.director_done()
        self.clock.advance(2400)
        native_batch.cmd_close(ns(batch='batch-auth'))
        os.rename(self.root / 'batches/batch-auth', self.root / 'batches/.creating-batch-auth-0123456789ab')
        with self.assertRaisesRegex(BudgetAuthorityError, 'creating-batch-auth'):
            batches.list_batches(self.root)


class ForeignTaskReleaseTests(RegistryCase):
    """Another engine version's batch with unsettled tasks is never released by its deadline alone."""

    def foreign(self, status: str, task: dict, **values: object) -> None:
        path = self.root / 'batches/batch-auth/authority.json'
        record = json.loads(path.read_text())
        record.update(schemaVersion=99, status=status, startEpoch=time.time() - 3000, **values)
        record['production']['tasks'] = {'critic': task}
        for clip in record['clips'].values():   # P0 adapt: no foreign capacity policy (native_budget_batches:212)
            clip.pop('capacityClock', None)
        path.write_text(json.dumps(record))

    def test_unsettled_foreign_tasks_block_the_archive(self) -> None:
        for status, task in (('active', {'state': 'running', 'unresolved': False}),
                             ('closed', {'state': 'abandoned', 'unresolved': True}),
                             ('draining', {'state': 'cancelled', 'unresolved': False}),
                             ('active', 'unreadable')):
            self.foreign(status, task, closedAtElapsed=5.0 if status == 'closed' else None)
            self.assertFalse(batches.foreign_released(json.loads(
                (self.root / 'batches/batch-auth/authority.json').read_text())))
            with self.assertRaises((BudgetAuthorityError, registry.BudgetRefused)):
                batches.archive_batch(self.root, 'batch-auth', 'migration')

    def test_settled_foreign_tasks_release_after_the_deadline(self) -> None:
        self.foreign('active', {'state': 'completed', 'unresolved': False})
        batches.archive_batch(self.root, 'batch-auth', 'migration')
        self.assertTrue((self.root / 'archive/batch-auth/authority.json').is_file())



class AuthorizationTests(RegistryCase):
    """The clock starts at authorization; setup (capacity, hashing, engine) runs inside it and never re-anchors."""

    def start_late(self, digests: object, clips: str = 'A,B') -> dict:
        from pathlib import Path
        from studio import native_budget_forecast as forecast
        from studio.production import commands
        with mock.patch.object(commands, 'source_digests', side_effect=digests), \
                mock.patch.object(forecast, 'heavy_lane_capacity', return_value=1):
            return native_batch.cmd_start(start_args(self.work, 'batch-late', clips,
                                                     source=[Path('/TEST/recording.mov')]))

    def late_record(self) -> dict:
        return store.read_batch(self.root, 'batch-late')

    def test_a_slow_source_hash_is_charged_and_never_moves_the_start(self) -> None:
        from _budget_fixture import source_sha
        self.close_batch()
        handover = self.clock.wall

        def slow_hash(_sources: object) -> list[str]:
            self.clock.advance(700)                     # the verifier's 700-second source check
            return [source_sha()]
        started = self.start_late(slow_hash)
        record = self.late_record()
        self.assertEqual((started['authorizedAtEpoch'], record['startEpoch']), (handover, handover))
        self.assertAlmostEqual(started['setupElapsed'], 700.0)
        self.assertAlmostEqual(record['clock']['elapsed'], 700.0)
        self.assertEqual(record['claims'], [source_sha()])

    def test_a_failed_setup_keeps_the_authorization_and_a_rerun_resumes_it(self) -> None:
        from _budget_fixture import source_sha
        self.close_batch()
        handover = self.clock.wall
        with self.assertRaises(FileNotFoundError):
            self.start_late(FileNotFoundError('TEST recording missing'))
        record = self.late_record()
        self.assertEqual((record['startEpoch'], record['production']['authorization']['setup']), (handover, 'pending'))
        with self.assertRaisesRegex(registry.BudgetRefused, 'setup .* has not completed'):
            binding.bind_project(self.root, 'batch-late', 'A', self.project)
        self.clock.advance(120)
        resumed = self.start_late(lambda _sources: [source_sha()])
        self.assertEqual((resumed['resumed'], resumed['authorizedAtEpoch']), (True, handover))
        self.assertEqual(self.late_record()['startEpoch'], handover)
        self.assertGreaterEqual(resumed['setupElapsed'], 120.0)
        binding.bind_project(self.root, 'batch-late', 'A', self.project)
        with self.assertRaisesRegex(registry.BudgetRefused, 'still active'):
            self.start_late(lambda _sources: [], clips='A')      # a different authorization never restarts it



class VisibleHandoffTests(RegistryCase):
    """handoff needs unit B3's verifier to accept a confirmation of one of the clip's deliveries, then its own
    checks: the MP4 re-hashes, observed playback and an attestation, the batch-clock window, once per clip."""

    def setUp(self) -> None:
        super().setUp()
        budget = self.reserve(self.project, route='draft')
        self.mp4 = test_mp4(self.work / 'attempt', 'review-draft.mp4')
        binding.record_request_outcome({'productionBudget': budget}, {
            'status': 'native-short-review-draft', 'output': self.mp4[0], 'sha256': self.mp4[1]})
        self.clock.advance(30)

    def hand_off(self, confirmation: object) -> dict:
        return native_batch.cmd_handoff(ns(batch='batch-auth', clip='A', confirmation=confirmation))

    def confirmation(self, name: str, change: object = None, at: float | None = None) -> Path:
        """A fixture confirmation, optionally edited and then accepted by the stand-in (B3 said yes)."""
        from _budget_fixture import B3_CONFIRMATIONS
        path = handoff_confirmation(self.work / name, self.mp4, at=self.clock.wall if at is None else at)
        if change:
            value = json.loads(path.read_text())
            change(value)
            path.write_text(json.dumps(value))
            B3_CONFIRMATIONS.add(hashlib.sha256(path.read_bytes()).hexdigest())
        return path

    def test_without_b3s_verifier_no_confirmation_is_accepted(self) -> None:
        # Probe p2: hand-written B3-shaped JSON (no native_handoff.py, Studio or browser) is refused by name.
        with self.assertRaisesRegex(registry.BudgetRefused, "B3's verifier refused the confirmation"):  # P0 adapt: B3 in src
            self.hand_off(self.confirmation('forged'))
        with mock.patch('studio.production.handoff.b3_verifier', return_value=mock.Mock(
                side_effect=ValueError('TEST B3: no page-reported playback'))):
            with self.assertRaisesRegex(registry.BudgetRefused, "B3's verifier refused the confirmation"):
                self.hand_off(self.confirmation('b3-refuses'))
        self.assertEqual(self.record()['clips']['A']['state'], 'active')

    def test_a_confirmed_delivery_is_handed_off_with_the_confirmations_time(self) -> None:
        with b3_stand_in():
            handed = self.hand_off(self.confirmation('ok'))
        visible = datetime.fromtimestamp(self.clock.wall, timezone.utc).isoformat(timespec='milliseconds')
        self.assertEqual((handed['handoff']['visibleHandoffAt'], handed['delivery']['sha256']), (visible, self.mp4[1]))
        last = json.loads((self.root / 'batches/batch-auth/events.jsonl').read_bytes().splitlines()[-1])
        self.assertEqual((last['event'], last['handoff']['visibleHandoffAt']), ('clip-handed-off', visible))

    def test_a_clip_is_handed_off_once(self) -> None:
        # Probe p2b: a second confirmation of the same clip is refused; one terminal event only.
        with b3_stand_in():
            self.hand_off(self.confirmation('first'))
            self.clock.advance(5)
            with self.assertRaisesRegex(registry.BudgetRefused, 'already handed off'):
                self.hand_off(self.confirmation('second'))
        trail = (self.root / 'batches/batch-auth/events.jsonl').read_bytes().splitlines()
        events = [json.loads(line) for line in trail]
        self.assertEqual(sum(1 for event in events if event.get('event') == 'clip-handed-off'), 1)

    def test_evidence_that_is_not_a_visible_hand_off_of_this_delivery_is_refused(self) -> None:
        other = test_mp4(self.work / 'other', 'other.mp4')
        start = self.record()['startEpoch']
        cases = {
            'views-ready alone': (handoff_confirmation(self.work / 'v', self.mp4, visible=False, at=self.clock.wall),
                                  'not a visible hand-off'),
            'another MP4': (handoff_confirmation(self.work / 'm', other, at=self.clock.wall),
                            'not a recorded delivery'),
            'incomplete confirmation': (self.confirmation('i', lambda v: v.update(status='handoff-incomplete')),
                                        'only visible-handoff'),
            'another view': (self.confirmation('t', lambda v: v.update(viewToken='TEST-other')), 'another view'),
            'no observed playback': (self.confirmation('p', lambda v: v['observed'].update(reviewPagePlayback=[])),
                                     'no observed review-page playback'),
            'no attestation': (self.confirmation('a', lambda v: v.pop('attestation')), 'no attestation'),
            'before the delivery (probe p2: years before the batch)': (
                self.confirmation('early', at=start - 3 * 365 * 86400), 'precedes the delivery'),
            'in the future': (self.confirmation('late', at=self.clock.wall + 3600), 'lies in the future')}
        changed = self.confirmation('c')
        record = self.work / 'c' / f'handoff-{self.mp4[1][:8]}.json'
        record.write_text(record.read_text().replace('TEST-owner', 'TEST-other'))
        cases['record changed after confirming'] = (changed, 'changed after its confirmation')
        with b3_stand_in():
            for name, (path, reason) in cases.items():
                with self.subTest(name), self.assertRaisesRegex(registry.BudgetRefused, reason):
                    self.hand_off(path)
            Path(self.mp4[0]).write_bytes(b'TEST bytes replaced after the hand-off was confirmed')
            with self.assertRaisesRegex(registry.BudgetRefused, 'no longer has the bytes'):
                self.hand_off(self.confirmation('rehash'))
        self.assertEqual(self.record()['clips']['A']['state'], 'active')

    def test_supporting_work_for_a_handed_off_clip_is_refused(self) -> None:
        with b3_stand_in():
            self.hand_off(self.confirmation('ok'))
        owner = SimpleNamespace(hard_deadline=None, project=self.project, label='native-review', deadline=600,
                                settings=SimpleNamespace(serves=None))
        with self.assertRaisesRegex(registry.BudgetRefused, 'handed off'):
            owner_budget.apply_budget_to_owner(owner)
        with self.assertRaisesRegex(registry.BudgetRefused, 'handed off'):
            self.reserve(self.project, route='final', name='after-handoff', options={'n': 9})


if __name__ == '__main__':
    unittest.main()
