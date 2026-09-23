"""Collect process identities and footprints in one already-started bounded helper.

Launching Python between the two process-table reads widened the race window
enough to repeatedly miss short FFmpeg processes. Keep both reads around the
same public API collection inside the helper; preserve complete-tree validation.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

from native_render_macos import collect
from native_render_process_table import identity_table
from native_render_processes import (
    ProcessIdentity, ProcessRequest, ResourceMeasurementError, MissingProcessFootprint,
    process_selection, reconcile_process_request,
)
from native_render_resources import ResourceSnapshot, _read_command, parse_snapshot

def collect_bracketed(request: ProcessRequest) -> dict:
    """The parent enforces three seconds around both tables and real API readings."""
    before = identity_table(request)
    pids = sorted(process_selection(before, request)['owned'])
    started = time.monotonic()
    direct = collect(pids)
    direct['elapsedSeconds'] = time.monotonic() - started
    observed = reconcile_process_request(before, before, request)
    after = identity_table(observed)
    return {'before': before, 'after': after, 'direct': direct}


def read_compact_snapshot(directory: Path, request: ProcessRequest) -> ResourceSnapshot:
    """Reject new unmeasured live children and keep exits distinct from zero memory."""
    started = time.time()
    raw = {'sysctl': _read_command(['/usr/sbin/sysctl', 'hw.memsize', 'vm.swapusage',
                                  'kern.memorystatus_vm_pressure_level']),
           'pressure': _read_command(['/usr/bin/memory_pressure', '-Q'])}
    encoded = json.dumps({'root': asdict(request.root) if request.root else None,
                          'remembered': [asdict(row) for row in request.remembered]})
    text = _read_command([sys.executable, str(Path(__file__).resolve())], encoded)
    try:
        if len(text) > 16 * 1024 * 1024:
            raise ValueError('Process sampling envelope exceeds limit')
        value = json.loads(text)
        if value.get('status') == 'unavailable':
            raise_helper_error(value)
        request = reconcile_process_request(value['before'], value['after'], request)
        raw.update(ps=value['after'], direct=json.dumps(value['direct']))
    except (ValueError, KeyError, TypeError) as error:
        raise ResourceMeasurementError('Invalid bracketed memory measurement') from error
    snapshot = parse_snapshot(raw, request, shutil.disk_usage(directory).free)
    return replace(snapshot, measured_at=started)


def raise_helper_error(value: dict) -> None:
    """Retain genuine identity churn as retryable; permission/ABI failures stay terminal."""
    evidence = value.get('evidence')
    if value.get('errorType') == 'MissingProcessFootprint' and isinstance(evidence, dict):
        identities = tuple(ProcessIdentity(**row) for row in evidence['identities'])
        raise MissingProcessFootprint(identities, evidence['reason'])
    raise ResourceMeasurementError(value.get('error', 'Identity measurement unavailable'))


def main() -> None:
    """Accept bounded explicit identity arguments; never discover unrelated roots."""
    encoded = sys.stdin.read(1024 * 1024 + 1)
    if len(sys.argv) != 1 or len(encoded) > 1024 * 1024:
        raise ValueError('Expected one bounded process request on stdin')
    value = json.loads(encoded)
    if set(value) != {'root', 'remembered'} or len(value['remembered']) > 4096:
        raise ValueError('Invalid process request')
    root = ProcessIdentity(**value['root']) if value['root'] else None
    request = ProcessRequest(root, tuple(ProcessIdentity(**row) for row in value['remembered']))
    try:
        result = collect_bracketed(request)
    except (ResourceMeasurementError, OSError, ValueError) as error:
        result = {'status': 'unavailable', 'error': str(error), 'errorType': type(error).__name__,
                  'evidence': getattr(error, 'evidence', None)}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
