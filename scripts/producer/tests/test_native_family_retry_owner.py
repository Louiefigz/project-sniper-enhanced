"""One real family reservation retry debit reaches its exact technical owner once."""
from __future__ import annotations

import unittest

import test_native_budget_family_admission as fixtures
from studio.native_budget_family import record_family_outcome
from studio.native_budget_registry import BudgetRefused
from studio.native_budget_sections import SectionBudgetOwner


class FamilyRetryOwnerTests(unittest.TestCase):
    """Use the existing private real authority without launching any media subprocess."""

    def setUp(self) -> None:
        """Prepare registered authors and an isolated original Long clock."""
        self.h = fixtures.FamilyAdmissionTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def test_family_retry_owner_does_not_spend_second_retry(self) -> None:
        """A precharged invocation retries its matching failed picture owner, then stops."""
        first = self.h.reserve('first', False)
        owner = SectionBudgetOwner(first, 'segment-picture-0')
        owner.before_launch()
        failure = {'status': 'failed', 'failureCategory': 'host-memory-pressure'}
        owner.complete(failure)
        record_family_outcome(first, failure)
        retry = self.h.reserve('first', False)
        self.assertEqual(self.h.h.budget.record()['clips']['A']['counters']['transientRetry'], 1)
        repeated = SectionBudgetOwner(retry, 'segment-picture-0')
        repeated.before_launch()
        clip = self.h.h.budget.record()['clips']['A']
        self.assertEqual(clip['counters']['transientRetry'], 1)
        self.assertEqual(clip['counters']['pictureGeneration'], 1)
        self.assertEqual(clip['sectionOwners'][-1]['retryOf'], owner.identity)
        repeated.complete(failure)
        with self.assertRaisesRegex(BudgetRefused, 'already used'):
            SectionBudgetOwner(retry, 'segment-picture-0').before_launch()


if __name__ == '__main__':
    unittest.main()
