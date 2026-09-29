"""Operational Long service demand follows actual launch, grant and mixed-queue arithmetic."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from _native_section_budget_fixture import SectionBudgetFixture, SUPERVISOR
from studio.native_budget_forecast import launch_fits, route_seconds
from studio.native_budget_launch import LaunchRequest, admit_launch, long_latest_start
from studio.production.formats import clip_deadlines, clip_rates
from studio.production.mixed_forecast import Demand, ForecastInputs, long_launch_refusal


class ServiceLaunchForecastTests(unittest.TestCase):
    """Actual shared arithmetic on isolated records; no host rate or media is fabricated."""

    def setUp(self) -> None:
        """Use the existing private budget fixture and make its first launch available."""
        self.fixture = SectionBudgetFixture(self)
        self.record = self.fixture.record()
        self.clip = self.record['clips']['A']
        self.clip['attempts'] = []
        self.clip['counters']['exportAttempt'] = 0
        self.enterContext(patch('studio.native_budget_forecast.heavy_lane_capacity', return_value=1))
        self.enterContext(patch('studio.native_budget_launch.own_identity', return_value=SUPERVISOR))

    def launch(self, route: str, service: float = 0.0) -> LaunchRequest:
        """A synthetic internal reservation with an explicit known service allowance."""
        return LaunchRequest('A', route, 'b' * 64, ('/TEST/project', '/TEST/output'), 60,
                             window_seconds=60 if route == 'preview' else None,
                             family_members=3, following_members=3, service_seconds=service)

    def fit(self, route: str, service: float = 0.0) -> dict:
        """Call the actual common entry; the last tuple item is the optional allowance."""
        value = self.launch(route, service)
        return launch_fits(self.record, ('A', route, 60, value.paths[0], value.window_seconds,
                                        value.family_members, value.following_members, service), 0)

    def test_final_service_is_counted_once_and_preserves_deadline(self) -> None:
        """Operational work extends demand, never the original latest-finish authority."""
        before, after = self.fit('final'), self.fit('final', 317.5)
        self.assertEqual(after['forecastSeconds'] - before['forecastSeconds'], 317.5)
        self.assertEqual(after['forecastFinishElapsed'] - before['forecastFinishElapsed'], 317.5)
        self.assertEqual(after['latestFinishElapsed'], before['latestFinishElapsed'])
        self.assertEqual(after['followingExportSeconds'], 0)

    def test_preview_reserves_final_service_in_its_actual_charged_grant(self) -> None:
        """The service reserve survives the normal _charge_launch path, not only a side guard."""
        base = admit_launch(copy.deepcopy(self.record), self.launch('preview'), 0)
        changed = admit_launch(self.record, self.launch('preview', 317.5), 0)
        self.assertTrue(base.allowed and changed.allowed)
        self.assertEqual(changed.detail['forecast']['forecastSeconds'], base.detail['forecast']['forecastSeconds'])
        self.assertEqual(changed.detail['forecast']['followingExportSeconds']
                         - base.detail['forecast']['followingExportSeconds'], 317.5)
        self.assertEqual(base.detail['attempt']['grantedSeconds']
                         - changed.detail['attempt']['grantedSeconds'], 317.5)
        self.assertEqual(self.clip['counters']['previewLaunch'], 1)

    def test_forecast_refusal_has_no_new_counter_or_attempt(self) -> None:
        """Too much package demand refuses before permanent launch charging."""
        before = copy.deepcopy(self.record)
        result = admit_launch(self.record, self.launch('final', 20000), 0)
        self.assertFalse(result.allowed)
        self.assertIn('Forecast misses', result.reason)
        self.assertEqual(self.record, before)

    def test_zero_service_preserves_short_forecast_and_nonzero_refuses(self) -> None:
        """Neither standalone nor Long-derived Shorts may borrow the Long field."""
        for derived in (None, 'TEST-parent-long'):
            self.clip['output']['format'] = 'short'
            self.clip['output']['derivedFrom'] = derived
            old = launch_fits(self.record, ('A', 'preview', 60, '/TEST/project'), 0)
            explicit = launch_fits(self.record, ('A', 'preview', 60, '/TEST/project', None, 1, 1, 0), 0)
            self.assertEqual(explicit, old)
            with self.assertRaisesRegex(ValueError, 'only for Long'):
                launch_fits(self.record, ('A', 'final', 60, '/TEST/project', None, 1, 1, 1), 0)

    def test_invalid_service_never_becomes_negative_or_nan_demand(self) -> None:
        """Closed numerical admission refuses booleans and nonfinite values as well."""
        for value in (-1, float('nan'), float('inf'), True, '1'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Invalid Long service'):
                self.fit('final', value)

    def test_mixed_candidate_includes_service_in_the_correct_route(self) -> None:
        """Committed Short protection receives the same final service burden as admission."""
        self.record['clips']['S'] = {'output': {'format': 'short'}}
        inputs = ForecastInputs((0,), (Demand('S', (10,), 0, 100),))
        rates = clip_rates(self.record, self.clip)
        for route in ('preview', 'final'):
            launch = self.launch(route, 317.5)
            with patch('studio.production.mixed_forecast.launch_misses', return_value=(set(), {})) as place:
                self.assertIsNone(long_launch_refusal(self.record, launch, 0, inputs))
            demand = place.call_args.args[1]
            expected = route_seconds(rates, 'final', 60, (None, 3)) + 317.5
            self.assertEqual(demand.durations[-1], expected)
            if route == 'preview':
                self.assertEqual(demand.durations[0], route_seconds(rates, 'preview', 60, (60, 3)))

    def test_latest_start_advice_keeps_the_same_grant_end(self) -> None:
        """The user-facing risk advice must not omit the service cost or extend the clock."""
        rates = clip_rates(self.record, self.clip)
        deadline = clip_deadlines(self.record, self.clip)
        end = deadline['deliverySeconds'] - deadline['handoffReserveSeconds']
        latest = end - route_seconds(rates, 'final', 60, (None, 3)) - 317.5
        text = long_latest_start(self.record, self.clip, self.launch('final', 317.5))
        self.assertIn(f'latest final start is {latest:.0f}s', text)
        self.assertIn(f'grant ends at {end:.0f}s', text)


if __name__ == '__main__':
    unittest.main()
