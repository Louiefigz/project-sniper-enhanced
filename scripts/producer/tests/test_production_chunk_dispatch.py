"""Public chunk dispatch over real task authority and seals; media judgments are synthetic."""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from _native_long_isolation_fixture import write_static_project
from _production_chunk_fixture import ChunkFixture
from cut_preview_io import write_new
from studio.native_long_chunk_evidence import chunk_geometry
from studio.native_long_chunks import bind_chunk_request
from studio.native_export_history import attempt_reservation, register_attempt
from studio.native_runtime import digest
from studio.native_segments.plan import initial_long_plan
from studio.production import api
from studio.production.callbacks import TaskResult
from studio.production.claims import ClaimRef
from studio.production.section_plan import pin_file
from studio.production.section_results import claim_directory
from studio.production.sections import (
    assembly_task_snapshot, bind_section_tasks, encoded_spec, enqueue_section_authors, materialize_section_reviews,
)
from test_native_long_chunk_admission import ChunkAdmissionTests
from test_production_chunk_global_joins import ChunkGlobalJoinTests
from test_production_sections import ProductionSectionsTests


class ChunkDispatchTests(unittest.TestCase):
    """Later seals update ready scopes without another task, reviewer charge or approval."""

    def setUp(self) -> None:
        """Publish an actual authored contract and bound synthetic immutable export request."""
        self.host = ProductionSectionsTests()
        self.host.setUp()
        self.addCleanup(self.host.doCleanups)
        host = self.host
        canvas = {'width': 320, 'height': 180, 'frameRate': '1/1', 'totalFrames': 180}
        project = host.fixture.project
        write_static_project(project, canvas, ('A1', 'A2', 'C'))
        (project / 'LONG-PROJECT.json').write_text(json.dumps({'canvas': canvas, 'scenes': [
            {'startFrame': start, 'endFrame': start + 60} for start in (0, 60, 120)]}))
        host.request.update(revision=initial_long_plan(canvas, 'a' * 64, [0, 60, 120, 180]))
        host.plan['assignments'] = [host.assignment('first', [0, 120], 'index.html'),
                                    host.assignment('last', [120, 180], 'LONG-PROJECT.json')]
        host.planfile = host.budget.base / 'public-chunk-assignments.json'
        write_new(host.planfile, host.plan)
        host.context = enqueue_section_authors(host.planfile)['sectionProduction']
        geometry = chunk_geometry(project, host.context)
        fixture = SimpleNamespace(project=project, context=host.context, geometry=geometry)
        write_new(project / 'LONG-CHUNKS.json', ChunkAdmissionTests.authored_contract(fixture))
        host.fixture.inputs.update({str(file): digest(file) for file in project.rglob('*') if file.is_file()})
        host.request['pins'] = dict(host.fixture.inputs)
        for row in host.context['assignments']:
            host.complete(row['authorTaskId'])
        bind_section_tasks(host.request, host.planfile)
        host.request['prebuildReview'] = {'status': 'recorded-independent-plan-pass',
                                          'scope': 'native-long-full-project'}
        bind_chunk_request(host.request)
        host.preview = host.make_previews()
        host.fixture.write_request(host.request)
        host.publish_previews()
        host.early()
        from _native_review_package_fixture import install_test_packages
        install_test_packages(self, host)

    def claim(self, task_id: str, index: int = 0) -> ChunkFixture:
        """Reuse synthetic receipt builders against the task actually published by dispatch."""
        host = self.host
        fixture = ChunkFixture.__new__(ChunkFixture)
        fixture.host = host
        fixture.spec = encoded_spec(host.request, host.context['assignments'][index], host.budget.record())
        self.assertEqual(fixture.spec.task_id, task_id)
        claim = api.claim_task(host.budget.root, 'section-test', task_id, host.handle('director'))
        fixture.ref = ClaimRef(task_id, claim['epoch'], claim['token'])
        api.attach_task(host.budget.root, 'section-test', fixture.ref, host.handle('TEST-public-chunk-reviewer'))
        claim_directory(fixture.task()).mkdir(parents=True)
        return fixture

    def test_ready_chunk_dispatch_replays_one_task_while_other_media_is_missing(self) -> None:
        """First chunk QC proceeds before later windows and never spends another review charge."""
        host = self.host
        before = materialize_section_reviews(host.request, 'encoded')
        self.assertEqual(before['enqueued'], [])
        self.assertEqual(before['readyChunks'], [])
        host.seal(0)
        first = materialize_section_reviews(host.request, 'encoded')
        self.assertEqual(len(first['enqueued']), 1)
        self.assertEqual(len(first['readyChunks']), 1)
        fixture = self.claim(first['enqueued'][0])
        fixture.record(fixture.progress(0))
        host.seal(1)
        second = materialize_section_reviews(host.request, 'encoded')
        self.assertEqual(second['enqueued'], [])
        self.assertEqual(second['replayed'], first['enqueued'])
        self.assertEqual(len(second['readyChunks']), 3)
        self.assertEqual(host.budget.record()['clips']['A']['counters']['review'], 3)
        fixture.record(fixture.progress(1))
        fixture.record(fixture.progress(2))
        api.complete_task(host.budget.root, 'section-test', fixture.ref, TaskResult((fixture.final(),)))
        with self.assertRaises((ValueError, RuntimeError, FileNotFoundError)):
            assembly_task_snapshot(host.request)
        self.assertFalse((host.fixture.root / 'segment-picture-2-stage.json').exists())

    def test_changed_contract_refuses_dispatch_before_any_review_task(self) -> None:
        """An admitted flag cannot hide changed real transition policy bytes."""
        host = self.host
        file = host.fixture.project / 'LONG-CHUNKS.json'
        file.write_text(file.read_text() + ' ')
        with self.assertRaises(ValueError):
            materialize_section_reviews(host.request, 'encoded')

    def test_all_current_chunk_and_join_reviews_satisfy_public_assembly_barrier(self) -> None:
        """The new public path completes with exact local inventories and both global join stages."""
        host = self.host
        with attempt_reservation(host.request):
            register_attempt(host.request)
        for index in range(3):
            host.seal(index)
        result = materialize_section_reviews(host.request, 'encoded')
        self.assertEqual(len(result['enqueued']), 2)
        specs = [encoded_spec(host.request, row, host.budget.record()) for row in host.context['assignments']]
        self.assertEqual(set(result['enqueued']), {spec.task_id for spec in specs})
        first = self.claim(specs[0].task_id)
        for index in range(3):
            first.record(first.progress(index))
        api.complete_task(host.budget.root, 'section-test', first.ref, TaskResult((first.final(),)))
        last = self.claim(specs[1].task_id, 1)
        fixture = ChunkGlobalJoinTests.__new__(ChunkGlobalJoinTests)
        fixture.host, fixture.ref, fixture.task = host, last.ref, last.task()
        fixture.request_pin = pin_file(host.fixture.root / 'export-request.json')
        fixture.complete_last()
        snapshot = assembly_task_snapshot(host.request)
        self.assertEqual(len(snapshot['assignments']), 2)
        self.assertEqual(len(snapshot['assignments'][0]['chunkReviews']), 3)
        self.assertEqual([row['stage'] for row in snapshot['joins']], ['early', 'encoded'])
        self.assertEqual(host.budget.record()['clips']['A']['counters']['review'], 4)


if __name__ == '__main__':
    unittest.main()
