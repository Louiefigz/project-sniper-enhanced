"""Starting one managed Studio view: the view bound, admission, launch, verification and failure record.

managed_preview.py calls launch() inside its registry transaction and uses the record helpers here;
this module never imports managed_preview. Startup holds a Studio pool slot
(native_work_pool_studio), never a render slot: it waits for one only until the open's own deadline
(the registry transaction's; the wait holds the Studio registry lock, so other projects' opens, stops
and status calls wait with it). The slot is released (completed) after a verified start and after a
failed start whose cleanup is verified: nothing was attempted, the start failed before spawning
anything (studio_server's ``preview_spawned = False``), or what it spawned is proved gone (X97 ruling
3, X150). It stays quarantined only when that cleanup is unverified. Such a start's survivors are the
registry's 'launching' record (managed_preview_state), which fences only this project while one of them
runs and which ``stop`` discharges; when they are known, the quarantined member records them too (phase
'launching', X244 M1), so native_work_recovery.py <nonce> refuses while any of them lives. A member whose
survivors are unknown (the launched PID was never learned, or the opener was killed after spawning) stays
in phase 'admitted' with no process: its recovery checks the project's registry record instead
(native_work_pool_recovery.studio_launch_evidence, X244 b'). Recovery never signals a process.
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

GROUP_SETTLE_SECONDS = 2.0   # how long a failed start's own group may take to empty before it counts as surviving


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


def group_survivors(pid: int | None) -> list[dict]:
    """Live processes of the launched root's own process group (X165 G1, G9).

    studio_server starts the preview in its own session and reaps only the root on a failed start, so a
    process the preview started there (a browser) can outlive it; state.discharge_launch's "already exited"
    proves only the root gone. While any process has that group ID, no new process can take the PID, so an
    empty group and an absent root prove gone every process that stayed in the group. One that left it
    (setsid, or setpgid into another group) is not covered, the same limit as for every tool process.
    """
    if pid is None:
        return []
    return [dict(pid=key, pgid=row[1], started=row[2]) for key, row in state.read_tree_table().items() if row[1] == pid]


def settled_group(pid: int | None) -> list[dict]:
    """``group_survivors`` polled for up to GROUP_SETTLE_SECONDS: a group member that exits on its own once the
    root dies (a helper seeing EOF) can still be in the table for a moment (X244 m1)."""
    deadline = time.monotonic() + GROUP_SETTLE_SECONDS
    group = group_survivors(pid)
    while group and time.monotonic() < deadline:
        time.sleep(0.1)
        group = group_survivors(pid)
    return group


def settle_failed_launch(reg: registry.Registry, launch: dict, error: BaseException) -> bool:
    """Record a failed launch as stopped only when the preview it started is verified gone; return whether it is.

    A started but unverified server is stopped by its exact identity. Otherwise the 'launching'
    record keeps its survivors, fencing only this project until they exit or ``stop`` stops them.
    A verified discharge still fails while a process of the root's own group runs (group_survivors).
    A launch never attempted started nothing, so its cleanup is verified as it stands.
    """
    if not launch['attempted']:
        return True
    if not spawned(error):  # studio_server tagged a failure before any child
        cleanup = dict(verified=True, survivors=[], signals=[], reason='startup failed before spawning a process')
    else:
        pid = launch['pid'] or getattr(error, 'preview_pid', None)
        cleanup = state.discharge_launch(launch['project'], launch['port'], pid)
        group = settled_group(pid) if cleanup['verified'] else []
        if group:  # a process of the failed start's own session still runs: not proved gone
            cleanup = dict(cleanup, verified=False, survivors=group, reason='a process of the failed start still runs')
    launch['survivors'] = cleanup.get('survivors', [])  # the quarantined Studio member records them too (_release)
    outcome = dict(state='stopped', stoppedAt=time.time()) if cleanup['verified'] else \
        dict(state='launching', settledAt=time.time())
    registry.write_entry(reg, dict(schemaVersion=2, project=launch['project'], port=launch['port'], cli=launch['cli'],
                                   cleanup=cleanup, processes=cleanup.get('survivors', []), **outcome, **registry.owned_by(launch)))
    return cleanup['verified'] is True


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
    """Record a failed launch and whether its cleanup is verified; one that cannot be settled is noted on the error.

    attempt['verified'] stays False when settling itself fails: the fence and the Studio slot stay.
    """
    try:
        attempt['verified'] = settle_failed_launch(reg, attempt, error)
    except Exception as cleanup_error:  # noqa: BLE001 - the fence stays; both causes are reported.
        error.add_note(f'Studio startup cleanup was not verified: {cleanup_error}')


def _release(slot: object, attempt: dict) -> None:
    """Complete the Studio slot unless a process of the start may survive, then close it.

    A failed start releases it when its cleanup is verified (X97 ruling 3, X150): nothing was attempted,
    nothing was spawned (studio_server's tag), or what was spawned is proved gone. Only an unverified
    cleanup leaves it quarantined; its known survivors are recorded on the member as well as in the registry
    (X244 M1), so recovery by nonce must find them gone.
    """
    try:
        if not slot.completed and attempt['verified'] is True:
            slot.complete()
        elif not slot.completed and attempt.get('survivors'):
            slot.mark_launching()
            slot.record_processes(attempt['survivors'])
    finally:
        slot.close()


def launch(reg: registry.Registry, project: str, request: dict, stale: dict | None) -> ServerRecord:
    """Admit, start and register one preview; an unverified outcome fences only this project.

    ``request`` holds port, cli, media, owner and until: the open's monotonic deadline, which also
    bounds the wait for a Studio pool slot.
    """
    require_capacity(reg, project)
    slot = _studio_slot(project, request['until'])
    attempt = dict(project=project, attempted=False, verified=False, port=None, pid=None, cli=request['cli'],
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
        _record_failure(reg, attempt, error)
        raise
    finally:
        _release(slot, attempt)  # complete after a verified start or cleanup; quarantined only if unverified
