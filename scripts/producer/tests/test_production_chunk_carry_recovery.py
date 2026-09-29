"""Registered exact resume retains mixed current/carried review provenance.

Claims, recovery readers and StageEvidence are real. Media bytes and editorial
judgments are explicit TEST fixtures, never playback or performance evidence.
"""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

import test_production_chunk_carry_dispatch as fixtures
from _native_review_package_fixture import prepare_test_master
from studio.native_export_history import attempt_reservation, register_attempt
from studio.native_long_recovery import prepare_section_recovery
from studio.native_segments.owners import restore_window
from studio.native_short_pipeline import NativeShortPipeline
from studio.production import api
from studio.production.callbacks import TaskResult
from studio.production.section_chunk_dispatch import chunk_snapshot
from studio.production.sections import assembly_task_snapshot, materialize_section_reviews


class ChunkCarryRecoveryTests(unittest.TestCase):
    """Use public authority boundaries without inventing new tasks, claims or counters."""

    def setUp(self) -> None:
        """Prepare a real B-author replacement and current sealed fictional media."""
        self.case = fixtures.ChunkCarryDispatchTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.host = self.case.host

    def resume(self, original: dict) -> dict:
        """Reopen the current repaired inventory and restore its exact registered seals."""
        host, fixture = self.host, self.host.fixture
        fresh = fixture.restart()
        # The fixture's base inventory predates repair; use the current frozen inputs.
        fresh['pins'] = dict(original['pins'])
        resumed = prepare_section_recovery(fresh, Path(original['output']))
        resumed['revision'] = {**resumed['revision'], 'windowDonors': {
            f'segment-picture-{index}': str(Path(original['output']) / f'segment-picture-{index}-stage.json')
            for index in range(3)}}
        fixture.write_request(resumed)
        host.request, fixture.request, fixture.root = resumed, resumed, Path(resumed['output'])
        prepare_test_master(host)
        with attempt_reservation(resumed):
            register_attempt(resumed)
        pipeline = NativeShortPipeline(resumed, {})
        for index in range(3):
            self.assertTrue(restore_window(pipeline, f'segment-picture-{index}'))
        return resumed

    def test_exact_resume_preserves_carry_and_rejects_corrupt_envelope(self) -> None:
        """One claimed reviewer completes fresh seams; assembly still cold-checks each retained receipt."""
        self.case.dispatch()
        review = self.case.attach()
        review.record(review.progress(1))
        original = copy.deepcopy(self.host.request)
        original_task = review.task()
        counters = self.host.budget.record()['clips']['A']['counters'].copy()
        resumed = self.resume(original)
        result = materialize_section_reviews(resumed, 'encoded')
        self.assertEqual(result['enqueued'], [])
        self.assertEqual(review.task()['sectionCarry'], original_task['sectionCarry'])
        self.assertEqual(review.task()['claim'], original_task['claim'])
        self.assertEqual(self.host.budget.record()['clips']['A']['counters'], counters)
        for index in (3, 4):
            review.record(review.progress(index, resumed))
        api.complete_task(self.host.budget.root, 'section-test', review.ref, TaskResult((self.case.final(review),)))
        self.assertEqual(review.task()['state'], 'completed')
        value = chunk_snapshot(review.task(), resumed)
        self.assertEqual(sum('retainedJudgment' in row for row in value['chunkReviews']), 2)
        self.assertEqual(self.host.budget.record()['clips']['A']['counters'], counters)
        assembly_task_snapshot(resumed)
        pin = next(iter(review.task()['sectionCarry'].values()))
        Path(pin['path']).write_bytes(b'TEST corrupted carried envelope')
        with self.assertRaises((ValueError, RuntimeError)):
            assembly_task_snapshot(resumed)


if __name__ == '__main__':
    unittest.main()
