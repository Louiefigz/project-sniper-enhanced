"""Managed native Studio previews: one per project, bounded, never switching another project's view.

Opening reuses a project's exact live server or starts one (only its own stale-runtime server or
the survivor of its own interrupted launch is replaced); at most MAX_MANAGED_PREVIEWS run and a
refusal stops nothing. A Studio server is one small Node process that renders nothing, so startup holds a
host-pool slot only until ready. Unverified startup keeps that slot quarantined. An unfinished launch fences
only its own project, and only while a process of it still runs. Studio is served only from the
qualified runtime whose analytics are switched off. ``open_view`` is the owned open a hand-off uses
(ownership, holds and refusals: ``managed_preview_holds``; release: ``managed_preview_owned``).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from native_render_resources import read_snapshot
from native_render_policy import adaptive_admission_reasons, capacity_policy
from studio import managed_preview_registry as registry
from studio import managed_preview_state as state
from studio.native_runtime import install_runtime, runtime_identity
from studio.studio_server import (
    ServerRecord, StudioServerError, is_live_preview, launch_preview,
    pick_free_port, read_record,
)

DEFAULT_WAIT_SECONDS = 60.0


def _utc() -> str:
    """Wall-clock evidence for registry records."""
    return datetime.now(timezone.utc).isoformat()


def _project(directory: str) -> str:
    """Require an existing native composition without writing or regenerating it."""
    project = Path(directory).resolve(strict=True)
    if not (project / 'index.html').is_file():
        raise StudioServerError('Native preview requires an existing index.html')
    return str(project)


def _running(project: str, record: ServerRecord) -> dict:
    """Bind readiness to live process identity before releasing startup exclusion."""
    result = dict(schemaVersion=2, state='running', project=project,
                  record=record.to_json(), identity=state.verified_preview(project, record))
    state._validate_running(result)
    return state.snapshot_owned(result)


def _uses_runtime(value: dict, cli: str) -> bool:
    """Require this qualified runtime: its exact CLI, or another checkout's copy of the same content."""
    command = value['identity']['command']
    if command.partition(' ')[2].startswith(f'{cli} preview '):
        return True
    served, identity = state.served_cli(command), runtime_identity(cli)
    return identity is not None and served is not None and runtime_identity(served) == identity


def _persist(reg: registry.Registry) -> Callable[[dict], None]:
    """A writer that records one entry in this registry transaction."""
    return lambda value: registry.write_entry(reg, value)


def _close_dead(reg: registry.Registry, entry: dict) -> dict:
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


def _adopt_legacy(reg: registry.Registry) -> None:
    """A live view from the earlier single-slot registry keeps running as its project's view."""
    legacy = registry.legacy_running(reg)
    if legacy is None:
        return
    state._validate_running(legacy)
    current = registry.read_entry(reg, legacy['project'])
    if (current and current['state'] != 'stopped') or not state.matches(legacy):
        return
    registry.write_entry(reg, dict(state.snapshot_owned(legacy), schemaVersion=2,
                                   adoptedFrom='legacy-single-slot-registry'))


def _require_capacity(reg: registry.Registry, project: str) -> None:
    """Refuse beyond the bound, naming every other view that still holds resources."""
    rows = [_close_dead(reg, state.settle_launch(_persist(reg), entry)) for entry in registry.entries(reg)
            if entry['project'] != project]
    active = [row for row in rows if row['state'] != 'stopped']
    if len(active) < registry.MAX_MANAGED_PREVIEWS:
        return
    views = '; '.join(f"{row['project']} [{row['state']}] {row.get('record', {}).get('url', '')}".strip()
                      for row in active)
    raise StudioServerError(f'Managed Studio limit of {registry.MAX_MANAGED_PREVIEWS} views reached; running: '
                            f'{views}. Nothing was stopped; stop one with managed_preview.py stop <project>.')


def _rebound(entry: dict, adopted: bool, binding: dict | None) -> dict | None:
    """The entry to write if this open is admitted: a new review MP4 (or an adopted server), else nothing."""
    if binding and binding != entry.get('media'):
        return dict(entry, media=binding)
    return entry if adopted else None


def _plan(reg: registry.Registry, project: str, cli: str,
          binding: dict | None) -> tuple[ServerRecord | None, dict | None, dict | None]:
    """Return (reusable record, this project's own stale view to replace, the entry to write once admitted).

    Nothing is written here: a refused open (another owner's view, a full hold list) leaves the registry,
    including another holder's MP4 binding, exactly as it was (operator review item #5)."""
    prior = registry.read_entry(reg, project)
    if prior and prior['state'] == 'launching':
        prior = state.settle_launch(_persist(reg), prior)
    if prior and prior['state'] == 'launching':
        return None, prior, None  # its own interrupted launch's survivors, replaced only after admission
    if prior and prior['state'] == 'running':
        prior = _close_dead(reg, prior)
    adopted = not prior or prior['state'] == 'stopped'
    if adopted:
        existing = read_record(project)
        if not existing or not is_live_preview(project, existing):
            return None, None, None
        prior = dict(_running(project, existing), media=binding)
    pending = _rebound(prior, adopted, binding)
    if state.matches(prior) and _uses_runtime(prior, cli):
        return state.record_from(prior), None, pending
    return None, prior, pending


def _settle_failed_launch(reg: registry.Registry, launch: dict, error: BaseException) -> None:
    """Record a failed launch as stopped only when the preview it started is verified gone.

    A started but unverified server is stopped by its exact identity. Otherwise the 'launching'
    record keeps its survivors, fencing only this project until they exit or ``stop`` stops them.
    """
    if not launch['attempted']:
        return
    if getattr(error, 'preview_spawned', True) is False:  # studio_server tagged a failure before any child
        cleanup = dict(verified=True, survivors=[], signals=[], reason='startup failed before spawning a process')
    else:
        pid = launch['pid'] or getattr(error, 'preview_pid', None)
        cleanup = state.discharge_launch(launch['project'], launch['port'], pid)
    outcome = dict(state='stopped', stoppedAt=time.time()) if cleanup['verified'] else \
        dict(state='launching', settledAt=time.time())
    registry.write_entry(reg, dict(schemaVersion=2, project=launch['project'], port=launch['port'], cli=launch['cli'],
                                   cleanup=cleanup, processes=cleanup.get('survivors', []), **outcome, **registry.owned_by(launch)))


def _retire(reg: registry.Registry, stale: dict) -> None:
    """Stop this project's own stale view, or its interrupted launch's survivors, verified."""
    if stale['state'] == 'launching':
        state.settle_launch(_persist(reg), stale, discharge=True)
        return
    state.stop_registered(_persist(reg), stale)


def _launch(reg: registry.Registry, project: str, request: dict, stale: dict | None) -> ServerRecord:
    """Admit, start and register one preview; an unverified outcome fences only this project."""
    _require_capacity(reg, project)
    from native_work_lease import NativeWorkLease
    heavy = NativeWorkLease.acquire('heavy', project)
    launch = dict(project=project, attempted=False, port=None, pid=None, cli=request['cli'], owner=request['owner'])
    try:
        if stale:
            _retire(reg, stale)
        snapshot = read_snapshot(Path(project))
        reasons = adaptive_admission_reasons(snapshot, capacity_policy(snapshot))
        if reasons:
            raise StudioServerError('Preview admission refused: ' + '; '.join(reasons))
        launch['port'] = pick_free_port() if request['port'] is None else request['port']
        registry.write_entry(reg, dict(schemaVersion=2, state='launching', project=project, port=launch['port'],
                                       cli=request['cli'], launchedAt=_utc(), **registry.owned_by(request)))
        launch['attempted'] = True
        record = launch_preview(request['cli'], project, launch['port'], open_browser=False)
        launch['pid'] = record.pid
        running = _running(project, record)
        if not _uses_runtime(running, request['cli']):
            raise StudioServerError('Started preview does not use the qualified native runtime')
        registry.write_entry(reg, dict(running, media=request['media'], openedAt=_utc(), **registry.owned_by(request)))
        heavy.complete()
        return record
    except BaseException as error:
        try:
            _settle_failed_launch(reg, launch, error)
        except Exception as cleanup_error:  # noqa: BLE001 - the fence stays; both causes are reported.
            error.add_note(f'Studio startup cleanup was not verified: {cleanup_error}')
        raise
    finally:
        try:
            if not launch['attempted'] and not heavy.completed:
                heavy.complete()
        finally:
            heavy.close()


def _open(directory: str, options: dict, wait_seconds: float) -> tuple[ServerRecord, bool]:
    """Reuse this project's exact live view or start one; True only when this call launched it."""
    project, port = _project(directory), options['port']
    if port is not None and (type(port) is not int or not 1 <= port <= 65535):
        raise ValueError('Preview port must be an integer between 1 and 65535')
    until = registry.monotonic_until(wait_seconds)
    binding, cli = registry.media_binding(options['media']), str(install_runtime() / 'dist/cli.js')
    with registry.transaction(until) as reg:
        _adopt_legacy(reg)
        reused, stale, pending = _plan(reg, project, cli, binding)
        registry.admit_open(reg, (project, reused, stale), options['owner'], pending)
        request = dict(port=port, cli=cli, media=binding, owner=options['owner'])
        return (reused, False) if reused else (_launch(reg, project, request, stale), True)


def open_preview(directory: str, port: int | None = None, media: Path | None = None,
                 wait_seconds: float = DEFAULT_WAIT_SECONDS) -> ServerRecord:
    """Reuse this project's exact live view or start one; other projects' views are untouched."""
    return _open(directory, dict(port=port, media=media, owner=None), wait_seconds)[0]


def open_view(directory: str, owner: registry.ViewOwner | None, media: Path | None = None,
              wait_seconds: float = DEFAULT_WAIT_SECONDS) -> tuple[ServerRecord, bool]:
    """Open like ``open_preview`` for ``owner`` (launch tag + hold, never a foreign replacement); True if launched."""
    return _open(directory, dict(port=None, media=media, owner=registry.view_owner(owner)), wait_seconds)


def _merge_adoption(prior: dict | None, candidate: dict) -> dict:
    """Keep earlier descendant witnesses for the same server; refuse to displace another live one."""
    if not prior or prior['state'] != 'running':
        return candidate
    prior = state.snapshot_owned(prior)
    if prior['identity'] != candidate['identity'] and state.live_owned(prior):
        raise StudioServerError('Another managed preview is active for this project; adoption refused')
    if prior['identity'] != candidate['identity']:
        return candidate
    return state.snapshot_owned(dict(candidate, processes=prior.get('processes', []) + candidate['processes']))


def adopt_preview(directory: str, record: ServerRecord, wait_seconds: float = DEFAULT_WAIT_SECONDS) -> ServerRecord:
    """Register an explicitly identified existing server without restarting it."""
    project = _project(directory)
    candidate = _running(project, record)
    with registry.transaction(registry.monotonic_until(wait_seconds)) as reg:
        registry.write_entry(reg, _merge_adoption(registry.read_entry(reg, project), candidate))
    return record


def stop_preview(directory: str, wait_seconds: float = DEFAULT_WAIT_SECONDS) -> None:
    """Stop only this project's managed view or unfinished launch; every other view keeps running."""
    project = str(Path(directory).resolve())
    with registry.transaction(registry.monotonic_until(wait_seconds)) as reg:
        prior = registry.read_entry(reg, project)
        if prior and prior['state'] == 'running':
            state.stop_registered(_persist(reg), prior)
        if prior and prior['state'] == 'launching':
            state.settle_launch(_persist(reg), prior, discharge=True)


def _status(reg: registry.Registry, entry: dict | None) -> dict:
    """Refresh descendant witnesses and report exact identity and review-media currency."""
    if entry and entry['state'] == 'launching':
        entry = state.settle_launch(_persist(reg), entry)
    if entry and entry['state'] == 'running':
        entry = state.snapshot_owned(entry)
        registry.write_entry(reg, entry)
    live = bool(entry and entry['state'] == 'running' and state.matches(entry))
    return dict(preview=entry, live=live, media=registry.media_status(entry.get('media') if entry else None))


def preview_status(directory: str, wait_seconds: float = DEFAULT_WAIT_SECONDS) -> dict:
    """Return this project's registry state without starting media."""
    project = str(Path(directory).resolve())
    with registry.transaction(registry.monotonic_until(wait_seconds)) as reg:
        return _status(reg, registry.read_entry(reg, project))


def list_previews(wait_seconds: float = DEFAULT_WAIT_SECONDS) -> list[dict]:
    """Every managed view with its project, URL, liveness and bound review MP4."""
    with registry.transaction(registry.monotonic_until(wait_seconds)) as reg:
        _adopt_legacy(reg)
        return [_status(reg, entry) for entry in registry.entries(reg)]


def main() -> None:
    """Serve authored native files directly, with shared lifecycle enforcement."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['open', 'stop', 'status', 'list'])
    parser.add_argument('project', nargs='?')
    parser.add_argument('--port', type=int)
    parser.add_argument('--review-mp4', type=Path, help='Record the review MP4 this view accompanies')
    parser.add_argument('--wait-seconds', type=float, default=DEFAULT_WAIT_SECONDS,
                        help='Longest wait for another Studio registry operation (the caller bound)')
    args = parser.parse_args()
    if args.action != 'list' and not args.project:
        parser.error('project is required')
    from studio.native_short_draft import review_state_notice
    actions = {
        'open': lambda: {**open_preview(args.project, args.port, args.review_mp4, args.wait_seconds).to_json(),
                         **review_state_notice(args.project)},
        'stop': lambda: stop_preview(args.project, args.wait_seconds) or {'status': 'stopped-or-not-registered'},
        'status': lambda: preview_status(args.project, args.wait_seconds),
        'list': lambda: list_previews(args.wait_seconds)}
    print(json.dumps(actions[args.action]()))

if __name__ == '__main__':
    main()
