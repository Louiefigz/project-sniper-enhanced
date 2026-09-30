"""Durable authority and exporter boundary: budgets survive folders, processes, resets and failures."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from _budget_fixture import (
    CHANGE_REASON, ENGINE, FakeClock, approval, fake_clock, make_project, private_root, source_sha,
)
from studio.production.approvals import ApprovalChange  # P0 adapt: src takes one typed change (WAVES:186)
from studio import native_budget_binding as binding
from studio import native_budget_exporter as exporter
from studio import native_budget_registry as registry
from studio.native_budget_clock import start_anchor
from studio.native_budget_policy import BatchSpec, new_batch_record
from studio import native_budget_batches as batches
from studio.native_budget_batches import create_batch
from studio.native_budget_store import BudgetAuthorityError, locked_batch

HERE = Path(__file__).resolve().parents[1]


class AuthorityCase(unittest.TestCase):
    """Real private files and kernel locks under a temporary per-user root."""

    def setUp(self) -> None:
        self.root = private_root(self)
        self.work = self.root.parent / 'work'
        self.work.mkdir()
        from studio import native_budget_store as store
        for target in (binding, exporter, store):  # the store: every call site that reads the root at call time
            patch = mock.patch.object(target, 'default_root', return_value=self.root)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(binding, 'engine_identity', return_value=dict(ENGINE))
        patch.start()
        self.addCleanup(patch.stop)
        self.enterContext(mock.patch('studio.native_budget_forecast.heavy_lane_capacity', return_value=1))  # X144
        self.clock = FakeClock()
        context = fake_clock(self.clock)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.start('batch-auth', ('A', 'B'))
        self.project = make_project(self.work, 'native-v1')
        binding.bind_project(self.root, 'batch-auth', 'A', self.project)

    def start(self, batch_id: str, clips: tuple, claims: tuple | None = None) -> None:
        spec = BatchSpec(batch_id, clips, claims or (source_sha(),), 1,
                         approvals={clip: approval(clip) for clip in clips})
        record = new_batch_record(spec, start_anchor())
        record['engine'] = dict(ENGINE)
        create_batch(self.root, record)

    def utility(self, kind: str, clip: str = 'A', fmt: str = 'short') -> dict:
        return binding.reserve_utility(self.root, {'batchId': 'batch-auth', 'clipId': clip, 'format': fmt}, kind)

    def reserve(self, project: Path, route: str = 'final', name: str = 'attempt', options: dict | None = None) -> dict:
        return binding.reserve_launch(project, self.work / name, route, options or {})

    def record(self, batch_id: str = 'batch-auth') -> dict:
        with locked_batch(self.root, batch_id) as session:
            return session.read()

    def counters(self, clip: str = 'A') -> dict:
        return self.record()['clips'][clip]['counters']

    def close(self, budget: dict, status: str = 'failed', category: str = 'renderer-failure') -> None:
        binding.record_request_outcome({'productionBudget': budget},
                                       {'status': status, 'failureCategory': category, 'error': 'x'})

    def mutate(self, batch_id: str, change: object) -> None:
        with locked_batch(self.root, batch_id) as session:
            record = session.read()
            change(record)
            session.commit(record, {'event': 'test-mutation'})


class AuthorityBoundaryTests(AuthorityCase):
    """Reservation, rebinding, resets and fail-closed authority."""

    def test_reservation_is_durable_before_any_preparation(self) -> None:
        budget = self.reserve(self.project)
        self.assertEqual(self.counters()['exportAttempt'], 1)
        self.assertEqual(budget['clipId'], 'A')
        attempt = self.record()['clips']['A']['attempts'][-1]
        self.assertEqual((attempt['outputSeconds'], attempt['status']), (60.0, 'running'))

    def test_any_unbound_folder_is_refused_while_a_batch_is_active(self) -> None:
        revision = make_project(self.work, 'native-v2')
        altered = make_project(self.work, 'altered', source=b'source-video+1')
        unrelated = make_project(self.work, 'other', source=b'another-recording')
        for project in (revision, altered, unrelated):
            with self.assertRaisesRegex(registry.BudgetRefused, 'is active: bind this project'):
                self.reserve(project)

    def test_a_bound_revision_continues_the_same_counters(self) -> None:
        self.close(self.reserve(self.project))
        revision = make_project(self.work, 'native-v2')
        binding.bind_project(self.root, 'batch-auth', 'A', revision)
        self.close(self.reserve(revision, name='attempt-2', options={'n': 2}))
        with self.assertRaisesRegex(registry.BudgetRefused, 'exportAttempt limit reached'):
            self.reserve(revision, name='attempt-3', options={'n': 3})

    def test_case_variant_or_identical_content_cannot_move_to_another_clip(self) -> None:
        variant = Path(str(self.project).replace('native-v1', 'NATIVE-V1'))
        if variant.exists() and os.path.samefile(variant, self.project):
            with self.assertRaisesRegex(registry.BudgetRefused, 'already bound|already belongs'):
                binding.bind_project(self.root, 'batch-auth', 'B', variant)
        copy = self.work / 'copy-of-v1'
        copy.mkdir()
        for name in ('SHORT-PROJECT.json', 'PROJECT-MANIFEST.json'):
            (copy / name).write_bytes((self.project / name).read_bytes())
        with self.assertRaisesRegex(registry.BudgetRefused, 'identical content'):
            binding.bind_project(self.root, 'batch-auth', 'B', copy)

    def test_close_is_not_a_reset_and_keeps_the_projects(self) -> None:
        self.mutate('batch-auth', lambda record: record.update(status='closed', closedAtElapsed=5.0))
        with self.assertRaisesRegex(registry.BudgetRefused, 'closed batch batch-auth'):
            self.reserve(self.project)
        revision = make_project(self.work, 'native-v2')
        with self.assertRaisesRegex(registry.BudgetRefused, 'closed batch'):
            exporter.refuse_if_budgeted(revision)

    def test_a_new_batch_is_the_explicit_way_to_new_work(self) -> None:
        self.mutate('batch-auth', lambda record: record.update(status='closed', closedAtElapsed=5.0))
        self.start('batch-next', ('A',))
        binding.bind_project(self.root, 'batch-next', 'A', self.project)
        self.assertEqual(self.reserve(self.project)['batchId'], 'batch-next')

    def test_only_one_batch_is_active_at_a_time(self) -> None:
        with self.assertRaisesRegex(registry.BudgetRefused, 'batch-auth is still active'):
            self.start('batch-two', ('X',))
        self.assertFalse((self.root / 'batches/batch-two').exists())

    def test_a_new_process_sees_the_same_counters(self) -> None:
        self.close(self.reserve(self.project))
        script = ('import sys, json; from pathlib import Path; sys.path[:0] = [sys.argv[1]]\n'
                  'from studio.native_budget_store import locked_batch\n'
                  'with locked_batch(Path(sys.argv[2]), "batch-auth") as session:\n'
                  '    print(json.dumps(session.read()["clips"]["A"]["counters"]))\n')
        result = subprocess.run([sys.executable, '-c', script, str(HERE), str(self.root)],
                                capture_output=True, text=True, timeout=30, check=True)
        self.assertEqual(json.loads(result.stdout)['exportAttempt'], 1)

    def test_parseable_but_corrupt_authority_refuses_new_work(self) -> None:
        file = self.root / 'batches/batch-auth/authority.json'
        record = json.loads(file.read_text())
        record['clips']['A']['counters']['exportAttempt'] = -3
        file.write_text(json.dumps(record))
        with self.assertRaises(BudgetAuthorityError):
            self.reserve(self.project)

    def test_unreadable_authority_refuses_new_work(self) -> None:
        file = self.root / 'batches/batch-auth/authority.json'
        os.chmod(file, 0o000)
        self.addCleanup(os.chmod, file, 0o600)
        with self.assertRaises(BudgetAuthorityError):
            self.reserve(self.project)

    def test_unwritable_authority_refuses_and_charges_nothing(self) -> None:
        directory = self.root / 'batches/batch-auth'
        os.chmod(directory, 0o500)
        try:
            with self.assertRaises(BudgetAuthorityError):
                self.reserve(self.project)
        finally:
            os.chmod(directory, 0o700)
        self.assertEqual(self.counters()['exportAttempt'], 0)

    def test_engine_change_during_batch_is_refused(self) -> None:
        with mock.patch.object(binding, 'engine_identity', return_value={'identity': 'engine-2'}):
            with self.assertRaisesRegex(registry.BudgetRefused, 'engine changed'):
                self.reserve(self.project)
        self.assertEqual(self.counters()['exportAttempt'], 0)

    def test_failure_before_request_publication_is_charged_and_closed(self) -> None:
        exporter.close_unpublished_launch(self.reserve(self.project), RuntimeError('check-export failed'))
        attempt = self.record()['clips']['A']['attempts'][-1]
        self.assertEqual((attempt['status'], attempt['failure']['phase']), ('failed', 'preparation'))
        self.assertEqual(self.counters()['exportAttempt'], 1)

    def test_nested_charges_from_a_worker_request(self) -> None:
        request = {'productionBudget': self.reserve(self.project)}
        binding.charge_request(request, 'pictureGeneration')
        binding.charge_request(request, 'pictureGeneration')
        with self.assertRaisesRegex(registry.BudgetRefused, 'full-picture generation limit'):
            binding.charge_request(request, 'pictureGeneration')

    def test_deadline_passed_refuses_launch_and_utilities(self) -> None:
        self.clock.advance(2400)
        with self.assertRaisesRegex(registry.BudgetRefused, '40-minute'):
            self.reserve(self.project)
        with self.assertRaisesRegex(registry.BudgetRefused, '40-minute'):
            self.utility('audio-stage')

    def test_utility_is_refused_inside_the_cleanup_reserve(self) -> None:
        self.clock.advance(2280 - 30)
        with self.assertRaisesRegex(registry.BudgetRefused, 'cleanup reserve'):
            self.utility('review-bundle')

    def test_utility_admission_uses_the_deadline_but_no_counter(self) -> None:
        grant = self.utility('audio-stage')
        self.assertIsNone(grant['attemptId'])
        self.assertGreater(grant['allocation']['grantedSeconds'], 2000)
        self.assertEqual(self.counters()['exportAttempt'], 0)

    def test_outcome_keeps_the_stage_timings_and_delivery(self) -> None:
        budget = self.reserve(self.project)
        binding.record_request_outcome({'productionBudget': budget}, {
            'status': 'native-short-checked-for-review', 'output': '/x/review.mp4', 'sha256': 'a' * 64,
            'stages': [{'phase': 'capture', 'status': 'ok', 'elapsedSeconds': 90.5, 'receipt': '/r'}]})
        clip = self.record()['clips']['A']
        self.assertEqual(clip['attempts'][-1]['stages'], [{'phase': 'capture', 'status': 'ok', 'elapsedSeconds': 90.5}])
        self.assertEqual(clip['deliveries'][-1]['kind'], 'final')

    def test_lost_authority_with_budgeted_history_refuses(self) -> None:
        attempt = self.work / 'old-attempt'
        attempt.mkdir()
        budget = self.reserve(self.project, name='old-attempt')
        (attempt / 'export-request.json').write_text(json.dumps({'project': str(self.project), 'productionBudget': budget}))
        os.rename(self.root / 'batches/batch-auth', self.root.parent / 'moved-away')
        request = {'project': str(self.project), 'output': str(self.work / 'next'), 'runtime': str(self.work / 'rt/x')}
        with mock.patch('studio.native_export_history.candidate_attempts', return_value=[attempt]):
            with self.assertRaisesRegex(registry.BudgetRefused, 'missing or unreadable'):
                binding.require_budget_continuity(request)


class ExporterBoundaryTests(AuthorityCase):
    """Route naming, canonical option identity, direct callers and reservation order."""

    def test_route_naming_from_exporter_arguments(self) -> None:
        cases = [({'preview_only': True}, 'preview'), ({}, 'preview'), ({'preview_reviews': Path('/r')}, 'final'),
                 ({'verify_from': Path('/v')}, 'verify'), ({'resume_from': Path('/r')}, 'resume'),
                 ({'review_draft': True}, 'draft'), ({'promote_draft': Path('/d')}, 'promote')]
        for values, route in cases:
            self.assertEqual(exporter.launch_route(argparse.Namespace(**values)), route)

    def test_respelled_option_paths_have_one_identity(self) -> None:
        reviews = self.work / 'reviews.json'
        reviews.write_text('{"x": 1}')
        (self.work / 'sub').mkdir()
        plain = exporter.launch_options(argparse.Namespace(preview_reviews=reviews))
        respelled = exporter.launch_options(argparse.Namespace(preview_reviews=self.work / 'sub/../reviews.json'))
        self.assertEqual(plain, respelled)
        reviews.write_text('{"x": 2}')
        self.assertNotEqual(plain, exporter.launch_options(argparse.Namespace(preview_reviews=reviews)))

    def test_direct_prepare_callers_cannot_run_budgeted_work(self) -> None:
        with self.assertRaisesRegex(registry.BudgetRefused, 'native_export.py'):
            exporter.refuse_if_budgeted(self.project)
        with self.assertRaisesRegex(registry.BudgetRefused, 'is active'):
            exporter.refuse_if_budgeted(make_project(self.work, 'native-direct'))

    def test_reserve_happens_after_validation_and_before_prepare(self) -> None:
        from studio import native_short_export as export
        order = []
        args = argparse.Namespace(project=Path('/tmp'), output=Path('/tmp/new-attempt'), render_only=False,
                                  unused_ram_advisory=False)
        with mock.patch.object(export, 'validate_options', side_effect=lambda *a: order.append('validate')), \
                mock.patch.object(export, 'reserve_for_args', side_effect=lambda a: order.append('reserve') or (True, {'b': 1})), \
                mock.patch.object(export, 'prepare', side_effect=RuntimeError('boom')), \
                mock.patch.object(export, 'close_unpublished_launch',
                                  side_effect=lambda budget, error: order.append(('close', str(error)))):
            with self.assertRaises(RuntimeError):
                export.execute(args)
        self.assertEqual(order, ['validate', 'reserve', ('close', 'boom')])

    def test_invalid_arguments_are_rejected_before_any_charge(self) -> None:
        from studio import native_short_export as export
        existing = self.work / 'existing-attempt'
        existing.mkdir()
        args = argparse.Namespace(project=self.project, output=existing, render_only=False, cache=None,
                                  audio_donor=None, picture_donor=None, cached_native_batches=False,
                                  acquire_source_cache=False, unused_ram_advisory=False)
        with self.assertRaises(ValueError):
            export.execute(args)
        self.assertEqual(self.counters()['exportAttempt'] + self.counters()['previewLaunch'], 0)

    def test_refused_reservation_launches_nothing(self) -> None:
        from studio import native_short_export as export
        args = argparse.Namespace(project=Path('/tmp'), output=Path('/tmp/new-attempt'))
        with mock.patch.object(export, 'validate_options'), \
                mock.patch.object(export, 'reserve_for_args', return_value=(False, None)), \
                mock.patch.object(export, 'prepare') as prepare:
            self.assertFalse(export.execute(args))
        prepare.assert_not_called()



class ApprovalAuthorityTests(AuthorityCase):
    """The approved title and script are bound at start; later changes never touch the clock."""

    def test_the_record_carries_the_approvals_and_the_production_block(self) -> None:
        record = self.record()
        self.assertEqual(record['schemaVersion'], 8)  # M-044 (X7): schema 8 lifts 5/6/7
        self.assertFalse(any('output' in clip for clip in record['clips'].values()))  # declared Shorts: batch clock
        authorization = record['production'].pop('authorization')
        self.assertEqual(record['production'], {'ai': {'slots': 4, 'reservations': 38, 'charged': 0},
                                                'drain': None, 'tasks': {}, 'governance': None})
        self.assertEqual((authorization['setup'], authorization['setupElapsed']), ('complete', 0.0))
        self.assertEqual([row['title'] for row in record['clips']['A']['approvals']], ['TEST title A'])

    def test_a_script_change_is_recorded_and_the_clock_is_not_reset(self) -> None:
        from studio.production import api
        self.clock.advance(300)
        retitled = approval('A', 'TEST retitled A')
        changed = api.record_script_change(self.root, 'batch-auth', 'A', ApprovalChange(retitled, CHANGE_REASON))
        record = self.record()
        self.assertEqual((changed['approval']['elapsed'], record['clock']['elapsed']), (300.0, 300.0))
        self.assertEqual((changed['changed'], changed['material']), (['title'], True))
        trail = (self.root / 'batches/batch-auth/events.jsonl').read_text().splitlines()
        self.assertEqual(json.loads(trail[-1])['event'], 'approval-changed')
        self.assertEqual([row['elapsed'] for row in record['clips']['A']['approvals']], [0.0, 300.0])
        self.assertEqual(record['startEpoch'], 1_800_000_000.0)

    def test_the_reader_is_the_single_source_for_a_clip_or_its_project(self) -> None:
        from studio.production import api
        read = api.read_approval(self.root, 'batch-auth', 'A')
        self.assertEqual((read['current']['title'], len(read['history']), read['status']), ('TEST title A', 1, 'active'))
        self.assertTrue(read['canonicalForm'].startswith('approval-v2'))
        self.assertEqual(api.approval_for_project(self.root, self.project)['clipId'], 'A')
        self.assertIsNone(api.approval_for_project(self.root, make_project(self.work, 'free', source=b'other')))
        self.mutate('batch-auth', lambda record: record.update(status='closed', closedAtElapsed=5.0))
        batches.archive_batch(self.root, 'batch-auth', 'operator released it')
        self.assertEqual(api.read_approval(self.root, 'batch-auth', 'A')['current']['script'], read['current']['script'])

    def test_an_added_clip_binds_its_approval_under_the_running_clock(self) -> None:
        from studio.production import api
        self.clock.advance(600)
        from _budget_fixture import transcript_words, write_transcript
        words = transcript_words()
        words[650].update(end=words[650]['start'])               # the writer would drop word 650
        diverging = self.work / 'diverging-transcript.json'
        bad = approval('C', transcript_path=str(diverging), transcript_sha256=write_transcript(diverging, words))
        with self.assertRaisesRegex(ValueError, 'drops words \\[650\\]'):
            api.add_clip(self.root, 'batch-auth', 'C', api.AddedClip('fourth Short', bad))
        added = api.add_clip(self.root, 'batch-auth', 'C', api.AddedClip('fourth Short', approval('C')))
        self.assertEqual(added['approval']['elapsed'], 600.0)
        self.clock.advance(900)                                   # M-052 (C8): no minute 25; D starts its own clock
        later = api.add_clip(self.root, 'batch-auth', 'D', api.AddedClip('after minute 25', approval('D')))
        self.assertEqual((later['output']['authorizedElapsed'], later['output']['deadlineElapsed']), (1500.0, 3900.0))

    def test_clip_work_needs_an_approval_bound_at_start(self) -> None:
        from _budget_fixture import DIRECTOR, FINGERPRINT, task_spec
        from studio.production import api
        from studio.production.claims import Enrollment
        from studio.native_budget_policy import new_clip
        self.mutate('batch-auth', lambda record: record['clips'].update(C=new_clip('legacy add-clip', True)))
        api.enroll_director(self.root, 'batch-auth', Enrollment('director', DIRECTOR, 'v1', FINGERPRINT))
        with self.assertRaisesRegex(registry.BudgetRefused, 'Clip C has no approved title and script'):
            api.enqueue_tasks(self.root, 'batch-auth', (task_spec('author-c', 'author', clip_id='C',
                                                                  parent='director'),))
        claimed = api.enqueue_tasks(self.root, 'batch-auth', (task_spec('author-a', 'author', parent='director'),))
        self.assertEqual(claimed['enqueued'], ['author-a'])
        detail = api.claim_task(self.root, 'batch-auth', 'author-a', DIRECTOR)
        self.assertEqual(detail['approval']['title'], 'TEST title A')
        path = self.root / 'batches/batch-auth/authority.json'
        record = json.loads(path.read_text())
        record['clips']['B']['approvals'] = []                   # dropping a bound approval is tampering
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(BudgetAuthorityError, 'authorization identity does not match'):
            self.record()

    def test_a_task_launch_must_belong_to_the_claims_batch(self) -> None:
        from studio.production.claims import ClaimRef
        other = make_project(self.work, 'unbound-other', source=b'another-recording')
        launch = binding.TaskLaunch(other, self.work / 'o', 'draft', {}, 'batch-auth', ClaimRef('x', 1, '0' * 32),
                                    'a' * 64)
        with self.assertRaisesRegex(registry.BudgetRefused, 'bind this project'):
            binding.reserve_task_launch(launch)
        with self.assertRaisesRegex(registry.BudgetRefused, 'not bound to batch batch-other'):
            binding.reserve_task_launch(binding.TaskLaunch(self.project, self.work / 'o', 'draft', {}, 'batch-other',
                                                           ClaimRef('x', 1, '0' * 32), 'a' * 64))



REQUEST_SHA = 'e' * 64   # the kept request's SHA-256 the claim names (TEST)


class TaskReservationTests(AuthorityCase):
    """A claimed media task's exporter reserves its one launch against the acknowledged claim (unit A3), only
    for the request and rendered inputs the task was enqueued with; the watchdog settles it (fix round)."""

    def setUp(self) -> None:
        super().setUp()
        from _budget_fixture import CHILD, DISPATCHER, task_spec
        from studio.production import api
        from studio.production.claims import ClaimRef
        from studio.production.process import TaskClaim
        from studio.native_budget_binding import launch_fingerprint  # P0 adapt: moved (B-7, D.4)
        self.args = argparse.Namespace(project=self.project, output=self.work / 'attempt', review_draft=True)
        identity = binding.input_identity(self.project, 'draft', exporter.launch_options(self.args))
        fingerprint = launch_fingerprint(REQUEST_SHA, identity)
        api.enqueue_tasks(self.root, 'batch-auth', (task_spec('draft', 'media', input_fingerprint=fingerprint),))
        claimed = api.claim_task(self.root, 'batch-auth', 'draft', DISPATCHER)
        api.attach_task(self.root, 'batch-auth', ClaimRef('draft', claimed['epoch'], claimed['token']), CHILD)
        self.task = TaskClaim('batch-auth', 'draft', claimed['epoch'], claimed['token'], REQUEST_SHA)
        self.child = {key: CHILD[key] for key in ('pid', 'pgid', 'started')}

    def reserve_as(self, identity: dict, task: object = None) -> tuple:
        import contextlib
        import io
        from _budget_fixture import table
        from studio import native_budget_launch as launch
        out = io.StringIO()
        with mock.patch.object(binding, 'own_identity', return_value=identity), \
                mock.patch.object(launch, 'own_identity', return_value=identity), \
                mock.patch.object(launch, '_process_table', return_value=table({'type': 'process', **identity})), \
                contextlib.redirect_stdout(out):
            result = exporter.reserve_for_task(self.args, task or self.task)
        return result, out.getvalue()

    def test_the_acknowledging_exporter_reserves_exactly_once(self) -> None:
        (admitted, grant), _ = self.reserve_as(self.child)
        self.assertTrue(admitted)
        self.assertEqual((grant['route'], self.record()['production']['tasks']['draft']['attempt']),
                         ('draft', grant['attemptId']))
        (again, _), printed = self.reserve_as(self.child)
        self.assertFalse(again)
        self.assertEqual((json.loads(printed)['status'], json.loads(printed)['taskId']),
                         ('refused-by-production-budget', 'draft'))
        self.assertEqual(self.counters()['exportAttempt'], 1)
        self.assertEqual(self.record()['production']['tasks']['draft']['state'], 'running')  # its first launch runs

    def test_another_process_cannot_reserve_the_claims_launch(self) -> None:
        (admitted, _), printed = self.reserve_as({**self.child, 'pid': 7099})
        self.assertFalse(admitted)
        self.assertIn('Only the process that acknowledged', json.loads(printed)['reason'])
        self.assertEqual(self.counters()['exportAttempt'], 0)

    def test_inputs_changed_after_enqueue_are_refused(self) -> None:
        # Probe p12: an author edits the project after enqueue; the reservation refuses the changed inputs.
        manifest = json.loads((self.project / 'PROJECT-MANIFEST.json').read_text())
        manifest['files'] = [{'path': 'graphics/new-card.html', 'sha256': 'd' * 64}]
        (self.project / 'PROJECT-MANIFEST.json').write_text(json.dumps(manifest))
        (admitted, _), printed = self.reserve_as(self.child)
        self.assertFalse(admitted)
        self.assertIn('enqueue a replacement', json.loads(printed)['reason'])
        from dataclasses import replace
        (admitted, _), printed = self.reserve_as(self.child, replace(self.task, request_sha256='f' * 64))
        self.assertIn('enqueue a replacement', json.loads(printed)['reason'])
        self.assertEqual(self.counters()['exportAttempt'], 0)

    def test_a_refused_launch_is_settled_by_the_watchdog_with_the_reason(self) -> None:
        # Minor 8: the child only publishes its refusal; the watchdog settles the task once, from it.
        from studio.production.process_settle import Ending, settle
        with mock.patch.object(exporter, 'reserve_task_launch', side_effect=registry.BudgetRefused('TEST forecast')):
            (admitted, _), _ = self.reserve_as(self.child)
        self.assertFalse(admitted)
        self.assertEqual(self.record()['production']['tasks']['draft']['state'], 'running')   # the child never settles
        settled = settle(self.task, Ending(self.child['pid'], None, (), 'BudgetRefused: TEST forecast'))
        self.assertEqual((settled['state'], settled['failure']),
                         ('failed', {'category': 'launch-refused', 'detail': 'BudgetRefused: TEST forecast'}))
        self.assertTrue(self.record()['production']['tasks']['draft']['endConfirmed'])
        self.assertFalse(settle(self.task, Ending(self.child['pid'], None, (), 'again'))['settled'])
        self.assertEqual(self.counters()['exportAttempt'], 0)


if __name__ == '__main__':
    unittest.main()
