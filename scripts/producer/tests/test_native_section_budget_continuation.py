"""A fully sealed review resume keeps the original deadline without buying a render attempt."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest import mock

from _native_section_budget_fixture import SectionBudgetFixture
from studio import native_budget_continuation as continuation
from studio.native_budget_clock import BudgetExhausted, allocation_remaining
from studio.native_budget_registry import BudgetRefused
from studio.native_budget_binding import charge_request
from studio.native_budget_owner import aac_budget_hook


class ReviewContinuationTests(unittest.TestCase):
    """Durable same-store continuation behavior, with retained-media proof stubs at its boundary."""

    def setUp(self) -> None:
        """Leave a settled render attempt with its spent launch charge intact."""
        self.fixture = SectionBudgetFixture(self)
        record = self.fixture.record()
        attempt = record['clips']['A']['attempts'][0]
        attempt.update(status='failed', completedElapsed=10, failure={
            'category': 'section-review-pending', 'phase': 'picture', 'errorType': None, 'signature': 'pending'})
        self.fixture.raw(record)

    def reserve(self) -> dict:
        """Use the real continuation transaction under its original grant."""
        return continuation._reserve_review(self.fixture.root, self.fixture.request['productionBudget'],
                                             (self.fixture.request, self.fixture.base / 'review-resume'), {})

    def test_review_wait_never_refreshes_grant_or_launch_counters(self) -> None:
        """Waiting to supply independent reviews consumes the original 9000-second allocation."""
        original = copy.deepcopy(self.fixture.record()['clips']['A'])
        self.fixture.elapsed = 500
        budget = self.reserve()
        self.assertIsNone(budget['attemptId'])
        self.assertEqual(budget['continuationOf'], 'a' * 32)
        self.assertEqual(allocation_remaining(budget['allocation']), 8500)
        self.assertEqual(self.fixture.record()['clips']['A'], original)

    def test_expired_review_cannot_receive_fresh_deadline(self) -> None:
        """A saved MP4 does not confer another media allowance."""
        self.fixture.elapsed = 8990
        with self.assertRaises(BudgetExhausted):
            self.reserve()
        self.assertEqual(self.fixture.record()['clips']['A']['counters']['exportAttempt'], 1)

    def test_missing_section_cannot_fall_back_to_rendering(self) -> None:
        """A continuation with a single absent donor refuses all new section launch work."""
        request = {**self.fixture.request, 'productionBudget': self.reserve()}
        with self.assertRaisesRegex(BudgetRefused, 'cannot launch'):
            continuation.require_review_only(request, ['segment-picture-1'])
        continuation.require_review_only(request, [])

    def test_changed_plan_cannot_reuse_review_only_permission(self) -> None:
        """Sealed-plan identity is part of the narrow supporting-work grant."""
        request = {**self.fixture.request, 'productionBudget': self.reserve(),
                   'revision': {'identity': 'd' * 64}}
        with self.assertRaisesRegex(BudgetRefused, 'cannot launch'):
            continuation.require_review_only(request, [])

    def test_complete_keeps_original_failed_attempt_and_records_delivery(self) -> None:
        """Continuation success does not rewrite the original render outcome or its costs."""
        request = {**self.fixture.request, 'productionBudget': self.reserve()}
        continuation.record_review_outcome(request, {'status': 'native-long-checked-for-review',
                                                     'output': '/TEST/review.mp4', 'sha256': 'e' * 64})
        clip = self.fixture.record()['clips']['A']
        self.assertEqual(clip['attempts'][0]['status'], 'failed')
        self.assertEqual(clip['counters']['exportAttempt'], 1)
        self.assertEqual(clip['deliveries'][0]['sha256'], 'e' * 64)

    def test_review_audio_debits_original_attempt_and_enforces_existing_cap(self) -> None:
        """A second resume does not reset the three-candidate per-audio ceiling."""
        budget = self.reserve()
        request = {**self.fixture.request, 'productionBudget': budget, 'output': budget['continuationOutput']}
        hook = aac_budget_hook(request, 'f' * 64, 'TEST')
        for index in range(3):
            hook(index)
        with self.assertRaisesRegex(BudgetRefused, 'candidate limit'):
            hook(4)
        clip = self.fixture.record()['clips']['A']
        self.assertEqual(clip['attempts'][0]['nested']['aacCandidate'], 3)
        self.assertEqual(clip['attempts'][0]['status'], 'failed')
        self.assertEqual(clip['counters']['exportAttempt'], 1)
        self.assertEqual(clip['counters']['aacCandidate'], 3)

    def test_review_audio_wait_exhausts_original_clock_before_charge(self) -> None:
        """An admitted continuation cannot start another AAC candidate after its original deadline."""
        budget = self.reserve()
        request = {**self.fixture.request, 'productionBudget': budget, 'output': budget['continuationOutput']}
        self.fixture.elapsed = 8990
        with self.assertRaises(BudgetExhausted):
            aac_budget_hook(request, 'f' * 64, 'TEST')(1)
        self.assertEqual(self.fixture.record()['clips']['A']['counters']['aacCandidate'], 0)

    def test_review_continuation_cannot_charge_picture_or_another_output(self) -> None:
        """The supporting-work exception remains limited to exact continuation audio."""
        budget = self.reserve()
        request = {**self.fixture.request, 'productionBudget': budget, 'output': budget['continuationOutput']}
        with self.assertRaises(BudgetRefused):
            charge_request(request, 'pictureGeneration')
        with self.assertRaises(BudgetRefused):
            charge_request({**request, 'output': '/TEST/another'}, 'aacCandidate', 'f' * 64)
        self.assertEqual(self.fixture.record()['clips']['A']['counters']['pictureGeneration'], 0)

    def test_checked_continuation_cannot_reserve_or_publish_another_final(self) -> None:
        """A different output path cannot replay one original attempt's checked final delivery."""
        budget = self.reserve()
        request = {**self.fixture.request, 'productionBudget': budget}
        result = {'status': 'native-long-checked-for-review', 'output': '/TEST/first.mp4', 'sha256': 'e' * 64}
        continuation.record_review_outcome(request, result)
        with self.assertRaisesRegex(BudgetRefused, 'already has a checked delivery'):
            self.reserve()
        with self.assertRaisesRegex(BudgetRefused, 'already has a checked delivery'):
            continuation.record_review_outcome(request, {**result, 'output': '/TEST/second.mp4'})
        self.assertEqual(len(self.fixture.record()['clips']['A']['deliveries']), 1)

    def test_exact_committed_result_replay_is_idempotent(self) -> None:
        """The caller may acknowledge an already atomic publication without a second delivery."""
        request = {**self.fixture.request, 'productionBudget': self.reserve()}
        result = {'status': 'native-long-checked-for-review', 'output': '/TEST/first.mp4', 'sha256': 'e' * 64}
        continuation.record_review_outcome(request, result)
        original = self.fixture.record()['clips']['A']
        continuation.record_review_outcome(request, result)
        self.assertEqual(self.fixture.record()['clips']['A'], original)
        with self.assertRaises(BudgetRefused):
            continuation.record_review_outcome(request, {**result, 'sha256': 'f' * 64})

    def test_published_but_unrecorded_delivery_requires_reconciliation(self) -> None:
        """A crash after publishing checked media cannot buy another free final output."""
        request = self.fixture.request
        output = Path(request['output'])
        output.mkdir()
        (output / 'delivery.json').write_text('{"status":"native-long-checked-for-review"}')
        with mock.patch.object(continuation, '_reserve_review') as reserve:
            with self.assertRaisesRegex(BudgetRefused, 'already published'):
                continuation.reserve_section_review(request, Path(request['project']), self.fixture.base / 'next')
        reserve.assert_not_called()

    def test_real_reservation_requires_every_current_window_proof(self) -> None:
        """A broken saved section stops before any continuation or utility grant is created."""
        request = {**self.fixture.request, 'revision': {**self.fixture.request['revision'], 'mode': 'initial-long'}}
        with mock.patch.object(continuation, 'attempt_reservation'), \
                mock.patch.object(continuation, 'require_current_section_attempt'), \
                mock.patch.object(continuation, 'current_window', side_effect=RuntimeError('seal changed')), \
                mock.patch.object(continuation, '_reserve_review') as reserve:
            with self.assertRaisesRegex(RuntimeError, 'seal changed'):
                continuation.reserve_section_review(request, Path(request['project']), self.fixture.base / 'next')
        reserve.assert_not_called()


if __name__ == '__main__':
    unittest.main()
