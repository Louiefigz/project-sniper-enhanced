"""Validate direct macOS samples without inventing unavailable owned measurements.

The bounded owner reads ps before and after this payload. Parsing shares the
historical process-selection authority; it cannot create owned identities.
"""
from __future__ import annotations

import json
import math
import errno
from typing import Any

from native_render_macos import COMPRESSED_UNAVAILABLE, SAMPLER
from native_render_processes import (
    MissingProcessFootprint, ProcessRequest, ResourceMeasurementError, select_footprints,
)


class DirectMeasurementError(ResourceMeasurementError):
    """Retain failed public API evidence without retrying malformed data."""

    def __init__(self, reason: str, payload: Any) -> None:
        """The owner persists this evidence through its existing failure path."""
        self.evidence = {'reason': reason, 'sampler': SAMPLER, 'payload': payload}
        super().__init__(f'Direct macOS resource measurement unavailable: {reason}')


def unsigned(value: Any, label: str) -> int:
    """Reject booleans, fractions, negative values, infinity and absent counters."""
    if type(value) is not int or not 0 <= value <= 2**64 - 1:
        raise ValueError(f'Invalid unsigned measurement: {label}')
    return value


def host_values(host: dict) -> tuple[int, int]:
    """Use the same physical page formulas and kernel page size as Apple top-144."""
    page_size = unsigned(host['pageSizeBytes'], 'page size')
    if page_size not in {4096, 16384} or host['pageSizeSource'] != 'vm_kernel_page_size':
        raise ValueError('Unsupported kernel page size')
    if type(host['returnedIntegerCount']) is not int or host['returnedIntegerCount'] != 38:
        raise ValueError('Incomplete host VM statistics count')
    raw = host['raw']
    compressor = unsigned(raw['compressor_page_count'], 'compressor pages') * page_size
    unused = unsigned(raw['free_count'], 'free pages') * page_size
    speculative = unsigned(raw['speculative_count'], 'speculative pages')
    if speculative > raw['free_count']:
        raise ValueError('Speculative pages exceed inclusive free count')
    if (unsigned(host['compressorBytes'], 'compressor bytes') != compressor
            or unsigned(host['unusedPhysicalBytes'], 'unused bytes') != unused):
        raise ValueError('Host memory formula mismatch')
    return compressor, unused


def process_values(row: dict) -> dict:
    """Accept only paired live kernel identities and explicit missing CMPRS provenance."""
    start = unsigned(row['processStartAbstime'], 'process start')
    if not start or unsigned(row['processStartAbstimeBefore'], 'earlier process start') != start:
        raise ValueError('Unstable rusage process identity')
    if unsigned(row['processExitAbstime'], 'process exit') != 0:
        raise ValueError('Exited rusage process is not live')
    if row['compressedBytes'] is not None or row['compressedStatus'] != COMPRESSED_UNAVAILABLE:
        raise ValueError('Invalid compressed diagnostic provenance')
    if row['footprintSource'] != 'proc_pid_rusage:RUSAGE_INFO_V0:ri_phys_footprint':
        raise ValueError('Unexpected process memory metric')
    return {'footprint_bytes': unsigned(row['footprintBytes'], 'physical footprint'),
        'compressed_bytes': None, 'memory_sampler': SAMPLER,
        'compressed_status': COMPRESSED_UNAVAILABLE, 'process_start_abstime': start,
        'process_start_abstime_before': row['processStartAbstimeBefore'],
        'process_exit_abstime': row['processExitAbstime']}


def require_disappearance(row: dict) -> None:
    """Only ESRCH is a supported transient API failure; permission errors are terminal."""
    if set(row) != {'pid', 'status', 'result', 'errno'} or row['status'] != 'unavailable':
        raise ValueError('Malformed or mixed raw libproc failure evidence')
    if type(row['result']) is not int or row['result'] != -1:
        raise ValueError('Libproc failure requires the actual minus-one result')
    code = row['errno']
    if type(code) is not int or code != errno.ESRCH:
        raise ValueError(f'Permanent or unsupported libproc API failure: errno={code!r}')


def raw_identity(row: dict) -> tuple[int, int]:
    """Validate absolute timestamps without accepting an unstable raw reading as memory."""
    if row['status'] != 'measured':
        raise ValueError('Unknown raw rusage status')
    start = unsigned(row['processStartAbstime'], 'raw process start')
    if not start:
        raise ValueError('Missing raw rusage process start')
    return start, unsigned(row['processExitAbstime'], 'raw process exit')


def require_transient_unavailable(row: dict) -> None:
    """Classify one bounded pair; unknown failures cannot enter missing-row retries."""
    if 'errno' in row:
        require_disappearance(row)
        return
    if set(row) != {'pid', 'status', 'reason', 'before', 'after'}:
        raise ValueError('Malformed paired rusage failure evidence')
    before, after = row['before'], row['after']
    if any(type(side['pid']) is not int or side['pid'] != row['pid'] for side in (before, after)):
        raise ValueError('Mismatched raw rusage PID')
    if row['reason'] == 'rusage-identity-not-stable-and-live':
        first, second = raw_identity(before), raw_identity(after)
        if first[0] == second[0] and first[1] == second[1] == 0:
            raise ValueError('Claimed rusage identity race has no evidence')
        return
    if row['reason'] != 'rusage-api-failed':
        raise ValueError('Unknown unavailable rusage reason')
    errors = [side for side in (before, after) if side['status'] == 'unavailable']
    if not errors:
        raise ValueError('Claimed rusage API failure has no error')
    for side in errors:
        require_disappearance(side)
    for side in (before, after):
        if side not in errors:
            raw_identity(side)


def payload_values(payload: dict) -> tuple[int, int, dict[int, dict]]:
    """Validate schema and every supplied row before selecting current owned identities."""
    if type(payload['schemaVersion']) is not int or payload['schemaVersion'] != 1:
        raise ValueError('Unknown direct sampler schema')
    if payload['sampler'] != SAMPLER or payload['status'] != 'measured':
        raise ValueError('Direct API sampling failed or sampler is unknown')
    elapsed = payload['elapsedSeconds']
    if type(elapsed) not in {int, float} or not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError('Invalid direct sample duration')
    compressor, unused = host_values(payload['host'])
    rows, found, seen = payload['processes'], {}, set()
    if not isinstance(rows, list) or len(rows) > 4096:
        raise ValueError('Unbounded direct process readings')
    for row in rows:
        pid = unsigned(row['pid'], 'PID')
        if pid <= 1 or pid in seen or row['status'] not in {'measured', 'unavailable'}:
            raise ValueError('Invalid or duplicate direct PID')
        seen.add(pid)
        if row['status'] == 'measured':
            found[pid] = process_values(row)
        else:
            require_transient_unavailable(row)
    return compressor, unused, found


def parse_direct(text: str, ps_text: str, request: ProcessRequest) -> dict:
    """Never fallback to top or accept an absent live owned footprint as zero."""
    payload: Any = text
    try:
        if len(text) > 8 * 1024 * 1024:
            raise ValueError('Direct sample exceeds bounded payload size')
        payload = json.loads(text)
        compressor, unused, found = payload_values(payload)
        selection = select_footprints(ps_text, found, request)
    except MissingProcessFootprint as error:
        error.evidence.update(sampler=SAMPLER, directReadings=payload)
        raise
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise DirectMeasurementError(str(error), payload) from error
    return {'compressor': compressor, 'unused': unused, 'selection': selection, 'sampler': SAMPLER}
