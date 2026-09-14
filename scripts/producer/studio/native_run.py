"""Supervise one stock native full render with host-side memory and owned cleanup.

Does not claim protection from SIGKILL of this supervisor or ownership of an
unobserved detached process. Failed/unproved cleanup never qualifies an output.
"""
from __future__ import annotations

import json
import signal
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from datetime import datetime, timezone

from studio.native_runtime import digest
from studio.native_owned_processes import OwnedRegistry
from studio.native_measurement_retry import MeasurementWindow
from studio.native_run_config import NativeRunConfig, policy_for_baseline, source_hashes

from native_render_processes import ProcessIdentity, ProcessRequest, ResourceMeasurementError
from native_render_resources import admission_reasons, resource_warnings, stop_reasons
from native_work_lease import NativeWorkLease


def utc() -> str:
    """Record UTC without restarting the earlier failed edit clock."""
    return datetime.now(timezone.utc).isoformat()


def owner_file_pins() -> dict[str, str]:
    """Bind shared supervision code even when a capture adapter omits its pins."""
    studio = Path(__file__).resolve().parent
    files = [studio / name for name in (
        'native_run.py', 'native_owned_processes.py', 'native_measurement_retry.py',
        'native_run_config.py', 'native_runtime.py')]
    files += list(studio.parent.glob('native_render_*.py'))
    files += [studio.parent / name for name in (
        'native_work_lease.py', 'headless/durable_files.py')]
    return {str(file): digest(file) for file in files}


class NativeRun:
    """One explicit attempt; all post-launch failures enter owned cleanup."""

    def __init__(self, label: str, settings: NativeRunConfig) -> None:
        """Prepare an admitted, still-unstarted attempt and closed limits."""
        self.label, self.settings = label, settings
        self.project, self.cli, self.root = settings.project, settings.cli, settings.root
        self.admission, self.native_env = settings.admission, settings.environment
        self.deadline, self.policy = settings.deadline, settings.policy
        self.path = self.root / f'{label}.render.json'
        self.started = time.monotonic()
        self.child, self.registry, self.abort_reason = None, None, None
        self.log, self.samples = None, None
        self.receipt_owned = False
        self.lease, self.lease_identities = None, None
        self.owner_pins = owner_file_pins()
        self.additional_pins = {**self.owner_pins, **settings.additional_pins}
        self.success_status = settings.success_status
        self.result = {'status': 'preparing', 'startedAt': utc(), 'admission': self.admission,
                       'project': str(self.project), 'output': self.admission['output'],
                       'sdkVersion': '0.8.31', 'sourceHashesBefore': source_hashes(self.project),
                       'renderOnlyTiming': True, 'policy': asdict(self.policy), 'args': settings.command,
                       'nativeOverrides': self.native_env, 'runDeadlineSeconds': self.deadline,
                       'supervisorSigkillProtection': False,
                       'unusedRamAdvisory': settings.unused_ram_advisory,
                       'compressorAdmissionMode': settings.compressor_admission,
                       'additionalFilePinsBefore': self.additional_pins}

    def persist(self, initial: bool = False) -> None:
        """Record failures durably; an inability to write is not render success."""
        mode = 'x' if initial or not self.receipt_owned else 'w'
        with self.path.open(mode) as handle:
            self.receipt_owned = True
            json.dump(self.result, handle, indent=2)
            handle.flush()

    def request_abort(self, value: int, _frame: object) -> None:
        """Signal handlers request the same bounded cleanup as resource failures."""
        self.abort_reason = self.abort_reason or f'supervisor received {signal.Signals(value).name}'

    def prepare(self) -> None:
        """Own evidence and require bounded fresh telemetry before any child exists."""
        self.persist(initial=True)
        if any(digest(Path(path)) != expected for path, expected in self.additional_pins.items()):
            raise RuntimeError('Prepared native input or supervision code changed before launch')
        for value in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(value, self.request_abort)
        self.lease = NativeWorkLease.acquire('heavy', str(self.project))
        self.baseline = self.measure_resources(ProcessRequest())
        self.policy = policy_for_baseline(self.settings, self.baseline)
        self.result.update(baseline=asdict(self.baseline), policy=asdict(self.policy))
        reasons = admission_reasons(self.baseline, self.policy)
        if self.settings.unused_ram_advisory:
            reasons = tuple(reason for reason in reasons
                            if reason != 'unused physical RAM is below the reserved host margin')
        self.result['admissionReasons'] = reasons
        self.persist()
        if reasons:
            raise RuntimeError('Admission refused: ' + '; '.join(reasons))
        self.result['logPath'] = str(self.root / f'{self.label}.render.log')
        self.persist()
        self.log = (self.root / f'{self.label}.render.log').open('xb', buffering=0)
        self.samples = (self.root / f'{self.label}.resources.jsonl').open('x', buffering=1)

    def launch(self) -> None:
        """Only the native child enters the existing localhost-only sandbox."""
        if self.abort_reason:
            raise RuntimeError(self.abort_reason)
        if time.monotonic() >= self.started + self.deadline:
            raise RuntimeError('Independent render-only deadline exceeded before launch')
        if owner_file_pins() != self.owner_pins:
            raise RuntimeError('Native supervision code changed during admission')
        self.child = subprocess.Popen(
            self.result['args'], cwd=self.project, env=self.native_env, start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT,
        )
        self.registry = OwnedRegistry(self.child.pid)
        self.record_lease_processes()
        self.result.update(status='running', pid=self.child.pid,
                           nativeLaunchedAt=utc(), ownerIdentities=self.registry.identities())
        self.persist()

    def sample(self) -> None:
        """Bound both host pressure and the full remembered native/browser tree."""
        self.registry.live()
        root = self.registry.known[self.child.pid]
        identity = ProcessIdentity(root.pid, root.started, root.pgid)
        remembered = tuple(ProcessIdentity(row.pid, row.started, row.pgid)
                           for row in self.registry.known.values())
        request = ProcessRequest(identity, remembered)
        snapshot = self.measure_resources(request)
        if self.child.poll() is not None:
            return
        if snapshot.identity_verified:
            self.registry.remember_measured(snapshot.processes)
            self.record_lease_processes()
        measured = asdict(snapshot) | {'warnings': resource_warnings(snapshot, self.policy)}
        self.samples.write(json.dumps(measured) + '\n')
        self.result['latestResourceSnapshot'] = measured
        reasons = stop_reasons(snapshot, self.baseline, self.policy)
        if reasons:
            self.abort_reason = '; '.join(reasons)
        self.result['ownerIdentities'] = [asdict(row) for row in self.registry.known.values()]
        self.persist()
        print(json.dumps({'status': 'running' if not self.abort_reason else 'aborting',
                          'elapsedSeconds': round(time.monotonic() - self.started, 1),
                          'ownedGiB': round(snapshot.owned_footprint_bytes / 2**30, 3),
                          'unusedGiB': round(snapshot.unused_physical_bytes / 2**30, 3),
                          'kernelPressure': snapshot.kernel_pressure_level,
                          'warnings': measured['warnings'],
                          'abortReason': self.abort_reason}), flush=True)

    def measure_resources(self, request: ProcessRequest):
        """Keep bounded retries and fail on missing live telemetry."""
        try:
            return MeasurementWindow(self, request).run()
        except ResourceMeasurementError:
            if self.child is None or self.child.poll() is None:
                raise
            return None

    def monitor(self) -> None:
        """Discover detached groups each second; sample actual footprint every five."""
        next_sample = 0
        while self.child.poll() is None and self.abort_reason is None:
            self.registry.live()
            self.record_lease_processes()
            if time.monotonic() - self.started > self.deadline:
                self.abort_reason = 'Independent render-only deadline exceeded'
                break
            if time.monotonic() >= next_sample:
                self.sample()
                next_sample = time.monotonic() + 5
            time.sleep(.5)

    def record_lease_processes(self) -> None:
        """Durably retain newly discovered identities without per-poll write churn."""
        if self.registry is None or self.lease is None:
            return
        rows = [{'pid': row.pid, 'started': row.started, 'pgid': row.pgid}
                for row in self.registry.known.values()]
        if rows != self.lease_identities:
            self.lease.record_processes(rows)
            self.lease_identities = rows

    def release_lease(self) -> None:
        """Clear the heavy lane only after independently verified owned cleanup."""
        if self.lease is None:
            return
        try:
            self.record_lease_processes()
            if self.result.get('cleanup', {}).get('verified'):
                self.lease.complete()
                self.result['leaseCleanupVerified'] = True
        except Exception as error:
            self.result['leaseCleanupVerified'] = False
            self.abort_reason = self.abort_reason or f'Heavy-work cleanup fence: {error}'
        finally:
            self.lease.close()

    def cleanup(self) -> None:
        """Run on success as well as failure; no surviving browsers are accepted."""
        if self.child is None:
            self.result['cleanup'] = {'verified': True, 'childNeverLaunched': True}
            return
        if self.registry is not None:
            self.result['cleanup'] = self.registry.cleanup(self.child)
        else:
            self.stop_direct_child()
            self.result['cleanup'] = {'verified': False, 'reason': 'Descendant ownership never bound'}
        self.result['exitCode'] = self.child.poll()

    def stop_direct_child(self) -> None:
        """Retain direct-child authority when descendant observation is unavailable."""
        if self.child is None or self.child.poll() is not None:
            return
        self.child.terminate()
        try:
            self.child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.wait(timeout=2)

    def finish(self) -> None:
        """Qualify no output here: even successful rendering still awaits output QC."""
        self.result['elapsedSeconds'] = time.monotonic() - self.started
        self.result['completedAt'] = utc()
        self.result['abortReason'] = self.abort_reason
        self.result['additionalFilePinsAfter'] = None
        try:
            self.result['sourceHashesAfter'] = source_hashes(self.project)
            self.result['sourceStable'] = self.result['sourceHashesBefore'] == self.result['sourceHashesAfter']
            self.result['sdkStable'] = self.admission['sdkSha256'] == digest(self.cli)
            self.result['sandboxStable'] = self.admission['sandboxSha256'] == digest(self.settings.sandbox)
            self.result['additionalFilePinsAfter'] = {path: digest(Path(path)) for path in self.additional_pins}
            self.result['additionalFilesStable'] = self.additional_pins == self.result['additionalFilePinsAfter']
        except OSError as error:
            self.result['pinVerificationError'] = {'type': type(error).__name__, 'message': str(error)}
            self.result.update(sourceStable=False, sdkStable=False, sandboxStable=False, additionalFilesStable=False)
            self.abort_reason = self.abort_reason or f'Final pin verification failed: {error}'
            self.result['abortReason'] = self.abort_reason
        output = Path(self.result['output'])
        success = (self.child is not None and self.child.returncode == 0 and not self.abort_reason
                   and self.result.get('cleanup', {}).get('verified') and output.is_file()
                   and self.result['sourceStable'] and self.result['sdkStable'] and self.result['sandboxStable']
                   and self.result['additionalFilesStable'])
        success = success and self.result.get('leaseCleanupVerified', False) and self.result['additionalFilesStable']
        self.result['status'] = self.success_status if success else 'failed'
        if output.is_file():
            self.result['outputBytes'] = output.stat().st_size
        try:
            self.persist()
        except FileExistsError:
            self.result['receiptOwnershipFailed'] = True
            self.result['status'] = 'failed'
        print(json.dumps({key: self.result[key] for key in
                          ('status', 'elapsedSeconds', 'output', 'abortReason', 'cleanup')}), flush=True)

    def execute(self) -> bool:
        """Keep lifecycle cleanup mandatory after every launch/error path."""
        try:
            self.prepare()
            self.launch()
            self.monitor()
        except Exception as error:
            if getattr(error, 'evidence', None):
                self.result.setdefault('measurementFailureEvidence', []).append(error.evidence)
            self.abort_reason = self.abort_reason or f'{type(error).__name__}: {error}'
        finally:
            try:
                self.cleanup()
            except Exception as error:
                self.result['cleanup'] = {'verified': False, 'error': str(error)}
                self.abort_reason = self.abort_reason or f'Cleanup failed: {error}'
                try:
                    self.stop_direct_child()
                except Exception as direct_error:
                    self.result['cleanup']['directChildError'] = str(direct_error)
            self.release_lease()
            for handle in (self.log, self.samples):
                if handle is not None:
                    handle.close()
            self.finish()
        return self.result['status'] == self.success_status
