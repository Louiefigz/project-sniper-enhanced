"""The forecast models exclusive occupancy; Short capacity comes only from the Shorts that hold or request slots.

M-059 (P1 Step M3). TEST batch records in memory on a TEST host qualified by TEST profiles in a private folder;
the supervisor and process table are TEST values, so no process is started. Before M-059 an authorized Long
collapsed every Short forecast to one heavy slot (LA-07: F2 ``probe_la07``, D ``s_la07``). Needs M-044's v2 clocks
(``queue_clock.writable``, ``queue_clock_schema``), which Phase 1 lands before M-059.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest
from unittest import mock

import test_native_budget_family_admission as family_admission
from _budget_fixture import FakeClock, approval, fake_clock
from _native_pool_fixture import TEST_HOST, fixture_job, fixture_profile, qualify_fixture_profiles
from studio.native_budget_clock import start_anchor
from studio.native_budget_family_forecast import pending_seconds
from studio.native_budget_forecast import (
    attempt_forecast, heavy_lane_capacity, lane_exclusive, launch_fits, route_seconds, slot_count, slot_free_times,
)
from studio.native_budget_forecast_snapshot import capture_forecast
from studio.native_budget_launch import LaunchRequest, admit_launch, long_latest_start
from studio.native_budget_owner import MAX_CAPACITY_WAIT
from studio.native_budget_policy import BatchSpec, new_batch_record
from studio.production.mixed_forecast import (
    Demand, ForecastInputs, forecast_inputs, launch_misses, long_launch_refusal, running_launches,
)
from studio.production.mixed_forecast_place import place
from studio.production.outputs import OutputAuthorization, authorize_output
from studio.production.queue_clock import enabled, problem, writable
from studio.production.queue_clock_schema import POLICY_V1, V1_KEYS, new_clock

SUPERVISOR = {'pid': 7001, 'pgid': 7001, 'started': 'TEST supervisor'}
SHORTS = ('A', 'B', 'C', 'D')
LONG_SECONDS = 660.0


class OccupancyCase(unittest.TestCase):
    """Shared setup: fresh caches, TEST profiles, TEST processes and a four-Short TEST batch (3 pool slots)."""

    def setUp(self) -> None:
        """Clear both forecast caches, qualify the TEST host and create the batch record in memory."""
        for cached in (heavy_lane_capacity, lane_exclusive):
            cached.cache_clear()
            self.addCleanup(cached.cache_clear)
        qualify_fixture_profiles(self, self.profiles())
        for target, value in (('studio.native_budget_launch.own_identity', dict(SUPERVISOR)),
                              ('studio.native_budget_launch._process_table', {7001: (1, 7001, 'TEST supervisor')})):
            self.enterContext(mock.patch(target, return_value=value))
        with fake_clock(FakeClock()):
            spec = BatchSpec('batch-occupancy', SHORTS, (), 3, approvals={clip: approval(clip) for clip in SHORTS})
            self.record = new_batch_record(spec, start_anchor())

    def profiles(self) -> list[dict]:
        """The TEST qualification: one Short profile, 3 heavy slots, Shorts up to 60 s."""
        return [fixture_profile({'heavy': 3, 'audio': 1})]

    def authorize_long(self) -> dict:
        """Authorize the TEST Long L at 0 s; it stays idle until a test launches it."""
        authorize_output(self.record, OutputAuthorization('L', 'long', 'TEST reason', 'TEST operator',
                                                          output_seconds=LONG_SECONDS), 0.0)
        return self.record['clips']['L']

    def request(self, clip: str, seconds: float | None = None) -> LaunchRequest:
        """A TEST launch request: a Short's draft (45 s), or the Long's final (its declared duration)."""
        if clip == 'L':
            return LaunchRequest('L', 'final', 'l' * 64, ('/TEST/L', '/TEST/L-out'), seconds or LONG_SECONDS)
        return LaunchRequest(clip, 'draft', clip.lower() * 64, (f'/TEST/{clip}', f'/TEST/{clip}-out'), seconds or 45.0)

    def cold_caches(self) -> None:
        """Forget every capacity and exclusivity answer, so only what the next call reads is cached."""
        heavy_lane_capacity.cache_clear()
        lane_exclusive.cache_clear()

    def start(self, clip: str, at: float, seconds: float | None = None) -> float:
        """Admit a TEST launch at ``at`` that stays running; return when its forecast ends."""
        decision = admit_launch(self.record, self.request(clip, seconds), at)
        self.assertTrue(decision.allowed, decision.reason)
        attempt = decision.detail['attempt']
        return at + attempt_forecast(self.record, self.record['clips'][clip], attempt)


class MixedOccupancyTests(OccupancyCase):
    """Real forecast, admission and mixed-forecast code with 3 qualified heavy Short slots."""

    def test_authorized_idle_long_keeps_short_capacity(self) -> None:
        """F2 probe_la07: three 45 s Shorts keep 3 slots beside an authorized, idle Long (was 1)."""
        for clip in SHORTS[:3]:
            self.record['clips'][clip]['outputSeconds'] = 45.0
        self.assertEqual(slot_count(self.record, 45.0, 'short'), 3)
        self.authorize_long()
        self.assertEqual(slot_count(self.record, 45.0, 'short'), 3)
        self.assertEqual(slot_count(self.record, LONG_SECONDS, 'long'), 3)

    def test_handed_off_long_keeps_short_capacity(self) -> None:
        """D s_la07: a handed-off Long never reduces Short capacity (was 1 after hand-off)."""
        self.record['clips']['A']['outputSeconds'] = 60.0
        self.authorize_long()['state'] = 'handed-off'
        self.assertEqual(slot_count(self.record, 60.0), 3)

    def test_running_long_holds_every_slot_until_its_end(self) -> None:
        """A running Long is exclusive: every slot frees at its forecast end, and Short capacity stays 3."""
        self.authorize_long()
        end = self.start('L', 0.0)
        self.assertEqual(slot_free_times(self.record, 100.0, 45.0, 'short'), [end] * 3)
        fit = launch_fits(self.record, ('A', 'draft', 45.0), 100.0)
        self.assertEqual((fit['queueDelaySeconds'], fit['slots']), (round(end - 100.0, 1), 3))

    def test_short_behind_running_long_fits_on_counted_time(self) -> None:
        """A queue-clock Short behind the Long misses on wall time but fits on counted time (its clock pauses)."""
        self.authorize_long()
        self.start('L', 0.0)
        fit = launch_fits(self.record, ('A', 'draft', 45.0), 100.0)
        self.assertGreater(fit['forecastFinishElapsed'], fit['latestFinishElapsed'])
        self.assertTrue(fit['fits'])
        self.assertAlmostEqual(fit['forecastCountedFinishElapsed'],
                               100.0 + route_seconds(self.record['rates'], 'draft', 45.0))
        self.assertAlmostEqual(fit['forecastCountedFinishElapsed'],
                               fit['forecastFinishElapsed'] - fit['queueDelaySeconds'], delta=0.1)
        self.assertGreater(fit['queueDelaySeconds'], 600.0)
        self.assertTrue(admit_launch(self.record, self.request('A'), 100.0).allowed)  # the 600 s bound is a Long's

    def test_a_v1_clock_is_never_forecast_as_credited(self) -> None:
        """X95 O1: a v1 clock (the P0 engine's) never advances here, so its Short's queue wait counts in full."""
        self.authorize_long()
        self.start('L', 0.0)
        clip = self.record['clips']['A']
        clip['capacityClock'] = {**{key: value for key, value in new_clock().items() if key in V1_KEYS},
                                 'policy': POLICY_V1}
        self.assertEqual((problem(clip), enabled(clip), writable(clip)), (None, True, False))
        fit = launch_fits(self.record, ('A', 'draft', 45.0), 100.0)
        self.assertFalse(fit['fits'])
        self.assertEqual(round(fit['forecastCountedFinishElapsed'], 1), fit['forecastFinishElapsed'])
        waits = {row.clip_id: row.exclude_capacity_wait for row in forecast_inputs(self.record, 100.0).demands}
        self.assertEqual((waits['A'], waits['B']), (False, True))

    def test_long_candidate_waits_for_the_pool_to_drain(self) -> None:
        """Shorts ending at d, d + 100 and d + 200: a Long's delay is the last end minus now, and it is admitted."""
        self.authorize_long()
        ends = [self.start(clip, at) for clip, at in zip(SHORTS, (0.0, 100.0, 200.0))]
        fit = launch_fits(self.record, ('L', 'final', LONG_SECONDS), 250.0)
        self.assertEqual(fit['queueDelaySeconds'], round(max(ends) - 250.0, 1))
        self.assertLessEqual(fit['queueDelaySeconds'], MAX_CAPACITY_WAIT)
        self.assertTrue(admit_launch(self.record, self.request('L'), 250.0).allowed)

    def test_an_admitted_long_waiting_behind_a_short_is_replayed_after_it(self) -> None:
        """A Long admitted while a Short runs (the pool queues it) starts only once every slot is free."""
        self.authorize_long()
        short_end = self.start('A', 0.0)
        long_end = self.start('L', 10.0)                      # 465 s forecast wait: within patience, admitted
        self.assertEqual(slot_free_times(self.record, 20.0, 45.0, 'short'), [short_end + long_end - 10.0] * 3)

    def test_a_long_wait_of_exactly_the_patience_launches(self) -> None:
        """Only a wait longer than MAX_CAPACITY_WAIT is refused."""
        self.authorize_long()
        with mock.patch('studio.native_budget_launch.launch_fits', return_value={'fits': True, 'queueDelaySeconds': 600.0}):
            self.assertTrue(admit_launch(self.record, self.request('L'), 10.0).allowed)

    def test_long_launch_refused_by_name_when_wait_exceeds_patience(self) -> None:
        """Four running Shorts on three slots: the Long would wait past 600 s, so it is refused by name, uncharged."""
        clip = self.authorize_long()
        for index, short in enumerate(SHORTS):
            self.start(short, float(index))
        fit = launch_fits(self.record, ('L', 'final', LONG_SECONDS), 10.0)
        wait = fit['queueDelaySeconds']
        self.assertGreater(wait, MAX_CAPACITY_WAIT)
        decision = admit_launch(self.record, self.request('L'), 10.0)
        running = '; '.join(running_launches(self.record, 10.0))
        self.assertEqual(decision.reason, f'Long L final would wait about {wait:.0f}s for the heavy pool ({running}), '
                         f'longer than an owner may queue ({MAX_CAPACITY_WAIT}s); launch it after about '
                         f'{10.0 + wait:.0f}s. {long_latest_start(self.record, clip, self.request("L"))}')
        self.assertEqual((decision.allowed, decision.detail, clip['counters']['exportAttempt'], clip['attempts']),
                         (False, fit, 0, []))

    def test_place_exclusive_demand_takes_every_slot(self) -> None:
        """An exclusive demand waits for every slot and then holds all three; a shared one takes one slot."""
        urgent_long, short = Demand('L', (100.0,), 0.0, 150.0, exclusive=True), Demand('S', (50.0,), 0.0, 1000.0)
        self.assertEqual(place((0.0, 0.0, 0.0), (urgent_long, short), 0.0), {'L': 100.0, 'S': 150.0})
        shared = Demand('L', (100.0,), 0.0, 150.0)
        self.assertEqual(place((0.0, 0.0, 0.0), (shared, short), 0.0), {'L': 100.0, 'S': 50.0})
        relaxed_long, urgent_short = Demand('L', (100.0,), 0.0, 1000.0, exclusive=True), Demand('S', (50.0,), 0.0, 60.0)
        self.assertEqual(place((0.0, 30.0, 60.0), (relaxed_long, urgent_short), 0.0), {'S': 50.0, 'L': 160.0})

    def test_launch_misses_with_a_held_long_uses_the_whole_pool(self) -> None:
        """A held exclusive Long makes a wall-clock Short miss that a one-slot Long would not; counted time never."""
        inputs = ForecastInputs((0.0, 0.0, 0.0), (Demand('S', (475.0,), 0.0, 500.0),))
        held = Demand('L', (2000.0,), 0.0, 9000.0, exclusive=True)
        self.assertEqual(launch_misses(inputs, held, {'S'}, 0.0)[0], ['S'])
        self.assertEqual(launch_misses(inputs, Demand('L', (2000.0,), 0.0, 9000.0), {'S'}, 0.0)[0], [])
        counted = ForecastInputs((0.0, 0.0, 0.0), (Demand('S', (475.0,), 0.0, 500.0, exclude_capacity_wait=True),))
        self.assertEqual(launch_misses(counted, held, {'S'}, 0.0)[0], [])
        staggered = ForecastInputs((0.0, 500.0, 500.0), (Demand('S', (100.0,), 0.0, 850.0),))
        self.assertEqual(launch_misses(staggered, Demand('L', (300.0,), 0.0, 9000.0, exclusive=True), {'S'}, 0.0)[0], ['S'])

    def test_long_launch_waits_while_holding_the_pool_would_make_a_wall_clock_short_miss(self) -> None:
        """Only a Short judged on its original clock can hold a Long back: the Long would hold all three slots."""
        self.authorize_long()
        del self.record['clips']['A']['capacityClock']  # a historical Short: its waits count on its own clock
        self.record['clips']['A']['outputSeconds'] = 45.0
        decision = admit_launch(self.record, self.request('L'), 10.0)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.reason.startswith('Long L final waits: holding a slot now'), decision.reason)
        self.assertIn('A (short) would finish at', decision.reason)

    def test_short_outside_every_profile_is_modeled_exclusive(self) -> None:
        """A 75 s Short (the profile covers 60 s) runs alone: it holds every slot and never sets Short capacity."""
        self.assertEqual((lane_exclusive(75.0, 'short'), lane_exclusive(45.0, 'short')), (True, False))
        end = self.start('A', 0.0, 75.0)
        self.assertEqual(slot_free_times(self.record, 10.0, 45.0, 'short'), [end] * 3)
        self.assertEqual(slot_count(self.record, 45.0, 'short'), 3)
        self.record['clips']['B']['outputSeconds'] = 75.0
        demands = {row.clip_id: row.exclusive for row in forecast_inputs(self.record, 10.0).demands}
        self.assertEqual((demands['B'], demands['C']), (True, False))

    def test_prepared_admission_reads_no_host_record_after_capture(self) -> None:
        """capture_forecast asks every exclusivity question the pure admission after the last clock sample asks."""
        end = self.start('A', 0.0)
        self.authorize_long()
        self.record['clips']['B']['outputSeconds'] = 75.0
        self.cold_caches()
        snapshot = capture_forecast(self.record, self.request('L', 600.0))
        with mock.patch('native_work_pool_policy.host_identity', side_effect=AssertionError('host read after sample')):
            fit = launch_fits(self.record, ('L', 'final', 600.0), 50.0, snapshot)
            inputs = forecast_inputs(self.record, 50.0, None, snapshot)
            self.assertIsNone(long_launch_refusal(self.record, self.request('L', 600.0), 50.0, inputs))
        self.assertEqual((fit['slots'], fit['queueDelaySeconds']), (3, round(end - 50.0, 1)))

    def test_prepared_short_admission_behind_a_running_long_reads_nothing_after_capture(self) -> None:
        """The running Long's actual 600 s cut (declared 660 s) is asked about only through its media launch."""
        self.authorize_long()
        end = self.start('L', 0.0, 600.0)
        self.cold_caches()
        snapshot = capture_forecast(self.record, self.request('A'))
        with mock.patch('native_work_pool_policy.host_identity', side_effect=AssertionError('host read after sample')):
            fit = launch_fits(self.record, ('A', 'draft', 45.0), 50.0, snapshot)
            demands = forecast_inputs(self.record, 50.0, None, snapshot).demands
        self.assertEqual((fit['slots'], fit['queueDelaySeconds']), (3, round(end - 50.0, 1)))
        self.assertEqual({row.clip_id: row.exclusive for row in demands}['B'], False)


class SectionFamilyDemandTests(unittest.TestCase):
    """A Long whose remaining work is a section family (its real family admission) is still exclusive demand."""

    def setUp(self) -> None:
        """The family-admission harness (private authority, TEST processes, 1 heavy slot) and a TEST host."""
        for cached in (heavy_lane_capacity, lane_exclusive):
            cached.cache_clear()
            self.addCleanup(cached.cache_clear)
        self.enterContext(mock.patch('native_work_pool_policy.host_identity', return_value=dict(TEST_HOST)))
        self.h = family_admission.FamilyAdmissionTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def test_a_section_family_long_demand_holds_every_slot(self) -> None:
        """With one preview child running, the family's pending members are one exclusive Demand."""
        self.h.reserve('first')
        record = self.h.h.budget.record()
        pending = pending_seconds(record, record['clips']['A'])
        demand = {row.clip_id: row for row in forecast_inputs(record, record['clock']['elapsed']).demands}['A']
        self.assertTrue(pending)
        self.assertEqual((demand.durations, demand.exclusive), (pending, True))


class OpenShortCapacityTests(OccupancyCase):
    """Two TEST Short profiles: 3 slots up to 45 s, 2 slots up to 60 s."""

    def profiles(self) -> list[dict]:
        """3 heavy slots for Shorts up to 45 s, 2 for Shorts up to 60 s."""
        return [fixture_profile({'heavy': 3, 'audio': 1}, [fixture_job(i, durationSeconds=45.0) for i in range(3)]),
                fixture_profile({'heavy': 2, 'audio': 1}, [fixture_job(i, durationSeconds=60.0) for i in range(2)])]

    def test_short_capacity_counts_only_open_committed_shorts(self) -> None:
        """A committed 55 s Short limits Short capacity to 2 until it is handed off, delivered or past its deadline."""
        self.assertEqual((heavy_lane_capacity(45.0, 'short'), heavy_lane_capacity(55.0, 'short')), (3, 2))
        clip = self.record['clips']['B']
        clip['outputSeconds'] = 55.0
        self.assertEqual(slot_count(self.record, 45.0), 2)
        clip['state'] = 'handed-off'
        self.assertEqual(slot_count(self.record, 45.0), 3)
        clip['state'], clip['deliveries'] = 'active', [{'kind': 'draft'}]
        self.assertEqual(slot_count(self.record, 45.0), 3)
        clip['deliveries'] = []
        self.assertEqual(slot_count(self.record, 45.0), 2)
        self.record['clock']['elapsed'] = 2400.0
        self.assertEqual(slot_count(self.record, 45.0), 3)

    def test_a_running_launch_keeps_capacity_after_hand_off(self) -> None:
        """B hands off while its 55 s launch still runs: that launch keeps Short capacity at 2."""
        self.start('B', 0.0, 55.0)
        self.record['clips']['B']['state'] = 'handed-off'
        self.assertEqual(slot_count(self.record, 45.0), 2)


if __name__ == '__main__':
    unittest.main()
