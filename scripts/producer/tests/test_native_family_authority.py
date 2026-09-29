"""Logical waiting preserves actual child liveness, clocks and terminal record room."""
from __future__ import annotations

import copy
import unittest
from unittest import mock

from _native_section_budget_fixture import SectionBudgetFixture, SUPERVISOR
from studio.native_budget_family_schema import family_problem
from studio.native_budget_family_state import active_family_attempts, require_phase
from studio.native_budget_forecast import attempt_forecast, route_seconds
from studio.native_budget_launch import reconcile_running
from studio.native_budget_registry import BudgetRefused
from studio.native_budget_schema import SCHEMA_VERSION, validate_record
from studio.native_budget_store import BudgetAuthorityError
from studio.production.formats import clip_rates
from studio.production.settlement import _family_room, encoded, WIDEST_OUTCOME


class FamilyAuthorityTests(unittest.TestCase):
    """Use private real records; no live budget, renderer or provider is touched."""

    def setUp(self) -> None:
        """Create a frozen three-section family under the already charged launch."""
        self.fixture = SectionBudgetFixture(self)
        self.record = self.fixture.record()
        self.clip = self.record['clips']['A']
        pin = {'path': '/TEST/plan.json', 'sha256': 'c' * 64, 'bytes': 1}
        assignments = [{'sectionId': key, 'authorTaskId': f'author-{key}', 'generation': 1,
                        'inputIdentity': 'e' * 64, 'frameRange': [i * 600, (i + 1) * 600]}
                       for i, key in enumerate(('A', 'B', 'C'))]
        inventory = [{'sectionId': row['sectionId'], 'frameRange': row['frameRange'],
                      'windows': [row['frameRange']]} for row in assignments]
        inventory.append({'sectionId': None, 'frameRange': [0, 1800], 'windows': [[540, 660], [1140, 1260]]})
        self.family = {'id': 'a' * 32, 'plan': pin, 'sharedPlan': pin, 'assignments': assignments,
                       'previewInventory': inventory, 'state': 'awaiting-sections', 'invocations': []}
        self.clip['sectionFamilies'] = [self.family]

    def invocation(self) -> dict:
        """One live child with immutable paths and no invented successful outcome."""
        row = {'id': 'b' * 32, 'sectionId': 'A', 'project': '/TEST/project', 'output': '/TEST/output',
               'planSha256': 'e' * 64, 'scopeSha256': 'f' * 64, 'requestSha256': None,
               'supervisor': SUPERVISOR, 'status': 'running', 'admittedElapsed': 10,
               'completedElapsed': None, 'resultStatus': None, 'resultIdentity': None, 'failure': None}
        self.family['invocations'].append(row)
        return row

    def test_schema_six_lift_preserves_every_other_field(self) -> None:
        """The additive lift cannot reopen counters or restart a clock."""
        del self.clip['sectionFamilies']
        self.record['schemaVersion'] = 6
        self.fixture.raw(self.record)
        expected = {**copy.deepcopy(self.record), 'schemaVersion': SCHEMA_VERSION}
        self.assertEqual(self.fixture.record(), expected)

    def test_old_versions_cannot_smuggle_families(self) -> None:
        """Closed old-schema validation precedes any reader upgrade."""
        for version in (5, 6):
            self.record['schemaVersion'] = version
            self.fixture.raw(self.record)
            with self.assertRaises(BudgetAuthorityError):
                self.fixture.record()

    def test_gap_and_duplicate_preview_windows_are_refused(self) -> None:
        """Two-program forecast bound depends on exact contiguous disjoint membership."""
        validate_record(self.record)
        self.family['assignments'][1]['frameRange'][0] += 1
        self.assertIsNotNone(family_problem(self.record))
        self.family['assignments'][1]['frameRange'][0] -= 1
        self.family['previewInventory'][0]['windows'] *= 2
        self.assertIsNotNone(family_problem(self.record))

    def test_awaiting_author_is_not_an_abandoned_supervisor(self) -> None:
        """A logical launch has no fake live process while waiting for the next ready section."""
        with mock.patch('studio.native_budget_launch._process_table', return_value={}):
            self.assertEqual(reconcile_running(self.record, 100), [])
        self.assertEqual(self.clip['attempts'][0]['status'], 'running')
        self.assertEqual(self.clip['counters']['exportAttempt'], 1)

    def test_late_join_inventory_cannot_be_removed(self) -> None:
        """Every multi-section preview family reserves its actual final boundary member."""
        self.family['previewInventory'].pop()
        self.assertIsNotNone(family_problem(self.record))

    def test_scoped_capability_cannot_verify_full_delivery(self) -> None:
        """No scoped family token admits complete-program stages even before worker checks."""
        row = self.invocation()
        request = {'productionBudget': {'route': 'final'}}
        for phase in ('picture', 'render', 'verify'):
            with self.assertRaises(BudgetRefused):
                require_phase(self.family, row, request, phase)

    def test_dead_child_is_charged_but_does_not_erase_siblings(self) -> None:
        """Actual invocation liveness is observed separately from future membership."""
        row = self.invocation()
        with mock.patch('studio.native_budget_family_state._process_table', return_value={}):
            self.assertEqual(active_family_attempts(self.record, 100), {'a' * 32})
        self.assertEqual(row['status'], 'abandoned')
        self.assertEqual(self.family['state'], 'awaiting-sections')
        validate_record(self.record)

    def test_waiting_cannot_extend_original_deadline(self) -> None:
        """No child can keep a logical launch open past the original allocation."""
        self.assertEqual(active_family_attempts(self.record, 9000), set())
        self.assertEqual(self.family['state'], 'failed')
        self.assertEqual(self.clip['attempts'][0]['status'], 'abandoned')
        validate_record(self.record)

    def test_family_forecast_counts_join_repeats_and_four_startups(self) -> None:
        """Queued replay and initial admission retain identical grouped demand."""
        attempt = self.clip['attempts'][0]
        attempt['route'] = 'preview'
        rates = clip_rates(self.record, self.clip)
        expected = route_seconds(rates, 'preview', 60, (68, 4))
        self.assertEqual(attempt_forecast(self.record, self.clip, attempt), expected)
        self.assertGreater(expected, route_seconds(rates, 'preview', 60, 60))
        with self.assertRaises(ValueError):
            route_seconds(rates, 'preview', 60, 68)

    def test_terminal_room_includes_widest_child_growth(self) -> None:
        """An already admitted child can retain the maximum bounded failure outcome."""
        row = self.invocation()
        widest = {**row, 'status': 'abandoned', 'completedElapsed': 100.12345678901234,
                  'resultStatus': 'r' * 128, 'resultIdentity': 'e' * 64, 'requestSha256': 'f' * 64,
                  'failure': WIDEST_OUTCOME['failure']}
        self.assertGreaterEqual(_family_room(self.family), encoded(widest) - encoded(row))

    def test_final_integration_cannot_launch_missing_pictures_or_previews(self) -> None:
        """Joining donors is allowed; incomplete media never buys a free render."""
        row = self.invocation()
        row['sectionId'] = None
        request = {'productionBudget': {'route': 'final'}, 'revision': {
            'renderWindows': [{'startFrame': 0, 'endFrame': 600}], 'windowDonors': {}}}
        for phase in ('segment-picture-0', 'preview-picture-0', 'preview-package-0'):
            with self.assertRaises(BudgetRefused):
                require_phase(self.family, row, request, phase)
        request['revision']['windowDonors']['segment-picture-0'] = '/TEST/seal.json'
        for phase in ('segment-picture-0', 'capture', 'preview', 'picture', 'render', 'verify'):
            require_phase(self.family, row, request, phase)


if __name__ == '__main__':
    unittest.main()
