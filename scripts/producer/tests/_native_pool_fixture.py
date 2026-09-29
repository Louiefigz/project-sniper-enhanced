"""Shared TEST helpers for the host work pool: isolated namespaces, legacy fences, doubles.

Nothing here touches the canonical /private/tmp/sniper-native-work-<uid> namespace or
the per-user qualification record: every helper patches state_root() to a private
temporary directory (which also disables the host record) before any pool call.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import native_work_lease as work
from native_render_resources import GIB

EXCLUSIVE_RESERVATION = 16 * GIB


def pool_lease_double(reservation: int = EXCLUSIVE_RESERVATION) -> mock.Mock:
    """A TEST lease double exposing the pool member protocol NativeRun reads."""
    lease = mock.Mock()
    lease.reservation_bytes = reservation
    lease.admission = {'mode': 'TEST-double', 'reservationBytes': reservation,
                       'scope': 'TEST double; not a host admission'}
    lease.retire_processes.return_value = []  # Every retired row reported absent.
    return lease


def isolate_pool(case: unittest.TestCase) -> Path:
    """Patch the pool namespace to a private temporary root for this test only."""
    temporary = tempfile.TemporaryDirectory(prefix='native-pool-')
    case.addCleanup(temporary.cleanup)
    root = Path(temporary.name).resolve() / 'registry'
    patch = mock.patch.object(work, 'state_root', return_value=root)
    patch.start()
    case.addCleanup(patch.stop)
    return root


def project_dir(case: unittest.TestCase, name: str = 'project') -> Path:
    """Create a real project/output directory so disk accounting can bind a device."""
    temporary = tempfile.TemporaryDirectory(prefix='native-pool-project-')
    case.addCleanup(temporary.cleanup)
    path = Path(temporary.name).resolve() / name
    path.mkdir()
    return path


def write_legacy_marker(root: Path, record: dict) -> bytes:
    """Write heavy.active.json exactly as the old lease code would (TEST legacy job)."""
    root.mkdir(mode=0o700, exist_ok=True)
    data = (json.dumps(record, sort_keys=True) + '\n').encode()
    path = root / 'heavy.active.json'
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, data)
    finally:
        os.close(descriptor)
    return data


def legacy_record(nonce: str, supervisor: int, processes: list[dict]) -> dict:
    """The legacy schemaVersion 1 active record shape."""
    return {'schemaVersion': 1, 'nonce': nonce, 'supervisorPid': supervisor,
            'project': '/TEST/legacy-project', 'startedAt': 1.0, 'processes': processes}


def hold_legacy_exclusive(case: unittest.TestCase, root: Path) -> int:
    """Hold heavy.lock exclusively as a running old-code job would (released on cleanup)."""
    root.mkdir(mode=0o700, exist_ok=True)
    descriptor = os.open(root / 'heavy.lock', os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    case.addCleanup(os.close, descriptor)
    return descriptor


def members(root: Path) -> list[Path]:
    """Pool member records currently present (live or quarantined)."""
    pool = root / 'pool-v1'
    return sorted(pool.glob('m-*.json')) if pool.is_dir() else []


TEST_HOST = {'cpuBrand': 'TEST CPU (fixture host, never a real machine)', 'physicalCpus': 16,
             'logicalCpus': 16, 'memsizeBytes': 64 * GIB, 'osProductVersion': 'TEST-26.0',
             'osBuild': 'TEST0'}


def fixture_record(slots: dict, host: dict = TEST_HOST) -> dict:
    """A TEST-labelled qualification record for a fixture host (never production authority)."""
    import native_work_qualification as qualification
    from native_work_pool_policy import policy_identity
    jobs = [{'id': f'TEST-{index}', 'passed': True, 'referenceMatched': True,
             'status': 'native-short-checked-for-review'} for index in range(slots['heavy'])]
    return {'schemaVersion': 1, 'kind': qualification.RECORD_KIND, 'host': dict(host),
            'policy': policy_identity(),
            'configuration': {'heavySlots': slots['heavy'], 'audioSlots': slots['audio']},
            'evidence': {'scope': 'TEST fixture evidence; not a measured qualification',
                         'allJobsPassed': True, 'fullExports': True, 'jobs': jobs,
                         'peakConcurrentJobs': slots['heavy'], 'summarySha256': '0' * 64}}


def qualify_fixture_host(case: unittest.TestCase, slots: dict) -> Path:
    """Patch host identity and record folder to TEST values and write a TEST record."""
    import native_work_pool_policy as policy
    import native_work_qualification as qualification
    temporary = tempfile.TemporaryDirectory(prefix='native-pool-record-')
    case.addCleanup(temporary.cleanup)
    directory = Path(temporary.name).resolve() / 'native-pool'
    for patch in (mock.patch.object(policy, 'host_identity', return_value=dict(TEST_HOST)),
                  mock.patch.object(qualification, 'record_directory', return_value=directory)):
        patch.start()
        case.addCleanup(patch.stop)
    qualification.write_record(fixture_record(slots), dict(TEST_HOST))
    return directory


TEST_ENGINE = {'identity': hashlib.sha256(b'TEST engine; never a real checkout').hexdigest(), 'files': 1}
SHORT_STAGES = ['capture', 'pipeline', 'preview', 'verification']
SHORT_PIXELS = 1080 * 1920


def fixture_job(index: int, **facts: object) -> dict:
    """A TEST passing Short job with the facts a schema-2 profile needs (override any)."""
    return {'id': f'TEST-{index}', 'passed': True, 'referenceMatched': True, 'format': 'short',
            'stages': list(SHORT_STAGES), 'durationSeconds': 60.0, 'pixels': SHORT_PIXELS, 'cacheState': 'cold',
            'ownAudioStage': False, **facts}


def fixture_metrics() -> dict:
    """TEST CPU/memory/disk/throughput/failure/cleanup figures (not measurements)."""
    return {'cpu': {'logicalCpus': 16, 'maximumAdmissionLoad1m': 8.0},
            'memory': {'aggregatePeakOwnedBytes': 7 * GIB, 'minimumFreePercent': 50.0, 'maximumKernelPressureLevel': 1},
            'disk': {'minimumDiskFreeBytes': 200 * GIB, 'maximumAttemptBytes': GIB},
            'throughput': {'outputSeconds': 180.0, 'batchWallSeconds': 690.0, 'outputSecondsPerWallSecond': 0.26},
            'failures': {'failedJobs': 0, 'failedOwners': 0}, 'cleanup': {'owners': 12, 'unverifiedOwners': 0}}


def fixture_profile(slots: dict, jobs: list[dict] | None = None, class_mix: str = 'heavy-only',
                    evidence: dict | None = None) -> dict:
    """A TEST-labelled schema-2 profile whose bounds equal its TEST jobs (never production authority)."""
    from native_work_profiles import derived_bounds
    jobs = jobs if jobs is not None else [fixture_job(index) for index in range(slots['heavy'])]
    base = {'scope': 'TEST fixture evidence; not a measured qualification', 'allJobsPassed': True,
            'fullExports': True, 'jobs': jobs, 'peakConcurrentJobs': slots['heavy'], 'summarySha256': '0' * 64,
            'overlap': {'jobsWithHeavyPeak': slots['heavy'], 'heavyOwnersPeak': slots['heavy'],
                        'audioOwnersPeak': 0, 'audioWithHeavyPeak': 0, 'audioStageWithHeavyPeak': 0},
            **fixture_metrics()}
    formats = '_'.join(sorted({job['format'] for job in jobs}))
    return {'id': f"TEST-{formats}-{class_mix}-h{slots['heavy']}a{slots['audio']}", 'engine': dict(TEST_ENGINE),
            'configuration': {'heavySlots': slots['heavy'], 'audioSlots': slots['audio']},
            'workload': derived_bounds(jobs, class_mix), 'evidence': {**base, **(evidence or {})},
            'harness': {'path': '/TEST/harness', 'sha256': '0' * 64}, 'writtenAt': 'TEST'}


def profile_record(profiles: list[dict], host: dict = TEST_HOST) -> dict:
    """A TEST schema-2 record holding the given TEST profiles."""
    import native_work_qualification as qualification
    from native_work_pool_policy import policy_identity
    return {'schemaVersion': 2, 'kind': qualification.RECORD_KIND, 'host': dict(host),
            'policy': policy_identity(), 'profiles': profiles}


def qualify_fixture_profiles(case: unittest.TestCase, profiles: list[dict],
                             engine: str | None = TEST_ENGINE['identity'], directory: Path | None = None) -> Path:
    """Patch host and record folder (and, unless engine is None, the engine identity) to TEST
    values and write a TEST schema-2 record; engine=None keeps this checkout's real identity,
    and a directory (from qualify_fixture_host) puts it beside a TEST schema-1 record."""
    import native_work_pool_policy as policy
    import native_work_qualification as qualification
    import native_work_workload as workloads
    if directory is None:
        temporary = tempfile.TemporaryDirectory(prefix='native-pool-profiles-')
        case.addCleanup(temporary.cleanup)
        directory = Path(temporary.name).resolve() / 'native-pool'
    patches = [mock.patch.object(policy, 'host_identity', return_value=dict(TEST_HOST)),
               mock.patch.object(qualification, 'record_directory', return_value=directory)]
    if engine is not None:
        patches.append(mock.patch.object(workloads, 'current_engine', return_value=engine))
    for patch in patches:
        patch.start()
        case.addCleanup(patch.stop)
    qualification.write_record(profile_record(profiles), dict(TEST_HOST))
    return directory


def plan_project(case: unittest.TestCase, kind: str, seconds: float, size: tuple[int, int] = (1920, 1080)) -> Path:
    """A TEST project folder holding one native plan whose canvas states duration (and Long size)."""
    project = project_dir(case, f'TEST-{kind}')
    canvas = {'totalFrames': int(seconds * 30), 'frameRate': '30/1'}
    if kind == 'long':
        canvas.update(width=size[0], height=size[1])
    name = 'SHORT-PROJECT.json' if kind == 'short' else 'LONG-PROJECT.json'
    (project / name).write_text(json.dumps({'scope': 'TEST plan', 'canvas': canvas}))
    return project


BASE_DRIVER = Path(__file__).resolve().parent / 'fixtures/base_pool_driver.py'
CURRENT_DRIVER = BASE_DRIVER.with_name('native_pool_driver.py')


class BasePoolClient:
    """TEST mixin: the unmodified base-engine (4a15560) pool client as separate processes.

    base_pool_driver.py imports hash-checked copies of the base pool modules and runs
    native_pool_driver commands in the test's private namespace (self.root) with the TEST
    schema-1 record folder (self.records); the canonical pool and record are never read.
    """

    root: Path
    records: Path

    def base(self, *args: str, stdin: bool = False, driver: Path = BASE_DRIVER) -> subprocess.Popen:
        """Start one base-engine client process (or, with CURRENT_DRIVER, this engine's); killed at cleanup."""
        process = subprocess.Popen([sys.executable, '-B', str(driver), args[0], str(self.root),
                                    str(self.records), *args[1:]], stdout=subprocess.PIPE, text=True,
                                   stdin=subprocess.PIPE if stdin else None, cwd=BASE_DRIVER.parents[2])
        self.addCleanup(self.stop, process)
        return process

    def stop(self, process: subprocess.Popen) -> None:
        """Kill and reap a driver that is still running."""
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        process.stdout.close()
        if process.stdin:
            process.stdin.close()

    def event(self, process: subprocess.Popen) -> dict:
        """The next JSON event line from a driver."""
        line = process.stdout.readline()
        self.assertTrue(line, 'TEST driver exited without an event')
        return json.loads(line)

    def send(self, process: subprocess.Popen, line: str = 'go') -> None:
        """Release a driver waiting on stdin."""
        process.stdin.write(line + '\n')
        process.stdin.flush()
