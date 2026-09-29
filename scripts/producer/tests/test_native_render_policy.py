"""Capacity and sustained-pressure decisions without native media work."""
from __future__ import annotations

import unittest
from dataclasses import replace

from native_render_deferral import (
    DEFERRAL_MARGIN_SECONDS, NO_CPU_PROFILE, NO_INTERVAL, CpuDeferralProfile, DeferralRequest, launch_deferral,
)
from native_render_policy import AdaptiveMemoryGuard, adaptive_admission_reasons, capacity_policy
from native_render_resources import GIB, ResourceSnapshot, parse_snapshot
from native_work_pool_policy import RESERVATION_BYTES, reserved_policy
from test_native_render_resources import REQUEST, direct_sample, raw_sample

POOL_RECORD, EVIDENCE = 'a' * 64, 'b' * 64
PROFILE = CpuDeferralProfile('TEST-profile', POOL_RECORD, ('heavy',), .8, 60.0, EVIDENCE)
QUALIFIED_POOL = {'mode': 'qualified', 'modeRecord': {'path': '/TEST/record.json', 'sha256': POOL_RECORD}}


def deferral(busy: float | None, **changes: object) -> DeferralRequest:
    """A memory-admitted heavy launch whose latest CPU interval shows ``busy``."""
    cpu = ({'status': 'baseline', 'reason': 'first-cpu-reading'} if busy is None else
           {'status': 'measured', 'host': {'status': 'measured', 'busyFraction': busy}})
    values = {'lane': 'heavy', 'pool': QUALIFIED_POOL, 'cpu': cpu, 'waited_seconds': 0.0,
              'remaining_seconds': 120.0} | changes
    return DeferralRequest(**values)


def policy_snapshot(capacity: int = 64) -> ResourceSnapshot:
    """Build complete synthetic telemetry, with consistent small-host counters."""
    current = parse_snapshot(raw_sample(), REQUEST, 40 * GIB)
    return replace(current, measured_at=1000.0, physical_bytes=capacity * GIB,
                   compressor_bytes=capacity * GIB // 32,
                   unused_physical_bytes=capacity * GIB // 2,
                   owned_footprint_bytes=min(3 * GIB, capacity * GIB // 8),
                   largest_owned_process_bytes=min(2 * GIB, capacity * GIB // 16))


class CapacityPolicyTests(unittest.TestCase):
    """Derived budgets grow with the host, then stop at the shared ceiling."""

    def test_budgets_cover_small_and_large_hosts(self) -> None:
        """The same policy must serve 8 through 128 GiB without a 4 GiB cliff."""
        for size, tree, process, swap in [(8, 2, 1.5, .5), (16, 4, 3, 1),
                                         (32, 8, 6, 2), (64, 16, 8, 4),
                                         (128, 16, 8, 4)]:
            policy = capacity_policy(policy_snapshot(size))
            with self.subTest(capacity=size):
                self.assertEqual(policy.maximum_owned_gib, tree)
                self.assertEqual(policy.maximum_process_gib, process)
                self.assertEqual(policy.maximum_swap_growth_gib, swap)

    def test_normal_host_admits_old_compression_swap_and_low_literal_unused(self) -> None:
        """Old host allocations are not evidence of active render exhaustion."""
        current = replace(policy_snapshot(), compressor_bytes=30 * GIB,
                          unused_physical_bytes=GIB, swap_used_bytes=30 * GIB)
        self.assertEqual(adaptive_admission_reasons(current, capacity_policy(current), now=1000), ())

    def test_admission_requires_current_normal_pressure_and_real_headroom(self) -> None:
        """Adaptive limits preserve admission checks before any child starts."""
        baseline = policy_snapshot()
        cases = [('kernel_pressure_level', 2), ('kernel_pressure_level', 4),
                 ('free_percent', 24.9), ('disk_free_bytes', 9 * GIB),
                 ('measured_at', 969.0), ('measured_at', 1001.0)]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.assertTrue(adaptive_admission_reasons(
                    replace(baseline, **{field: value}), capacity_policy(baseline), now=1000))

    def test_capacity_requires_a_real_positive_byte_count(self) -> None:
        """Invalid capacity cannot produce a guessed host budget."""
        for value in [0, -1, True, float('nan'), float('inf'), '64']:
            with self.subTest(value=value), self.assertRaises((ValueError, RuntimeError)):
                capacity_policy(replace(policy_snapshot(), physical_bytes=value))


    def test_admission_invalid_telemetry_returns_reasons_without_numeric_fallback(self) -> None:
        """Typed failure is preferable to accepting NaN or crashing on an unknown value."""
        baseline = policy_snapshot()
        cases = [('free_percent', float('nan')), ('free_percent', 101),
                 ('free_percent', '60'), ('compressor_bytes', -1),
                 ('disk_free_bytes', float('inf')), ('unused_physical_bytes', True)]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.assertTrue(adaptive_admission_reasons(replace(baseline, **{field: value}),
                    capacity_policy(baseline), now=1000))


class AdaptiveGuardTests(unittest.TestCase):
    """Fresh complete readings prove duration; host-history warnings stay advisory."""

    def setUp(self) -> None:
        """Use deterministic wall and monotonic clocks, independent of the host."""
        self.baseline = policy_snapshot()
        self.guard = AdaptiveMemoryGuard(self.baseline, capacity_policy(self.baseline))

    def evaluate(self, elapsed: float, changes: dict | None = None) -> dict:
        """Evaluate one later telemetry reading using both explicitly controlled clocks."""
        current = replace(self.baseline, measured_at=1001 + elapsed, **(changes or {}))
        return self.guard.evaluate(current, monotonic_now=100 + elapsed, wall_now=1001 + elapsed)

    def test_observed_4_point_112_gib_short_is_below_64_gib_host_budget(self) -> None:
        """Reproduce the actual 4.112 GiB tree that the former fixed cap aborted."""
        result = self.evaluate(0, {'owned_footprint_bytes': int(4.112 * GIB)})
        self.assertFalse(result['stopReasons'])
        self.assertEqual(result['mode'], 'capacity-adaptive-v1')
        self.assertIn('budgets', result)

    def test_one_warning_does_not_abort_and_recovery_resets_the_window(self) -> None:
        """A later recurrence needs its own sustained evidence."""
        self.assertFalse(self.evaluate(0, {'kernel_pressure_level': 2})['stopReasons'])
        recovered = self.evaluate(5)
        self.assertIn('kernel-warning', recovered['recoveries'])
        self.assertFalse(self.evaluate(10, {'kernel_pressure_level': 2})['stopReasons'])
        self.assertFalse(self.evaluate(15, {'kernel_pressure_level': 2})['stopReasons'])
        self.assertTrue(self.evaluate(20, {'kernel_pressure_level': 2})['stopReasons'])

    def test_warning_needs_three_readings_and_ten_seconds(self) -> None:
        """Several rapid samples cannot manufacture ten seconds of pressure."""
        for elapsed in (0, 1, 2, 9.99):
            self.assertFalse(self.evaluate(elapsed, {'kernel_pressure_level': 2})['stopReasons'])
        result = self.evaluate(10, {'kernel_pressure_level': 2})
        self.assertTrue(result['stopReasons'])
        self.assertGreaterEqual(result['conditions']['kernel-warning']['readings'], 3)
        self.assertGreaterEqual(result['conditions']['kernel-warning']['ageSeconds'], 10)

    def test_two_slow_readings_do_not_replace_the_three_reading_minimum(self) -> None:
        """Elapsed time alone must not infer an unobserved middle reading."""
        self.assertFalse(self.evaluate(0, {'free_percent': 9})['stopReasons'])
        self.assertFalse(self.evaluate(12, {'free_percent': 9})['stopReasons'])
        self.assertTrue(self.evaluate(13, {'free_percent': 9})['stopReasons'])

    def test_alternating_conditions_do_not_accumulate_each_others_duration(self) -> None:
        """Warning pressure and low free percentage maintain independent windows."""
        changes = [{'kernel_pressure_level': 2}, {'free_percent': 9}] * 4
        for index, change in enumerate(changes):
            self.assertFalse(self.evaluate(index * 5, change)['stopReasons'])

    def test_simultaneous_conditions_accumulate_independently(self) -> None:
        """Recovery of one condition cannot erase the other condition's evidence."""
        self.evaluate(0, {'kernel_pressure_level': 2, 'free_percent': 9})
        self.evaluate(5, {'kernel_pressure_level': 2, 'free_percent': 9})
        result = self.evaluate(10, {'free_percent': 9})
        self.assertTrue(result['stopReasons'])
        self.assertIn('kernel-warning', result['recoveries'])
        self.assertEqual(result['conditions']['low-headroom']['readings'], 3)

    def test_gap_beyond_fifteen_seconds_restarts_observation(self) -> None:
        """A long unobserved interval is not continuous warning evidence."""
        self.evaluate(0, {'kernel_pressure_level': 2})
        self.evaluate(5, {'kernel_pressure_level': 2})
        result = self.evaluate(20.01, {'kernel_pressure_level': 2})
        self.assertFalse(result['stopReasons'])
        self.assertEqual(result['conditions']['kernel-warning']['readings'], 1)
        self.assertFalse(self.evaluate(25.01, {'kernel_pressure_level': 2})['stopReasons'])
        self.assertTrue(self.evaluate(30.02, {'kernel_pressure_level': 2})['stopReasons'])

    def test_exact_fifteen_second_gap_retains_valid_evidence(self) -> None:
        """The configured maximum gap is inclusive."""
        self.evaluate(0, {'kernel_pressure_level': 2})
        self.evaluate(5, {'kernel_pressure_level': 2})
        self.assertTrue(self.evaluate(20, {'kernel_pressure_level': 2})['stopReasons'])

    def test_hostwide_compression_and_swap_growth_only_warn(self) -> None:
        """Several persistent host-history samples cannot independently abort."""
        changes = {'compressor_bytes': 30 * GIB, 'swap_used_bytes': 30 * GIB,
                   'unused_physical_bytes': GIB}
        for elapsed in (0, 5, 10, 15):
            result = self.evaluate(elapsed, changes)
            self.assertFalse(result['stopReasons'])
            self.assertTrue(result['warnings'])

    def test_hard_limits_stop_without_waiting_for_more_samples(self) -> None:
        """Critical pressure, capacity, identity and disk failures remain immediate."""
        cases = [('kernel_pressure_level', 4), ('kernel_pressure_level', 0),
                 ('free_percent', 4.99), ('disk_free_bytes', 9 * GIB),
                 ('owned_footprint_bytes', 17 * GIB), ('largest_owned_process_bytes', 9 * GIB),
                 ('identity_verified', False), ('owned_pids', ())]
        for field, value in cases:
            guard = AdaptiveMemoryGuard(self.baseline, capacity_policy(self.baseline))
            current = replace(self.baseline, measured_at=1001, **{field: value})
            with self.subTest(field=field):
                self.assertTrue(guard.evaluate(current, monotonic_now=100, wall_now=1001)['stopReasons'])

    def test_five_percent_headroom_still_uses_the_sustained_window(self) -> None:
        """The severe threshold is strictly below five percent."""
        self.assertFalse(self.evaluate(0, {'free_percent': 5})['stopReasons'])

    def test_duplicate_or_decreasing_telemetry_timestamp_fails_closed(self) -> None:
        """Neither the admission reading nor repeated runtime data may count twice."""
        for measured_at in (999, 1000):
            guard = AdaptiveMemoryGuard(self.baseline, capacity_policy(self.baseline))
            result = guard.evaluate(replace(self.baseline, measured_at=measured_at),
                                    monotonic_now=100, wall_now=1001)
            self.assertTrue(result['stopReasons'])
        self.evaluate(0)
        repeated = replace(self.baseline, measured_at=1001)
        self.assertTrue(self.guard.evaluate(repeated, monotonic_now=105, wall_now=1006)['stopReasons'])

    def test_duplicate_or_reversed_monotonic_clock_fails_closed(self) -> None:
        """Fresh wall timestamps cannot disguise a nonadvancing duration clock."""
        for now in (100, 99, float('nan'), float('inf'), True):
            guard = AdaptiveMemoryGuard(self.baseline, capacity_policy(self.baseline))
            guard.evaluate(replace(self.baseline, measured_at=1001), monotonic_now=100, wall_now=1001)
            with self.subTest(now=now):
                self.assertTrue(guard.evaluate(replace(self.baseline, measured_at=1006),
                    monotonic_now=now, wall_now=1006)['stopReasons'])

    def test_stale_future_or_invalid_telemetry_cannot_be_counted_as_healthy(self) -> None:
        """Invalid values fail before condition accumulation or budget comparisons."""
        cases = [('measured_at', 969), ('measured_at', 1002), ('free_percent', float('nan')),
                 ('free_percent', 101), ('physical_bytes', 32 * GIB),
                 ('kernel_pressure_level', True), ('owned_footprint_bytes', -1)]
        for field, value in cases:
            guard = AdaptiveMemoryGuard(self.baseline, capacity_policy(self.baseline))
            current = replace(self.baseline, **({'measured_at': 1001} | {field: value}))
            with self.subTest(field=field, value=value):
                self.assertTrue(guard.evaluate(current, monotonic_now=100, wall_now=1001)['stopReasons'])


    def test_invalid_wall_or_sample_times_return_structured_failure(self) -> None:
        """Invalid clock values must not reach subtraction or become healthy samples."""
        cases = [(field, value) for field in ('wall_now', 'measured_at')
                 for value in ['1001', True, float('nan'), float('inf'), -1]]
        for field, value in cases:
            guard = AdaptiveMemoryGuard(self.baseline, capacity_policy(self.baseline))
            current = replace(self.baseline, measured_at=value if field == 'measured_at' else 1001)
            wall = value if field == 'wall_now' else 1001
            with self.subTest(field=field, value=value):
                self.assertTrue(guard.evaluate(current, monotonic_now=100, wall_now=wall)['stopReasons'])

    def test_invalid_byte_counters_do_not_crash_or_advance_pressure_evidence(self) -> None:
        """Incomplete synthetic telemetry cannot manufacture an extra valid observation."""
        cases = [('compressor_bytes', 'unknown'), ('swap_used_bytes', float('nan')),
                 ('disk_free_bytes', True), ('unused_physical_bytes', -1),
                 ('owned_footprint_bytes', -1), ('largest_owned_process_bytes', float('inf'))]
        for field, value in cases:
            guard = AdaptiveMemoryGuard(self.baseline, capacity_policy(self.baseline))
            guard.evaluate(replace(self.baseline, measured_at=1001, kernel_pressure_level=2),
                           monotonic_now=100, wall_now=1001)
            current = replace(self.baseline, measured_at=1006, kernel_pressure_level=2, **{field: value})
            with self.subTest(field=field, value=value):
                result = guard.evaluate(current, monotonic_now=105, wall_now=1006)
                self.assertTrue(result['stopReasons'])
                self.assertEqual(result['conditions']['kernel-warning']['readings'], 1)



class CpuSeparationTests(unittest.TestCase):
    """CPU is evidence: it never stops running work and never shrinks a reservation."""

    def test_saturated_cpu_never_stops_healthy_work(self) -> None:
        """Every processor busy and a huge owned CPU counter leave the guard's decision alone."""
        direct = parse_snapshot(direct_sample(), REQUEST, 40 * GIB)
        baseline = replace(policy_snapshot(), host_cpu=direct.host_cpu)
        busy = replace(direct.host_cpu, processor_ticks=((2 ** 32 - 1, 2 ** 32 - 1, 0, 0),) * 16)
        guard = AdaptiveMemoryGuard(baseline, capacity_policy(baseline))
        for index in range(4):
            current = replace(baseline, measured_at=1001 + 5 * index, host_cpu=busy,
                              processes=tuple(replace(row, cpu_user_ns=10 ** 15) for row in baseline.processes))
            result = guard.evaluate(current, monotonic_now=100 + 5 * index, wall_now=1001 + 5 * index)
            self.assertFalse(result['stopReasons'])

    def test_low_recent_rss_never_reduces_a_live_reservation(self) -> None:
        """Budgets derive from physical RAM and the ledger reservation, never from sampled RSS."""
        tiny, large = (replace(policy_snapshot(), owned_footprint_bytes=value, largest_owned_process_bytes=value)
                       for value in (1024, 12 * GIB))
        bound = [reserved_policy(capacity_policy(item), RESERVATION_BYTES['heavy']) for item in (tiny, large)]
        self.assertEqual(bound[0], bound[1])
        self.assertEqual(bound[0].maximum_owned_gib, 6)
        guard = AdaptiveMemoryGuard(tiny, bound[0])
        for index in range(5):
            result = guard.evaluate(replace(tiny, measured_at=1001 + 5 * index),
                                    monotonic_now=100 + 5 * index, wall_now=1001 + 5 * index)
            self.assertEqual(result['budgets']['maximum_owned_gib'], 6)
        self.assertIs(guard.policy, bound[0])


class LaunchDeferralTests(unittest.TestCase):
    """The hook consumes only a qualified profile, and none exists."""

    def test_without_a_profile_cpu_never_holds_a_launch(self) -> None:
        """Even a saturated host launches: no measured profile has shown a benefit."""
        for busy in (None, 0.0, .999, 1.0):
            with self.subTest(busy=busy):
                decision = launch_deferral(deferral(busy), None)
                self.assertEqual((decision['enabled'], decision['decision'], decision['reasons']),
                                 (False, 'launch', ()))
                self.assertEqual(decision['why'], NO_CPU_PROFILE)

    def test_qualified_profile_holds_only_a_measured_busy_host(self) -> None:
        """At or above its measured threshold the profile holds; below it launches."""
        held = launch_deferral(deferral(.85), PROFILE)
        self.assertEqual((held['decision'], held['profile']), ('defer', 'TEST-profile'))
        self.assertIn('host busy 0.850 >= 0.800', held['reasons'][0])
        self.assertEqual(launch_deferral(deferral(.8), PROFILE)['decision'], 'defer')
        self.assertEqual(launch_deferral(deferral(.79), PROFILE)['reasons'], ())

    def test_only_a_measured_interval_can_hold_a_launch(self) -> None:
        """A first, stale or unavailable reading neither holds every launch nor reads as idle."""
        stale = {'status': 'unavailable', 'reason': 'sample-clock-not-advancing'}
        host_stale = {'status': 'measured', 'host': {'status': 'unavailable', 'reason': 'host-counters-stale'}}
        for cpu in (None, stale, host_stale, 'not-a-record'):
            request = deferral(None) if cpu is None else deferral(None, cpu=cpu)
            with self.subTest(cpu=cpu):
                decision = launch_deferral(request, PROFILE)
                self.assertEqual((decision['decision'], decision['reasons'], decision['why']),
                                 ('launch', (), NO_INTERVAL))

    def test_a_hold_never_outlives_its_budget_or_the_owner_limit(self) -> None:
        """Deferral stops before the capacity-wait limit, so it never becomes a refusal."""
        exhausted = launch_deferral(deferral(1.0, waited_seconds=60.0), PROFILE)
        self.assertEqual((exhausted['decision'], exhausted['why']), ('launch', 'qualified deferral time is exhausted'))
        late = launch_deferral(deferral(1.0, remaining_seconds=DEFERRAL_MARGIN_SECONDS), PROFILE)
        self.assertEqual(late['decision'], 'launch')

    def test_profile_applies_only_to_its_pool_record_and_lane(self) -> None:
        """A profile measured elsewhere, or for another class, cannot hold this launch."""
        cases = [{'lane': 'audio'}, {'pool': {'mode': 'exclusive'}},
                 {'pool': {'mode': 'qualified', 'modeRecord': {'sha256': 'c' * 64}}},
                 {'pool': {'mode': 'qualification-session', 'modeRecord': {'session': 'x'}}}]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual(launch_deferral(deferral(1.0, **changes), PROFILE)['decision'], 'launch')

    def test_profiles_require_exact_evidence_and_bounded_holds(self) -> None:
        """No unnamed, unmeasured, unbounded or unknown-lane profile can be constructed."""
        valid = ('TEST-profile', POOL_RECORD, ('heavy',), .8, 60.0, EVIDENCE)
        invalid = {0: ['', '  ', None], 1: ['A' * 64, 'a' * 63, None], 2: [(), ('preview',), ['heavy']],
                   3: [0, 1, 1.5, float('nan'), True], 4: [0, -1, 601, float('inf'), True],
                   5: ['', 'z' * 64]}
        for index, values in invalid.items():
            for value in values:
                fields = list(valid)
                fields[index] = value
                with self.subTest(field=index, value=value), self.assertRaises(ValueError):
                    CpuDeferralProfile(*fields)

    def test_deferral_reasons_never_read_as_disk_refusals(self) -> None:
        """Admission refuses immediately on disk wording; CPU holds must never match it."""
        for request in (deferral(None), deferral(.95)):
            self.assertFalse([reason for reason in launch_deferral(request, PROFILE)['reasons'] if 'disk' in reason])

if __name__ == '__main__':
    unittest.main()
