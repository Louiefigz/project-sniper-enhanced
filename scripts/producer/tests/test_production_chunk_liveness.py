"""Last-slot claim admission over real frozen chunk inputs; no new scheduler or releases."""
from __future__ import annotations

import copy
from dataclasses import replace
import unittest
from pathlib import Path
from unittest.mock import patch

from _production_chunk_fixture import ChunkFixture
from studio.production.claims import claim
from studio.production import api
from studio.production.tasks import TaskRefused, TaskSpec, active_ai


class ChunkReviewerLivenessTests(unittest.TestCase):
    """Use actual cold review-plan readers while varying in-memory claim-admission scenarios."""

    def setUp(self) -> None:
        """Start from registered current authors/early reviews, resetting only the unit-test candidate claim."""
        self.fixture = ChunkFixture(self)
        self.host = self.fixture.host
        self.record = self.host.budget.record()
        self.task = self.record['production']['tasks'][self.fixture.ref.task_id]
        self.task.update(state='ready', claim=None, handle=None, charged=False, epochs=0)
        self.record['production']['ai']['charged'] -= 1
        self.record['clips']['A']['counters']['review'] -= 1
        self.record['production']['ai']['slots'] = active_ai(self.record) + 1
        self.last = self.host.context['assignments'][-1]

    def pending(self, task_id: str) -> dict:
        """Model an exact current prerequisite awaiting an execution in the private scenario record."""
        task = self.record['production']['tasks'][task_id]
        task.update(state='ready', claim=None, handle=None, terminalElapsed=None, receipts=[], reason=None)
        return task

    def claim_review(self) -> object:
        """Call the actual common claim mutation, where refusal precedes charging."""
        return claim(self.record, self.task['id'], self.host.handle('director'), self.host.budget.elapsed)

    def test_last_slot_stays_available_for_current_unfinished_author(self) -> None:
        """Refusal leaves both existing author and review counters/deadline/claim untouched."""
        author = self.pending(self.last['authorTaskId'])
        before = copy.deepcopy(self.record)
        with self.assertRaisesRegex(TaskRefused, 'leave an AI slot'):
            self.claim_review()
        self.assertEqual(before, self.record)
        result = claim(self.record, author['id'], self.host.handle('director'), self.host.budget.elapsed)
        self.assertEqual(result.detail['taskId'], author['id'])
        self.assertEqual(author['state'], 'claimed')

    def test_spare_slot_allows_incremental_review_and_then_author(self) -> None:
        """The ordinary four-slot policy can admit overlap while retaining room for required authors."""
        author = self.pending(self.last['authorTaskId'])
        self.record['production']['ai']['slots'] += 1
        charged = self.record['production']['ai']['charged']
        self.claim_review()
        claim(self.record, author['id'], self.host.handle('director'), self.host.budget.elapsed)
        self.assertEqual((self.task['state'], author['state']), ('claimed', 'claimed'))
        self.assertEqual(self.record['production']['ai']['charged'], charged + 1)

    def test_obsolete_unclaimed_authors_do_not_reserve_phantom_capacity(self) -> None:
        """Only exact current frozen assignments count, even with earlier fixture plans still queued."""
        current = {row['authorTaskId'] for row in self.host.context['assignments']}
        obsolete = [task for task in self.record['production']['tasks'].values()
                    if task['kind'] == 'author' and task['id'] not in current]
        self.assertTrue(obsolete)
        self.assertTrue(all(task['state'] == 'ready' for task in obsolete))
        self.claim_review()
        self.assertEqual(self.task['state'], 'claimed')

    def test_current_early_review_also_needs_progress_capacity(self) -> None:
        """A complete author alone cannot free the last slot if its required early reviewer is waiting."""
        early = next(task for task in self.record['production']['tasks'].values()
                     if task.get('sectionBinding', {}).get('role') == 'early-review'
                     and task['sectionBinding']['authorTaskId'] == self.last['authorTaskId'])
        self.pending(early['id'])
        with self.assertRaisesRegex(TaskRefused, 'early review'):
            self.claim_review()

    def test_running_author_can_finish_and_free_its_existing_slot(self) -> None:
        """The guard does not invent another author reservation when required work already executes."""
        author = self.pending(self.last['authorTaskId'])
        author.update(state='running', handle=self.host.handle('TEST-live-author'))
        self.record['production']['ai']['slots'] = active_ai(self.record) + 1
        self.claim_review()
        self.assertEqual(self.task['state'], 'claimed')

    def test_corrupt_completed_early_evidence_does_not_count_as_progress(self) -> None:
        """Cold evidence refusal cannot silently turn an old completed label into current readiness."""
        early = next(task for task in self.record['production']['tasks'].values()
                     if task.get('sectionBinding', {}).get('role') == 'early-review'
                     and task['sectionBinding']['authorTaskId'] == self.last['authorTaskId'])
        Path(early['receipts'][0]['path']).write_text('TEST corrupt retained early evidence')
        before = copy.deepcopy(self.record)
        with self.assertRaises((ValueError, RuntimeError)):
            self.claim_review()
        self.assertEqual(self.record, before)

    def test_locked_public_claim_rechecks_original_deadline_after_cold_proof(self) -> None:
        """Hashing cannot lend time past the original deadline or charge a reviewer after expiry."""
        from studio.production.section_chunk_liveness import reviewer_liveness_refusal
        spec = replace(self.fixture.spec, task_id='TEST-late-chunk-review')
        other = TaskSpec('TEST-other-work', 'section-test', 'planning', 'v1', 'c' * 64, 9000,
                         parent='director')
        api.enqueue_tasks(self.host.budget.root, 'section-test', (spec, other))
        api.claim_task(self.host.budget.root, 'section-test', other.task_id, self.host.handle('director'))
        before = self.host.budget.record()

        def proof_then_expire(record: dict, task: dict) -> str | None:
            """Run actual pinned cold readers before advancing only the isolated original clock."""
            result = reviewer_liveness_refusal(record, task)
            self.assertIsNone(result)
            self.host.budget.elapsed = 9001
            return result

        with patch('studio.production.section_chunk_liveness.reviewer_liveness_refusal',
                   side_effect=proof_then_expire) as proof:
            with self.assertRaisesRegex(TaskRefused, 'deadline'):
                api.claim_task(self.host.budget.root, 'section-test', spec.task_id, self.host.handle('director'))
        after = self.host.budget.record()
        self.assertEqual(proof.call_count, 1)
        self.assertEqual(after['production']['ai']['charged'], before['production']['ai']['charged'])
        self.assertEqual(after['clips']['A']['counters'], before['clips']['A']['counters'])
        self.assertEqual(after['production']['tasks'][spec.task_id]['state'], 'failed')
        self.assertEqual(after['production']['tasks'][spec.task_id]['epochs'], 0)


if __name__ == '__main__':
    unittest.main()
