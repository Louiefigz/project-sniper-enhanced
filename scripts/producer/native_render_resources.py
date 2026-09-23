"""Measure macOS native-render pressure and decide whether work can continue.

This module never launches or signals a render; its owner enforces decisions,
verifies identities and retains evidence. macOS top MEM includes compression:
do not add CMPRS or substitute RSS. Limits are policy, not qualified SDK caps.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import math
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Mapping

from native_render_processes import (
    ProcessFootprint, ProcessIdentity, ProcessRequest, ResourceMeasurementError,
    identity_matches, parse_size, process_table, read_identities,
    reconcile_process_request, select_processes, process_selection,
)
from native_render_measurements import parse_direct

GIB = 1024 ** 3
LOGGER = logging.getLogger(__name__)
# XNU sysctl converts its internal enum to these userspace notification masks.
# bsd/kern/kern_memorystatus_notify.c and bsd/sys/event_private.h (Apple XNU).
KERNEL_PRESSURE_NORMAL = 1
KERNEL_PRESSURE_NAMES = {1: "normal", 2: "warning", 4: "critical"}
SAFE_NATIVE_ENV = {
    "PRODUCER_LOW_MEMORY_MODE": "true",
    "PRODUCER_FRAME_DATA_URI_CACHE_LIMIT": "32",
    "PRODUCER_FRAME_DATA_URI_CACHE_BYTES_MB": "64",
    "PRODUCER_EXPERIMENTAL_FAST_CAPTURE": "false",
}


class ResourceCommandTimeout(ResourceMeasurementError):
    """Retain a bounded command timeout without accepting its partial reading."""

    def __init__(self, command: list[str], error: subprocess.TimeoutExpired) -> None:
        """Keep the exact command, timeout and partial bytes for the owner receipt."""
        self.identities: tuple[ProcessIdentity, ...] = ()
        partial = (error.stdout, error.stderr)
        encoded = [base64.b64encode(value.encode() if isinstance(value, str) else value or b'')
                   .decode('ascii') for value in partial]
        self.evidence = {'reason': 'resource-command-timeout', 'command': list(command),
                         'timeoutSeconds': error.timeout,
                         'stdoutBase64': encoded[0], 'stderrBase64': encoded[1]}
        super().__init__(f'Native resource command timed out: {command[0]}')

    def retain_readings(self, raw: dict[str, str], request: ProcessRequest) -> None:
        """Keep prior actual reads and observed ownership, never a partial snapshot."""
        self.evidence['completedReadings'] = dict(raw)
        if 'ps' not in raw:
            return
        observed = reconcile_process_request(raw['ps'], raw['ps'], request)
        self.identities = observed.remembered
        self.evidence['identities'] = [asdict(row) for row in self.identities]


@dataclass(frozen=True)
class ResourceSnapshot:
    """Live system pressure and the inclusive footprint of one owned tree."""

    measured_at: float
    physical_bytes: int
    free_percent: float
    swap_used_bytes: int
    compressor_bytes: int
    disk_free_bytes: int
    owned_footprint_bytes: int
    largest_owned_process_bytes: int
    owned_pids: tuple[int, ...]
    processes: tuple[ProcessFootprint, ...]
    identity_verified: bool
    unused_physical_bytes: int
    missing_registered_pids: tuple[int, ...]
    reused_registered_pids: tuple[int, ...]
    kernel_pressure_level: int
    memory_sampler: str = 'macos-top-v1'


@dataclass(frozen=True)
class ResourcePolicy:
    """Conservative initial limits; success still requires measured full runs."""

    admission_free_percent: float = 25
    stop_free_percent: float = 10
    maximum_compressor_fraction: float = 0.25
    maximum_owned_gib: float = 16
    maximum_process_gib: float = 8
    maximum_swap_growth_gib: float = 4
    minimum_disk_free_gib: float = 10
    minimum_unused_physical_gib: float = 6
    maximum_snapshot_age_seconds: float = 30

    def __post_init__(self) -> None:
        """Reject invalid or unbounded policies before any execution decision."""
        values = tuple(self.__dict__.values())
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in values):
            raise ValueError("Resource limits must be finite positive numbers")
        if any(not math.isfinite(x) or x <= 0 for x in values):
            raise ValueError("Resource limits must be finite positive numbers")
        if not self.stop_free_percent < self.admission_free_percent < 100:
            raise ValueError("Stop pressure threshold must precede admission headroom")
        if self.maximum_compressor_fraction >= 1:
            raise ValueError("Compressor fraction must be below one")


def _match(pattern: str, text: str) -> re.Match:
    """Require a measurement instead of substituting a healthy zero."""
    match = re.search(pattern, text)
    if not match:
        raise ResourceMeasurementError(f"Missing required measurement: {pattern}")
    return match


def _kernel_pressure(sysctl: str) -> int:
    """Require the userspace sysctl mask; internal enum zero is not normal here."""
    value = int(_match(r"(?m)^kern\.memorystatus_vm_pressure_level:\s*([0-9]+)[ \t]*$", sysctl)[1])
    if value not in KERNEL_PRESSURE_NAMES:
        raise ResourceMeasurementError(f"Unrecognized kernel memory pressure state: {value}")
    return value


def parse_snapshot(raw: Mapping[str, str], request: ProcessRequest,
                   disk_free_bytes: int) -> ResourceSnapshot:
    """Parse complete system output and one explicitly owned process tree."""
    if not {"sysctl", "pressure", "ps"} <= raw.keys():
        raise ResourceMeasurementError("Required resource measurement output is missing")
    physical = int(_match(r"hw.memsize:\s*(\d+)", raw["sysctl"])[1])
    swap = float(_match(r"used\s*=\s*([\d.]+)M", raw["sysctl"])[1])
    free = float(_match(r"System-wide memory free percentage:\s*([\d.]+)%", raw["pressure"])[1])
    memory = _memory_values(raw, request)
    if physical <= 0 or not 0 <= free <= 100 or disk_free_bytes < 0:
        raise ResourceMeasurementError("Invalid system capacity measurement")
    if 'direct' in raw and memory['compressor'] + memory['unused'] > physical:
        raise ResourceMeasurementError('Direct host memory counters exceed measured physical capacity')
    selected = memory['selection']
    processes = selected["processes"]
    kernel_pressure = _kernel_pressure(raw["sysctl"])
    footprints = [process.footprint_bytes for process in processes]
    return ResourceSnapshot(time.time(), physical, free, int(swap * 1024 ** 2),
                            memory['compressor'], disk_free_bytes, sum(footprints),
                            max(footprints, default=0), tuple(x.pid for x in processes), processes,
                            selected["verified"], memory['unused'], selected["missing"], selected["reused"],
                            kernel_pressure, memory['sampler'])


def _memory_values(raw: Mapping[str, str], request: ProcessRequest) -> dict:
    """Read either explicit historical top evidence or the current direct payload."""
    if ('top' in raw) == ('direct' in raw):
        raise ResourceMeasurementError('Exactly one explicit memory sampler payload is required')
    if 'direct' in raw:
        return parse_direct(raw['direct'], raw['ps'], request)
    return {'compressor': parse_size(_match(r'([\d.]+[BKMGT])\s+compressor', raw['top'])[1]),
        'unused': parse_size(_match(r'([\d.]+[BKMGT])\s+unused', raw['top'])[1]),
        'selection': select_processes(raw['ps'], raw['top'], request), 'sampler': 'macos-top-v1'}


def _read_command(args: list[str], input_text: str | None = None) -> str:
    """Run only a bounded read-only measurement, logging failures explicitly."""
    try:
        return subprocess.run(args, capture_output=True, text=True, check=True,
                              timeout=3, input=input_text).stdout
    except subprocess.TimeoutExpired as error:
        LOGGER.error("Native resource measurement timed out for %s: %s", args[0], error)
        raise ResourceCommandTimeout(args, error) from error
    except (OSError, subprocess.SubprocessError) as error:
        LOGGER.error("Native resource measurement failed for %s: %s", args[0], error)
        raise ResourceMeasurementError(f"Cannot measure native resources: {args[0]}") from error


def read_snapshot(directory: Path, request: ProcessRequest = ProcessRequest()) -> ResourceSnapshot:
    """Bracket footprint collection with identity reads; unknown live memory fails."""
    started = time.time()
    commands = {
        "sysctl": ["/usr/sbin/sysctl", "hw.memsize", "vm.swapusage",
                   "kern.memorystatus_vm_pressure_level"],
        "pressure": ["/usr/bin/memory_pressure", "-Q"],
        "ps": ["/bin/ps", "-axo", "pid=,ppid=,pgid=,lstart="],
    }
    raw = {}
    try:
        for name, args in commands.items():
            raw[name] = _read_command(args)
        pids = sorted(process_selection(raw['ps'], request)['owned'])
        raw['direct'] = _read_command([sys.executable, str(Path(__file__).with_name('native_render_macos.py')),
                                      *map(str, pids)])
        after = _read_command(commands["ps"])
    except ResourceCommandTimeout as error:
        error.retain_readings(raw, request)
        raise
    request = reconcile_process_request(raw["ps"], after, request)
    raw["ps"] = after
    snapshot = parse_snapshot(raw, request, shutil.disk_usage(directory).free)
    return replace(snapshot, measured_at=started)


def verify_process_identity(identity: ProcessIdentity) -> bool:
    """Recheck start identity before the owner considers any lifecycle action."""
    if identity.started is None or identity.pgid is None:
        raise ValueError("A start identity is required before lifecycle actions")
    processes = _read_command(["/bin/ps", "-axo", "pid=,ppid=,pgid=,lstart="])
    return identity_matches(process_table(processes), identity)


def _system_reasons(snapshot: ResourceSnapshot, policy: ResourcePolicy,
                    minimum_free: float, now: float) -> list[str]:
    """Check measured headroom while keeping old swap use distinct from growth."""
    reasons = []
    age = now - snapshot.measured_at
    if age < 0 or age > policy.maximum_snapshot_age_seconds:
        reasons.append("resource measurement is stale or has an invalid timestamp")
    if type(snapshot.kernel_pressure_level) is not int or snapshot.kernel_pressure_level not in KERNEL_PRESSURE_NAMES:
        reasons.append("kernel memory pressure state is unrecognized")
    elif snapshot.kernel_pressure_level != KERNEL_PRESSURE_NORMAL:
        reasons.append("kernel memory pressure is " + KERNEL_PRESSURE_NAMES[snapshot.kernel_pressure_level])
    if snapshot.free_percent < minimum_free:
        reasons.append("system memory headroom is below policy")
    if snapshot.compressor_bytes > snapshot.physical_bytes * policy.maximum_compressor_fraction:
        reasons.append("physical memory occupied by the compressor exceeds policy")
    if snapshot.disk_free_bytes < policy.minimum_disk_free_gib * GIB:
        reasons.append("disk headroom for output and OS swap is below policy")
    return reasons


def resource_warnings(snapshot: ResourceSnapshot,
                      policy: ResourcePolicy = ResourcePolicy()) -> tuple[str, ...]:
    """Record low unused RAM without confusing reclaimable cache with pressure."""
    if snapshot.unused_physical_bytes < policy.minimum_unused_physical_gib * GIB:
        return ("unused physical RAM is below the reserved host margin",)
    return ()


def admission_reasons(snapshot: ResourceSnapshot,
                      policy: ResourcePolicy = ResourcePolicy()) -> tuple[str, ...]:
    """Return reasons to defer a launch; an empty tuple permits one worker only."""
    reasons = _system_reasons(snapshot, policy, policy.admission_free_percent, time.time())
    return tuple(reasons) + resource_warnings(snapshot, policy)


def owned_reasons(snapshot: ResourceSnapshot, policy: ResourcePolicy) -> list[str]:
    """Apply identical process ownership and hard footprint limits in both modes."""
    maximum_owned = min(policy.maximum_owned_gib * GIB, snapshot.physical_bytes * 0.25)
    checks = [
        (not snapshot.owned_pids, "ongoing render has no measured owned process tree"),
        (not snapshot.identity_verified, "owned root start identity was not bound"),
        (snapshot.owned_footprint_bytes > maximum_owned, "owned render footprint exceeds policy"),
        (snapshot.largest_owned_process_bytes > policy.maximum_process_gib * GIB,
         "one owned process footprint exceeds policy")]
    return [reason for failed, reason in checks if failed]


def stop_reasons(snapshot: ResourceSnapshot, baseline: ResourceSnapshot,
                 policy: ResourcePolicy = ResourcePolicy()) -> tuple[str, ...]:
    """Return reasons for the owning supervisor to stop its verified render tree."""
    reasons = _system_reasons(snapshot, policy, policy.stop_free_percent, time.time())
    reasons += owned_reasons(snapshot, policy)
    if snapshot.swap_used_bytes - baseline.swap_used_bytes > policy.maximum_swap_growth_gib * GIB:
        reasons.append("swap growth since admission exceeds policy")
    return tuple(reasons)


def main() -> None:
    """Print a read-only JSON sample; this command never launches or signals work."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--root-pid", type=int)
    parser.add_argument("--root-start")
    parser.add_argument("--root-pgid", type=int)
    parser.add_argument("--identities-file", type=Path)
    args = parser.parse_args()
    if (args.root_start is not None or args.root_pgid is not None) and args.root_pid is None:
        parser.error("--root-start and --root-pgid require --root-pid")
    identity = ProcessIdentity(args.root_pid, args.root_start, args.root_pgid) if args.root_pid is not None else None
    try:
        remembered = read_identities(args.identities_file) if args.identities_file else ()
        snapshot = read_snapshot(args.directory, ProcessRequest(identity, remembered))
        result = {"snapshot": asdict(snapshot), "admissionReasons": admission_reasons(snapshot),
                  "warnings": resource_warnings(snapshot),
                  "initialWorkers": 1, "nativeEnvironment": SAFE_NATIVE_ENV,
                  "scope": "Resource measurement only; no render or quality qualification."}
    except (ResourceMeasurementError, ValueError, OSError) as error:
        print(json.dumps({"status": "measurement-unavailable", "error": str(error),
                          "measurementEvidence": getattr(error, "evidence", None)}))
        raise SystemExit(2) from error
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
