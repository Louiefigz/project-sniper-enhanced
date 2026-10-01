"""Managed native Studio previews: one per project, bounded, never switching another project's view.

Opening reuses a project's exact live server or starts one (only its own stale-runtime server or
the survivor of its own interrupted launch is replaced); at most MAX_MANAGED_PREVIEWS run and a
refusal stops nothing. A Studio server is one small Node process that renders nothing, so startup holds a
Studio pool slot, never a render slot, only until ready; unverified startup keeps that Studio slot quarantined
(launch, admission and the failure record: ``managed_preview_launch``). An unfinished launch fences only its
own project, and only while a process of it still runs. Studio is served only from the qualified runtime
whose analytics are switched off. ``open_view`` is the owned open a hand-off uses (ownership, holds and
refusals: ``managed_preview_holds``; release: ``managed_preview_owned``).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio import managed_preview_registry as registry
from studio import managed_preview_state as state
from studio.managed_preview_launch import close_dead, launch, persist, running_record, uses_runtime
from studio.native_runtime import install_runtime
from studio.studio_server import ServerRecord, StudioServerError, is_live_preview, read_record

DEFAULT_WAIT_SECONDS = 60.0


def _project(directory: str) -> str:
    """Require an existing native composition without writing or regenerating it."""
    project = Path(directory).resolve(strict=True)
    if not (project / 'index.html').is_file():
        raise StudioServerError('Native preview requires an existing index.html')
    return str(project)


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
        prior = state.settle_launch(persist(reg), prior)
    if prior and prior['state'] == 'launching':
        return None, prior, None  # its own interrupted launch's survivors, replaced only after admission
    if prior and prior['state'] == 'running':
        prior = close_dead(reg, prior)
    adopted = not prior or prior['state'] == 'stopped'
    if adopted:
        existing = read_record(project)
        if not existing or not is_live_preview(project, existing):
            return None, None, None
        prior = dict(running_record(project, existing), media=binding)
    pending = _rebound(prior, adopted, binding)
    if state.matches(prior) and uses_runtime(prior, cli):
        return state.record_from(prior), None, pending
    return None, prior, pending


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
        request = dict(port=port, cli=cli, media=binding, owner=options['owner'], until=until)
        return (reused, False) if reused else (launch(reg, project, request, stale), True)


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
    candidate = running_record(project, record)
    with registry.transaction(registry.monotonic_until(wait_seconds)) as reg:
        registry.write_entry(reg, _merge_adoption(registry.read_entry(reg, project), candidate))
    return record


def stop_preview(directory: str, wait_seconds: float = DEFAULT_WAIT_SECONDS) -> None:
    """Stop only this project's managed view or unfinished launch; every other view keeps running."""
    project = str(Path(directory).resolve())
    with registry.transaction(registry.monotonic_until(wait_seconds)) as reg:
        prior = registry.read_entry(reg, project)
        if prior and prior['state'] == 'running':
            state.stop_registered(persist(reg), prior)
        if prior and prior['state'] == 'launching':
            state.settle_launch(persist(reg), prior, discharge=True)


def _status(reg: registry.Registry, entry: dict | None) -> dict:
    """Refresh descendant witnesses and report exact identity and review-media currency."""
    if entry and entry['state'] == 'launching':
        entry = state.settle_launch(persist(reg), entry)
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
