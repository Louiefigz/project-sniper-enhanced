"""Staged starts: first records kept under ``batches/.creating-<batch>-<12 hex>/`` until they go live.

A start writes its first record (and its ``batch-started`` event) into a hidden staging
directory and renames it into place once durable, so an interrupted start leaves nothing
that resolution reads. A start refused because another batch is still active or draining
stays staged too, anchored at the operator's go time, and a later start with the same
authorization adopts it.

Every hidden entry holding a record is classified here. An untouched staged record of this
schema is a staged start; an untouched one of another schema version (left by an earlier or
later engine) is reported as ``foreign-version`` and ignored, never adopted and never fatal.
Anything else hidden that holds a record (a renamed live batch) is not a staging; one that
vanishes while it is read (a start or discard moved it) is simply absent.

A staged start is adoptable only while its batch id is free and its clock still leaves the
latest-safe minimal deliverable (``adoption_floor``) before its delivery deadline, so a batch is
never born at the deadline cliff. One whose clock cannot be dated (the batch clock fails after a
restart, or the wall clock ran ahead of the boot clock) is ``unprovable``: never adopted and never
discarded automatically; the operator decides. Leftovers leave by name: ``sweep_stagings`` (run by
every start under the registry lock) discards the expired ones and those whose batch id is published
or archived; ``discard_staged`` is the operator's discard. Every discard records the authorization it
ends as a miss (go time, deadline, cause, reason) in a ``staging-discarded`` event, and the staging
moves unchanged otherwise to ``archive/.discarded-starts/``; nothing is deleted. A later batch of the
same id lists these (``prior_authorizations``).
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from headless.durable_files import DurableFileError, open_private_dir, private_child_dir
from studio import native_budget_schema as schema
from studio.native_budget_clock import BudgetClockError, ClockAnchor, observe
from studio.native_budget_forecast import route_seconds
from studio.native_budget_store import (
    AUTHORITY, EVENTS, BudgetAuthorityError, archived_directory, batch_directory, locked_batch,
)
from studio.production.authorization_record import PRIOR_BOUND
from studio.production.host_contract import clip_text

STAGING = re.compile(r'\.creating-([a-z0-9][a-z0-9-]{2,63})-[0-9a-f]{12}')
UNTOUCHED = ('projects', 'attempts', 'dispatches', 'deliveries', 'aacByAudio')
DISCARDED = '.discarded-starts'          # under archive/: discarded staged starts, kept unchanged
ADOPTABLE, EXPIRED, TAKEN, FOREIGN, UNPROVABLE = 'adoptable', 'expired', 'taken', 'foreign-version', 'unprovable'
# The latest-safe minimal deliverable: one full-length review draft of the longest approved clip.
# Without approved seconds a Short of this length is assumed.
ASSUMED_OUTPUT_SECONDS = 60.0
# Within one boot the wall clock may drift from the boot clock by seconds; running this far ahead
# means the wall clock was moved, and the staged clock cannot be dated.
CLOCK_SKEW_SECONDS = 60.0


@dataclass(frozen=True)
class Staging:
    """One staged start: its directory, batch id and raw first record (current: this schema's)."""

    path: Path
    batch_id: str
    raw: dict
    current: bool


def _untouched(raw: dict) -> bool:
    """No binding, launch, dispatch, delivery, hold, charge or task: the record never went live."""
    try:
        clips = list(raw['clips'].values())
        production = raw.get('production') or {}
        fresh = raw['status'] == 'active' and not raw['holds'] and not production.get('tasks') \
            and not (production.get('ai') or {}).get('charged') and production.get('drain') is None
        return fresh and all(not any(clip.get(name) for name in UNTOUCHED) and not any(clip['counters'].values())
                             for clip in clips)
    except (KeyError, TypeError, AttributeError):
        return False


def staging_of(entry: Path) -> Staging | None:
    """The staged start this hidden entry holds, or None when it is not one (a renamed batch, a stray record)."""
    match = STAGING.fullmatch(entry.name)
    try:
        raw = json.loads((entry / AUTHORITY).read_text()) if match else None
    except (OSError, UnicodeError, ValueError):
        return None
    if type(raw) is not dict or raw.get('batchId') != match.group(1) or not _untouched(raw):
        return None
    try:
        schema.validate_record(raw)
    except ValueError:
        foreign = raw.get('schemaVersion') != schema.SCHEMA_VERSION
        return Staging(entry, match.group(1), raw, False) if foreign else None
    return Staging(entry, match.group(1), raw, True)


def hidden_records(entries: list[Path]) -> tuple[list[Staging], list[str]]:
    """Staged starts among the hidden entries holding a record, and the names of those that are not.

    An entry that vanished between the listing and its read (renamed into place or discarded
    meanwhile) is absent, not unexpected.
    """
    held = [entry for entry in entries if entry.name.startswith('.') and (entry / AUTHORITY).exists()]
    found = [(entry, staging_of(entry)) for entry in held]
    return [row for _, row in found if row is not None], \
        [entry.name for entry, row in found if row is None and (entry / AUTHORITY).exists()]


def stagings(root: Path) -> list[Staging]:
    """Every staged start under batches/, oldest name first."""
    directory = root / 'batches'
    try:
        entries = sorted(directory.iterdir()) if directory.is_dir() else []
    except OSError as error:
        raise BudgetAuthorityError(f'Budget batch directory is unreadable: {error}') from error
    return hidden_records(entries)[0]


def adoption_floor(raw: dict) -> float:
    """Seconds a staged start must still have before its delivery deadline to be adopted: the draft
    forecast (with its safety factor) of its longest approved clip plus the hand-off and cleanup reserves."""
    lengths = [sum(end - start for start, end in clip['approvals'][-1]['ranges'])
               for clip in raw['clips'].values() if clip['approvals']]
    seconds = min(max(lengths, default=ASSUMED_OUTPUT_SECONDS), 3600.0)
    deadlines = raw['deadlines']
    return route_seconds(raw['rates'], 'draft', seconds) + deadlines['handoffReserveSeconds'] \
        + deadlines['cleanupReserveSeconds']


def _elapsed(raw: dict) -> float | str:
    """The staged clock's elapsed seconds now, or why it cannot be dated."""
    anchor = ClockAnchor.from_record(raw['clock'])
    try:
        now = observe(anchor, raw['startEpoch'])
    except BudgetClockError as error:
        return str(error)
    skew = (now.epoch - anchor.epoch) - (now.continuous - anchor.continuous)
    if now.boot == anchor.boot and now.continuous >= anchor.continuous and skew > CLOCK_SKEW_SECONDS:
        return f'the wall clock ran {skew:.0f} s ahead of the boot clock since this start was staged'
    return now.elapsed


def assess(root: Path, staging: Staging) -> dict:
    """The staging's state, and for this schema's free ones the remaining time, the floor or why it is undated."""
    if batch_directory(root, staging.batch_id).exists() or archived_directory(root, staging.batch_id).exists():
        return {'state': TAKEN}
    if not staging.current:
        return {'state': FOREIGN}
    elapsed, floor = _elapsed(staging.raw), adoption_floor(staging.raw)
    if type(elapsed) is str:
        return {'state': UNPROVABLE, 'why': elapsed}
    remaining = staging.raw['deadlines']['deliverySeconds'] - elapsed
    return {'state': ADOPTABLE if remaining >= floor else EXPIRED, 'remainingSeconds': round(remaining, 1),
            'floorSeconds': round(floor, 1)}


def adoptable_stagings(root: Path, batch_id: str | None = None) -> list[Staging]:
    """Staged starts that a start may still adopt (all of them, or one batch id's)."""
    return [row for row in stagings(root) if batch_id in (None, row.batch_id)
            and assess(root, row)['state'] == ADOPTABLE]


def _epochs(raw: dict) -> tuple[float | None, float | None]:
    """The staged go time and delivery deadline as wall-clock times, when its record states them."""
    try:
        start, deadline = float(raw['startEpoch']), float(raw['startEpoch']) + float(raw['deadlines']['deliverySeconds'])
    except (KeyError, TypeError, ValueError):
        return None, None
    return (start, deadline) if math.isfinite(deadline) else (None, None)


def report(root: Path, staging: Staging) -> dict:
    """What the operator sees for one staged start."""
    raw = staging.raw
    authorization = (raw.get('production') or {}).get('authorization') if staging.current else None
    start, deadline = _epochs(raw)
    return {'name': staging.path.name, 'batchId': staging.batch_id, 'schemaVersion': raw.get('schemaVersion'),
            'authorizedAtEpoch': start, 'deadlineEpoch': deadline,
            'authorization': (authorization or {}).get('identity'), **assess(root, staging)}


def staged_starts(root: Path) -> list[dict]:
    """Every staged start with its state; foreign-version and unprovable ones are listed, never adopted."""
    return [report(root, row) for row in stagings(root)]


def discard(root: Path, staging: Staging, cause: str, reason: str) -> dict:
    """Move one staged start by name out of batches/, recording it as a miss (call under the registry lock)."""
    row = report(root, staging)
    miss = {'name': row['name'], 'authorizedAtEpoch': row['authorizedAtEpoch'], 'deadlineEpoch': row['deadlineEpoch'],
            'discardedAtEpoch': time.time(), 'cause': cause, 'reason': clip_text(reason)}
    with locked_batch(root, staging.batch_id, create=True, directory=staging.path) as session:
        session.event({'event': 'staging-discarded', 'name': row['name'], 'state': row['state'], 'miss': miss})
    target = root / 'archive' / DISCARDED / staging.path.name[1:]
    try:
        archive_fd = open_private_dir(str(root / 'archive'))
        try:
            os.close(private_child_dir(archive_fd, DISCARDED))
        finally:
            os.close(archive_fd)
        os.rename(staging.path, target)
    except (OSError, DurableFileError) as error:
        raise BudgetAuthorityError(f'Cannot discard staged start {row["name"]}: {error}') from error
    return {**row, 'cause': cause, 'reason': miss['reason'], 'miss': miss, 'discardedTo': str(target)}


def sweep_stagings(root: Path) -> list[dict]:
    """Discard staged starts that can never be adopted: expired, or whose batch id is taken (registry lock held).

    Unprovable and foreign-version ones stay for the operator.
    """
    reasons = {EXPIRED: ('expired', 'its delivery deadline no longer leaves room for a minimal deliverable; a '
                                    'later start begins a new clock and this authorization is a miss'),
               TAKEN: ('taken', 'its batch id is published or archived; batches are never restarted')}
    return [discard(root, row, *reasons[state]) for row in stagings(root)
            if (state := assess(root, row)['state']) in reasons]


def _discarded_miss(entry: Path) -> dict:
    """The miss a discarded staging's ``staging-discarded`` event recorded."""
    try:
        events = [json.loads(line) for line in (entry / EVENTS).read_text().splitlines() if line.strip()]
    except (OSError, UnicodeError, ValueError) as error:
        raise BudgetAuthorityError(f'Discarded staged start {entry.name} is unreadable: {error}') from error
    misses = [row['miss'] for row in events if type(row) is dict and row.get('event') == 'staging-discarded']
    if not misses or type(misses[-1]) is not dict:
        raise BudgetAuthorityError(f'Discarded staged start {entry.name} does not record its discard')
    return misses[-1]


def prior_authorizations(root: Path, batch_id: str) -> tuple[list[dict], int]:
    """Earlier authorizations of this batch id that were discarded: the earliest PRIOR_BOUND, and how many more."""
    directory = root / 'archive' / DISCARDED
    names = sorted(entry.name for entry in directory.iterdir()) if directory.is_dir() else []
    ours = [name for name in names if (match := STAGING.fullmatch('.' + name)) and match.group(1) == batch_id]
    misses = sorted((_discarded_miss(directory / name) for name in ours),
                    key=lambda row: (row['authorizedAtEpoch'] is None, row['authorizedAtEpoch'] or 0, row['name']))
    return misses[:PRIOR_BOUND], max(0, len(misses) - PRIOR_BOUND)


def stage_record(root: Path, record: dict) -> Path:
    """Write the first record and its ``batch-started`` event into a new hidden staging directory."""
    staging = root / 'batches' / f'.creating-{record["batchId"]}-{uuid.uuid4().hex[:12]}'
    try:
        staging.mkdir(mode=0o700)
    except OSError as error:
        raise BudgetAuthorityError(f'Cannot stage batch {record["batchId"]}: {error}') from error
    with locked_batch(root, record['batchId'], create=True, directory=staging) as session:
        session.commit(record, {'event': 'batch-started', 'at': record['clock']['epoch'],
                                'batchId': record['batchId'],
                                'authorization': record['production']['authorization']['identity']})
    return staging


def publish_staged(root: Path, staging: Path, batch_id: str) -> None:
    """Rename a staged record into place (the batch becomes live)."""
    os.rename(staging, batch_directory(root, batch_id))
