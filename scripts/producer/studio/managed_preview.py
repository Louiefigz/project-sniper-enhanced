"""One registered native preview shared across draft folders and checkouts.

Call open_preview for authored native projects without regenerating their files.
All managed launches use host resource admission and the shared heavy-work lock.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from native_render_resources import read_snapshot
from native_render_policy import adaptive_admission_reasons, capacity_policy
from native_work_lease import NativeWorkLease
from studio import managed_preview_state as state
from studio.native_runtime import install_runtime
from studio.studio_server import (
    ServerRecord, StudioServerError, is_live_preview, launch_preview,
    pick_free_port, read_record,
)


@contextlib.contextmanager
def _control(project: str) -> Iterator[NativeWorkLease]:
    """Serialize short registry transactions; the preview record retains failures."""
    lease = NativeWorkLease.acquire('preview-control', project)
    try:
        yield lease
    finally:
        try:
            lease.complete()
        finally:
            lease.close()


def _project(directory: str) -> str:
    """Require an existing native composition without writing or regenerating it."""
    project = Path(directory).resolve(strict=True)
    if not (project / 'index.html').is_file():
        raise StudioServerError('Native preview requires an existing index.html')
    return str(project)


def _running(project: str, record: ServerRecord) -> dict:
    """Bind readiness to live process identity before releasing startup exclusion."""
    result = dict(schemaVersion=1, state='running', project=project,
                  record=record.to_json(), identity=state.verified_preview(project, record))
    state._validate_running(result)
    return state.snapshot_owned(result)


def _uses_runtime(value: dict, cli: str) -> bool:
    """Require the exact verified SDK path, not merely a HyperFrames process name."""
    return value['identity']['command'].partition(' ')[2].startswith(f'{cli} preview ')


def _launch(lease: NativeWorkLease, project: str, port: int | None, cli: str) -> ServerRecord:
    """Hold heavy exclusion until the preview has a durable ready-state owner."""
    heavy = NativeWorkLease.acquire('heavy', project)
    launch_attempted = False
    try:
        prior = state.read_preview(lease)
        if prior and prior['state'] == 'running':
            state.stop_registered(lease, prior)
        snapshot = read_snapshot(Path(project))
        reasons = adaptive_admission_reasons(snapshot, capacity_policy(snapshot))
        if reasons:
            raise StudioServerError('Preview admission refused: ' + '; '.join(reasons))
        chosen = pick_free_port() if port is None else port
        state.write_preview(lease, dict(schemaVersion=1, state='launching', project=project))
        launch_attempted = True
        record = launch_preview(cli, project, chosen, open_browser=False)
        running = _running(project, record)
        if not _uses_runtime(running, cli):
            raise StudioServerError('Started preview does not use the qualified native runtime')
        state.write_preview(lease, running)
        # The persistent lightweight server now belongs to preview.json. Heavy
        # exclusion covers its startup, not its idle lifetime; no media job ran.
        heavy.complete()
        return record
    finally:
        try:
            if not launch_attempted and not heavy.completed:
                heavy.complete()
        finally:
            heavy.close()


def open_preview(directory: str, port: int | None = None) -> ServerRecord:
    """Reuse the active draft or prove its exit before replacing it with another."""
    project = _project(directory)
    if port is not None and (type(port) is not int or not 1 <= port <= 65535):
        raise ValueError('Preview port must be an integer between 1 and 65535')
    with _control(project) as lease:
        cli = str(install_runtime() / 'dist/cli.js')
        prior = state.read_preview(lease)
        if prior and prior['state'] == 'running':
            if prior['project'] == project and state.matches(prior) and _uses_runtime(prior, cli):
                return state.record_from(prior)
        if not prior or prior['state'] == 'stopped':
            existing = read_record(project)
            if existing and is_live_preview(project, existing):
                running = _running(project, existing)
                state.write_preview(lease, running)
                if _uses_runtime(running, cli):
                    return existing
        return _launch(lease, project, port, cli)


def adopt_preview(directory: str, record: ServerRecord) -> ServerRecord:
    """Register an explicitly identified existing server without restarting it."""
    project = _project(directory)
    candidate = _running(project, record)
    with _control(project) as lease:
        prior = state.read_preview(lease)
        if prior and prior['state'] == 'running':
            prior = state.snapshot_owned(prior)
            if prior['identity'] != candidate['identity'] and state.live_owned(prior):
                raise StudioServerError('Another managed preview is active; adoption refused')
            if prior['identity'] == candidate['identity']:
                candidate = state.snapshot_owned(dict(candidate,
                    processes=prior.get('processes', []) + candidate['processes']))
        state.write_preview(lease, candidate)
    return record


def stop_preview(directory: str) -> None:
    """Stop only a central record bound to this project, preserving other work."""
    project = str(Path(directory).resolve())
    with _control(project) as lease:
        prior = state.read_preview(lease)
        if prior and prior['state'] == 'running' and prior['project'] == project:
            state.stop_registered(lease, prior)


def preview_status(directory: str) -> dict:
    """Return registry state and an exact identity check, without starting media."""
    with _control(directory) as lease:
        prior = state.read_preview(lease)
        if prior and prior['state'] == 'running':
            prior = state.snapshot_owned(prior)
            state.write_preview(lease, prior)
        return dict(preview=prior, live=bool(prior and prior['state'] == 'running' and state.matches(prior)))


def main() -> None:
    """Serve authored native files directly, with shared lifecycle enforcement."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['open', 'stop', 'status'])
    parser.add_argument('project')
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    if args.action == 'open':
        print(json.dumps(open_preview(args.project, args.port).to_json()))
    elif args.action == 'stop':
        stop_preview(args.project)
        print(json.dumps({'status': 'stopped-or-not-registered'}))
    else:
        print(json.dumps(preview_status(args.project)))


if __name__ == '__main__':
    main()
