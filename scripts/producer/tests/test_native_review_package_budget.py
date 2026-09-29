"""Real family store transactions for bounded review members; media identity is synthetic."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import test_native_budget_family_admission as family_fixture
from studio.native_budget_clock import BudgetExhausted
from studio.native_budget_family import verify_family_request
from studio.native_budget_registry import BudgetRefused
from studio.native_budget_sections import SectionBudgetOwner
from studio.native_segments.review_media import STATUS
from studio.native_segments.review_scopes import phase_for


class ReviewPackageBudgetTests(unittest.TestCase):
    """Exercise real original grants and durable counters without fake editorial approvals."""

    def setUp(self) -> None:
        """Reuse the isolated enrolled family; mock only the separate codec/scope fixture boundary."""
        self.h = family_fixture.FamilyAdmissionTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.request = self.h.reserve('first', False)
        self.request['sectionChunks'] = {'TEST': 'scope exercised separately by actual cold contract tests'}
        (Path(self.request['output']) / 'export-request.json').write_text(json.dumps(self.request))
        self.phase = phase_for('TEST chunk')
        self.enterContext(patch('studio.native_segments.review_scopes.phase_scope', return_value={'sectionIds': ['first']}))
        self.enterContext(patch('studio.native_segments.review_budget.phase_scope', return_value={'sectionIds': ['first']}))
        self.enterContext(patch('studio.native_segments.review_budget.package_identity', return_value='d' * 64))

    def owner(self) -> SectionBudgetOwner:
        """Use the real nonpicture launch and settlement callbacks."""
        return SectionBudgetOwner(self.request, self.phase, (f'{self.phase}.json', STATUS))

    def test_saved_package_forbids_second_encode_without_new_launch_or_picture_charge(self) -> None:
        """Member work is durable and bounded independently of final-delivery AAC candidates."""
        owner = self.owner()
        owner.before_launch()
        owner.complete({'status': STATUS})
        with self.assertRaisesRegex(BudgetRefused, 'no second AAC'):
            self.owner().before_launch()
        clip = self.h.h.budget.record()['clips']['A']
        self.assertEqual(len(clip['sectionOwners']), 1)
        self.assertEqual([clip['counters'][name] for name in ('exportAttempt', 'pictureGeneration', 'aacCandidate')], [1, 0, 0])

    def test_package_transient_failure_uses_only_original_one_retry(self) -> None:
        """A new owner object never refreshes the shared retry ceiling."""
        for _ in range(2):
            owner = self.owner()
            owner.before_launch()
            owner.complete({'status': 'failed', 'failureCategory': 'host-memory-pressure'})
        with self.assertRaisesRegex(BudgetRefused, 'transient-failure retry'):
            self.owner().before_launch()
        self.assertEqual(self.h.h.budget.record()['clips']['A']['counters']['transientRetry'], 1)

    def test_actual_family_proof_crossing_deadline_cannot_debit(self) -> None:
        """Complete the real family proof, then expire the original clock before final charge."""
        def expire(record: dict, request: dict, phase: str) -> tuple:
            """The source/assignment read consumes the remaining real test clock."""
            value = verify_family_request(record, request, phase)
            self.h.h.budget.elapsed = 9999
            return value

        with patch('studio.native_budget_family.verify_family_request', side_effect=expire):
            with self.assertRaises(BudgetExhausted):
                self.owner().before_launch()
        clip = self.h.h.budget.record()['clips']['A']
        self.assertEqual(clip.get('sectionOwners'), [])
        self.assertEqual(clip['counters']['pictureGeneration'], 0)
