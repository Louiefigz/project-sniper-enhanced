"""Starting one managed Studio view: the view bound, admission, launch, verification and failure record.

managed_preview.py calls launch() inside its registry transaction and uses the record helpers here;
this module never imports managed_preview. Startup holds a Studio pool slot
(native_work_pool_studio), never a render slot: it waits for one only until the open's own deadline
(the registry transaction's). The slot is released (completed) after a verified start, when nothing
was attempted, and when the start failed before spawning anything (studio_server's
``preview_spawned = False``: cleanup verified, X97); it stays quarantined only after a start that may
have spawned a process. The member records no process: such a start's survivors are the registry's
'launching' record (managed_preview_state), which fences only this project while one of them runs
and which ``stop`` discharges. So the member is a declaring owner that never marks a launch (phase
'admitted'), and native_work_recovery.py <nonce> releases its Studio slot once the opener has exited;
that frees capacity only, never a process.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from native_render_resources import read_snapshot
from native_render_policy import adaptive_admission_reasons, capacity_policy
from studio import managed_preview_registry as registry
from studio import managed_preview_state as state
from studio.native_runtime import runtime_identity
from studio.studio_server import ServerRecord, StudioServerError, launch_preview, pick_free_port


def _utc() -> str:
    """Wall-clock evidence for registry records."""
    return datetime.now(timezone.utc).isoformat()


def running_record(project: str, record: ServerRecord) -> dict:
    """Bind readiness to live process identity before releasing startup exclusion."""
    result = dict(schemaVersion=2, state='running', project=project,
                  record=record.to_json(), identity=state.verified_preview(project, record))
    state._validate_running(result)
    return state.snapshot_owned(result)


def uses_runtime(value: dict, cli: str) -> bool:
    """Require this qualified runtime: its exact CLI, or another checkout's copy of the same content."""
    command = value['identity']['command']
    if command.partition(' ')[2].startswith(f'{cli} preview '):
        return True
    served, identity = state.served_cli(command), runtime_identity(cli)
    return identity is not None and served is not None and runtime_identity(served) == identity


def persist(reg: registry.Registry) -> Callable[[dict], None]:
    """A writer that records one entry in this registry transaction."""
    return lambda value: registry.write_entry(reg, value)


def close_dead(reg: registry.Registry, entry: dict) -> dict:
    """Close a running record only when its whole recorded tree has exited on its own."""
    if entry['state'] != 'running' or state.matches(entry):
        return entry
    owned = state.snapshot_owned(entry)
    if state.live_owned(owned):
        return owned
    closed = dict(owned, state='stopped', stoppedAt=time.time(),
                  cleanup={'verified': True, 'survivors': [], 'reason': 'exited-before-this-observation'})
    registry.write_entry(reg, closed)
    return closed


def require_capacity(reg: registry.Registry, project: str) -> None:
    """Refuse beyond the bound, naming every other view that still holds resources."""
    rows = [close_dead(reg, state.settle_launch(persist(reg), entry)) for entry in registry.entries(reg)
            if entry['project'] != project]
    active = [row for row in rows if row['state'] != 'stopped']
    if len(active) < registry.MAX_MANAGED_PREVIEWS:
        return
    views = '; '.join(f"{row['project']} [{row['state']}] {row.get('record', {}).get('url', '')}".strip()
                      for row in active)
    raise StudioServerError(f'Managed Studio limit of {registry.MAX_MANAGED_PREVIEWS} views reached; running: '
                            f'{views}. Nothing was stopped; stop one with managed_preview.py stop <project>.')


def spawned(error: BaseException) -> bool:
    """False only when studio_server tagged the failure as raised before the preview child existed."""
    return getattr(error, 'preview_spawned', True) is not False


def settle_failed_launch(reg: registry.Registry, launch: dict, error: BaseException) -> None:
    """Record a failed launch as stopped only when the preview it started is verified gone.

    A started but unverified server is stopped by its exact identity. Otherwise the 'launching'
    record keeps its survivors, fencing only this project until they exit or ``stop`` stops them.
    """
    if not launch['attempted']:
        return
    if not spawned(error):  # studio_server tagged a failure before any child
        cleanup = dict(verified=True, survivors=[], signals=[], reason='startup failed before spawning a process')
    else:
        pid = launch['pid'] or getattr(error, 'preview_pid', None)
        cleanup = state.discharge_launch(launch['project'], launch['port'], pid)
    outcome = dict(state='stopped', stoppedAt=time.time()) if cleanup['verified'] else \
        dict(state='launching', settledAt=time.time())
    registry.write_entry(reg, dict(schemaVersion=2, project=launch['project'], port=launch['port'], cli=launch['cli'],
                                   cleanup=cleanup, processes=cleanup.get('survivors', []), **outcome, **registry.owned_by(launch)))


def retire(reg: registry.Registry, stale: dict) -> None:
    """Stop this project's own stale view, or its interrupted launch's survivors, verified."""
    if stale['state'] == 'launching':
        state.settle_launch(persist(reg), stale, discharge=True)
        return
    state.stop_registered(persist(reg), stale)


def _studio_slot(project: str, until: float) -> object:
    """Wait for a Studio pool slot until the open's deadline; the member stays in phase 'admitted'."""
    from native_work_pool import PoolRequest, acquire_until
    from native_work_pool_policy import STUDIO_CLASS
    return acquire_until(STUDIO_CLASS, project, until, PoolRequest(STUDIO_CLASS, project, declares_launch=True))


def _record_failure(reg: registry.Registry, attempt: dict, error: BaseException) -> None:
    """Record a failed launch; a cleanup that cannot be verified is noted on the error and the fence stays."""
    try:
        settle_failed_launch(reg, attempt, error)
    except Exception as cleanup_error:  # noqa: BLE001 - the fence stays; both causes are reported.
        error.add_note(f'Studio startup cleanup was not verified: {cleanup_error}')


def _release(slot: object, attempt: dict) -> None:
    """Complete the Studio slot unless a started process may survive, then close it.

    Nothing attempted, or a start that failed before spawning (cleanup verified), releases it; a start
    that may have spawned a process leaves it quarantined (its survivors are the registry's).
    """
    try:
        if not slot.completed and not (attempt['attempted'] and attempt['spawned']):
            slot.complete()
    finally:
        slot.close()


def launch(reg: registry.Registry, project: str, request: dict, stale: dict | None) -> ServerRecord:
    """Admit, start and register one preview; an unverified outcome fences only this project.

    ``request`` holds port, cli, media, owner and until: the open's monotonic deadline, which also
    bounds the wait for a Studio pool slot.
    """
    require_capacity(reg, project)
    slot = _studio_slot(project, request['until'])
    attempt = dict(project=project, attempted=False, spawned=True, port=None, pid=None, cli=request['cli'],
                   owner=request['owner'])
    try:
        if stale:
            retire(reg, stale)
        snapshot = read_snapshot(Path(project))
        reasons = adaptive_admission_reasons(snapshot, capacity_policy(snapshot))
        if reasons:
            raise StudioServerError('Preview admission refused: ' + '; '.join(reasons))
        attempt['port'] = pick_free_port() if request['port'] is None else request['port']
        registry.write_entry(reg, dict(schemaVersion=2, state='launching', project=project, port=attempt['port'],
                                       cli=request['cli'], launchedAt=_utc(), **registry.owned_by(request)))
        attempt['attempted'] = True
        record = launch_preview(request['cli'], project, attempt['port'], open_browser=False)
        attempt['pid'] = record.pid
        running = running_record(project, record)
        if not uses_runtime(running, request['cli']):
            raise StudioServerError('Started preview does not use the qualified native runtime')
        registry.write_entry(reg, dict(running, media=request['media'], openedAt=_utc(), **registry.owned_by(request)))
        slot.complete()
        return record
    except BaseException as error:
        attempt['spawned'] = spawned(error)
        _record_failure(reg, attempt, error)
        raise
    finally:
        _release(slot, attempt)  # complete after a verified start; quarantined only if a process may survive
