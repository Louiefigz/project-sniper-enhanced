"""Serve one owner child's disk request by growing the owner's pool reservation.

An owner configured with disk_expansion advertises `<label>.disk-request.json` beside its
receipt (native_run_admission.acquire_capacity). When the child — a Long about to extract
source frames — writes its per-directory demand there, the monitor loop calls
serve_disk_request once per tick:

- granted: the grown pool record is durable before `diskGrant` is persisted, so a child
  that saw the grant is covered even if this supervisor dies;
- waiting: a refusal that may clear (running members hold the bytes, a live member's record
  cannot be read, a busy ledger) or a timed-out host-identity sysctl is retried on later
  ticks for DISK_WAIT_SECONDS, each attempt waiting at most TICK_LEDGER_SECONDS for the
  ledger; expansion is never queued ahead of admissions (native_work_pool_expand.py states
  the policy);
- refused / error: a final pool refusal, a malformed request, or an unreadable request,
  ownership, host-identity or filesystem fault. It is recorded with its failure category
  and aborts the owner: 'disk-space' (reservations or free bytes), 'disk-unaccountable'
  (a filesystem the pool cannot charge, native_work_pool_storage), 'pool-unsupported-mix'
  (no profile covers the pool work present) or 'disk-reservation-error' (everything else).
"""
from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from cut_preview_io import bound_json
from native_work_lease import NativeWorkBusy
from native_work_pool_expand import expand_disk
from native_work_pool_fence import NativeWorkUnsupportedMix
from native_work_pool_storage import DiskUnaccountable
from native_work_pool_state import NativeWorkQueued

if TYPE_CHECKING:
    from studio.native_run import NativeRun

DISK_WAIT_SECONDS = 45.0  # below the child's 60 s wait in native_long_sources.mjs
TICK_LEDGER_SECONDS = 1.0
DISK_CATEGORY, ERROR_CATEGORY = 'disk-space', 'disk-reservation-error'
UNACCOUNTABLE_CATEGORY, MIX_CATEGORY = 'disk-unaccountable', 'pool-unsupported-mix'
CATEGORIES = (DISK_CATEGORY, ERROR_CATEGORY, UNACCOUNTABLE_CATEGORY, MIX_CATEGORY)


def _utc() -> str:
    """Wall-clock evidence only; durations use the monotonic clock."""
    return datetime.now(timezone.utc).isoformat()


def disk_request_path(receipt: Path) -> Path:
    """The one request file an owner's child may write, beside the owner receipt."""
    return receipt.with_name(receipt.name.removesuffix('.render.json') + '.disk-request.json')


def _disk_request(path: Path) -> dict:
    """Read the child's bounded request: an id and one to four directories with byte totals."""
    value = bound_json(path, maximum=16384)
    rows = value.get('directories')
    if value.get('schemaVersion') != 1 or not isinstance(value.get('id'), str) or not 0 < len(value['id']) <= 64 \
            or not isinstance(rows, list) or not 1 <= len(rows) <= 4:
        raise ValueError('Malformed native disk expansion request')
    directories: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('path'), str) or type(row.get('bytes')) is not int:
            raise ValueError('Malformed native disk expansion directory')
        directories[row['path']] = directories.get(row['path'], 0) + row['bytes']
    return {'id': value['id'], 'directories': directories}


def _wait(grant: dict, error: Exception) -> None:
    """Record a refusal that may clear; past the window it is final (a sysctl timeout is an error)."""
    waited = time.monotonic() - grant['waitStartedMonotonic']
    grant.update(status='waiting', waitedSeconds=waited, lastWaitReason=f'{type(error).__name__}: {error}')
    if waited < DISK_WAIT_SECONDS:
        return
    final = ('refused', DISK_CATEGORY) if isinstance(error, NativeWorkQueued) else ('error', ERROR_CATEGORY)
    grant.update(status=final[0], failureCategory=final[1],
                 reason=f"{grant['lastWaitReason']} (still after {waited:.1f} s)")


def pool_refusal_category(error: Exception) -> str | None:
    """The category of a pool refusal that is neither capacity nor quarantine (also used at admission)."""
    if isinstance(error, DiskUnaccountable):
        return UNACCOUNTABLE_CATEGORY
    return MIX_CATEGORY if isinstance(error, NativeWorkUnsupportedMix) else None


def _category(error: Exception) -> str:
    """The failure category of a final disk-request refusal."""
    named = pool_refusal_category(error)
    if named:
        return named
    return DISK_CATEGORY if isinstance(error, NativeWorkBusy) else ERROR_CATEGORY


def _attempt(owner: NativeRun, path: Path, grant: dict) -> None:
    """One bounded expansion attempt; classify its outcome into `grant`."""
    grant['attempts'] += 1
    try:
        request = _disk_request(path)
        grant['id'] = request['id']
        result = expand_disk(owner.lease, request['directories'], time.monotonic() + TICK_LEDGER_SECONDS)
    except (NativeWorkQueued, subprocess.TimeoutExpired) as error:
        _wait(grant, error)
        return
    except (NativeWorkBusy, ValueError) as error:
        grant.update(status='refused', reason=f'{type(error).__name__}: {error}', failureCategory=_category(error))
        return
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        grant.update(status='error', reason=f'{type(error).__name__}: {error}', failureCategory=ERROR_CATEGORY)
        return
    grant.update(result, status='granted', grantedAt=_utc())


def serve_disk_request(owner: NativeRun) -> None:
    """Answer (or keep retrying) this owner's single disk request; aborts the owner on a final refusal."""
    grant = owner.result.get('diskGrant')
    if not owner.settings.disk_expansion or owner.lease is None or owner.abort_reason \
            or (grant is not None and grant['status'] != 'waiting'):
        return  # an aborting owner grants nothing; its child is stopped by cleanup
    path = disk_request_path(owner.path)
    if grant is None and not os.path.lexists(path):
        return
    grant = grant or {'request': str(path), 'id': None, 'requestedAt': _utc(), 'attempts': 0,
                      'waitStartedMonotonic': time.monotonic()}
    previous = grant.get('status')
    _attempt(owner, path, grant)
    owner.result['diskGrant'] = grant
    if grant['status'] in ('refused', 'error'):
        owner.abort_reason = owner.abort_reason or f"Disk reservation {grant['status']}: {grant['reason']}"
        owner.result['failureCategory'] = grant['failureCategory']
    if grant['status'] != previous:
        owner.persist()
