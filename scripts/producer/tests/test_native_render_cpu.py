"""Identity-bound CPU deltas and the owner's CPU evidence, without processes or media."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from native_render_cpu import CONTINUITY_SECONDS, CpuTracker, journal_record
from native_render_deferral import launch_deferral
from native_render_macos import CPU_SOURCE
from native_render_measurements import HostCpuSample
from native_render_processes import ProcessIdentity, ProcessRequest
from native_render_resources import GIB, ResourceSnapshot, parse_snapshot
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig
from studio.native_runtime import digest
from test_native_render_policy import POOL_RECORD, PROFILE, policy_snapshot
from test_native_render_resources import IDENTITY, REQUEST, START, direct_sample, raw_sample
from _native_pool_fixture import pool_lease_double

TICKS_PER_SECOND = 24_000_000  # Mach ticks per second with the 125/3 Apple Silicon timebase.
DIRECT = parse_snapshot(direct_sample(), REQUEST, 40 * GIB)


def host(seconds: float, busy: float = .25, processors: int = 16) -> HostCpuSample:
    """Cumulative processor ticks at a constant busy share, read at ``seconds``."""
    rows = tuple((round(busy * 100 * seconds), 0, round((1 - busy) * 100 * seconds), 0)
                 for _ in range(processors))
    return HostCpuSample('measured', CPU_SOURCE, round(seconds * TICKS_PER_SECOND), 125, 3, 100, rows)


def advance(cpu: HostCpuSample, seconds: float, busy: float) -> HostCpuSample:
    """Continue cumulative processor ticks for ``seconds`` at a new busy share."""
    rows = tuple((user + round(busy * 100 * seconds), system, idle + round((1 - busy) * 100 * seconds), nice)
                 for user, system, idle, nice in cpu.processor_ticks)
    return replace(cpu, read_abstime=cpu.read_abstime + round(seconds * TICKS_PER_SECOND), processor_ticks=rows)


def process(pid: int, cpu_seconds: float, start: float = 0.0, started: str = START) -> object:
    """An owned process with ``cpu_seconds`` of its own CPU, started at ``start`` seconds."""
    return replace(DIRECT.processes[0], pid=pid, pgid=pid, started=started,
                   process_start_abstime=round(start * TICKS_PER_SECOND) + 1,
                   cpu_user_ns=round(cpu_seconds * 1e9), cpu_system_ns=0)


def reading(seconds: float, rows: tuple, cpu: HostCpuSample | None = None) -> ResourceSnapshot:
    """One complete owned-tree reading at ``seconds`` on the Mach clock."""
    return replace(DIRECT, processes=tuple(rows), owned_pids=tuple(row.pid for row in rows),
                   host_cpu=cpu or host(seconds))


class CpuTrackerTests(unittest.TestCase):
    """Deltas bind to kernel identities; unprovable intervals report no utilization."""

    def test_continuing_identities_yield_exact_owned_and_host_use(self) -> None:
        """Two browser processes over five seconds: 7.5 CPU-seconds is 1.5 cores."""
        tracker = CpuTracker()
        self.assertEqual(tracker.observe(reading(100, (process(100, 10), process(101, 4))))['status'],
                         'baseline')
        later = advance(host(100), 5, .5)
        interval = tracker.observe(reading(105, (process(100, 15), process(101, 6.5)), later))
        self.assertEqual(interval['status'], 'measured')
        self.assertAlmostEqual(interval['intervalSeconds'], 5)
        self.assertAlmostEqual(interval['owned']['cpuSeconds'], 7.5)
        self.assertAlmostEqual(interval['owned']['cores'], 1.5)
        self.assertAlmostEqual(interval['owned']['hostFraction'], 1.5 / 16)
        self.assertEqual(interval['owned']['completeness'], 'complete')
        self.assertEqual(interval['host']['status'], 'measured')
        self.assertAlmostEqual(interval['host']['processorCoverage']['minimum'], 1, places=3)
        self.assertAlmostEqual(interval['host']['processorCoverage']['maximum'], 1, places=3)
        self.assertAlmostEqual(interval['host']['busyFraction'], .5)
        self.assertAlmostEqual(interval['host']['busyCores'], 8)

    def test_reused_pid_is_a_new_identity_never_a_negative_or_borrowed_delta(self) -> None:
        """A recycled PID with a smaller counter is exit plus birth, not a counter drop."""
        tracker = CpuTracker()
        tracker.observe(reading(100, (process(100, 10), process(101, 40))))
        reborn = process(101, 1, start=102, started='Wed Sep  9 09:00:02 2026')
        interval = tracker.observe(reading(105, (process(100, 12), reborn)))
        owned = interval['owned']
        self.assertAlmostEqual(owned['cpuSeconds'], 3)
        self.assertEqual((owned['newIdentities'], owned['exitedIdentities']), (1, 1))
        self.assertEqual(owned['counterRegressionPids'], [])
        self.assertEqual(owned['completeness'], 'lower-bound')
        self.assertAlmostEqual(tracker.summary()['observedOwnedCpuSeconds'], 12 + 40 + 1)

    def test_identity_seen_first_after_it_started_is_unattributed(self) -> None:
        """Lifetime CPU of a process that predates the reference reading is not interval use."""
        tracker = CpuTracker()
        tracker.observe(reading(100, (process(100, 10),)))
        late = process(102, 50, start=90)
        owned = tracker.observe(reading(105, (process(100, 11), late)))['owned']
        self.assertAlmostEqual(owned['cpuSeconds'], 1)
        self.assertEqual(owned['unattributedPids'], [102])
        self.assertEqual(owned['completeness'], 'lower-bound')

    def test_counter_reset_is_excluded_and_the_highest_observation_is_kept(self) -> None:
        """A same-identity counter that falls contributes nothing and is named."""
        tracker = CpuTracker()
        tracker.observe(reading(100, (process(100, 10), process(101, 30))))
        owned = tracker.observe(reading(105, (process(100, 12), process(101, 2))))['owned']
        self.assertAlmostEqual(owned['cpuSeconds'], 2)
        self.assertEqual(owned['counterRegressionPids'], [101])
        self.assertEqual(owned['completeness'], 'lower-bound')
        self.assertAlmostEqual(tracker.summary()['observedOwnedCpuSeconds'], 12 + 30)

    def test_stale_or_repeated_reading_keeps_the_older_reference(self) -> None:
        """No elapsed Mach time means no utilization; the next fresh reading still measures."""
        tracker = CpuTracker()
        first = reading(100, (process(100, 10),))
        tracker.observe(first)
        for stale in (first, reading(99, (process(100, 9),))):
            with self.subTest(read=stale.host_cpu.read_abstime):
                result = tracker.observe(stale)
                self.assertEqual((result['status'], result['reason']),
                                 ('unavailable', 'sample-clock-not-advancing'))
                self.assertNotIn('owned', result)
        fresh = tracker.observe(reading(104, (process(100, 12),)))
        self.assertAlmostEqual(fresh['intervalSeconds'], 4)
        self.assertAlmostEqual(fresh['owned']['cpuSeconds'], 2)
        self.assertEqual(tracker.summary()['unavailableReasons'], {'sample-clock-not-advancing': 2})

    def test_host_ticks_that_do_not_advance_or_cover_the_interval_report_no_share(self) -> None:
        """Cached or stuck host counters never become idle or busy CPU."""
        cases = [(host(100), 'host-counters-not-advancing'), (host(101), 'host-counters-stale')]
        for cpu, reason in cases:
            tracker = CpuTracker()
            tracker.observe(reading(100, (process(100, 10),)))
            later = replace(cpu, read_abstime=105 * TICKS_PER_SECOND)
            with self.subTest(reason=reason):
                interval = tracker.observe(reading(105, (process(100, 11),), later))
                self.assertEqual(interval['host']['reason'], reason)
                self.assertNotIn('busyFraction', interval['host'])
                self.assertEqual(interval['owned']['status'], 'measured')

    def test_natural_t_wrap_is_exact_but_a_counter_reset_is_rejected(self) -> None:
        """Modular deltas are accepted only while they fit the elapsed ticks."""
        start = host(100)
        pairs = [((2 ** 32 - 100, 0, 1000, 0), (300, 0, 1500, 0)),  # 400 busy + 500 idle ticks
                 ((100_000, 0, 1000, 0), (5, 0, 1500, 0))]  # A drop far from the wrap point
        results = []
        for before, after in pairs:
            tracker = CpuTracker()
            earlier = replace(start, processor_ticks=(before,) * 16)
            tracker.observe(reading(100, (process(100, 1),), earlier))
            cpu = replace(start, read_abstime=109 * TICKS_PER_SECOND, processor_ticks=(after,) * 16)
            results.append(tracker.observe(reading(109, (process(100, 2),), cpu))['host'])
        self.assertEqual(results[0]['status'], 'measured')
        self.assertEqual(results[0]['wrappedCounters'], 16)
        self.assertAlmostEqual(results[0]['busyFraction'], 400 / 900)
        self.assertEqual(results[1]['reason'], 'host-counters-reset')

    def test_long_continuous_intervals_are_kept_but_identity_breaks_are_not(self) -> None:
        """Counters over a calm or busy minute are exact; an exit across it is not provable."""
        tracker = CpuTracker()
        tracker.observe(reading(100, (process(100, 10), process(101, 5))))
        long = CONTINUITY_SECONDS * 4
        busy = tracker.observe(reading(100 + long, (process(100, 70), process(101, 35)),
                                       advance(host(100), long, .75)))
        self.assertEqual((busy['owned']['status'], busy['host']['status']), ('measured', 'measured'))
        self.assertAlmostEqual(busy['owned']['cores'], 1.5)
        self.assertAlmostEqual(busy['host']['busyFraction'], .75)
        broken = tracker.observe(reading(100 + 2 * long, (process(100, 80),),
                                         advance(advance(host(100), long, .75), long, .5)))
        self.assertEqual(broken['owned']['reason'], 'identity-break-over-long-interval')
        self.assertEqual(broken['host']['status'], 'measured')
        short = tracker.observe(reading(100 + 2 * long + 5, (process(100, 81), process(102, 1, start=100 + 2 * long + 1)),
                                        advance(advance(advance(host(100), long, .75), long, .5), 5, .5)))
        self.assertEqual(short['owned']['completeness'], 'complete')
        self.assertAlmostEqual(tracker.summary()['measuredOwnedSeconds'], long + 5)

    def test_changed_processor_set_reports_no_host_share(self) -> None:
        """Deltas across a different processor count are not comparable."""
        tracker = CpuTracker()
        tracker.observe(reading(100, (process(100, 10),)))
        changed = tracker.observe(reading(105, (process(100, 11),), host(105, processors=8)))
        self.assertEqual(changed['host']['reason'], 'processor-count-changed')

    def test_every_processor_must_advance_with_the_interval(self) -> None:
        """A frozen idle counter or one stalled processor cannot inflate the busy share."""
        start = host(100, .55)
        frozen_idle = replace(start, read_abstime=105 * TICKS_PER_SECOND, processor_ticks=tuple(
            (user + 275, system, idle, nice) for user, system, idle, nice in start.processor_ticks))
        advanced = advance(start, 5, .55)
        stalled = replace(advanced, processor_ticks=start.processor_ticks[:1] + advanced.processor_ticks[1:])
        for later, minimum in ((frozen_idle, .55), (stalled, 0.0)):
            tracker = CpuTracker()
            tracker.observe(reading(100, (process(100, 10),), start))
            with self.subTest(minimum=minimum):
                result = tracker.observe(reading(105, (process(100, 11),), later))['host']
                self.assertEqual(result['reason'], 'host-counters-stale')
                self.assertAlmostEqual(result['processorCoverage']['minimum'], minimum)
                self.assertNotIn('busyFraction', result)

    def test_identity_is_pid_and_kernel_start_not_time_zone_text_or_group(self) -> None:
        """A time-zone change in lstart or a setpgid keeps one identity and one delta."""
        tracker = CpuTracker()
        tracker.observe(reading(100, (process(100, 10),)))
        moved = replace(process(100, 13), started='Wed Sep  9 16:00:00 2026', pgid=4242)
        owned = tracker.observe(reading(105, (moved,)))['owned']
        self.assertAlmostEqual(owned['cpuSeconds'], 3)
        self.assertEqual((owned['newIdentities'], owned['exitedIdentities'], owned['completeness']),
                         (0, 0, 'complete'))
        summary = tracker.summary()
        self.assertEqual(summary['observedIdentities'], 1)
        self.assertAlmostEqual(summary['observedOwnedCpuSeconds'], 13)

    def test_journal_lines_drop_raw_processor_ticks_but_keep_their_count(self) -> None:
        """Each resource line stays small; the interval already carries tick deltas."""
        record = {'host_cpu': {'status': 'measured', 'read_abstime': 5, 'processor_ticks': [[1, 2, 3, 4]] * 16},
                  'cpu': {'status': 'measured'}}
        line = journal_record(record)
        self.assertEqual(line['host_cpu'], {'status': 'measured', 'read_abstime': 5, 'processor_count': 16})
        self.assertEqual(len(record['host_cpu']['processor_ticks']), 16)
        for unchanged in ({'host_cpu': None}, {'host_cpu': {'status': 'unavailable', 'processor_ticks': []}}):
            self.assertIs(journal_record(unchanged), unchanged)

    def test_impossible_owned_use_is_rejected(self) -> None:
        """More CPU-seconds than the host's processors could supply is a bad reading."""
        tracker = CpuTracker()
        tracker.observe(reading(100, (process(100, 10),)))
        interval = tracker.observe(reading(101, (process(100, 40),)))
        self.assertEqual(interval['owned']['reason'], 'owned-cpu-exceeds-host-capacity')
        self.assertIsNone(tracker.summary()['meanOwnedCores'])

    def test_shared_browser_descendant_is_selected_and_counted_once(self) -> None:
        """A child reached by ancestry, group and memory contributes one delta."""
        raw = direct_sample()
        raw['ps'] = f'100 1 100 {START}\n101 100 100 {START}\n500 1 500 {START}\n'
        request = ProcessRequest(IDENTITY, (ProcessIdentity(101, START, 100), IDENTITY))
        first = parse_snapshot(raw, request, 40 * GIB)
        self.assertEqual(first.owned_pids, (100, 101))
        later = replace(first, host_cpu=replace(first.host_cpu, read_abstime=first.host_cpu.read_abstime
                                                + 5 * TICKS_PER_SECOND),
                        processes=tuple(replace(row, cpu_user_ns=row.cpu_user_ns + 2 * 10 ** 9)
                                        for row in first.processes))
        tracker = CpuTracker()
        tracker.observe(first)
        ticks = tuple(tuple(value + 250 * (index == 2) + 250 * (index == 0) for index, value in enumerate(row))
                      for row in first.host_cpu.processor_ticks)
        interval = tracker.observe(replace(later, host_cpu=replace(later.host_cpu, processor_ticks=ticks)))
        self.assertAlmostEqual(interval['owned']['cpuSeconds'], 4)
        self.assertEqual(interval['owned']['identities'], 2)

    def test_duplicate_identities_are_refused_instead_of_summed(self) -> None:
        """Two rows for one kernel identity cannot double one process's CPU."""
        tracker = CpuTracker()
        result = tracker.observe(reading(100, (process(100, 10), process(100, 10))))
        self.assertEqual(result['reason'], 'duplicate-owned-identity')
        self.assertEqual(tracker.summary()['observedIdentities'], 0)

    def test_samplers_without_cpu_stay_unknown(self) -> None:
        """Historical top rows and an unavailable CPU reader are not zero use."""
        tracker = CpuTracker()
        top = parse_snapshot(raw_sample(), REQUEST, 40 * GIB)
        self.assertEqual(tracker.observe(top)['reason'], 'sampler-has-no-cpu-counters')
        denied = replace(DIRECT, host_cpu=HostCpuSample('unavailable', error='OSError: denied'))
        result = tracker.observe(denied)
        self.assertEqual((result['reason'], result['error']), ('cpu-sampler-unavailable', 'OSError: denied'))
        missing = replace(DIRECT, processes=(replace(DIRECT.processes[0], cpu_user_ns=None),))
        self.assertEqual(tracker.observe(missing)['reason'], 'process-cpu-counters-missing')
        self.assertEqual(tracker.summary()['readings'], {'unavailable': 3})
        self.assertEqual(tracker.summary()['observedOwnedCpuSeconds'], 0)

    def test_summary_means_cover_measured_intervals_only(self) -> None:
        """Stage totals weight each measured interval by its own length."""
        tracker, first = CpuTracker(), host(100, .2)
        second = advance(first, 5, .2)
        tracker.observe(reading(100, (process(100, 10),), first))
        tracker.observe(reading(105, (process(100, 15),), second))
        tracker.observe(reading(105, (process(100, 15),), second))
        tracker.observe(reading(115, (process(100, 20),), advance(second, 10, .8)))
        summary = tracker.summary()
        self.assertAlmostEqual(summary['measuredOwnedSeconds'], 15)
        self.assertAlmostEqual(summary['meanOwnedCores'], 10 / 15)
        self.assertAlmostEqual(summary['peakOwnedCores'], 1)
        self.assertAlmostEqual(summary['meanHostBusyFraction'], (.2 * 5 + .8 * 10) / 15, places=3)
        self.assertEqual(summary['readings'], {'baseline': 1, 'measured': 2, 'unavailable': 1})


class OwnerCpuEvidenceTests(unittest.TestCase):
    """The real owner journals CPU per sample and per stage; CPU never stops or resizes it."""

    def setUp(self) -> None:
        """Non-media fixtures with a lease double; no browser, encoder or host pool."""
        temporary = tempfile.TemporaryDirectory(prefix='native-cpu-owner-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        project, output = root / 'project', root / 'output'
        project.mkdir()
        output.mkdir()
        cli, sandbox = root / 'cli.js', root / 'sandbox.sb'
        cli.write_text('TEST executable')
        sandbox.write_text('TEST sandbox')
        self.settings = NativeRunConfig(project, output, cli, ['TEST-NO-LAUNCH'], {},
            {'output': str(output / 'result.bin'), 'sdkSha256': digest(cli),
             'sandboxSha256': digest(sandbox)}, sandbox=sandbox)
        self.wall = time.time() - 20
        self.cpu = host(100)
        self.baseline = replace(policy_snapshot(), measured_at=self.wall, processes=(), owned_pids=(),
                                host_cpu=self.cpu)
        self.lease = pool_lease_double()
        self.enterContext(patch('studio.native_run.NativeWorkLease.acquire', return_value=self.lease))
        self.enterContext(patch('builtins.print'))

    def prepare_owner(self) -> NativeRun:
        """Real prelaunch admission, then an explicitly fake live registry."""
        owner = NativeRun('TEST', self.settings)
        self.addCleanup(self.close_owner, owner)
        with patch.object(owner, 'measure_resources', return_value=self.baseline):
            owner.prepare()
        owner.child = Mock(pid=100)
        owner.child.poll.return_value = None
        owner.registry = Mock(known={100: ProcessIdentity(100, START, 100)})
        owner.registry.cleanup.return_value = {'verified': True, 'TEST': 'mock child absent'}
        return owner

    def close_owner(self, owner: NativeRun) -> None:
        """Release test-owned files and restore the caller's signal handlers."""
        owner.cleanup()
        owner.release_lease()
        for handle in (owner.log, owner.samples):
            if handle is not None:
                handle.close()
        owner.signal_handlers.restore()

    def sample(self, owner: NativeRun, seconds: float, rows: tuple, busy: float) -> None:
        """Feed one owned reading through the owner's actual sample method."""
        self.cpu = advance(self.cpu, seconds - self.cpu.read_abstime / TICKS_PER_SECOND, busy)
        footprint = sum(row.footprint_bytes for row in rows)
        current = replace(self.baseline, measured_at=self.wall + seconds - 99, processes=rows,
                          owned_pids=tuple(row.pid for row in rows), host_cpu=self.cpu,
                          owned_footprint_bytes=footprint, largest_owned_process_bytes=footprint)
        with patch.object(owner, 'measure_resources', return_value=current), \
                patch('studio.native_run.time.monotonic', return_value=seconds):
            owner.sample()

    def test_admission_records_cpu_evidence_and_disabled_deferral(self) -> None:
        """No qualified profile exists, so admission records CPU and launches."""
        owner = self.prepare_owner()
        receipt = json.loads(owner.path.read_text())
        self.assertEqual(receipt['cpuAtAdmission']['status'], 'baseline')
        deferral = receipt['cpuLaunchDeferral']
        self.assertEqual((deferral['enabled'], deferral['decision'], deferral['reasons']), (False, 'launch', []))
        self.assertIn('No qualified CPU launch-deferral profile exists', deferral['why'])
        self.assertEqual(receipt['admissionReasons'], [])
        self.assertEqual(receipt['cpuDeferralSeconds'], 0)

    def test_saturated_cpu_is_journaled_but_never_stops_or_resizes_healthy_work(self) -> None:
        """Every processor busy and a small tree: evidence only, same policy and reservation."""
        owner = self.prepare_owner()
        policy, bound = owner.policy, dict(owner.result['poolReservationBound'])
        small = int(.05 * GIB)
        self.sample(owner, 101, (replace(process(100, 1, start=100.5), footprint_bytes=small),), .999)
        self.sample(owner, 106, (replace(process(100, 17, start=100.5), footprint_bytes=small),), .999)
        self.assertIsNone(owner.abort_reason)
        self.assertIs(owner.policy, policy)
        self.assertEqual(owner.result['poolReservationBound'], bound)
        self.assertEqual(self.lease.reservation_bytes, bound['reservationBytes'])
        rows = [json.loads(line) for line in Path(owner.samples.name).read_text().splitlines()]
        self.assertEqual([row['cpu']['status'] for row in rows], ['measured', 'measured'])
        self.assertAlmostEqual(rows[0]['cpu']['owned']['cpuSeconds'], 1)
        self.assertAlmostEqual(rows[1]['cpu']['owned']['cores'], 16 / 5)
        self.assertGreater(rows[1]['cpu']['host']['busyFraction'], .99)
        self.assertFalse(rows[1]['guard']['stopReasons'])
        self.assertEqual({row['host_cpu']['processor_count'] for row in rows}, {16})
        self.assertFalse([row for row in rows if 'processor_ticks' in row['host_cpu']])
        receipt = json.loads(owner.path.read_text())
        self.assertEqual(len(receipt['latestResourceSnapshot']['host_cpu']['processor_ticks']), 16)
        self.assertEqual(len(receipt['baseline']['host_cpu']['processor_ticks']), 16)
        stage = receipt['cpu']
        self.assertAlmostEqual(stage['observedOwnedCpuSeconds'], 17)
        self.assertEqual(stage['processorCount'], 16)

    def admit_with_profile(self, readings: list) -> tuple[NativeRun, list, list]:
        """Real admission with a TEST profile injected behind the hook; admission passes None.

        Returns the owner, each hook decision and the receipt persisted at every wait.
        """
        self.lease.admission = {'mode': 'qualified', 'modeRecord': {'sha256': POOL_RECORD}}
        self.settings = replace(self.settings, capacity_wait_seconds=600)
        owner, decisions, waits, clock = NativeRun('TEST', self.settings), [], [], [time.monotonic()]
        self.addCleanup(self.close_owner, owner)
        def sleep(seconds: float) -> None:
            waits.append(json.loads(owner.path.read_text()))
            clock[0] += seconds
        def qualified(request: object, profile: object) -> dict:
            self.assertIsNone(profile)  # Admission itself supplies no profile.
            decisions.append(launch_deferral(request, PROFILE))
            return decisions[-1]
        with patch.object(owner, 'measure_resources', side_effect=readings), \
                patch('studio.native_run_admission.time', Mock(monotonic=lambda: clock[0], sleep=sleep)), \
                patch('studio.native_run_admission.launch_deferral', side_effect=qualified):
            owner.prepare()
        return owner, decisions, waits

    def busy_readings(self, pattern: list) -> list:
        """Baselines two seconds apart: 'pressure' blocks memory admission; a float is the host
        busy share over the two seconds before that reading."""
        readings, cpu = [], self.cpu
        for index, item in enumerate(pattern):
            cpu = advance(cpu, 2, .5 if item == 'pressure' else item) if index else cpu
            changes = {'kernel_pressure_level': 2} if item == 'pressure' else {}
            readings.append(replace(self.baseline, host_cpu=cpu, **changes))
        return readings

    def test_a_qualified_profile_would_hold_then_launch_through_real_admission(self) -> None:
        """Interface proof only: holds need a measured busy interval and end at the budget.

        The first reading is a baseline, so the hold starts only after a memory wait
        produced an interval; CPU holds are counted apart from pressure waits.
        """
        owner, decisions, waits = self.admit_with_profile(self.busy_readings(['pressure'] + [.9] * 31))
        self.assertEqual([item['decision'] for item in decisions], ['defer'] * 30 + ['launch'])
        self.assertIn('host busy 0.900 >= 0.800', decisions[0]['why'])
        self.assertEqual(decisions[-1]['why'], 'qualified deferral time is exhausted')
        receipt = json.loads(owner.path.read_text())
        self.assertEqual((receipt['status'], receipt['admissionReasons']), ('preparing', []))
        self.assertAlmostEqual(receipt['pressureWaitSeconds'], 2)
        self.assertAlmostEqual(receipt['cpuDeferralSeconds'], 60)
        self.assertEqual(waits[0]['cpuLaunchDeferral']['decision'], 'not-evaluated')
        self.lease.mark_launching.assert_called_once()

    def test_each_poll_records_its_own_deferral_outcome(self) -> None:
        """A memory wait after a CPU hold never leaves the earlier hold in the receipt."""
        owner, decisions, waits = self.admit_with_profile(self.busy_readings(['pressure', .9, 'pressure', .9, .1]))
        self.assertEqual([item['cpuLaunchDeferral']['decision'] for item in waits],
                         ['not-evaluated', 'defer', 'not-evaluated', 'defer'])
        self.assertEqual([item['decision'] for item in decisions], ['defer', 'defer', 'launch'])
        receipt = json.loads(owner.path.read_text())
        self.assertEqual(receipt['cpuLaunchDeferral']['why'], 'host CPU is below the qualified threshold')
        self.assertAlmostEqual(receipt['pressureWaitSeconds'], 4)
        self.assertAlmostEqual(receipt['cpuDeferralSeconds'], 4)

    def test_without_a_measured_interval_a_profile_launches_at_once(self) -> None:
        """A first baseline reading never holds every launch for a poll."""
        owner, decisions, waits = self.admit_with_profile(self.busy_readings([.9]))
        self.assertEqual([item['decision'] for item in decisions], ['launch'])
        self.assertEqual(waits, [])
        self.assertEqual(json.loads(owner.path.read_text())['cpuDeferralSeconds'], 0)


if __name__ == '__main__':
    unittest.main()
