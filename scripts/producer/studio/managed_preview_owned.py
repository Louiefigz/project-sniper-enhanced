"""Studio views hand-offs launched or hold: counted for qualification, released only by their tokens.

A registry record names ``owner``/``ownerToken`` only when that hand-off's call launched the view
(``managed_preview.open_view``); every hand-off relying on a view is one ``heldBy`` hold and a
plain unowned reuse is the user hold (``managed_preview_holds``). ``owned_views`` reports an
owner's launched views with their retained process witnesses and holds, beside the number of other
active views. ``release_views`` takes the owner claims of specific hand-off records: it drops their
holds and stops a view only when a hand-off launched it and no hand-off or the user still holds it.
``prune_holds`` is the recovery for lost and finished holds: it keeps a hold only while its evidence
(the hand-off's intent or record) still names its token and that hand-off has not ended without a
view to keep: a record whose status is ``handoff-incomplete`` or ``handoff-interrupted`` holds nothing
(P-C), even though its intent file still names the token. An unverified cleanup stays recorded.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from cut_preview_io import bound_json
from studio import managed_preview as managed
from studio import managed_preview_registry as registry
from studio import managed_preview_state as state
from studio.studio_server import StudioServerError


def view_row(status: dict) -> dict:
    """One view as qualification counts it: identity, liveness, processes, holds and cleanup."""
    entry = status['preview']
    identity = entry.get('identity') or {}
    return {'project': entry['project'], 'state': entry['state'], 'live': status['live'],
            'url': (entry.get('record') or {}).get('url'), 'pid': identity.get('pid'),
            'started': identity.get('started'), 'openedAt': entry.get('openedAt'),
            'ownerToken': entry.get('ownerToken'), 'heldBy': entry.get('heldBy', []),
            'retainedProcesses': entry.get('processes', []), 'media': status['media'],
            'cleanup': entry.get('cleanup')}


def owned_views(owner: str, wait_seconds: float = managed.DEFAULT_WAIT_SECONDS) -> dict:
    """This owner's launched views (refreshed witnesses) and how many other views are active."""
    tag = registry.owner_tag(owner)
    rows = managed.list_previews(wait_seconds)
    mine = [view_row(row) for row in rows if row['preview'].get('owner') == tag]
    others = [row for row in rows if row['preview'].get('owner') != tag and row['preview']['state'] != 'stopped']
    return {'owner': tag, 'limit': registry.MAX_MANAGED_PREVIEWS, 'owned': mine,
            'ownedActive': sum(row['state'] != 'stopped' for row in mine), 'otherActive': len(others)}


def _stop(persist: Callable[[dict], None], entry: dict) -> dict:
    """Stop one running view or unfinished launch by identity; an unverified exit is reported, not hidden."""
    try:
        if entry['state'] == 'running':
            done = state.stop_registered(persist, entry)
        else:
            done = state.settle_launch(persist, entry, discharge=True)
    except StudioServerError as error:
        return {'stopped': False, 'verified': False, 'reason': str(error)[:600]}
    cleanup = done.get('cleanup') or {}
    return {'stopped': cleanup.get('verified') is True, 'verified': cleanup.get('verified') is True,
            'signals': cleanup.get('signals', []), 'survivors': cleanup.get('survivors', [])}


def _release_one(persist: Callable[[dict], None], entry: dict, tokens: set[str]) -> dict | None:
    """Drop these tokens' holds; stop a hand-off-launched view only once no hold remains.

    The launching hand-off's release stops it unless another hand-off still holds it; that last
    holder's release then stops it, because its launcher already let it go. A view no hand-off
    launched (the user's) is never stopped here.
    """
    holds, launcher = entry.get('heldBy', []), entry.get('ownerToken')
    launched = launcher in tokens
    if not launched and not any(row.get('token') in tokens for row in holds):
        return None
    remaining = [row for row in holds if row.get('token') not in tokens]
    let_go = launched or (launcher is not None and all(row.get('token') != launcher for row in holds))
    row = {'project': entry['project'], 'priorState': entry['state'], 'launchedByReleased': launched,
           'pid': (entry.get('identity') or {}).get('pid'), 'stillHeldBy': remaining}
    if let_go and not remaining:
        return {**row, **_stop(persist, dict(entry, heldBy=[]))}
    persist(dict(entry, heldBy=remaining))
    reason = ('another hand-off or the user still holds this view' if remaining
              else 'no hand-off launched this view (the user did); a reuser never stops it')
    return {**row, 'stopped': False, 'verified': True, 'reason': reason}


def _writer(reg: registry.Registry) -> Callable[[dict], None]:
    """Record one view's state inside this registry transaction."""
    return lambda value: registry.write_entry(reg, value)


def release_views(owners: list[registry.ViewOwner], wait_seconds: float = managed.DEFAULT_WAIT_SECONDS) -> dict:
    """Release these hand-offs' holds and stop what only they launched; count everything left running."""
    tokens = {registry.view_owner(owner).token for owner in owners}
    with registry.transaction(registry.monotonic_until(wait_seconds)) as reg:
        active = [entry for entry in registry.entries(reg) if entry['state'] != 'stopped']
        rows = [(entry, _release_one(_writer(reg), entry, tokens)) for entry in active]
    views = [row for _entry, row in rows if row is not None]
    return {'status': 'released' if all(row['verified'] for row in views) else 'cleanup-unverified',
            'views': views, 'otherActiveViewsUntouched': sum(row is None for _entry, row in rows),
            'releasedAt': time.time()}


HANDOFF_KINDS = {'native-visible-handoff', 'native-visible-handoff-intent'}
ENDED = {'handoff-incomplete', 'handoff-interrupted'}  # a finished hand-off with no view left to hold


def _evidence(row: dict) -> list[dict]:
    """The readable hand-off intent/record files that still name this hold's token."""
    found = []
    for path in row.get('evidence', []):
        try:
            value = bound_json(Path(path))
        except (OSError, ValueError, RuntimeError):
            continue
        if value.get('kind') in HANDOFF_KINDS and value.get('viewToken') == row['token']:
            found.append(value)
    return found


def _evidenced(row: dict) -> bool:
    """A hold stays while the user holds it, or its hand-off is named by its evidence and has not ended."""
    if row.get('user'):
        return True
    found = _evidence(row)
    return bool(found) and not any(value.get('status') in ENDED for value in found)


def prune_holds(project: str, wait_seconds: float = managed.DEFAULT_WAIT_SECONDS) -> dict:
    """Drop holds whose hand-off evidence is gone or names another token; stop nothing, report everything."""
    canonical = str(Path(project).resolve(strict=True))
    with registry.transaction(registry.monotonic_until(wait_seconds)) as reg:
        entry = registry.read_entry(reg, canonical)
        if entry is None:
            raise StudioServerError(f'No managed Studio view is registered for {canonical}')
        holds = entry.get('heldBy', [])
        kept = [row for row in holds if _evidenced(row)]
        if len(kept) != len(holds):
            registry.write_entry(reg, dict(entry, heldBy=kept))
    launcher = entry.get('ownerToken')
    return {'project': canonical, 'state': entry['state'], 'kept': kept,
            'dropped': [row for row in holds if row not in kept], 'prunedAt': time.time(),
            'launcherStillHolds': any(row.get('token') == launcher for row in kept) if launcher else None,
            'note': 'Pruning stops nothing; stop an unheld view with its launcher\'s release or managed_preview.py stop.'}
