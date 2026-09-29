"""Independent cross-continuation AAC limits; no actual media generation or playback."""
from __future__ import annotations

import unittest

import test_native_section_budget_continuation as continuation_fixture
from studio.native_budget_binding import charge_request
from studio.native_budget_clock import BudgetExhausted
from studio.native_budget_owner import aac_budget_hook
from studio.native_budget_registry import BudgetRefused


class ReviewBudgetAcceptanceTests(unittest.TestCase):
    """Multiple review resumes share original durable debits and the original clock."""

    def setUp(self) -> None:
        """Use the existing isolated real budget authority, not account production state."""
        self.case = continuation_fixture.ReviewContinuationTests('test_review_wait_never_refreshes_grant_or_launch_counters')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.fixture = self.case.fixture

    def request(self) -> dict:
        """Reserve another review continuation against the same settled original attempt."""
        budget = self.case.reserve()
        return {**self.fixture.request, 'productionBudget': budget, 'output': budget['continuationOutput']}

    def test_second_continuation_cannot_reset_same_audio_candidate_count(self) -> None:
        """Two earlier candidates leave exactly one, even after a fresh review reservation."""
        first = aac_budget_hook(self.request(), 'a' * 64, 'TEST-profile')
        first(1)
        first(2)
        self.fixture.elapsed = 200
        second = aac_budget_hook(self.request(), 'a' * 64, 'TEST-profile')
        second(1)
        with self.assertRaisesRegex(BudgetRefused, 'candidate limit'):
            second(2)
        clip = self.fixture.record()['clips']['A']
        self.assertEqual(clip['counters']['aacCandidate'], 3)
        self.assertEqual(clip['counters']['exportAttempt'], 1)
        self.assertEqual(clip['attempts'][0]['nested']['aacCandidate'], 3)
        self.assertEqual(clip['attempts'][0]['status'], 'failed')

    def test_expired_second_continuation_does_not_refund_spent_candidate(self) -> None:
        """A waiting reviewer cannot create another allowance or undo work already charged."""
        aac_budget_hook(self.request(), 'a' * 64, 'TEST-profile')(1)
        self.fixture.elapsed = 8990
        with self.assertRaises(BudgetExhausted):
            self.request()
        self.assertEqual(self.fixture.record()['clips']['A']['counters']['aacCandidate'], 1)

    def test_picture_refused_after_fresh_review_reservation_without_debit(self) -> None:
        """Repeated reservations preserve the audio-only supporting-work exception."""
        self.request()
        request = self.request()
        with self.assertRaisesRegex(BudgetRefused, 'only bound final audio'):
            charge_request(request, 'pictureGeneration')
        self.assertEqual(self.fixture.record()['clips']['A']['counters']['pictureGeneration'], 0)
