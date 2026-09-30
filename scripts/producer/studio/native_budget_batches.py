"""Batch creation, listing and archiving under the root-wide registry lock.

One batch is active at a time for a user: the host's capacity and the
unbound-export refusal both belong to it. A batch is staged in a hidden
``batches/.creating-*`` directory and renamed into place only once its first
record is durable (``native_budget_staging``), so an interrupted ``start`` leaves
nothing that resolution reads. Hidden entries (Finder files, staged starts of any
schema version) are ignored, but a hidden directory holding any other record (a
renamed batch) and any other unexpected entry are corrupt authority, named in the error.
Archiving moves a closed batch, with its record and trail unchanged, out of
resolution. That is the explicit release of its projects. Resolution (never a
strict read) lifts an exactly closed schema-3 batch in memory (``legacy_closed``),
so the batches an earlier engine left do not refuse every export after an upgrade;
their Shorts stay spent and their folders' supporting owners stay refused until
the operator archives them. A draining batch
(shutdown begun, owned work not yet settled) is neither archivable nor replaceable
by a new batch. Unsettled production tasks keep another engine version's batch unreleased;
this engine's closed batch is archived only once its closure and the host record list them (X37).
Until admission counts the host record (M-100), an open AI row in it, from any batch's closure and
archived or not, refuses a new batch by name (X114: fail closed); the live closed batches' closure rows are
appended to it first, as archive does (X125). While the host record is missing, the AI rows an archived closure
lists refuse by name too (unresolved_executions.archived_ai_rows, P1-RP2 m1).
"""
from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

from headless.durable_files import DurableFileError, read_private_file
from studio.native_budget_schema import AI_POLICY, SCHEMA_VERSION, validate_record
from studio.production.authorization_record import new_authorization
from studio.production.task_schema import holds_unresolved_work
from studio.native_budget_staging import hidden_records, publish_staged, stage_record
from studio.native_budget_store import (
    AUTHORITY, BATCH_ID, MAX_RECORD_BYTES, BudgetAuthorityError, archived_directory, batch_directory,
    locked_batch, read_batch, registry_lock, require_batch_id,
)

MAX_BATCHES = 256  # live (unarchived) batches; every resolution reads each one


class BudgetRefused(RuntimeError):
    """The production budget refuses this work; nothing was started."""

    category = 'budget-refused'


def list_batches(root: Path) -> list[str]:
    """Live batch ids, sorted; unreadable or unexpected contents are corrupt authority."""
    directory = root / 'batches'
    if not directory.exists():
        return []
    try:
        entries = list(directory.iterdir())
    except OSError as error:
        raise BudgetAuthorityError(f'Budget batch directory is unreadable: {error}') from error
    names = sorted(entry.name for entry in entries if not entry.name.startswith('.'))
    unexpected = hidden_records(entries)[1] + [name for name in names if BATCH_ID.fullmatch(name) is None]
    if unexpected:
        raise BudgetAuthorityError(f'Budget batch directory {directory} holds unexpected entries '
                                   f'{unexpected[:3]}; move them out to restore budget decisions')
    if len(names) > MAX_BATCHES:
        raise BudgetAuthorityError(f'More than {MAX_BATCHES} live batches; archive closed ones')
    return names


def live_records(root: Path) -> list[tuple[str, dict]]:
    """Every live batch's validated record; one archived between listing and reading is skipped."""
    return [(name, record) for name in list_batches(root) if (record := _read_live(root, name)) is not None]


def _read_live(root: Path, name: str) -> dict | None:
    """One validated read for resolution, or None when the batch left the live directory meanwhile.

    A record this schema refuses is read raw under the batch's lock; an exactly closed
    schema-3 batch is returned lifted read-only (``legacy_closed``), anything else re-raises.
    """
    try:
        return read_batch(root, name)
    except BudgetAuthorityError:
        if not (root / 'batches' / name).exists():
            return None
        lifted = _lifted_raw(root, name)
        if lifted is None:
            raise
        return lifted


def _lifted_raw(root: Path, name: str) -> dict | None:
    """The lifted copy of a closed schema-3 record, read raw under its lock (never written)."""
    try:
        with locked_batch(root, name, create=True) as session:
            raw = json.loads(read_private_file(session.dir_fd, AUTHORITY, MAX_RECORD_BYTES).decode('utf-8'))
    except (OSError, DurableFileError, UnicodeError, ValueError):
        return None
    return legacy_closed(raw)


def legacy_closed(raw: object) -> dict | None:
    """A closed schema-3 batch lifted in memory to this schema for resolution only, or None.

    It must be schema 3, closed, with no production block, no clip approvals and no running
    launch; the lift adds empty approvals, an empty production block and a completed
    authorization, and is returned only if it passes this schema. Nothing is written or
    migrated: strict reads (status, archive, continuity) still refuse the record.
    """
    if type(raw) is not dict or raw.get('schemaVersion') != 3 or raw.get('status') != 'closed' or 'production' in raw:
        return None
    clips = raw.get('clips')
    if type(clips) is not dict or not all(type(clip) is dict and 'approvals' not in clip for clip in clips.values()):
        return None
    if any(type(row) is dict and row.get('status') == 'running' for clip in clips.values()
           for row in (clip.get('attempts') if type(clip.get('attempts')) is list else [])):
        return None
    lifted = {**copy.deepcopy(raw), 'schemaVersion': SCHEMA_VERSION}
    for clip in lifted['clips'].values():
        clip['approvals'] = []
    lifted['production'] = {'ai': {'slots': AI_POLICY['defaultSlots'], 'reservations': 1, 'charged': 0},
                            'drain': None, 'tasks': {}, 'governance': None, 'authorization': None}
    lifted['production']['authorization'] = new_authorization(lifted)
    try:
        validate_record(lifted)
    except ValueError:
        return None
    return lifted


def active_batches(root: Path) -> list[tuple[str, dict]]:
    """Every live batch's validated record whose status is active (normally at most one)."""
    return [(name, record) for name, record in live_records(root) if record['status'] == 'active']


def current_batches(root: Path) -> list[tuple[str, dict]]:
    """Every live batch that is not closed: active, or draining with unsettled work (normally at most one)."""
    return [(name, record) for name, record in live_records(root) if record['status'] != 'closed']


class PredecessorCurrent(BudgetRefused):
    """Another batch is still active or draining, or closed with unresolved AI work; a new batch waits."""


def _open_ai_rows(root: Path) -> list[dict]:
    """The host record's open AI rows, every host's (X114: fail closed until M-100 counts them at admission)."""
    from studio.production.host_contract import HOSTS
    from studio.production.task_schema import TASK_KINDS
    from studio.production.unresolved_executions import RECORD, open_rows
    if not (root / RECORD).exists():
        return []
    rows = {(row['batchId'], row['taskId']): row for host in HOSTS for row in open_rows(root, host)}
    return [row for row in rows.values() if TASK_KINDS[row['kind']] == 'ai']


def _record_closures(root: Path, records: list[tuple[str, dict]]) -> None:
    """Append the closure rows the host record lacks for every live closed batch of this engine, as archive does,
    so the creation check below reads them even after the host record lost them (X125 N3; a no-op normally)."""
    from studio.production.lifecycle import record_closure
    for _name, record in records:
        if record['status'] == 'closed' and record.get('schemaVersion') == SCHEMA_VERSION:
            record_closure(record, root)


def refuse_creation(root: Path, batch_id: str) -> None:
    """Raise unless a new batch with this id may be published now (call under the registry lock)."""
    from studio.production.unresolved_executions import RECORD, archived_ai_rows
    records = live_records(root)
    current = [(name, record['status']) for name, record in records if record['status'] != 'closed']
    if current:
        name, status = current[0]
        raise PredecessorCurrent(f'Batch {name} is still {status}; close it before starting another (one production '
                                 'batch runs at a time, and a draining batch keeps its unresolved work until it settles)')
    if not (root / RECORD).exists() and (listed := archived_ai_rows(root)):   # P1-RP2 m1: fail closed
        raise PredecessorCurrent(f'unresolved-executions.jsonl is missing, yet archived closures list unresolved AI '
                                 f'work ({", ".join(listed[:3])}); a new batch waits until that host record is '
                                 'restored (fail closed until admission counts it, M-100)')
    _record_closures(root, records)
    if unresolved := _open_ai_rows(root):
        tasks = ', '.join(f'{row["batchId"]}/{row["taskId"]}' for row in unresolved[:3])
        raise PredecessorCurrent(f'Batch {unresolved[0]["batchId"]} closed with unresolved AI work ({tasks}) still '
                                 'charged in unresolved-executions.jsonl; a new batch waits until termination evidence '
                                 'resolves it (fail closed until admission counts it, M-100)')
    if len(records) >= MAX_BATCHES:
        raise BudgetRefused(f'{len(records)} live batches exist; archive closed ones '
                            '(native_batch.py archive --batch ID) before starting another')
    if batch_directory(root, batch_id).exists() or archived_directory(root, batch_id).exists():
        raise BudgetAuthorityError(f'Batch {batch_id} already exists; batches are never restarted')


def create_batch(root: Path, record: dict) -> None:
    """Publish a brand-new batch exactly once, while no other batch is active or draining."""
    batch_id = require_batch_id(record.get('batchId'))
    validate_record(record)
    with registry_lock(root):
        refuse_creation(root, batch_id)
        publish_staged(root, stage_record(root, record), batch_id)


def archive_batch(root: Path, batch_id: str, reason: str) -> dict:
    """Move a closed batch without running launches out of resolution; nothing is deleted.

    A closed batch written by another engine version (refused by this schema) can be
    archived too: that is the migration path, recorded like any other archive.
    """
    if type(reason) is not str or not reason.strip():
        raise ValueError("Archiving a batch needs the operator's reason")
    with registry_lock(root):
        with locked_batch(root, batch_id, create=True) as session:
            record = _archivable(session, root)
            session.event({'event': 'batch-archived', 'batchId': batch_id, 'reason': reason[:512]})
        target = archived_directory(root, batch_id)
        if target.exists():
            raise BudgetAuthorityError(f'An archived batch {batch_id} already exists')
        os.rename(batch_directory(root, batch_id), target)
    return record


def _current_or_foreign_closed(session: object) -> dict:
    """This engine's validated record, or another engine version's record that is released."""
    try:
        return session.read()
    except BudgetAuthorityError as error:
        try:
            raw = json.loads(read_private_file(session.dir_fd, AUTHORITY, MAX_RECORD_BYTES).decode('utf-8'))
        except (OSError, DurableFileError, UnicodeError, ValueError):
            raise error from None
        if foreign_released(raw):
            return {**raw, 'status': 'closed'}
        raise


def foreign_released(raw: object) -> bool:
    """Another engine version's record that is closed, or whose latest output deadline has passed.

    Such a batch can admit no new work with any engine, so this engine may archive it
    (and later readers may accept it as released history) without interpreting its media
    rows. Production tasks are read conservatively: any task that has not ended, or that
    holds an unresolved resource, and any draining status keep it unreleased. A clip
    without an ``output`` row is a Short (the batch's 40 minutes); one with a row keeps
    the run until its own ``deadlineElapsed`` (a Long's 180 minutes).
    """
    if type(raw) is not dict or raw.get('schemaVersion') == SCHEMA_VERSION or holds_unresolved_work(raw):
        return False
    if raw.get('status') == 'closed':
        return True
    if any('capacityClock' in clip for clip in raw.get('clips', {}).values()):
        return False  # A foreign capacity policy cannot be retired using its base wall deadline.
    try:
        rows = [clip.get('output') for clip in raw['clips'].values()]
        latest = max([float(raw['deadlines']['deliverySeconds'])] + [float(row['deadlineElapsed']) for row in rows if row])
        deadline = float(raw['startEpoch']) + latest
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    return raw.get('status') == 'active' and time.time() >= deadline


def _archivable(session: object, root: Path) -> dict:
    """The record, when it may leave resolution: closed, no running launch, unsettled work recorded at closure.

    This engine's closure rows the host record lacks are appended first, a no-op in normal operation (X37).
    """
    from studio.production.lifecycle import archive_refusal, record_closure
    record = _current_or_foreign_closed(session)
    if record.get('schemaVersion') == SCHEMA_VERSION:
        record_closure(record, root)
    refusal = archive_refusal(record, root)
    if refusal:
        raise BudgetRefused(refusal)
    return record
