"""Exact chunk continuation through actual public dispatch, authority and synthetic stage seals."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

import test_production_chunk_dispatch as fixtures
from studio.native_export_history import attempt_reservation, register_attempt
from studio.native_long_recovery import prepare_section_recovery
from studio.native_segments.owners import restore_window
from studio.native_short_pipeline import NativeShortPipeline
from studio.production import api
from studio.production.callbacks import TaskResult
from studio.production.section_chunk_dispatch import chunk_snapshot
from studio.production.sections import assembly_task_snapshot, materialize_section_reviews


class ChunkRecoveryTests(unittest.TestCase):
    """Exact resume preserves completed and partial reviewer tasks without extra charges."""

    def setUp(self) -> None:
        """Use the real authored Long chunk contract and ordinary assigned task APIs."""
        self.case = fixtures.ChunkDispatchTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.host = self.case.host

    def register(self) -> None:
        """Publish this exact fixture request through the existing export history authority."""
        with attempt_reservation(self.host.request):
            register_attempt(self.host.request)

    def resume(self, indexes: tuple[int, ...]) -> dict:
        """Reopen registered original policy, restore actual selected seals, and advance attempt highwater."""
        host, fixture = self.host, self.host.fixture
        original = copy.deepcopy(host.request)
        resumed = fixture.restart()
        resumed = prepare_section_recovery(resumed, Path(original['output']))
        resumed['revision'] = {**resumed['revision'], 'windowDonors': {f'segment-picture-{index}':
            str(Path(original['output']) / f'segment-picture-{index}-stage.json') for index in indexes}}
        fixture.write_request(resumed)
        host.request, fixture.request, fixture.root = resumed, resumed, Path(resumed['output'])
        from _native_review_package_fixture import prepare_test_master
        prepare_test_master(host)
        self.register()
        pipeline = NativeShortPipeline(resumed, {})
        for index in indexes:
            self.assertTrue(restore_window(pipeline, f'segment-picture-{index}'))
        return resumed

    def test_partial_review_resumes_remaining_chunks_under_same_claim_and_charge(self) -> None:
        """First original chunk receipt and later resumed receipts complete the same assigned reviewer."""
        host = self.host
        self.register()
        host.seal(0)
        published = materialize_section_reviews(host.request, 'encoded')
        reviewer = self.case.claim(published['enqueued'][0])
        first = reviewer.progress(0)
        reviewer.record(first)
        original_ref = reviewer.ref
        resumed = self.resume((0,))
        before = materialize_section_reviews(resumed, 'encoded')
        self.assertEqual(before['enqueued'], [])
        self.assertEqual(before['replayed'], [original_ref.task_id])
        host.seal(1)
        later = materialize_section_reviews(resumed, 'encoded')
        self.assertEqual(later['enqueued'], [])
        self.assertEqual(len(later['readyChunks']), 3)
        reviewer.record(reviewer.progress(1, resumed))
        reviewer.record(reviewer.progress(2, resumed))
        api.complete_task(host.budget.root, 'section-test', original_ref, TaskResult((reviewer.final(),)))
        snapshot = chunk_snapshot(reviewer.task(), resumed)
        self.assertEqual(snapshot['chunkReviews'][0]['receipt'], first)
        self.assertEqual(len(snapshot['chunkReviews']), 3)
        self.assertEqual(host.budget.record()['clips']['A']['counters']['review'], 3)
        self.assertEqual(reviewer.task()['claim']['epoch'], original_ref.epoch)
        self.assertEqual(reviewer.task()['claim']['token'], original_ref.token)
        self.assertFalse((Path(resumed['output']) / 'segment-picture-2-stage.json').exists())

    def test_completed_chunk_and_global_reviews_survive_exact_resume_without_new_tasks(self) -> None:
        """Cold final barrier compares restored current bytes while retaining original review identities."""
        self.case.test_all_current_chunk_and_join_reviews_satisfy_public_assembly_barrier()
        before = assembly_task_snapshot(self.host.request)
        tasks = copy.deepcopy(self.host.budget.record()['production']['tasks'])
        resumed = self.resume((0, 1, 2))
        result = materialize_section_reviews(resumed, 'encoded')
        self.assertEqual(result['enqueued'], [])
        self.assertEqual(assembly_task_snapshot(resumed), before)
        self.assertEqual(self.host.budget.record()['production']['tasks'], tasks)
        self.assertEqual(self.host.budget.record()['clips']['A']['counters']['review'], 4)
        (Path(resumed['output']) / 'segment-picture-0-restored' / 'audio.wav').write_text('TEST corrupt restored PCM')
        with self.assertRaises((ValueError, RuntimeError)):
            assembly_task_snapshot(resumed)


if __name__ == '__main__':
    unittest.main()
