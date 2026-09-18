"""Capacity and sustained-pressure decisions without native media work."""
from __future__ import annotations

import unittest
from dataclasses import replace

from native_render_policy import AdaptiveMemoryGuard, adaptive_admission_reasons, capacity_policy
from native_render_resources import GIB, ResourceSnapshot, parse_snapshot
from test_native_render_resources import REQUEST, raw_sample


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


if __name__ == '__main__':
    unittest.main()
