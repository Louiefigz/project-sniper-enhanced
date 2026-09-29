"""Public changed-generation carry uses real claims/seals; media and editorial passes are fictional."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from _production_chunk_changed_fixture import ChangedChunkFixture
from _production_chunk_fixture import ChunkFixture
from cut_preview_io import write_new
from studio.production import api
from studio.production.callbacks import TaskResult
from studio.production.claims import ClaimRef
from studio.production.section_chunk_dispatch import chunk_snapshot
from studio.production.section_plan import pin_file
from studio.production.section_results import claim_directory, read_completed_result
from studio.production.sections import encoded_spec, materialize_section_reviews
from studio.production.tasks import TaskRefused


class ChunkCarryDispatchTests(unittest.TestCase):
    """A repaired author's unchanged chunks retain original judgments under current task authority."""

    def setUp(self) -> None:
        """Use a real explicit B-author replacement and registered current media, with no real playback."""
        self.fixture = ChangedChunkFixture(self)
        self.fixture.record_original()
        self.original = self.fixture.review.task()
        self.fixture.repair()
        self.host = self.fixture.host

    def dispatch(self) -> dict:
        """Enter the actual public materialization transaction."""
        return materialize_section_reviews(self.host.request, 'encoded')

    def attach(self) -> ChunkFixture:
        """Claim the already-public task without a second fixture-only task or scheduler."""
        h = self.host
        review = ChunkFixture.__new__(ChunkFixture)
        review.host = h
        review.spec = encoded_spec(h.request, h.context['assignments'][0], h.budget.record())
        claim = api.claim_task(h.budget.root, 'section-test', review.spec.task_id, h.handle('director'))
        review.ref = ClaimRef(review.spec.task_id, claim['epoch'], claim['token'])
        api.attach_task(h.budget.root, 'section-test', review.ref, h.handle('TEST-current-reviewer'))
        claim_directory(review.task()).mkdir(parents=True)
        return review

    def final(self, review: ChunkFixture, include_retained: bool = True) -> dict:
        """Explicitly select old judgments separately from this reviewer's new observations."""
        task = review.task()
        scopes = [row['id'] for row in review.scopes()]
        progress, carry = task.get('sectionProgress', {}), task.get('sectionCarry', {})
        value = {'schemaVersion': 1, 'kind': 'native-long-section-result', 'taskId': review.ref.task_id,
                 'epoch': review.ref.epoch, 'token': review.ref.token, 'binding': review.spec.section_binding,
                 'artifacts': [], 'review': {'status': 'pass', 'globalJoins': None,
                    'progress': [progress[key] for key in scopes if key in progress]}}
        if include_retained:
            value['review']['retained'] = [carry[key] for key in scopes if key not in progress and key in carry]
        file = claim_directory(task) / 'result.json'
        write_new(file, value)
        return pin_file(file)

    def test_public_dispatch_and_completion_preserve_original_review_provenance(self) -> None:
        """Only changed B2 and both seams get new reviews; B1/B3 stay attributed to the old reviewer."""
        result = self.dispatch()
        kept = [row for row in result['readyChunks'] if row.get('status') == 'retained-judgment']
        self.assertEqual([row['frameRange'] for row in kept], [[0, 60], [120, 180]])
        self.assertTrue(all(row['originalTaskId'] == self.original['id'] for row in kept))
        review = self.attach()
        before = self.host.budget.record()['clips']['A']['counters'].copy()
        for index in (1, 3, 4):
            review.record(review.progress(index))
        pin = self.final(review)
        api.complete_task(self.host.budget.root, 'section-test', review.ref, TaskResult((pin,)))
        task = review.task()
        self.assertEqual(task['state'], 'completed')
        snapshot = chunk_snapshot(task, self.host.request)
        retained = [row for row in snapshot['chunkReviews'] if 'retainedJudgment' in row]
        self.assertEqual(len(retained), 2)
        self.assertTrue(all(row['receipt'] == self.original['sectionProgress'][row['scopeId']] for row in retained))
        self.assertEqual(self.host.budget.record()['clips']['A']['counters'], before)
        read_completed_result(self.host.budget.record(), task['id'], task['sectionBinding'])

    def test_replay_does_not_rewrite_carry_or_add_a_reviewer(self) -> None:
        """The same task and immutable carry survive discovery retries without a new charge."""
        first = self.dispatch()
        before = self.host.budget.record()
        repeated = self.dispatch()
        self.assertFalse(repeated['committed'])
        self.assertEqual(repeated['readyChunks'], first['readyChunks'])
        self.assertEqual(self.host.budget.record()['production']['tasks'], before['production']['tasks'])
        self.assertEqual(self.host.budget.record()['clips']['A']['counters'], before['clips']['A']['counters'])

    def test_completion_must_explicitly_select_retained_judgments(self) -> None:
        """Presence of carry in state alone is not the current reviewer's final inventory."""
        self.dispatch()
        review = self.attach()
        for index in (1, 3, 4):
            review.record(review.progress(index))
        with self.assertRaisesRegex(ValueError, 'explicitly select'):
            api.complete_task(self.host.budget.root, 'section-test', review.ref,
                              TaskResult((self.final(review, False),)))
        self.assertEqual(review.task()['state'], 'running')

    def test_withdrawn_carry_requires_fresh_review_and_can_be_overridden(self) -> None:
        """Explicit old-judgment withdrawal never blocks new independent progress on that scope."""
        self.dispatch()
        review = self.attach()
        api.supersede_task(self.host.budget.root, 'section-test', self.original['id'], 'TEST withdraw old judgment')
        ready = self.dispatch()['readyChunks']
        self.assertFalse(any(row.get('status') == 'retained-judgment' for row in ready))
        self.assertEqual(len(review.task()['sectionCarry']), 2)
        for index in range(5):
            review.record(review.progress(index))
        api.complete_task(self.host.budget.root, 'section-test', review.ref, TaskResult((self.final(review),)))
        self.assertEqual(review.task()['state'], 'completed')
        self.assertFalse(any('retainedJudgment' in row for row in chunk_snapshot(review.task())['chunkReviews']))

    def test_withdrawal_after_completion_blocks_assembly_read(self) -> None:
        """A former pass cannot hide the now-withdrawn historical judgment from the current barrier."""
        self.dispatch()
        review = self.attach()
        for index in (1, 3, 4):
            review.record(review.progress(index))
        api.complete_task(self.host.budget.root, 'section-test', review.ref, TaskResult((self.final(review),)))
        api.supersede_task(self.host.budget.root, 'section-test', self.original['id'], 'TEST later withdrawal')
        task = review.task()
        with self.assertRaisesRegex(ValueError, 'no longer authorized'):
            read_completed_result(self.host.budget.record(), task['id'], task['sectionBinding'])
        from studio.production.section_judgments import read_interior_result
        with self.assertRaisesRegex(ValueError, 'no longer authorized'):
            read_interior_result(self.host.budget.record(), task['id'])

    def test_proof_cost_cannot_extend_original_grant(self) -> None:
        """The public enqueue rechecks elapsed time after the expensive carry proof work."""
        from studio.production.section_chunk_carry import planned_carry
        before = set(self.host.budget.record()['production']['tasks'])
        def expensive(record: dict, request: dict, row: dict, spec: object) -> dict:
            """Advance the actual fixture clock only after real proof generation."""
            result = planned_carry(record, request, row, spec)
            self.host.budget.elapsed = 9001
            return result
        with patch('studio.production.section_review_materialize.planned_carry', side_effect=expensive):
            with self.assertRaises(TaskRefused):
                self.dispatch()
        self.assertEqual(set(self.host.budget.record()['production']['tasks']), before)


if __name__ == '__main__':
    unittest.main()
