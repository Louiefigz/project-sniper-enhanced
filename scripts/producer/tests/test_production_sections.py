"""Logical production tasks over real authority and seals; all media/judgments here are synthetic."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from _native_long_sections_acceptance_fixture import LongSectionsFixture
from _native_section_budget_fixture import SectionBudgetFixture
from cut_preview_io import write_new
from studio.native_short_pipeline import NativeShortPipeline
from studio.native_review_regions import region_packet, preview_windows
from studio.native_segments.owners import restore_window
from studio.native_long_recovery import prepare_section_recovery
from studio.production import api
from studio.production.callbacks import TaskResult
from studio.production.claims import ClaimRef, Enrollment
from studio.production.section_media import read_media_manifest
from studio.production.section_plan import pin_file, read_plan
from studio.production.section_results import CHECKS, claim_directory
from studio.production.section_review_inputs import early_inputs
from studio.production.sections import (
    assembly_task_snapshot, bind_section_tasks, enqueue_section_authors,
    materialize_section_reviews, require_early_review,
)


class ProductionSectionsTests(unittest.TestCase):
    """Use actual claims/completion, persistent caps and StageEvidence with fake rendering only."""

    def setUp(self) -> None:
        """Freeze two logical assignments over three technical windows under an enrolled director."""
        self.budget = SectionBudgetFixture(self)
        media_root = self.budget.base / 'media'
        media_root.mkdir()
        self.fixture = LongSectionsFixture(media_root)
        self.request = self.fixture.request
        self.request['productionBudget'] = copy.deepcopy(self.budget.request['productionBudget'])
        self.enterContext(patch('studio.native_short_pipeline.NativeRun', side_effect=self.fixture.owner_factory))
        api.enroll_director(self.budget.root, 'section-test', Enrollment('director', self.handle('director'),
                                                                       'test-v1', 'd' * 64))
        shared = self.budget.base / 'shared-plan.json'
        shared.write_text('{"TEST":"one shared creative plan"}')
        self.plan = {'schemaVersion': 1, 'kind': 'native-long-section-assignments',
                     'authority': str(self.budget.root), 'batchId': 'section-test', 'clipId': 'A',
                     'directorTaskId': 'director', 'deadlineElapsed': 9000,
                     'outputRoot': str(self.budget.base / 'private-authors'), 'sharedPlan': pin_file(shared),
                     'assignments': [self.assignment('first', [0, 50], 'index.html'),
                                     self.assignment('last', [50, 75], 'LONG-PROJECT.json')]}
        self.planfile = self.budget.base / 'assignments.json'
        write_new(self.planfile, self.plan)
        self.context = enqueue_section_authors(self.planfile)['sectionProduction']
        self.preview = self.make_previews()

    def handle(self, thread: str) -> dict:
        """Register distinct exact synthetic host turns; this is not authenticated playback."""
        return {'type': 'host', 'host': 'codex', 'thread': thread, 'turn': 'TEST-turn'}

    def assignment(self, name: str, bounds: list[int], source: str) -> dict:
        """Declare private outputs copied to one current project file."""
        return {'sectionId': name, 'generation': 1, 'frameRange': bounds, 'inputs': [],
                'projectFiles': {'authored.txt': source}}

    def make_previews(self) -> dict:
        """Provide two nondecodable muxed test inputs with actual digest-bound intervals."""
        clips = []
        packet = region_packet(self.request)
        for index, window in enumerate(preview_windows(packet)):
            bounds = [window['startFrame'], window['endFrame']]
            file = self.budget.base / f'TEST-preview-{index}.mp4'
            file.write_text(f'TEST synthetic muxed preview {index}')
            clips.append({**pin_file(file), 'absoluteFrameRange': bounds})
        return {'status': 'native-motion-previews-complete', 'packet': packet, 'priorPreview': None, 'clips': clips}

    def complete(self, task_id: str, omit_observation: bool = False, change_review: object = None) -> None:
        """Run actual claim, attach and completion APIs around canonical test-only result bytes."""
        claimed = api.claim_task(self.budget.root, 'section-test', task_id, self.handle('director'))
        ref = ClaimRef(task_id, claimed['epoch'], claimed['token'])
        api.attach_task(self.budget.root, 'section-test', ref, self.handle(task_id))
        task = self.budget.record()['production']['tasks'][task_id]
        binding = task['sectionBinding']
        directory = claim_directory(task)
        directory.mkdir(parents=True)
        artifacts, review = [], None
        if binding['role'] == 'author':
            row = next(row for row in self.context['assignments'] if row['authorTaskId'] == task_id)
            source = self.fixture.project / row['projectFiles']['authored.txt']
            artifact = directory / 'authored.txt'
            artifact.write_bytes(source.read_bytes())
            artifacts = [pin_file(artifact)]
        else:
            observations = self.observations(binding)
            review = {'status': 'pass', 'checks': dict.fromkeys(CHECKS, True),
                      'assessments': dict.fromkeys(CHECKS, 'TEST synthetic judgment; no actual playback'),
                      'observations': observations[:-1] if omit_observation else observations}
            if binding.get('reviewScope'):
                from studio.production.section_review_scope import read_scope
                review['scopes'] = [{'id': scope['id'], 'checks': dict.fromkeys(CHECKS, True),
                    'assessments': dict.fromkeys(CHECKS, 'TEST explicit scope; not real playback'),
                    'observations': scope['observations']} for scope in read_scope(binding)[1]]
            if change_review is not None:
                change_review(review)
        value = {'schemaVersion': 1, 'kind': 'native-long-section-result', 'taskId': task_id,
                 'epoch': ref.epoch, 'token': ref.token, 'binding': binding, 'artifacts': artifacts, 'review': review}
        file = directory / 'result.json'
        write_new(file, value)
        api.complete_task(self.budget.root, 'section-test', ref, TaskResult((pin_file(file),)))

    def observations(self, binding: dict) -> list[dict]:
        """Read exact adapter-selected windows, never invent encoded ranges."""
        if binding['role'] == 'encoded-review':
            return read_media_manifest(binding)
        row = next(row for row in self.context['assignments'] if row['sectionId'] == binding['sectionId'])
        return early_inputs(self.request, row)[1]

    def bind(self) -> None:
        """Complete both registered authors and publish the fully integrated request."""
        for row in self.context['assignments']:
            self.complete(row['authorTaskId'])
        bind_section_tasks(self.request, self.planfile)
        self.fixture.write_request(self.request)
        self.publish_previews()

    def publish_previews(self) -> None:
        """Make a synthetic completed original preview owner for real transitive recovery validation."""
        file = self.fixture.root / 'motion-previews.json'
        write_new(file, self.preview)
        request_pin = pin_file(self.fixture.root / 'export-request.json')
        owner = self.fixture.owner_record(self.request, {request_pin['path']: request_pin['sha256']},
                                         self.preview['status'], str(file))
        write_new(self.fixture.root / 'preview.render.json', {**owner, 'completedAt': 'TEST completed'})

    def early(self) -> None:
        """Complete every current early-review task using distinct registered host identities."""
        result = materialize_section_reviews(self.request)
        for task_id in result['enqueued']:
            self.complete(task_id)

    def seal(self, index: int) -> None:
        """Retain real cleanup and stage seals around synthetic owner media."""
        self.fixture.launch_section(NativeShortPipeline(self.request, {}), f'segment-picture-{index}')

    def test_authors_are_idempotent_and_integrated_outputs_are_required(self) -> None:
        """Re-enqueue keeps identities/counters; no author completion means no render admission."""
        replay = enqueue_section_authors(self.planfile)
        self.assertFalse(replay['enqueued'])
        self.assertEqual(len(replay['replayed']), 2)
        with self.assertRaisesRegex(ValueError, 'registered claim'):
            bind_section_tasks(self.request, self.planfile)
        self.bind()
        record = self.budget.record()
        self.assertEqual(record['clips']['A']['counters']['author'], 2)
        with self.assertRaisesRegex(ValueError, 'unknown section task'):
            require_early_review(self.request, 'segment-picture-0')
        self.early()
        require_early_review(self.request, 'segment-picture-0')

    def test_first_logical_review_runs_while_last_window_remains_unrendered(self) -> None:
        """Two verified early windows enable one review; assembly still waits for every logical group."""
        self.bind()
        self.early()
        self.seal(0)
        self.assertEqual(materialize_section_reviews(self.request, 'encoded')['pendingSections'], ['first', 'last'])
        self.seal(1)
        result = materialize_section_reviews(self.request, 'encoded')
        self.assertEqual(result['pendingSections'], ['last'])
        self.assertEqual(len(result['enqueued']), 1)
        self.complete(result['enqueued'][0])
        with self.assertRaises((ValueError, RuntimeError, FileNotFoundError)):
            assembly_task_snapshot(self.request)
        self.seal(2)
        result = materialize_section_reviews(self.request, 'encoded')
        self.complete(result['enqueued'][0])
        snapshot = assembly_task_snapshot(self.request)
        self.assertEqual(len(snapshot['assignments']), 2)
        self.assertEqual(self.budget.record()['clips']['A']['counters']['review'], 4)

    def test_authored_project_mutation_and_superseded_review_block(self) -> None:
        """Old receipts cannot approve changed project bytes or a revoked current task."""
        self.bind()
        self.early()
        receipt = require_early_review(self.request, 'segment-picture-0')
        record = self.budget.record()
        task = next(task for task in record['production']['tasks'].values() if receipt in task['receipts'])
        api.supersede_task(self.budget.root, 'section-test', task['id'], 'TEST revoked review')
        with self.assertRaisesRegex(ValueError, 'not current'):
            require_early_review(self.request, 'segment-picture-0')
        (self.fixture.project / 'index.html').write_text('TEST changed integrated picture')
        with self.assertRaisesRegex(ValueError, 'differs from its assigned author'):
            materialize_section_reviews(self.request)

    def test_plan_scope_overlap_and_unaligned_windows_refused(self) -> None:
        """Logical work cannot leave gaps, share writable outputs or ambiguously own one encoder window."""
        for bounds in ([51, 75], [49, 75]):
            plan = copy.deepcopy(self.plan)
            plan['assignments'][1]['frameRange'] = bounds
            file = self.budget.base / f'invalid-{bounds[0]}.json'
            write_new(file, plan)
            with self.assertRaisesRegex(ValueError, 'contiguous'):
                read_plan(file)
        self.bind()
        changed = copy.deepcopy(self.request)
        changed['sectionProduction']['assignments'][0]['generation'] = 2
        with self.assertRaisesRegex(ValueError, 'production plan changed'):
            require_early_review(changed, 'segment-picture-0')

    def test_missing_representative_preview_does_not_silently_skip_early_review(self) -> None:
        """A logical group without current sample media requires explicit new preview work."""
        self.bind()
        self.enterContext(patch('studio.native_motion_previews.current_motion_previews', return_value={'clips': []}))
        with self.assertRaisesRegex(ValueError, 'representative moving previews'):
            materialize_section_reviews(self.request)
        self.assertEqual(self.budget.record()['clips']['A']['counters']['review'], 0)

    def test_exact_resume_retains_all_completed_reviews_without_new_charges(self) -> None:
        """New attempt paths preserve original reviewed proofs only after exact current byte checks."""
        self.bind()
        self.early()
        for index in range(3):
            self.seal(index)
        result = materialize_section_reviews(self.request, 'encoded')
        for task_id in result['enqueued']:
            self.complete(task_id)
        before = assembly_task_snapshot(self.request)
        resumed = self.fixture.restart()
        resumed['productionBudget'] = self.request['productionBudget']
        with patch('studio.native_export_history.known_attempts', return_value=[self.fixture.root]):
            resumed = prepare_section_recovery(resumed, self.fixture.root)
        resumed['revision'] = {**resumed['revision'], 'windowDonors': {
            f'segment-picture-{index}': str(self.fixture.root / f'segment-picture-{index}-stage.json')
            for index in range(3)}}
        self.fixture.write_request(resumed)
        pipeline = NativeShortPipeline(resumed, {})
        for index in range(3):
            self.assertTrue(restore_window(pipeline, f'segment-picture-{index}'))
        self.assertEqual(materialize_section_reviews(resumed, 'early')['enqueued'], [])
        self.assertEqual(materialize_section_reviews(resumed, 'encoded')['enqueued'], [])
        self.assertEqual(assembly_task_snapshot(resumed), before)
        self.assertEqual(self.budget.record()['clips']['A']['counters']['review'], 4)
        media = Path(resumed['output']) / 'segment-picture-0-restored/media.mp4'
        media.write_text('TEST corrupt restored picture')
        with self.assertRaises((ValueError, RuntimeError)):
            assembly_task_snapshot(resumed)

    def test_three_authors_allow_only_provenanced_middle_repair_without_reauthoring_neighbors(self) -> None:
        """The real authority charges repairCycle once, preserves author3, and keeps A/C claims intact."""
        extra = self.fixture.project / 'third.txt'
        extra.write_text('TEST third private artifact')
        self.request['pins'][str(extra)] = pin_file(extra)['sha256']
        plan = {**self.plan, 'assignments': [self.assignment('A', [0, 25], 'index.html'),
                self.assignment('B', [25, 50], 'LONG-PROJECT.json'), self.assignment('C', [50, 75], 'third.txt')]}
        file = self.budget.base / 'three-authors.json'
        write_new(file, plan)
        self.context = enqueue_section_authors(file)['sectionProduction']
        for row in self.context['assignments']:
            self.complete(row['authorTaskId'])
        before = self.budget.record()
        repaired = copy.deepcopy(plan)
        repaired['parentPlan'] = pin_file(file)
        for index, row in enumerate(repaired['assignments']):
            row['priorAuthorTaskId'] = self.context['assignments'][index]['authorTaskId']
        repaired['assignments'][1]['generation'] = 2
        repair_file = self.budget.base / 'middle-repair.json'
        write_new(repair_file, repaired)
        result = enqueue_section_authors(repair_file)
        self.assertEqual(len(result['enqueued']), 1)
        self.assertEqual(len(result['replayed']), 2)
        self.context = result['sectionProduction']
        self.complete(result['enqueued'][0])
        after = self.budget.record()
        self.assertEqual(after['clips']['A']['counters']['author'], 3)
        self.assertEqual(after['clips']['A']['counters']['repairCycle'], 1)
        for row in (self.context['assignments'][0], self.context['assignments'][2]):
            task_id = row['authorTaskId']
            self.assertEqual(before['production']['tasks'][task_id], after['production']['tasks'][task_id])
        old_middle = before['production']['tasks'][repaired['assignments'][1]['priorAuthorTaskId']]
        self.assertEqual(after['production']['tasks'][old_middle['id']]['state'], 'superseded')

    def test_arbitrary_repair_kind_cannot_bypass_initial_author_cap(self) -> None:
        """Without a completed exact predecessor, role-author repairCycle declarations are refused."""
        from dataclasses import replace
        from studio.production.section_plan import task_spec
        row = self.context['assignments'][0]
        spec = task_spec(self.context, row, row['authorBinding'])
        forged = replace(spec, task_id='forged-repair', kind='repairCycle', replaces=None)
        with self.assertRaisesRegex(ValueError, 'registered authored predecessor'):
            api.enqueue_tasks(self.budget.root, 'section-test', (forged,))


if __name__ == '__main__':
    unittest.main()
