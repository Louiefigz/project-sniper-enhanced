"""Long family service arithmetic: no real catalog adoption or authority mutation."""
from __future__ import annotations

import copy
import unittest

import test_native_review_service as fixtures
from native_work_service_rates import RateCatalog
from studio.native_segments.review_forecast import package_seconds, project_work
from studio.native_segments.review_service_family import family_service, selected_remaining


def fresh_state() -> dict:
    """Explicit TEST cold-reader output; it is not a production completion API."""
    return {'members': {}, 'packages': set(), 'progress': set(), 'carry': set(),
            'completedSections': set(), 'additionalDemand': [], 'hasMedia': False,
            'actual': {}, 'actualReads': {}, 'complete': False}


class FamilyServiceTests(unittest.TestCase):
    """Exercise exact frozen geometry and the unchanged conservative route arithmetic."""

    def setUp(self) -> None:
        """Reuse actual authored geometry; rate cells remain unmistakably synthetic."""
        self.fixture = fixtures.ReviewServiceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.evidence = self.fixture.plan()
        self.state = fresh_state()
        self.sections = sorted({row['sectionIds'][0] for row in self.evidence['scopes']
                                if len(row['sectionIds']) == 1})

    def test_initial_partition_equals_existing_frozen_normal_inventory(self) -> None:
        """All members sum once; integrated local-scope cold reads are not lost."""
        whole = selected_remaining(self.evidence, self.state)
        expected = {row['key']: row['calls'] for row in self.evidence['readPlan']['calls']}
        self.assertEqual(whole['calls'], expected)
        members = [selected_remaining(self.evidence, self.state, key) for key in [*self.sections, None]]
        self.assertEqual({key: sum(row['calls'][key] for row in members) for key in expected}, expected)
        final = selected_remaining(self.evidence, self.state, None)
        self.assertTrue(all(final['calls'][row['key']] > 0 for row in self.evidence['readPlan']['calls']
                            if row['site'] == 'publication'))

    def test_missing_catalog_preserves_exact_existing_member_fallback(self) -> None:
        """No new fallback policy or rate can bypass the existing admission calculation."""
        source = self.fixture.case
        work = project_work(source.project, source.context)
        before = copy.deepcopy(self.state)
        for member in ['*', *self.sections, None]:
            result = family_service(self.evidence, RateCatalog(), self.state, member)
            self.assertEqual(result['status'], 'fallback')
            self.assertEqual(result['seconds'], package_seconds(work, self.evidence['fallbackRates'], member))
        self.assertEqual(self.state, before)

    def test_sealed_windows_reduce_only_future_normal_publish_calls(self) -> None:
        """Completed work cannot repeatedly reserve its original full coordinator inventory."""
        section = self.sections[0]
        self.state['members'][section] = {'terminal': False, 'facts': {'pendingWindows': 2}}
        calls = selected_remaining(self.evidence, self.state, section)['calls']
        scopes = {row['id'] for row in self.evidence['scopes'] if row['sectionIds'] == [section]}
        self.assertEqual({calls[row['key']] for row in self.evidence['readPlan']['calls']
                          if row['site'] == 'ready-discovery' and row['scopeId'] in scopes}, {3})
        self.state['members'][section]['terminal'] = True
        after = selected_remaining(self.evidence, self.state, section)['calls']
        self.assertTrue(all(after[row['key']] == 0 for row in self.evidence['readPlan']['calls']
                            if row['site'] in ('ready-discovery', 'family-outcome')))

    def test_carry_removes_package_and_progress_but_keeps_future_proof_reads(self) -> None:
        """Withdrawing carry restores demand; it never consumes a new review or launch cap."""
        scope = self.evidence['scopes'][0]
        self.state['carry'].add(scope['id'])
        selected = selected_remaining(self.evidence, self.state)['calls']
        calls = {row['site']: row['key'] for row in self.evidence['readPlan']['calls'] if row['scopeId'] == scope['id']}
        self.assertEqual(selected[calls['package-create']], 0)
        self.assertEqual(selected[calls['review-progress']], 0)
        self.assertGreater(selected[calls['ready-discovery']], 0)
        self.state['carry'].clear()
        restored = selected_remaining(self.evidence, self.state)['calls']
        self.assertEqual(restored[calls['package-create']], 1)
        self.assertEqual(restored[calls['review-progress']], 1)

    def test_actual_media_requires_actual_full_proof_inventory(self) -> None:
        """Prospective covered cells cannot mask missing actual transitive traversal facts."""
        self.assertEqual(family_service(self.evidence, self.fixture.catalog, self.state)['status'], 'measured')
        self.state['hasMedia'] = True
        result = family_service(self.evidence, self.fixture.catalog, self.state)
        self.assertEqual(result['status'], 'fallback')
        self.assertIn('unobserved', result['reason'])

    def test_settled_private_member_transfers_new_local_work_to_integration(self) -> None:
        """Withdrawn carry cannot hide package work behind a terminal private invocation."""
        section = self.sections[0]
        self.state['members'][section] = {'terminal': True, 'facts': {'pendingWindows': 0}}
        before = family_service(self.evidence, RateCatalog(), fresh_state(), None)['seconds']
        after = family_service(self.evidence, RateCatalog(), self.state, None)
        calls = {row['key']: row for row in self.evidence['readPlan']['calls']}
        scopes = {row['id'] for row in self.evidence['scopes'] if row['sectionIds'] == [section]}
        self.assertTrue(all(after['remaining']['calls'][key] == 1 for key, row in calls.items()
                            if row['site'] == 'package-create' and row['scopeId'] in scopes))
        self.assertGreater(after['seconds'], before)
        self.state['carry'] = scopes
        self.assertEqual(family_service(self.evidence, RateCatalog(), self.state, None)['seconds'], before)

    def test_retry_and_external_work_are_not_prepaid_or_mutating(self) -> None:
        """Explicit extra demand uses fallback without deleting the cold valid-work facts."""
        self.state['packages'].add(self.evidence['scopes'][0]['id'])
        for extra in ('retry', 'recovery', 'external-inspection', 'callback-replay'):
            self.state['additionalDemand'] = [extra]
            before = copy.deepcopy(self.state)
            self.assertEqual(family_service(self.evidence, self.fixture.catalog, self.state)['status'], 'fallback')
            self.assertEqual(self.state, before)


if __name__ == '__main__':
    unittest.main()
