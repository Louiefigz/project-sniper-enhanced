"""Supervise native rendering with host memory and verified owned cleanup.
No supervisor SIGKILL protection or unobserved-process ownership is claimed; unproved cleanup never qualifies output.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
from cut_preview_io import write_new
from studio.native_runtime import digest
from studio.native_owned_processes import OwnedRegistry
from studio.native_measurement_retry import MeasurementWindow
from studio.native_run_config import owner_file_pins, NativeRunConfig, policy_for_baseline, source_hashes
from studio.native_run_lifecycle import NativeSignalHandlers, finalize_attempt, publish_completed_attempt
from studio.native_workload import ProgressWatch
from studio.native_run_admission import acquire_capacity
from studio.native_run_disk import serve_disk_request
from studio.native_export import launch_binding, worker_environment
from native_render_processes import ProcessIdentity, ProcessRequest, ResourceMeasurementError
from native_render_resources import ResourceSnapshot, admission_reasons, resource_warnings, stop_reasons
from native_render_policy import AdaptiveMemoryGuard, MODE, adaptive_admission_reasons, capacity_derivation
from native_work_lease import NativeWorkLease


def utc() -> str:
    """Record UTC without restarting the earlier failed edit clock."""
    return datetime.now(timezone.utc).isoformat()


class NativeRun:
    """One explicit attempt; all post-launch failures enter owned cleanup."""

    def __init__(self, label: str, settings: NativeRunConfig) -> None:
        """Prepare an admitted, still-unstarted attempt and closed limits."""
        settings.validate_admission()
        self.label, self.settings = label, settings
        self.project, self.cli, self.root = settings.project, settings.cli, settings.root
        self.admission, self.native_env = dict(settings.admission), settings.environment
        self.deadline, self.policy = settings.deadline, settings.policy
        self.hard_deadline = dict(settings.hard_deadline) if settings.hard_deadline else None
        self.capacity_context = None
        self.resource_guard = None
        self.path = self.root / f'{label}.render.json'
        self.started = time.monotonic()
        self.child, self.registry, self.abort_reason = None, None, None
        self.progress_watch = None
        self.log, self.samples = None, None
        self.receipt_owned = False
        self.lease, self.lease_identities = None, None
        self.signal_handlers = NativeSignalHandlers(self.request_abort)
        self.owner_pins = owner_file_pins()
        self.additional_pins = {**self.owner_pins, **settings.additional_pins}
        self.success_status = settings.success_status
        self.result = {'status': 'preparing', 'startedAt': utc(), 'admission': self.admission,
                       'project': str(self.project), 'output': self.admission['output'],
                       'sdkVersion': '0.8.31', 'sourceHashesBefore': source_hashes(self.project),
                       'renderOnlyTiming': True, 'policy': asdict(self.policy) if self.policy else None,
                       'resourcePolicyMode': MODE if settings.policy is None else 'fixed', 'args': settings.command,
                       'nativeOverrides': self.native_env, 'runDeadlineSeconds': self.deadline,
                       'productionAllocation': self.hard_deadline,
                       'supervisorSigkillProtection': False,
                       'unusedRamAdvisory': settings.policy is None or settings.unused_ram_advisory,
                       'compressorAdmissionMode': settings.compressor_admission if settings.policy else 'host-pressure-advisory',
                       'additionalFilePinsBefore': self.additional_pins}

    def persist(self, initial: bool = False) -> None:
        """Publish complete snapshots so a starting worker cannot read half-written JSON."""
        value = json.loads(json.dumps(self.result, allow_nan=False))  # Preserve the existing tuple-to-array JSON shape.
        if initial or not self.receipt_owned:
            write_new(self.path, value)
            self.receipt_owned = True
            return
        pending = self.path.with_name(f'.{self.path.name}.{uuid4().hex}.pending')
        write_new(pending, value)
        pending.replace(self.path)

    def request_abort(self, value: int, _frame: object) -> None:
        """Signal handlers request the same bounded cleanup as resource failures."""
        self.abort_reason = self.abort_reason or f'supervisor received {signal.Signals(value).name}'

    def prepare(self) -> None:
        """Own evidence and require bounded fresh telemetry before any child exists."""
        from studio.native_budget_owner import apply_budget_to_owner
        from studio.native_queue_accounting import start_owner
        apply_budget_to_owner(self)
        self.result.update(productionAllocation=self.hard_deadline, runDeadlineSeconds=self.deadline)
        start_owner(self)
        self.settings.validate_admission()
        launch_binding(self.settings)
        if self.settings.admission != self.admission:
            raise ValueError('Native admission changed after owner preparation')
        self.persist(initial=True)
        if any(digest(Path(path)) != expected for path, expected in self.additional_pins.items()):
            raise RuntimeError('Prepared native input or supervision code changed before launch')
        self.signal_handlers.install()
        acquire_capacity(self)
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
        if any(digest(Path(path)) != expected for path, expected in self.additional_pins.items()):
            raise RuntimeError('Native input changed while waiting for capacity')
        environment = worker_environment(self.settings, self.path)
        from studio.native_run_lifecycle import bind_launch_allocation, require_launch_time
        bind_launch_allocation(self)
        require_launch_time(self)
        from headless.process_runner import LEDGER_ENV, _ledger_note, note_owned_session
        if os.environ.get(LEDGER_ENV):
            environment[LEDGER_ENV] = os.environ[LEDGER_ENV]
        command = tuple(self.result['args'])
        _ledger_note('intent', None, command)
        try:
            self.child = subprocess.Popen(
                self.result['args'], cwd=self.project, env=environment, start_new_session=True,
                stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT,
            )
        except OSError:
            _ledger_note('spawn-failed', None, command)
            raise
        note_owned_session(self.child, command)
        self.registry = OwnedRegistry(self.child.pid)
        if self.settings.idle_deadline:
            self.progress_watch = ProgressWatch(Path(self.result['logPath']),
                                                time.monotonic(), self.settings.idle_deadline)
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
        evaluation = self.resource_guard.evaluate(snapshot) if self.resource_guard else {
            'mode': 'fixed', 'stopReasons': stop_reasons(snapshot, self.baseline, self.policy),
            'warnings': resource_warnings(snapshot, self.policy)}
        measured = asdict(snapshot) | {'warnings': evaluation['warnings'], 'guard': evaluation}
        self.samples.write(json.dumps(measured) + '\n')
        self.result['latestResourceSnapshot'] = measured
        self.result['resourcePolicyEvaluation'] = evaluation
        reasons = evaluation['stopReasons']
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

    def measure_resources(self, request: ProcessRequest) -> ResourceSnapshot:
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
            from studio.native_run_lifecycle import monitor_limits
            if monitor_limits(self):
                break
            if time.monotonic() >= next_sample:
                self.sample()
                from studio.native_run_lifecycle import check_progress
                check_progress(self, time.monotonic())
                next_sample = time.monotonic() + 5
            serve_disk_request(self)
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
        publish_completed_attempt(self, success)

    def execute(self) -> bool:
        """Keep lifecycle cleanup mandatory after every launch/error path."""
        try:
            self.prepare()
            self.launch()
            self.monitor()
        except Exception as error:
            if getattr(error, 'category', None) == 'budget-exhausted':
                self.result['failureCategory'] = error.category
            if isinstance(error, ResourceMeasurementError):
                self.result['failureCategory'] = 'measurement-unavailable'
            if getattr(error, 'evidence', None):
                self.result.setdefault('measurementFailureEvidence', []).append(error.evidence)
            self.abort_reason = self.abort_reason or f'{type(error).__name__}: {error}'
        finally:
            try:
                finalize_attempt(self)
            finally:
                self.signal_handlers.restore()
                from studio.native_queue_accounting import finish_owner
                finish_owner(self)
        return self.result['status'] == self.success_status and not self.abort_reason
