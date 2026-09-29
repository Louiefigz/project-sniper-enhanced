"""Retained chunk judgments under real repair authority; all media and statements are synthetic."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from _production_chunk_fixture import ChunkFixture
from studio.native_export_history import register_attempt
from studio.production import api
from studio.production.callbacks import TaskResult
from studio.production.section_review_reuse import retained_snapshot
from studio.production.sections import assembly_task_snapshot, encoded_spec, materialize_section_reviews
import test_production_scoped_repair as fixtures


class ChunkReuseTests(unittest.TestCase):
    """A/C explicit chunk judgments remain scoped when B changes under the unchanged review8 cap."""

    def setUp(self) -> None:
        """Reuse the existing three-author repair and supported static isolation fixture."""
        self.case = fixtures.ScopedRepairTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.h = self.case.h
        self.scenes(self.h.fixture.project)
        self.case.reset_project_pins(self.h.request, self.h.fixture.project)
        self.h.preview = self.h.make_previews()

    def scenes(self, project: Path) -> None:
        """Declare actual cold scene geometry; short durations are explicit planner exceptions."""
        file = project / 'LONG-PROJECT.json'
        value = json.loads(file.read_text())
        value['scenes'] = [{'startFrame': start, 'endFrame': start + 25} for start in (0, 25, 50)]
        file.write_text(json.dumps(value))

    def complete_chunks(self, row: dict) -> None:
        """Keep one actual reviewer charge, canonical progress receipts and ordinary final callback."""
        fixture = object.__new__(ChunkFixture)
        fixture.host = self.h
        fixture.start(row)
        for index in range(len(fixture.scopes())):
            fixture.record(fixture.progress(index))
        api.complete_task(self.h.budget.root, 'section-test', fixture.ref, TaskResult((fixture.final(),)))

    def initial(self) -> dict:
        """Register A/C chunk reviewers plus B's existing join reviewer at exactly six reviews."""
        h = self.h
        h.bind()
        register_attempt(h.request)
        h.early()
        for index in range(3):
            h.seal(index)
        for index in (0, 2):
            self.complete_chunks(h.context['assignments'][index])
        middle = encoded_spec(h.request, h.context['assignments'][1], h.budget.record())
        api.enqueue_tasks(h.budget.root, 'section-test', (middle,))
        h.complete(middle.task_id)
        self.assertEqual(h.budget.record()['clips']['A']['counters']['review'], 6)
        return copy.deepcopy(h.request)

    def repair(self, original: dict) -> None:
        """Preserve the exact global clock/scene plan while the fixture changes only B's private source."""
        from unittest.mock import patch
        from test_production_scoped_repair import write_static_project
        def with_scenes(project: Path, canvas: dict, texts: tuple) -> Path:
            """Add the identical authored scene geometry before any admission pins are published."""
            result = write_static_project(project, canvas, texts)
            self.scenes(result)
            return result
        with patch('test_production_scoped_repair.write_static_project', side_effect=with_scenes):
            self.case.repair(original)

    def test_local_b_repair_retains_a_c_chunk_receipts_with_review_eight(self) -> None:
        """Current seals and compatible local geometry preserve only unchanged independently judged interiors."""
        h = self.h
        original = self.initial()
        originals = [row for row in h.budget.record()['production']['tasks'].values()
                     if row.get('sectionBinding', {}).get('chunkPlan')]
        self.repair(original)
        early = materialize_section_reviews(h.request)
        self.assertEqual(len(early['enqueued']), 1)
        h.complete(early['enqueued'][0])
        generated = self.case.copied_owner()
        for index in range(3):
            h.seal(index)
        for index in (0, 2):
            value = retained_snapshot(h.request, h.context['assignments'][index], h.budget.record())
            self.assertTrue(value['interiorOnly'])
            self.assertIn('chunkPlan', value)
            self.assertEqual(len(value['chunkReviews']), 1)
        encoded = materialize_section_reviews(h.request, 'encoded')
        self.assertEqual(len(encoded['enqueued']), 1)
        h.complete(encoded['enqueued'][0])
        self.assertEqual(generated, [1])
        self.assertEqual(h.budget.record()['clips']['A']['counters']['review'], 8)
        for task in originals:
            self.assertEqual(h.budget.record()['production']['tasks'][task['id']], task)
        snapshot = assembly_task_snapshot(h.request)
        self.assertEqual(len(snapshot['joins']), 4)

    def test_retained_chunk_current_pcm_corruption_is_refused(self) -> None:
        """The unchanged author and chunk map cannot authorize different current mastered audio."""
        h = self.h
        self.repair(self.initial())
        early = materialize_section_reviews(h.request)
        h.complete(early['enqueued'][0])
        self.case.copied_owner()
        for index in range(3):
            h.seal(index)
        (Path(h.request['output']) / 'segment-picture-0-TEST.wav').write_text('TEST different PCM')
        with self.assertRaises((ValueError, RuntimeError)):
            retained_snapshot(h.request, h.context['assignments'][0], h.budget.record())


if __name__ == '__main__':
    unittest.main()
