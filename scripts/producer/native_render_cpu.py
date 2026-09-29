"""Identity-bound CPU deltas for one native owner, derived from its own resource samples.

Evidence only: nothing here admits, defers, stops or signals work. Each owned process
is keyed by PID and kernel start time (not the time-zone-formatted lstart or a group a
process may change), so a reused PID or reset counter is a different or regressed
identity, never a negative or borrowed delta. Host use is a ratio of fresh
per-processor ticks over the same Mach interval; every processor must have advanced
0.8-1.2x its tick rate. A clock that does not advance, ticks that do not fit, or an
identity break across more than 15 seconds yields no utilization rather than a guessed
one; longer intervals over continuous identities are exact and kept. Totals are lower
bounds: CPU after an identity's last sample, and processes that lived entirely between
samples, are unobserved.
"""
from __future__ import annotations

from collections import Counter

SCHEMA = 'native-owned-cpu-v1'
CONTINUITY_SECONDS = 15.0  # Same gap as native_render_policy; longer owned intervals need no breaks.
TICK_MODULUS = 2 ** 32  # natural_t processor-load counters wrap.
PROCESSOR_COVERAGE_BOUNDS = (.8, 1.2)  # One processor's ticks / (tick rate x interval); live 0.965-1.015.
CAPACITY_TOLERANCE = 1.1
SCOPE = ('Sampled rusage of recorded owned identities plus fresh per-processor ticks. '
         'Lower bound: CPU after an identity\'s last sample and processes living entirely '
         'between samples are unobserved. Diagnostic evidence; never a stop or admission input.')


def identity(row: object) -> tuple:
    """Kernel-exact identity: a recycled PID never continues an earlier process's counter."""
    return row.pid, row.process_start_abstime


def cpu_ns(row: object) -> int:
    """A process's own user plus system CPU; RUSAGE_INFO_V0 carries no child totals."""
    return row.cpu_user_ns + row.cpu_system_ns


def unusable(snapshot: object) -> str | None:
    """Name why a reading cannot anchor a CPU interval; None when it can."""
    host = snapshot.host_cpu
    if host is None:
        return 'sampler-has-no-cpu-counters'
    if host.status != 'measured' or not host.processor_ticks:
        return 'cpu-sampler-unavailable'
    if any(row.cpu_user_ns is None or row.cpu_system_ns is None for row in snapshot.processes):
        return 'process-cpu-counters-missing'
    if len({identity(row) for row in snapshot.processes}) != len(snapshot.processes):
        return 'duplicate-owned-identity'
    return None


def interval_seconds(previous: object, current: object) -> float:
    """Elapsed Mach time between two host reads, in seconds."""
    ticks = current.read_abstime - previous.read_abstime
    return ticks * current.timebase_numer / current.timebase_denom / 1e9


def contribution(row: object, before: dict, since: int) -> tuple[str, int]:
    """Classify one current identity and the nanoseconds it adds to this interval."""
    key, now = identity(row), cpu_ns(row)
    if key in before:
        if now < before[key]:
            return 'counterRegressionPids', 0
        return 'continued', now - before[key]
    if row.process_start_abstime is None or row.process_start_abstime < since:
        return 'unattributedPids', 0
    return 'started', now


def owned_interval(previous: object, current: object, seconds: float) -> dict:
    """Sum identity-bound deltas once per identity; exclude anything unprovable."""
    before = {identity(row): cpu_ns(row) for row in previous.processes}
    kinds, total, pids = Counter(), 0, {'counterRegressionPids': [], 'unattributedPids': []}
    for row in current.processes:
        kind, amount = contribution(row, before, previous.host_cpu.read_abstime)
        kinds[kind] += 1
        total += amount
        if kind in pids:
            pids[kind].append(row.pid)
    exited = len(before.keys() - {identity(row) for row in current.processes})
    if not current.processes:
        return {'status': 'unavailable', 'reason': 'no-owned-processes', 'exitedIdentities': exited}
    processors = len(current.host_cpu.processor_ticks)
    cores = total / 1e9 / seconds
    if cores > processors * CAPACITY_TOLERANCE + .1:
        return {'status': 'unavailable', 'reason': 'owned-cpu-exceeds-host-capacity', 'cores': cores}
    complete = not (exited or pids['counterRegressionPids'] or pids['unattributedPids'])
    if seconds > CONTINUITY_SECONDS and not complete:
        return {'status': 'unavailable', 'reason': 'identity-break-over-long-interval',
                'exitedIdentities': exited, **pids}
    return {'status': 'measured', 'cpuSeconds': total / 1e9, 'cores': cores,
            'hostFraction': cores / processors, 'completeness': 'complete' if complete else 'lower-bound',
            'identities': len(current.processes), 'newIdentities': kinds['started'],
            'exitedIdentities': exited, **pids}


def tick_deltas(previous: object, current: object) -> tuple[list[int], list[int], int]:
    """Per-state deltas summed over processors, each processor's total, and natural_t wraps."""
    states, totals, wrapped = [0, 0, 0, 0], [], 0
    for old, new in zip(previous.processor_ticks, current.processor_ticks):
        deltas = [(second - first) % TICK_MODULUS for first, second in zip(old, new)]
        wrapped += sum(second < first for first, second in zip(old, new))
        totals.append(sum(deltas))
        states = [state + delta for state, delta in zip(states, deltas)]
    return states, totals, wrapped


def host_interval(previous: object, current: object, seconds: float) -> dict:
    """Host busy share of fresh ticks; any processor that is stale or reset yields no share."""
    processors = len(current.processor_ticks)
    if processors != len(previous.processor_ticks):
        return {'status': 'unavailable', 'reason': 'processor-count-changed'}
    (user, system, idle, nice), totals, wrapped = tick_deltas(previous, current)
    expected = current.clock_ticks_per_second * seconds
    coverage = {'minimum': min(totals) / expected, 'maximum': max(totals) / expected}
    low, high = PROCESSOR_COVERAGE_BOUNDS
    if not max(totals):
        return {'status': 'unavailable', 'reason': 'host-counters-not-advancing'}
    if coverage['minimum'] < low or coverage['maximum'] > high:
        reason = 'host-counters-stale' if coverage['minimum'] < low else 'host-counters-reset'
        return {'status': 'unavailable', 'reason': reason, 'processorCoverage': coverage}
    busy = (user + system + nice) / sum(totals)
    return {'status': 'measured', 'busyFraction': busy, 'busyCores': busy * processors,
            'processorCount': processors, 'processorCoverage': coverage, 'wrappedCounters': wrapped,
            'ticks': {'user': user, 'system': system, 'idle': idle, 'nice': nice}}


def journal_record(record: dict) -> dict:
    """Keep raw processor ticks out of each resource line; its interval carries the deltas.

    The owner receipt's baseline and latest snapshot keep the raw counters.
    """
    host = record.get('host_cpu')
    if not isinstance(host, dict) or not host.get('processor_ticks'):
        return record
    compact = {key: value for key, value in host.items() if key != 'processor_ticks'}
    return record | {'host_cpu': compact | {'processor_count': len(host['processor_ticks'])}}


class CpuTracker:
    """Successive CPU readings of one owner (one stage) and their running summary."""

    def __init__(self) -> None:
        """Start with no reference reading and no observed identities."""
        self.previous = None
        self.peak_ns: dict[tuple, int] = {}
        self.readings: Counter = Counter()
        self.unavailable: Counter = Counter()
        self.owned = {'seconds': 0.0, 'cpuSeconds': 0.0, 'peakCores': None}
        self.host = {'seconds': 0.0, 'busySeconds': 0.0, 'peakBusyFraction': None, 'processorCount': None}

    def observe(self, snapshot: object) -> dict:
        """Record one interval against the last accepted reading; never guess a missing part."""
        problem = unusable(snapshot)
        if problem:
            error = snapshot.host_cpu.error if snapshot.host_cpu else None
            return self.record({'status': 'unavailable', 'reason': problem, 'error': error})
        for row in snapshot.processes:
            self.peak_ns[identity(row)] = max(self.peak_ns.get(identity(row), 0), cpu_ns(row))
        previous, self.previous = self.previous, snapshot
        if previous is None:
            return self.record({'status': 'baseline', 'reason': 'first-cpu-reading'})
        old, new = previous.host_cpu, snapshot.host_cpu
        if (old.timebase_numer, old.timebase_denom) != (new.timebase_numer, new.timebase_denom):
            return self.record({'status': 'unavailable', 'reason': 'timebase-changed'})
        seconds = interval_seconds(old, new)
        if seconds <= 0:
            self.previous = previous
            return self.record({'status': 'unavailable', 'reason': 'sample-clock-not-advancing'})
        return self.record({'status': 'measured', 'intervalSeconds': seconds,
                            'owned': owned_interval(previous, snapshot, seconds),
                            'host': host_interval(old, new, seconds)})

    def record(self, interval: dict) -> dict:
        """Accumulate a measured interval's parts into the stage summary."""
        interval = {'schema': SCHEMA, **interval}
        self.readings[interval['status']] += 1
        if interval['status'] == 'unavailable':
            self.unavailable[interval['reason']] += 1
        owned, host = interval.get('owned', {}), interval.get('host', {})
        if owned.get('status') == 'measured':
            self.owned['seconds'] += interval['intervalSeconds']
            self.owned['cpuSeconds'] += owned['cpuSeconds']
            self.owned['peakCores'] = max(self.owned['peakCores'] or 0.0, owned['cores'])
        if host.get('status') == 'measured':
            self.host['seconds'] += interval['intervalSeconds']
            self.host['busySeconds'] += host['busyFraction'] * interval['intervalSeconds']
            self.host['peakBusyFraction'] = max(self.host['peakBusyFraction'] or 0.0, host['busyFraction'])
            self.host['processorCount'] = host['processorCount']
        return interval

    def summary(self) -> dict:
        """Per-stage totals for the owner receipt; means cover measured intervals only."""
        owned, host = self.owned, self.host
        return {'schema': SCHEMA, 'observedOwnedCpuSeconds': sum(self.peak_ns.values()) / 1e9,
                'observedIdentities': len(self.peak_ns), 'readings': dict(self.readings),
                'unavailableReasons': dict(self.unavailable),
                'measuredOwnedSeconds': owned['seconds'], 'measuredOwnedCpuSeconds': owned['cpuSeconds'],
                'meanOwnedCores': owned['cpuSeconds'] / owned['seconds'] if owned['seconds'] else None,
                'peakOwnedCores': owned['peakCores'], 'measuredHostSeconds': host['seconds'],
                'meanHostBusyFraction': host['busySeconds'] / host['seconds'] if host['seconds'] else None,
                'peakHostBusyFraction': host['peakBusyFraction'], 'processorCount': host['processorCount'],
                'scope': SCOPE}
