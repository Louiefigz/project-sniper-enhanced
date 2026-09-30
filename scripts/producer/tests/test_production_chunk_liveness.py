"""Last-slot claim admission over real frozen chunk inputs; no new scheduler or releases."""
from __future__ import annotations

import copy
from dataclasses import replace
import unittest
from pathlib import Path
from unittest.mock import patch

from _production_chunk_fixture import ChunkFixture
from studio.production import section_chunk_liveness as liveness
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
        task.update(state='ready', claim=None, handle=None, terminalElapsed=None, receipts=[], reason=None,
                    unresolved=False, endConfirmed=False)
        # Its codex completion held a slot (G9: no host end evidence before M-102); rewinding it frees that
        # slot, so the ceiling is pinned again to make the reviewer's claim the last slot.
        self.record['production']['ai']['slots'] = active_ai(self.record) + 1
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
        """The ordinary four-slot policy can admit overlap while retaining room for required authors. G9 row (X125):
        a section not yet authored needs two slots (its author's and its early review's), so one spare slot is not
        enough for the reviewer; two are."""
        author = self.pending(self.last['authorTaskId'])
        self.record['production']['ai']['slots'] += 1
        with self.assertRaisesRegex(TaskRefused, r'\(2 free, 0 reserved .* 1 section\(s\) not yet authored'):
            self.claim_review()
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

    def early_of(self, author_id: str) -> dict:
        """The fixture's early-review task of one author."""
        return next(task for task in self.record['production']['tasks'].values()
                    if task.get('sectionBinding', {}).get('role') == 'early-review'
                    and task['sectionBinding']['authorTaskId'] == author_id)

    def test_a_running_host_turn_author_keeps_a_slot_for_its_early_review(self) -> None:
        """G9 (was: the running author can finish and free its existing slot): a host turn's end keeps its slot
        until host end evidence exists (none before M-102), so the last slot stays reserved for its early review."""
        author = self.pending(self.last['authorTaskId'])
        self.pending(self.early_of(author['id'])['id'])   # this generation's early review waits for the author
        author.update(state='running', handle=self.host.handle('TEST-live-author'))
        self.record['production']['ai']['slots'] = active_ai(self.record) + 1
        before = copy.deepcopy(self.record)
        with self.assertRaisesRegex(TaskRefused, 'leave an AI slot'):
            self.claim_review()
        self.assertEqual(before, self.record)

    def test_the_early_review_is_admitted_after_the_authors_g9_completion(self) -> None:
        """The slot the refused reviewer left is the one the early review takes after the author's turn completes."""
        author = self.pending(self.last['authorTaskId'])
        early = self.pending(self.early_of(author['id'])['id'])
        author.update(state='running', handle=self.host.handle('TEST-live-author'))
        self.record['production']['ai']['slots'] = active_ai(self.record) + 1
        with self.assertRaisesRegex(TaskRefused, 'leave an AI slot'):
            self.claim_review()
        # The author's host turn completes; under G9 it keeps its slot (unresolved) instead of freeing it.
        author.update(state='completed', unresolved=True, endConfirmed=True, terminalElapsed=self.host.budget.elapsed)
        claimed = claim(self.record, early['id'], self.host.handle('director'), self.host.budget.elapsed)
        self.assertEqual((claimed.detail['taskId'], early['state']), (early['id'], 'claimed'))

    def two_rows(self) -> tuple[dict, dict, dict, dict, list[dict]]:
        """The last row's author and early review waiting, and a TEST copy of both as a second current row."""
        tasks = self.record['production']['tasks']
        author = self.pending(self.last['authorTaskId'])
        early = self.pending(self.early_of(author['id'])['id'])
        second = {**copy.deepcopy(author), 'id': 'TEST-second-author'}
        second_early = {**copy.deepcopy(early), 'id': 'TEST-second-early'}
        second_early['sectionBinding'].update(authorTaskId=second['id'], sectionId='TEST-mid')
        tasks.update({second['id']: second, second_early['id']: second_early})
        rows = [*self.host.context['assignments'], {**self.last, 'sectionId': 'TEST-mid', 'authorTaskId': second['id']}]
        for task, name in ((author, 'TEST-live-author'), (second, 'TEST-live-second')):
            task.update(state='running', handle=self.host.handle(name))
        self.record['production']['ai']['slots'] = active_ai(self.record) + 2
        return author, early, second, second_early, rows

    def test_two_running_host_turn_authors_reserve_two_slots(self) -> None:
        """X125 N2 (the delta review's probe): two current authors run on codex turns with two slots free. The
        chunk reviewer waits; both authors complete holding their slots, and both early reviews are admitted."""
        author, early, second, second_early, rows = self.two_rows()
        with patch.object(liveness, '_current_rows', return_value=[(row, None) for row in rows]):
            with self.assertRaisesRegex(TaskRefused, r'^Chunk reviewer .*\(2 free, 2 reserved'):
                self.claim_review()
            for task in (author, second):
                task.update(state='completed', unresolved=True, endConfirmed=True,
                            terminalElapsed=self.host.budget.elapsed)
            for task in (early, second_early):
                claim(self.record, task['id'], self.host.handle('director'), self.host.budget.elapsed)
        self.assertEqual((early['state'], second_early['state'], self.task['state']), ('claimed', 'claimed', 'ready'))
        self.assertEqual(active_ai(self.record), self.record['production']['ai']['slots'])

    def test_no_pending_row_reserves_nothing(self) -> None:
        """X125: with every current row's early review done, nothing is reserved and the last slot is claimable."""
        self.assertEqual(active_ai(self.record) + 1, self.record['production']['ai']['slots'])
        self.claim_review()
        self.assertEqual(self.task['state'], 'claimed')

    def test_an_author_whose_end_frees_its_slot_reserves_nothing(self) -> None:
        """X125: only an author whose end keeps its slot reserves one. When one of two running authors has an end
        proof that releases its slot (host end evidence, from M-102), the reservation drops to one."""
        _author, _early, second, _second_early, rows = self.two_rows()
        real = liveness.end_proof

        def proof(task: dict, cause: str) -> object:
            """The real proof, released for the second author only."""
            found = real(task, cause)
            return replace(found, slot_released=True) if task['id'] == second['id'] else found

        other = {'id': 'TEST-other-work', 'clipId': 'A', 'sectionBinding': {}}
        with patch.object(liveness, '_current_rows', return_value=[(row, None) for row in rows]), \
                patch.object(liveness, 'end_proof', side_effect=proof):
            self.claim_review()
            refusal = liveness.reviewer_liveness_refusal(self.record, other)
        self.assertEqual(self.task['state'], 'claimed')
        self.assertIn('(1 free, 1 reserved', refusal)

    def test_an_author_waits_for_room_for_its_own_early_review(self) -> None:
        """X125: where the Long's rows are known, a current row's author starts only while the reserved slots and
        its own early review still fit after it; with one free slot it waits, with two it is admitted."""
        author = self.pending(self.last['authorTaskId'])
        rows = [(row, None) for row in self.host.context['assignments']]
        with patch.object(liveness, '_current_rows', return_value=rows):
            before = copy.deepcopy(self.record)
            with self.assertRaisesRegex(TaskRefused, r'^Section author .* 0 free slot\(s\) must still hold 1 early'):
                claim(self.record, author['id'], self.host.handle('director'), self.host.budget.elapsed)
            self.assertEqual(before, self.record)
            self.record['production']['ai']['slots'] += 1
            claim(self.record, author['id'], self.host.handle('director'), self.host.budget.elapsed)
        self.assertEqual(author['state'], 'claimed')

    def test_current_rows_come_from_the_claims_long_clip_only(self) -> None:
        """X125: work of a Long clip with a recorded section family, or run-scoped work, meets that clip's rows; a
        Short's work and a handed-off Long's rows are never read."""
        record = {'clips': {'L': {'state': 'active', 'sectionFamilies': [{}]}, 'S': {'state': 'active'},
                            'H': {'state': 'handed-off', 'sectionFamilies': [{}]}}}
        row = {'authorTaskId': 'TEST-author', 'sectionId': 's1'}
        with patch.object(liveness, '_family_context', return_value={'assignments': [row]}) as family:
            found = {clip: liveness._current_rows(record, {'id': 'TEST-work', 'clipId': clip, 'sectionBinding': {}})
                     for clip in ('L', 'S', None)}
        self.assertEqual(found, {'L': [(row, None)], 'S': [], None: [(row, None)]})
        self.assertEqual([call.args[1] for call in family.call_args_list], ['L', 'L'])

    def test_an_ended_author_still_holding_its_slot_reserves_nothing(self) -> None:
        """X125 N5, X168 P2-M1: an author that failed or was cancelled on a host turn still holds its own slot (G9,
        already counted as active), and its early review can never bind (a review binds to its author's completed
        result), so its row reserves nothing: the last slot is claimable."""
        author = self.pending(self.last['authorTaskId'])
        self.pending(self.early_of(author['id'])['id'])
        author.update(handle=self.host.handle('TEST-ended-author'), unresolved=True, endConfirmed=True,
                      terminalElapsed=self.host.budget.elapsed)
        for state in ('failed', 'cancelled'):
            author.update(state=state, failure={'category': 'host-failure', 'detail': 'TEST'} if state == 'failed'
                          else None)
            self.record['production']['ai']['slots'] = active_ai(self.record) + 1   # the ended author holds one
            with self.subTest(state):
                self.assertIsNone(liveness.reviewer_liveness_refusal(self.record, self.task))
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
