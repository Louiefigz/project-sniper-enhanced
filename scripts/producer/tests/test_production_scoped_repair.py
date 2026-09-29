"""Real task caps, static isolation and StageEvidence; all media/review observations are synthetic."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import test_production_sections as fixtures
from _native_long_isolation_fixture import write_static_project
from _native_long_sections_acceptance_fixture import CANVAS
from cut_preview_io import write_new
from studio.native_export_history import register_attempt
from studio.native_runtime import digest
from studio.native_segments.compatibility import prepare_long_repair, reuse_window
from studio.native_segments.dependency import inventory
from studio.production.section_plan import pin_file
from studio.production.section_review_scope import read_scope
from studio.production.sections import (
    assembly_task_snapshot, bind_section_tasks, enqueue_section_authors,
    materialize_section_reviews, require_all_early_reviews,
)


class ScopedRepairTests(unittest.TestCase):
    """Prove scoped review accounting and current join coverage without fabricated media qualification."""

    def setUp(self) -> None:
        """Use the existing real authority fixture and a supported cold-derived three-section project."""
        self.h = fixtures.ProductionSectionsTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        h, f = self.h, self.h.fixture
        write_static_project(f.project, CANVAS, ('A', 'B', 'C'))
        self.reset_project_pins(h.request, f.project)
        h.request['sectionImplementationPins'] = {str(f.node): digest(f.node)}
        h.plan['assignments'] = [h.assignment(name, [index * 25, (index + 1) * 25],
                                f'compositions/unit-{index}.html') for index, name in enumerate('ABC')]
        h.planfile = h.budget.base / 'three-scoped-assignments.json'
        write_new(h.planfile, h.plan)
        h.context = enqueue_section_authors(h.planfile)['sectionProduction']
        h.preview = h.make_previews()

    def reset_project_pins(self, request: dict, project: Path) -> None:
        """Replace only the new unpublished fixture's project inventory, preserving tools and sources."""
        request['pins'] = {path: sha for path, sha in request['pins'].items()
                           if not Path(path).is_relative_to(Path(request['project']))}
        request['project'] = str(project)
        request['pins'].update({str(project / name): sha for name, sha in inventory(project).items()})

    def initial(self) -> dict:
        """Complete three independent author/early/encoded chains at exactly six reviews."""
        h = self.h
        h.bind()
        register_attempt(h.request)
        h.early()
        for index in range(3):
            h.seal(index)
        result = materialize_section_reviews(h.request, 'encoded')
        for task_id in result['enqueued']:
            h.complete(task_id)
        snapshot = assembly_task_snapshot(h.request)
        self.assertEqual(h.budget.record()['clips']['A']['counters']['review'], 6)
        self.assertEqual(len(snapshot['joins']), 4)
        return copy.deepcopy(h.request)

    def repair(self, original: dict) -> None:
        """Publish a new immutable B generation using real registered donor compatibility."""
        h, f = self.h, self.h.fixture
        project = write_static_project(h.budget.base / 'repaired-project', CANVAS, ('A', 'B changed', 'C'))
        current = {**copy.deepcopy(original), 'output': str(h.budget.base / 'repaired-attempt'),
                   'sectionAttemptSequence': 1}
        Path(current['output']).mkdir()
        self.reset_project_pins(current, project)
        current = prepare_long_repair(current, Path(original['output']))
        plan = copy.deepcopy(h.plan)
        plan['parentPlan'] = pin_file(h.planfile)
        for index, row in enumerate(plan['assignments']):
            row['priorAuthorTaskId'] = h.context['assignments'][index]['authorTaskId']
        plan['assignments'][1]['generation'] = 2
        h.planfile = h.budget.base / 'repair-assignments.json'
        write_new(h.planfile, plan)
        h.context = enqueue_section_authors(h.planfile)['sectionProduction']
        h.request, f.request, f.project, f.root = current, current, project, Path(current['output'])
        h.complete(h.context['assignments'][1]['authorTaskId'])
        bind_section_tasks(current, h.planfile)
        f.write_request(current)
        register_attempt(current)
        h.preview = h.make_previews()
        h.publish_previews()

    def copied_owner(self) -> list[int]:
        """Exercise actual donor copies and fresh PCM under synthetic supervised owners."""
        f = self.h.fixture
        original_writer = f.write_phase
        generated = []

        def write_phase(label: str, root: Path) -> None:
            """Only B uses the synthetic picture generator; A/C use production copy validation."""
            phase = label.split('-retry-')[0]
            index = int(phase.rsplit('-', 1)[1])
            if index == 1:
                generated.append(index)
                original_writer(label, root)
                return
            value = reuse_window(f.request, phase, root / f'{phase}-copied')
            audio = root / f'{phase}-TEST.wav'
            audio.write_bytes(f'TEST non-decodable section audio {index}'.encode())
            value['audio'] = {'path': str(audio), 'sha256': digest(audio)}
            from _native_long_probe_fixture import synthetic_dependency_probe
            directory = root / f'{phase}-probe'
            directory.mkdir()
            value['dependencyProbe'] = synthetic_dependency_probe(f.request, phase, directory, value)
            (root / f'{phase}.json').write_text(json.dumps(value))

        f.write_phase = write_phase
        return generated

    def test_three_sections_local_b_repair_finishes_at_review_eight(self) -> None:
        """A/C keep current explicit interiors; B's two new reviews replace both changed joins."""
        h = self.h
        original = self.initial()
        before = h.budget.record()
        self.repair(original)
        early = materialize_section_reviews(h.request)
        self.assertEqual(len(early['enqueued']), 1)
        h.complete(early['enqueued'][0])
        generated = self.copied_owner()
        for index in range(3):
            h.seal(index)
        encoded = materialize_section_reviews(h.request, 'encoded')
        self.assertEqual(len(encoded['enqueued']), 1)
        h.complete(encoded['enqueued'][0])
        snapshot = assembly_task_snapshot(h.request)
        self.assertEqual(generated, [1])
        counters = h.budget.record()['clips']['A']['counters']
        self.assertEqual((counters['author'], counters['repairCycle'], counters['review']), (3, 1, 8))
        for index in (0, 2):
            task_id = h.context['assignments'][index]['authorTaskId']
            self.assertEqual(before['production']['tasks'][task_id], h.budget.record()['production']['tasks'][task_id])
            self.assertTrue(snapshot['assignments'][index]['interiorOnly'])
        self.assertEqual({row['receipt']['path'] for row in snapshot['joins']},
                         {h.budget.record()['production']['tasks'][name]['receipts'][0]['path']
                          for name in (early['enqueued'][0], encoded['enqueued'][0])})

    def test_changed_neighbor_approval_and_current_pcm_are_not_reused(self) -> None:
        """The old B pass cannot satisfy repaired joins; changed retained audio invalidates its interior."""
        h = self.h
        self.repair(self.initial())
        with self.assertRaises((ValueError, RuntimeError, FileNotFoundError)):
            assembly_task_snapshot(h.request)
        result = materialize_section_reviews(h.request)
        h.complete(result['enqueued'][0])
        self.copied_owner()
        for index in range(3):
            h.seal(index)
        audio = Path(h.request['output']) / 'segment-picture-0-TEST.wav'
        audio.write_bytes(b'TEST changed mastered PCM')
        with self.assertRaises((ValueError, RuntimeError)):
            materialize_section_reviews(h.request, 'encoded')

    def test_missing_explicit_join_scope_cannot_complete_review(self) -> None:
        """Six top-level passing checks cannot replace omitted independent boundary observations."""
        h = self.h
        h.bind()
        register_attempt(h.request)
        h.early()
        for index in range(3):
            h.seal(index)
        result = materialize_section_reviews(h.request, 'encoded')
        tasks = h.budget.record()['production']['tasks']
        middle = next(task_id for task_id in result['enqueued'] if tasks[task_id]['sectionBinding']['sectionId'] == 'B')
        with self.assertRaisesRegex(ValueError, 'scoped judgments'):
            h.complete(middle, change_review=lambda review: review['scopes'].pop())

    def test_join_reviewer_cannot_be_neighbor_author(self) -> None:
        """Independence applies to A and C even though the primary reviewed author is B."""
        h = self.h
        h.bind()
        register_attempt(h.request)
        h.early()
        for index in range(3):
            h.seal(index)
        result = materialize_section_reviews(h.request, 'encoded')
        tasks = h.budget.record()['production']['tasks']
        middle = next(task_id for task_id in result['enqueued'] if tasks[task_id]['sectionBinding']['sectionId'] == 'B')
        handle = h.handle
        h.handle = lambda thread: handle(h.context['assignments'][0]['authorTaskId'] if thread == middle else thread)
        with self.assertRaisesRegex(ValueError, 'involved author'):
            h.complete(middle)

    def test_middle_ready_first_renders_before_neighbors_and_keeps_six_reviews(self) -> None:
        """B's one encoded task later judges actual early and encoded joins without another review charge."""
        self.ready_first(1)

    def test_first_ready_section_retains_encoded_interior_through_integration(self) -> None:
        """A can finish its encoded review while B/C remain unclaimed, preserving the six-review budget."""
        self.ready_first(0)

    def ready_first(self, index: int) -> None:
        """Exercise real scoped task dependencies for either an interior or the designated join owner."""
        h, f = self.h, self.h.fixture
        middle = h.context['assignments'][index]
        h.request['sectionScope'] = {'schemaVersion': 1, 'sectionId': middle['sectionId'],
            **{key: middle[key] for key in ('generation', 'inputIdentity', 'frameRange')},
            'sharedPlan': h.context['sharedPlan'], 'snapshotProject': h.request['project'],
            'snapshotPinsHash': 'f' * 64}  # Scoped prebuild admission is exercised by its owner's tests.
        h.complete(middle['authorTaskId'])
        bind_section_tasks(h.request, h.planfile)
        f.write_request(h.request)
        register_attempt(h.request)
        h.preview = h.make_previews()
        h.publish_previews()
        h.early()
        require_all_early_reviews(h.request)
        h.seal(index)
        encoded = materialize_section_reviews(h.request, 'encoded')
        self.assertEqual(encoded['pendingSections'], ['B'] if index == 1 else [])
        for task_id in encoded['enqueued']:
            h.complete(task_id)
        with self.assertRaisesRegex(ValueError, 'cannot assemble'):
            assembly_task_snapshot(h.request)
        self.assertEqual(h.budget.record()['clips']['A']['counters']['author'], 1)
        original = copy.deepcopy(h.request)
        self.integrate_ready(original)
        h.early()
        for window in range(3):
            h.seal(window)
        result = materialize_section_reviews(h.request, 'encoded')
        for task_id in result['enqueued']:
            h.complete(task_id)
        snapshot = assembly_task_snapshot(h.request)
        self.assertEqual(h.budget.record()['clips']['A']['counters']['review'], 6)
        self.check_integrated_joins(snapshot, index)

    def check_integrated_joins(self, snapshot: dict, ready_index: int) -> None:
        """The B result explicitly records both observation stages, even if its early task was interior-only."""
        h = self.h
        tasks = h.budget.record()['production']['tasks']
        middle_encoded = next(task for task in tasks.values() if task.get('sectionBinding', {}).get('role')
                              == 'encoded-review' and task['sectionBinding']['sectionId'] == 'B')
        scope_ids = [scope['id'] for scope in read_scope(middle_encoded['sectionBinding'])[1]]
        self.assertEqual(scope_ids, ['interior', 'early-join:A:B', 'encoded-join:A:B',
                                     'early-join:B:C', 'encoded-join:B:C'])
        encoded_joins = [row for row in snapshot['joins'] if row['stage'] == 'encoded' or ready_index == 1]
        self.assertEqual({row['receipt']['path'] for row in encoded_joins}, {middle_encoded['receipts'][0]['path']})

    def integrate_ready(self, original: dict) -> None:
        """Admit an immutable complete fixture and bind its real original scoped result pointer."""
        h, f = self.h, self.h.fixture
        project = write_static_project(h.budget.base / 'integrated-project', CANVAS, ('A', 'B', 'C'))
        current = copy.deepcopy(original)
        current.pop('sectionScope')
        current['output'] = str(h.budget.base / 'integrated-attempt')
        Path(current['output']).mkdir()
        self.reset_project_pins(current, project)
        current['pins'].update(original['pins'])
        request_pin = pin_file(Path(original['output']) / 'export-request.json')
        current['pins'][request_pin['path']] = request_pin['sha256']
        section_id = original['sectionScope']['sectionId']
        current['sectionIntegrations'] = [{'sectionId': section_id, 'originalAttempt': original['output'],
                                           'originalRequestSha256': request_pin['sha256']}]
        h.request, f.request, f.project, f.root = current, current, project, Path(current['output'])
        for row in h.context['assignments']:
            if row['sectionId'] != section_id:
                h.complete(row['authorTaskId'])
        bind_section_tasks(current, h.planfile)
        f.write_request(current)
        register_attempt(current)
        h.preview = h.make_previews()
        h.publish_previews()


if __name__ == '__main__':
    unittest.main()
