"""Close native attempts and return temporary signal ownership to the caller."""
from __future__ import annotations

import signal
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from studio.native_run_disk import CATEGORIES as DISK_CATEGORIES

if TYPE_CHECKING:
    from studio.native_run import NativeRun

ABORT_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
SignalHandler = Callable[[int, object], None] | signal.Handlers | None


class NativeSignalHandlers:
    """Retain the caller's handlers without overwriting later external ownership."""

    def __init__(self, handler: Callable[[int, object], None]) -> None:
        """Save no process state until this attempt actually reaches preparation."""
        self.handler = handler
        self.previous: dict[int, SignalHandler] = {}

    def install(self) -> None:
        """Record each successful registration so partial setup remains reversible."""
        if self.previous:
            raise RuntimeError('Native abort signal handlers are already installed')
        for number in ABORT_SIGNALS:
            if signal.getsignal(number) is None:
                raise RuntimeError(f'Cannot preserve the unknown {signal.Signals(number).name} handler')
            self.previous[number] = signal.signal(number, self.handler)

    def restore(self) -> None:
        """Attempt every restoration even if an individual signal API call fails."""
        errors = []
        for number, previous in tuple(self.previous.items()):
            try:
                self.restore_one(number, previous)
            except (OSError, RuntimeError, ValueError) as error:
                errors.append(f'{signal.Signals(number).name}: {error}')
        if errors:
            raise RuntimeError('Could not restore native abort signals: ' + '; '.join(errors))

    def restore_one(self, number: int, previous: SignalHandler) -> None:
        """Restore only the handler still owned by this attempt; preserve replacements."""
        if signal.getsignal(number) == self.handler:
            signal.signal(number, previous)
        del self.previous[number]


def finalize_attempt(owner: NativeRun) -> None:
    """Complete the existing cleanup, lease, file and receipt lifecycle in order."""
    try:
        owner.cleanup()
    except Exception as error:
        owner.result['cleanup'] = {'verified': False, 'error': str(error)}
        owner.abort_reason = owner.abort_reason or f'Cleanup failed: {error}'
        try:
            owner.stop_direct_child()
        except Exception as direct_error:
            owner.result['cleanup']['directChildError'] = str(direct_error)
    owner.release_lease()
    for handle in (owner.log, owner.samples):
        if handle is not None:
            handle.close()
    owner.finish()


def failure_category(result: dict) -> str | None:
    """Distinguish measured pressure from unavailable telemetry and execution errors."""
    if result.get('status') != 'failed':
        return None
    if result.get('cleanup', {}).get('verified') is not True:
        return 'cleanup-unverified'
    reason = result.get('abortReason') or ''
    if 'signal' in reason or 'KeyboardInterrupt' in reason or reason.startswith('supervisor received SIG'):
        return 'cancelled'
    if result.get('failureCategory') == 'measurement-unavailable':
        return 'measurement-unavailable'
    if result.get('failureCategory') in (*DISK_CATEGORIES, 'host-inspection-timeout', 'budget-exhausted',
                                         'process-registry-overflow'):
        return result['failureCategory']
    if 'Disk admission refused' in reason and not result.get('pid'):
        return 'disk-space'
    if 'Admission refused' in reason and not result.get('pid'):
        return 'capacity-timeout'
    if any(word in reason for word in ('kernel-warning', 'kernel memory pressure', 'low-headroom')):
        return 'host-memory-pressure'
    if 'footprint exceeds' in reason:
        return 'render-memory-limit'
    return 'renderer-failure'


def owner_pins_changed(owner: NativeRun, boundary: str) -> bool:
    """Compare every additional pin, recording this boundary's hashed and memoized bytes."""
    from studio.native_digest_memo import integrity_boundary
    from studio.native_runtime import digest
    with integrity_boundary(owner.root, f'{boundary}:{owner.label}'):
        return any(digest(Path(path)) != expected for path, expected in owner.additional_pins.items())


def verify_final_pins(owner: NativeRun) -> None:
    """Re-hash sources, SDK, sandbox and every additional pin after the child exits.

    Same-process repeats re-read only files whose exact identity changed
    (``studio/native_digest_memo.py``); the child cannot change content without that.
    """
    from studio.native_digest_memo import integrity_boundary
    from studio.native_run_config import source_hashes
    from studio.native_runtime import digest
    result = owner.result
    result['additionalFilePinsAfter'] = None
    try:
        with integrity_boundary(owner.root, f'owner-final:{owner.label}'):
            result['sourceHashesAfter'] = source_hashes(owner.project)
            result['sourceStable'] = result['sourceHashesBefore'] == result['sourceHashesAfter']
            result['sdkStable'] = owner.admission['sdkSha256'] == digest(owner.cli)
            result['sandboxStable'] = owner.admission['sandboxSha256'] == digest(owner.settings.sandbox)
            result['additionalFilePinsAfter'] = {path: digest(Path(path)) for path in owner.additional_pins}
            result['additionalFilesStable'] = owner.additional_pins == result['additionalFilePinsAfter']
    except OSError as error:
        result['pinVerificationError'] = {'type': type(error).__name__, 'message': str(error)}
        result.update(sourceStable=False, sdkStable=False, sandboxStable=False, additionalFilesStable=False)
        owner.abort_reason = owner.abort_reason or f'Final pin verification failed: {error}'
        result['abortReason'] = owner.abort_reason


def owner_succeeded(owner: NativeRun, output: Path) -> bool:
    """Success needs a clean exit, verified cleanup, the output and every stability proof."""
    result = owner.result
    stable = all(result.get(key) for key in ('sourceStable', 'sdkStable', 'sandboxStable', 'additionalFilesStable'))
    return (owner.child is not None and owner.child.returncode == 0 and not owner.abort_reason
            and bool(result.get('cleanup', {}).get('verified')) and output.is_file() and stable
            and bool(result.get('leaseCleanupVerified', False)))


def production_remaining(owner: NativeRun) -> float | None:
    """Return media time on the original allocation, preserving its cleanup reserve."""
    if owner.hard_deadline is None:
        return None
    from studio.native_budget_clock import allocation_remaining
    grants = getattr(owner, 'production_allocations', (owner.hard_deadline,))
    return min(allocation_remaining(grant) - grant['cleanupReserveSeconds'] for grant in grants)


def require_production_time(owner: NativeRun) -> float | None:
    """Refuse queue or launch after the original clock's usable media allowance expires."""
    remaining = production_remaining(owner)
    if remaining is not None and remaining <= 0:
        from studio.native_budget_clock import BudgetExhausted
        owner.result['failureCategory'] = 'budget-exhausted'
        raise BudgetExhausted('Production deadline reached; remaining time is reserved for cleanup and handoff')
    return remaining


def bind_launch_allocation(owner: NativeRun) -> None:
    """Debit only after admission, persist before Popen, and never lengthen inherited time."""
    from studio.native_run_config import validate_allocation
    require_production_time(owner)
    callback = owner.settings.before_launch
    if callback is not None:
        require_launch_binding(owner)
        if owner.lease is None or owner.result.get('productionLaunchReservationStarted'):
            raise RuntimeError('Production launch requires one admitted, uncharged owner')
        owner.result['productionLaunchReservationStarted'] = True
        owner.persist()
        previous = dict(owner.hard_deadline)
        grant = callback()
        validate_allocation(grant)
        if owner.hard_deadline != previous or grant is None or grant['boot'] != previous['boot'] or any(
                grant[key] > previous[key] for key in ('continuousDeadline', 'epochDeadline', 'grantedSeconds')) \
                or grant['cleanupReserveSeconds'] < previous['cleanupReserveSeconds']:
            raise ValueError('Production launch cannot extend or replace the original allocation')
        owner.hard_deadline = dict(grant)
        owner.result['productionLaunchReserved'] = True
    remaining = require_production_time(owner)
    if remaining is None:
        return
    import time
    owner.deadline = min(owner.deadline, time.monotonic() - owner.started + remaining)
    owner.result.update(productionAllocation=owner.hard_deadline, runDeadlineSeconds=owner.deadline)
    owner.persist()


def require_launch_binding(owner: NativeRun) -> None:
    """A section debit must belong to the exact pinned worker request and canonical phase."""
    from pathlib import Path
    from studio.native_runtime import digest
    callback_owner = getattr(owner.settings.before_launch, '__self__', None)
    binding = getattr(callback_owner, 'launch_binding', None)
    keys = {'request', 'requestSha256', 'phase', 'output', 'owner'}
    if type(binding) is not dict or set(binding) != keys:
        raise ValueError('Production launch callback lacks its exact section binding')
    command = owner.settings.command
    phase = '-'.join(owner.label.split('-')[:3])
    if command[-2:] != [binding['request'], binding['phase']] or phase != binding['phase'] \
            or owner.admission['output'] != binding['output'] \
            or owner.additional_pins.get(binding['request']) != binding['requestSha256'] \
            or digest(Path(binding['request'])) != binding['requestSha256'] \
            or not isinstance(binding['owner'], str) or len(binding['owner']) != 32:
        raise ValueError('Production launch callback belongs to another section or request')
    owner.result['productionLaunchBinding'] = dict(binding)


def require_launch_time(owner: NativeRun) -> None:
    """Recheck both clocks and cancellation after pin hashing, charging and persistence."""
    import time
    require_production_time(owner)
    if owner.abort_reason:
        raise RuntimeError(owner.abort_reason)
    if time.monotonic() >= owner.started + owner.deadline:
        raise RuntimeError('Independent render-only deadline exceeded before launch')


def monitor_limits(owner: NativeRun) -> bool:
    """Stop media before either original allocation or independent stage time expires."""
    import time
    remaining = production_remaining(owner)
    if remaining is not None and remaining <= 0:
        owner.abort_reason = 'Production deadline reached; cleanup reserve retained'
        owner.result['failureCategory'] = 'budget-exhausted'
        return True
    if time.monotonic() - owner.started > owner.deadline:
        owner.abort_reason = 'Independent render-only deadline exceeded'
        return True
    return False


def check_progress(owner: NativeRun, now: float) -> None:
    """Record a bounded no-progress failure without increasing monitor nesting."""
    if owner.progress_watch and not owner.progress_watch.inspect(now):
        owner.abort_reason = 'Native child made no measurable progress before its idle deadline'


def bind_completed_output(owner: NativeRun, success: bool) -> bool:
    """Capture bounded JSON result bytes after verified child exit/cleanup, before success publication."""
    from pathlib import Path
    from cut_preview_io import bound_json, file_hash
    limit = owner.settings.output_digest_limit
    if limit is None or not success:
        return success
    try:
        if owner.child is None or owner.child.poll() != 0 or owner.result.get('exitCode') != 0 \
                or owner.result.get('cleanup', {}).get('verified') is not True \
                or owner.result['cleanup'].get('survivors') != [] \
                or owner.result.get('leaseCleanupVerified') is not True:
            raise ValueError('Result binding requires exited child and verified owned cleanup')
        file = Path(owner.result['output'])
        sha = file_hash(file, maximum=limit)
        bound_json(file, sha, maximum=limit)
        owner.result['completedOutput'] = {'path': str(file), 'sha256': sha, 'bytes': file.stat().st_size}
        return True
    except (OSError, RuntimeError, ValueError) as error:
        owner.result.pop('completedOutput', None)
        owner.result['outputBindingError'] = {'type': type(error).__name__, 'message': str(error)}
        owner.abort_reason = owner.abort_reason or f'Completed result binding failed: {error}'
        owner.result['abortReason'] = owner.abort_reason
        return False


def publish_completed_attempt(owner: NativeRun, success: bool) -> None:
    """Preserve final status and receipt-ownership behavior after optional result binding."""
    import json
    from pathlib import Path
    success = bind_completed_output(owner, success)
    owner.result['status'] = owner.success_status if success else 'failed'
    owner.result['failureCategory'] = failure_category(owner.result)
    output = Path(owner.result['output'])
    if output.is_file():
        owner.result['outputBytes'] = output.stat().st_size
    try:
        owner.persist()
    except FileExistsError:
        owner.result['receiptOwnershipFailed'] = True
        owner.result['status'] = 'failed'
    print(json.dumps({key: owner.result[key] for key in
                      ('status', 'elapsedSeconds', 'output', 'abortReason', 'cleanup')}), flush=True)
