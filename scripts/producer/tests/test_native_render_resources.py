"""Memory exhaustion, measurement failure and process identity regressions."""
from __future__ import annotations

import unittest
import json
import re
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from native_render_resources import (
    GIB,
    ProcessIdentity,
    ProcessRequest,
    ResourceMeasurementError,
    ResourcePolicy,
    admission_reasons,
    parse_snapshot,
    read_snapshot,
    resource_warnings,
    stop_reasons,
    verify_process_identity,
)

START = "Wed Sep  9 09:00:00 2026"
IDENTITY = ProcessIdentity(100, START, 100)
REQUEST = ProcessRequest(IDENTITY)


def raw_sample() -> dict[str, str]:
    """Use real macOS column/unit formats with synthetic process identities."""
    return {
        "sysctl": "hw.memsize: 68719476736\nvm.swapusage: total = 8192.00M  used = 4096.00M  free = 4096.00M (encrypted)\nkern.memorystatus_vm_pressure_level: 1\n",
        "pressure": "The system has 68719476736.\nSystem-wide memory free percentage: 60%",
        "top": "PhysMem: 30G used (4G wired, 2G compressor), 34G unused.\nPID MEM CMPRS\n100 2G 1G\n101 1G 512M\n500 20G 10G\n",
        "ps": f"100 1 100 {START}\n101 100 101 {START}\n500 1 500 {START}\n",
    }


def direct_sample(raw: dict[str, str] | None = None) -> dict[str, str]:
    """Replay existing identity-turnover fixtures through the explicit live schema."""
    from native_render_macos import COMPRESSED_UNAVAILABLE, SAMPLER
    from native_render_processes import parse_size
    result = dict(raw or raw_sample())
    top = result.pop('top')
    processes = [{'pid': int(pid), 'status': 'measured', 'footprintBytes': parse_size(mem),
        'processStartAbstime': 123456 + int(pid), 'processStartAbstimeBefore': 123456 + int(pid),
        'processExitAbstime': 0, 'compressedBytes': None, 'compressedStatus': COMPRESSED_UNAVAILABLE,
        'footprintSource': 'proc_pid_rusage:RUSAGE_INFO_V0:ri_phys_footprint'}
        for pid, mem, _ in re.findall(r'(?m)^\s*(\d+)\s+(\S+)\s+(\S+)\s*$', top)]
    result['direct'] = json.dumps({'schemaVersion': 1, 'status': 'measured', 'sampler': SAMPLER,
        'elapsedSeconds': .0001, 'host': {'pageSizeBytes': 16384, 'pageSizeSource': 'vm_kernel_page_size',
        'returnedIntegerCount': 38, 'compressorBytes': 2 * GIB, 'unusedPhysicalBytes': 34 * GIB,
        'raw': {'compressor_page_count': 2 * GIB // 16384, 'free_count': 34 * GIB // 16384,
                'speculative_count': 100}}, 'processes': processes})
    return result


class NativeRenderResourceTests(unittest.TestCase):
    """Exercise decisions without starting a browser, encoder or signal."""

    def healthy(self):
        """Return a healthy owned tree for policy tests."""
        return parse_snapshot(raw_sample(), REQUEST, 40 * GIB)

    def test_mem_already_includes_compression_and_excludes_unrelated(self) -> None:
        """The snapshot must not double count CMPRS or charge another app."""
        snapshot = self.healthy()
        self.assertEqual(snapshot.owned_footprint_bytes, 3 * GIB)
        self.assertEqual(snapshot.owned_pids, (100, 101))
        self.assertEqual(snapshot.processes[1].compressed_bytes, GIB // 2)
        self.assertTrue(snapshot.identity_verified)
        self.assertEqual(stop_reasons(snapshot, snapshot), ())

    def test_observed_oom_shape_stops_despite_small_resident_memory(self) -> None:
        """Four 14GiB renderers must trip limits even when RSS looks small."""
        raw = raw_sample()
        raw["top"] = "PhysMem: 63G used (10G wired, 32G compressor), 134M unused.\nPID MEM CMPRS\n100 3G 3017M\n"
        raw["top"] += "".join(f"{pid} 14G 14G\n" for pid in range(101, 105))
        raw["ps"] = f"100 1 100 {START}\n" + "".join(f"{pid} 100 {pid} {START}\n" for pid in range(101, 105))
        raw["sysctl"] = raw["sysctl"].replace("used = 4096.00M", "used = 62539.06M")
        raw["pressure"] = "System-wide memory free percentage: 4%"
        snapshot = parse_snapshot(raw, REQUEST, 9 * GIB)
        reasons = stop_reasons(snapshot, self.healthy())
        self.assertEqual(snapshot.owned_footprint_bytes, 59 * GIB)
        self.assertIn("owned render footprint exceeds policy", reasons)
        self.assertIn("one owned process footprint exceeds policy", reasons)
        self.assertIn("swap growth since admission exceeds policy", reasons)
        self.assertTrue(admission_reasons(snapshot))

    def test_old_swap_is_distinct_from_new_render_swap_growth(self) -> None:
        """A healthy baseline may retain old swap, but new growth is bounded."""
        baseline = replace(self.healthy(), swap_used_bytes=30 * GIB)
        self.assertEqual(admission_reasons(baseline), ())
        current = replace(baseline, swap_used_bytes=35 * GIB)
        self.assertEqual(stop_reasons(current, baseline),
                         ("swap growth since admission exceeds policy",))

    def test_pid_reuse_is_not_owned_work(self) -> None:
        """A valid numeric PID with a different start identity is rejected."""
        snapshot = parse_snapshot(raw_sample(), ProcessRequest(ProcessIdentity(100, "another start", 100)), GIB)
        self.assertEqual(snapshot.reused_registered_pids, (100,))
        self.assertEqual(snapshot.owned_pids, ())
        with patch("native_render_resources._read_command", return_value=raw_sample()["ps"]):
            self.assertFalse(verify_process_identity(ProcessIdentity(100, "another start", 100)))
            self.assertTrue(verify_process_identity(IDENTITY))

    def test_unbound_observation_cannot_authorize_lifecycle_action(self) -> None:
        """Initial PID discovery is observation until its start identity is bound."""
        snapshot = parse_snapshot(raw_sample(), ProcessRequest(ProcessIdentity(100)), 40 * GIB)
        self.assertFalse(snapshot.identity_verified)
        self.assertIn("owned root start identity was not bound", stop_reasons(snapshot, snapshot))
        with self.assertRaises(ValueError):
            verify_process_identity(ProcessIdentity(100))

    def test_missing_or_partial_measurements_never_mean_zero_pressure(self) -> None:
        """A missing process or system reading requires fresh authoritative data."""
        for key in ["top", "pressure", "sysctl", "ps"]:
            raw = raw_sample()
            del raw[key]
            with self.subTest(key=key), self.assertRaises(ResourceMeasurementError):
                parse_snapshot(raw, REQUEST, GIB)
        raw = raw_sample()
        raw["top"] = raw["top"].replace("101 1G 512M\n", "")
        with self.assertRaisesRegex(ResourceMeasurementError, "footprint missing"):
            parse_snapshot(raw, REQUEST, GIB)

    def test_unavailable_commands_propagate_instead_of_defaulting_healthy(self) -> None:
        """Sandbox/OS errors must prevent the supervisor from admitting a job."""
        with patch("native_render_resources.subprocess.run", side_effect=PermissionError("denied")):
            with self.assertLogs("native_render_resources", level="ERROR"):
                with self.assertRaises(ResourceMeasurementError):
                    read_snapshot(Path("/tmp"))

    def test_snapshot_age_and_small_host_budget_are_enforced(self) -> None:
        """An old healthy reading or a large-job budget on a small host is unsafe."""
        snapshot = self.healthy()
        stale = replace(snapshot, measured_at=snapshot.measured_at - 60)
        self.assertIn("resource measurement is stale or has an invalid timestamp",
                      admission_reasons(stale))
        smaller = replace(snapshot, physical_bytes=8 * GIB)
        self.assertIn("owned render footprint exceeds policy", stop_reasons(smaller, smaller))

    def test_invalid_policy_cannot_disable_resource_limits(self) -> None:
        """Reject NaN, infinity, booleans and invalid threshold ordering."""
        for value in [0, -1, float("nan"), float("inf"), True, "16"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ResourcePolicy(maximum_owned_gib=value)
        with self.assertRaises(ValueError):
            ResourcePolicy(stop_free_percent=30, admission_free_percent=20)

    def test_remembered_detached_child_survives_parent_exit(self) -> None:
        """A Chrome process reparented to launchd remains counted by pinned identity."""
        raw = raw_sample()
        raw["ps"] = f"101 1 101 {START}\n500 1 500 {START}\n"
        request = ProcessRequest(IDENTITY, (ProcessIdentity(101, START, 101),))
        snapshot = parse_snapshot(raw, request, 40 * GIB)
        self.assertEqual(snapshot.owned_pids, (101,))
        self.assertEqual(snapshot.missing_registered_pids, (100,))
        self.assertTrue(snapshot.identity_verified)
        self.assertEqual(snapshot.owned_footprint_bytes, GIB)

    def test_recycled_or_regrouped_remembered_pid_is_excluded(self) -> None:
        """Remembered IDs cannot capture an unrelated process or process group."""
        raw = raw_sample()
        raw["ps"] = f"101 1 999 {START}\n500 1 500 {START}\n"
        request = ProcessRequest(None, (ProcessIdentity(101, START, 101),))
        snapshot = parse_snapshot(raw, request, 40 * GIB)
        self.assertEqual(snapshot.owned_pids, ())
        self.assertEqual(snapshot.reused_registered_pids, (101,))
        self.assertFalse(snapshot.identity_verified)

    def test_literal_unused_ram_is_reserved_even_when_pressure_looks_healthy(self) -> None:
        """The pressure percentage includes reclaimable memory, not only free RAM."""
        snapshot = replace(self.healthy(), unused_physical_bytes=5 * GIB)
        self.assertIn("unused physical RAM is below the reserved host margin",
                      admission_reasons(snapshot))

    def test_measurement_commands_have_three_second_deadlines(self) -> None:
        """A stalled sampler must not leave the supervisor blind for a minute."""
        with patch("native_render_resources.subprocess.run", side_effect=TimeoutError("fixture")) as run:
            with self.assertLogs("native_render_resources", level="ERROR"):
                with self.assertRaises(ResourceMeasurementError):
                    read_snapshot(Path("/tmp"))
        self.assertEqual(run.call_args.kwargs["timeout"], 3)

    def test_mixed_valid_and_malformed_process_rows_fail_closed(self) -> None:
        """A broken child row must not silently reduce the owned footprint."""
        raw = raw_sample()
        raw["ps"] += "102 100 missing-group-and-start\n"
        with self.assertRaisesRegex(ResourceMeasurementError, "Malformed nonempty"):
            parse_snapshot(raw, REQUEST, 40 * GIB)

    def test_duplicate_process_pid_fails_closed(self) -> None:
        """An ambiguous table must not overwrite an owned process's ancestry."""
        raw = raw_sample()
        raw["ps"] += f"101 500 500 {START}\n"
        with self.assertRaisesRegex(ResourceMeasurementError, "Duplicate PID"):
            parse_snapshot(raw, REQUEST, 40 * GIB)

    def test_low_unused_is_runtime_warning_but_still_prevents_launch(self) -> None:
        """Replay the V3 shape without allowing cache use to mask other limits."""
        baseline = self.healthy()
        current = replace(baseline, unused_physical_bytes=int(5.791 * GIB),
                          owned_footprint_bytes=int(6.968 * GIB),
                          largest_owned_process_bytes=int(5.667 * GIB))
        self.assertEqual(stop_reasons(current, baseline), ())
        self.assertEqual(resource_warnings(current), admission_reasons(current))
        self.assertTrue(resource_warnings(current))

    def test_warning_and_critical_kernel_states_always_stop_and_deny_launch(self) -> None:
        """Userspace values 2 and 4 override otherwise healthy host readings."""
        for value, name in [(2, "warning"), (4, "critical")]:
            raw = raw_sample()
            raw["sysctl"] = raw["sysctl"].replace("pressure_level: 1", f"pressure_level: {value}")
            current = parse_snapshot(raw, REQUEST, 40 * GIB)
            with self.subTest(state=value):
                self.assertEqual(current.kernel_pressure_level, value)
                self.assertIn(f"kernel memory pressure is {name}", stop_reasons(current, self.healthy()))
                self.assertIn(f"kernel memory pressure is {name}", admission_reasons(current))

    def test_missing_unknown_and_internal_enum_kernel_states_fail_closed(self) -> None:
        """Never confuse the internal normal enum zero with sysctl normal one."""
        for value in ["0", "3", "8", "-1", "true", "", "1.0"]:
            raw = raw_sample()
            raw["sysctl"] = raw["sysctl"].replace("pressure_level: 1", f"pressure_level: {value}")
            with self.subTest(state=value), self.assertRaises(ResourceMeasurementError):
                parse_snapshot(raw, REQUEST, 40 * GIB)
        raw = raw_sample()
        raw["sysctl"] = raw["sysctl"].split("kern.memorystatus")[0]
        with self.assertRaises(ResourceMeasurementError):
            parse_snapshot(raw, REQUEST, 40 * GIB)

    def test_normal_pressure_does_not_waive_any_other_runtime_limit(self) -> None:
        """Low unused RAM is advisory; footprint, swap, compressor and disk are not."""
        baseline = self.healthy()
        low_unused = replace(baseline, unused_physical_bytes=5 * GIB)
        cases = [("owned_footprint_bytes", 17 * GIB, "owned render footprint"),
                 ("largest_owned_process_bytes", 16 * GIB, "one owned process"),
                 ("swap_used_bytes", baseline.swap_used_bytes + 5 * GIB, "swap growth"),
                 ("compressor_bytes", 17 * GIB, "compressor"),
                 ("free_percent", 9, "system memory headroom"),
                 ("disk_free_bytes", 9 * GIB, "disk headroom")]
        for field, value, reason in cases:
            current = replace(low_unused, **{field: value})
            with self.subTest(field=field):
                self.assertTrue(any(reason in item for item in stop_reasons(current, baseline)))
                self.assertTrue(resource_warnings(current))

    def test_invalid_in_memory_kernel_state_never_allows_runtime(self) -> None:
        """Even manually constructed unknown or boolean state must stop work."""
        for state in [0, 3, 8, True, None]:
            current = replace(self.healthy(), kernel_pressure_level=state)
            with self.subTest(state=state):
                self.assertIn("kernel memory pressure state is unrecognized",
                              stop_reasons(current, self.healthy()))


if __name__ == "__main__":
    unittest.main()
