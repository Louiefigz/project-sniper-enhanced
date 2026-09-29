"""Independent review of real family callback admission and logical waiting demand."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import test_native_family_authority as authority_fixture
from studio.native_budget_family_state import verify_family_request
from studio.native_budget_forecast import attempt_forecast, queue_start_delay
from studio.native_budget_registry import BudgetRefused
from studio.native_budget_sections import SectionBudgetOwner
from studio.native_segments.long_plan import identity


class FamilyBoundaryReviewTests(unittest.TestCase):
    """The existing post-pool callback binds exact request bytes, ranges and shared counters."""

    def setUp(self) -> None:
        """Reuse the isolated real store fixture without invoking any real process or pool."""
        authority_fixture.FamilyAuthorityTests.setUp(self)
        self.enterContext(patch('studio.production.section_plan.revalidate_context', return_value={}))
        self.enterContext(patch('studio.production.section_plan.require_context'))

    def admitted_request(self) -> dict:
        """Publish exactly one reserved immutable child and freeze its source-plan pin."""
        request = copy.deepcopy(self.fixture.request)
        root = Path(request['output'])
        root.mkdir()
        scope = {'sectionId': 'A', 'frameRange': [0, 600]}
        request.update(sectionScope=scope, sectionProduction={'plan': self.family['plan']})
        request['revision']['renderWindows'][0].update(startFrame=0, endFrame=600)
        request['revision']['renderWindows'][1].update(startFrame=600, endFrame=1200)
        request['productionBudget'].update(route='final', familyId=self.family['id'], familyInvocation='b' * 32)
        request['pins'][str(Path(request['project']) / 'LONG-PROJECT.json')] = 'e' * 64
        row = authority_fixture.FamilyAuthorityTests.invocation(self)
        row.update(project=request['project'], output=request['output'], scopeSha256=identity(scope), admittedElapsed=0)
        (root / 'export-request.json').write_text(json.dumps(request))
        self.fixture.raw(self.record)
        return request

    def test_real_owner_callback_debits_once_and_refuses_neighbor_window(self) -> None:
        """An actual child callback cannot borrow its family token to render B from A's scope."""
        request = self.admitted_request()
        owner = SectionBudgetOwner(request, 'segment-picture-0')
        owner.before_launch()
        owner.before_launch()
        clip = self.fixture.record()['clips']['A']
        self.assertEqual(clip['counters']['pictureGeneration'], 1)
        self.assertEqual(len(clip['sectionOwners']), 1)
        with self.assertRaisesRegex(BudgetRefused, 'escaped'):
            SectionBudgetOwner(request, 'segment-picture-1').before_launch()
        self.assertEqual(self.fixture.record()['clips']['A']['counters']['pictureGeneration'], 1)

    def test_published_request_substitution_refuses_before_debit(self) -> None:
        """Post-reservation request mutation cannot borrow the same owner capability."""
        request = self.admitted_request()
        changed = copy.deepcopy(request)
        changed['sectionScope']['frameRange'] = [0, 1200]
        (Path(request['output']) / 'export-request.json').write_text(json.dumps(changed))
        with self.assertRaisesRegex(BudgetRefused, 'published bytes'):
            SectionBudgetOwner(request, 'segment-picture-0').before_launch()
        self.assertEqual(self.fixture.record()['clips']['A']['counters']['pictureGeneration'], 0)

    def test_waiting_logical_preview_does_not_hold_real_lane_until_hard_deadline(self) -> None:
        """Late authors must not deadlock first final admission behind a process that already exited."""
        attempt = self.clip['attempts'][0]
        attempt['route'] = 'preview'
        elapsed = attempt_forecast(self.record, self.clip, attempt) + 10
        with patch('studio.native_budget_forecast.heavy_lane_capacity', return_value=1):
            delay = queue_start_delay(self.record, elapsed, 60, 'long')
        self.assertLess(delay, attempt['grantedSeconds'] - elapsed)


    def test_waiting_family_remains_visible_as_pending_work(self) -> None:
        """Releasing a physical lane cannot erase the unfinished authorized Long demand."""
        from studio.production.mixed_forecast import forecast_inputs
        with patch('studio.native_budget_forecast.heavy_lane_capacity', return_value=1):
            inputs = forecast_inputs(self.record, 100)
        self.assertEqual(inputs.running, ())
        self.assertEqual(len(inputs.demands), 1)
        self.assertEqual(len(inputs.demands[0].durations), 4)
        self.assertGreater(sum(inputs.demands[0].durations), 0)

    def test_aggregate_final_equals_all_scoped_children_plus_full_integration(self) -> None:
        """Every startup and conservative complete integration cost is present in initial admission."""
        from studio.native_budget_family_forecast import member_seconds, family_members
        from studio.native_budget_forecast import route_seconds
        from studio.production.formats import clip_rates
        attempt = self.clip['attempts'][0]
        children = family_members(self.family, 'final')
        actual = sum(member_seconds(self.record, self.clip, attempt, row) for row in children)
        grouped = route_seconds(clip_rates(self.record, self.clip), 'final', 60, (None, 4))
        self.assertAlmostEqual(grouped, actual)
        self.assertEqual(attempt_forecast(self.record, self.clip, attempt), grouped)


    def test_singleton_preview_keeps_two_final_startups(self) -> None:
        """One private scope still has its own full integration, even without a join-preview member."""
        from studio.native_budget_forecast import launch_fits, route_seconds
        from studio.production.formats import clip_rates
        self.clip['attempts'] = []
        self.clip['sectionFamilies'] = []
        with patch('studio.native_budget_forecast.heavy_lane_capacity', return_value=1):
            fit = launch_fits(self.record, ('A', 'preview', 60, '/TEST/project', 60, 1, 2), 0)
        rates = clip_rates(self.record, self.clip)
        self.assertEqual(fit['followingExportSeconds'], route_seconds(rates, 'final', 60, (None, 2)))
        self.assertGreater(fit['followingExportSeconds'], route_seconds(rates, 'final', 60))


    def test_repair_preview_keeps_new_final_demand_after_original_delivery(self) -> None:
        """An old checked family cannot erase the changed plan's still-required final work."""
        from studio.native_budget_family_forecast import pending_seconds, family_members, member_seconds
        attempt = self.clip['attempts'][0]
        attempt['status'] = 'succeeded'
        self.family['state'] = 'complete'
        self.clip['deliveries'] = [{'attemptId': attempt['id'], 'kind': 'final'}]
        self.assertEqual(pending_seconds(self.record, self.clip), ())
        preview = {**copy.deepcopy(attempt), 'id': 'c' * 32, 'route': 'preview', 'status': 'running'}
        family = {**copy.deepcopy(self.family), 'id': preview['id'], 'state': 'awaiting-sections',
                  'plan': {**self.family['plan'], 'sha256': 'a' * 64}, 'invocations': []}
        self.clip['attempts'].append(preview)
        self.clip['sectionFamilies'].append(family)
        pending = pending_seconds(self.record, self.clip)
        self.assertEqual(len(pending), 8)
        final = {**preview, 'route': 'final'}
        required_final = sum(member_seconds(self.record, self.clip, final, member)
                             for member in family_members(family, 'final'))
        self.assertGreater(sum(pending), required_final)
        family['state'] = 'complete'  # Retained A/C need no invented successful invocation rows.
        after_preview = pending_seconds(self.record, self.clip)
        self.assertEqual(len(after_preview), 4)
        self.assertAlmostEqual(sum(after_preview), required_final)



if __name__ == '__main__':
    unittest.main()
