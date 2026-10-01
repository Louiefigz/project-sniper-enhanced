"""Durable production-budget authority, separate from best-effort stage timing.

``stage_timings.jsonl`` deliberately never fails production, so it cannot hold
a spending limit. This store is fail-closed instead: every read-modify-write
holds the batch's private kernel lock, every read is checked against the
closed schema (``native_budget_schema.validate_record``), writes are fsynced
pending-replace, and each transition is appended to an fsynced event trail
before the record changes. A change that is not itself a settlement must leave room for every open
production task to record its widest outcome (``task_schema.settlement_reserve``), parallel to the
event trail's reserve. Unreadable, corrupt or unwritable authority raises
``BudgetAuthorityError``, which callers treat as "refuse new work"; it never
touches an existing MP4.

Layout under one per-user root, resolved from the account database (not
``$HOME``) and outside every checkout::

    <root>/registry.lock                      serializes batch creation, binding, archiving
    <root>/batches/<batchId>/authority.json   the only source of truth
    <root>/batches/<batchId>/events.jsonl     fsynced transition trail
    <root>/archive/<batchId>/...              closed batches the operator archived

Bindings live inside the records themselves; there is no separate index that
could be deleted or disagree with them. Creation and archiving are in
``native_budget_batches``.
"""
from __future__ import annotations

import contextlib
import json
import os
import pwd
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from headless.durable_files import (
    DurableFileError, locked_private_dir, open_private_dir, open_private_file,
    private_child_dir, read_private_file, write_all, write_pending_replace,
)
from studio.native_budget_lift import (  # noqa: F401  lift_additive_fields is re-exported for its readers
    lift_additive_fields, newer_content_problem,
)
from studio.native_budget_schema import LIFTED_VERSIONS, SCHEMA_VERSION, a5_shape, validate_record
from studio.native_budget_trail import (  # noqa: F401  the trail's bound, reserve and classes are re-exported
    ERROR_TEXT_CHARS, MAX_EVENT_BYTES, RECORD_ONLY, ROOM_EXEMPT, TERMINAL_EVENTS, TERMINAL_RESERVE_BYTES, error_text,
    terminal as _terminal,
)
from studio.production.settlement import settlement_reserve

AUTHORITY, PENDING, EVENTS, LOCK = 'authority.json', 'authority.pending.json', 'events.jsonl', 'authority.lock'
REGISTRY_LOCK = 'registry.lock'
MAX_RECORD_BYTES = 4 * 1024 ** 2
BATCH_ID = re.compile(r'[a-z0-9][a-z0-9-]{2,63}')
CLIP_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')
A5_SHAPE_REFUSAL = ('Schema 5 record written by an A5-forecast build (attempts carry a forecast field): this engine '
                    'reads only the D1 schema-5 shape. Finish that batch with the engine that wrote it, or archive it '
                    'once closed.')


class BudgetAuthorityError(RuntimeError):
    """Budget authority is missing, unreadable, corrupt or unwritable: refuse new work."""


class TrailFull(BudgetAuthorityError):
    """The event trail refused a line that is not a settling event: it is within its terminal reserve."""


def canonical(value: dict) -> bytes:
    """Serialize one record deterministically; NaN/Infinity are never valid budget data."""
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def default_root() -> Path:
    """The per-user authority root, from the account database so HOME cannot redirect it."""
    base = Path(pwd.getpwuid(os.getuid()).pw_dir) / '.project-sniper'
    if not base.exists():
        base.mkdir(mode=0o700)
    return base.resolve(strict=True) / 'production-budgets'


def ensure_root(root: Path) -> None:
    """Create the private root with its batches and archive children; never loosen modes."""
    try:
        root.mkdir(mode=0o700, exist_ok=True)
        root_fd = open_private_dir(str(root))
        try:
            _private_children(root_fd, ('batches', 'archive'))
        finally:
            os.close(root_fd)
    except (OSError, DurableFileError) as error:
        raise BudgetAuthorityError(f'Budget authority root is unusable: {root}: {error}') from error


def _private_children(root_fd: int, names: tuple[str, ...]) -> None:
    """Create or verify each private child directory."""
    for name in names:
        os.close(private_child_dir(root_fd, name))


@contextlib.contextmanager
def registry_lock(root: Path) -> Iterator[None]:
    """One root-wide kernel lock around decisions that span batches."""
    ensure_root(root)
    try:
        with locked_private_dir(str(root), REGISTRY_LOCK):
            yield
    except DurableFileError as error:
        raise BudgetAuthorityError(f'Budget registry lock failed: {error}') from error


def require_batch_id(batch_id: object) -> str:
    """Batch identifiers are closed lowercase slugs."""
    if type(batch_id) is not str or BATCH_ID.fullmatch(batch_id) is None:
        raise ValueError('Batch id must be 3-64 lowercase letters, digits or hyphens')
    return batch_id


def require_clip_id(clip_id: object) -> str:
    """Logical clip identifiers are closed short names such as A or clip-03."""
    if type(clip_id) is not str or CLIP_ID.fullmatch(clip_id) is None:
        raise ValueError('Clip id must be 1-64 letters, digits, underscores or hyphens')
    return clip_id


@dataclass
class BatchSession:
    """One locked read-modify-write session over a batch's authority."""

    dir_fd: int
    batch_id: str

    def read(self) -> dict:
        """Read the record and validate it against the closed schema."""
        try:
            raw = read_private_file(self.dir_fd, AUTHORITY, MAX_RECORD_BYTES)
            record = json.loads(raw.decode('utf-8'))
            if type(record) is dict and record.get('schemaVersion') == 5 and a5_shape(record):
                raise BudgetAuthorityError(A5_SHAPE_REFUSAL)  # before any lift: the other schema-5 shape (P4-06)
            if problem := newer_content_problem(record):   # before any lift: a 5-7 record with v8-only content
                raise BudgetAuthorityError(f'Budget authority for {self.batch_id} {problem}')
            lift_additive_fields(record)
            validate_record(record)
            if record['schemaVersion'] in LIFTED_VERSIONS:
                record['schemaVersion'] = SCHEMA_VERSION  # Additive lift; retain clocks and counters.
        except (OSError, DurableFileError, UnicodeError, ValueError) as error:
            raise BudgetAuthorityError(f'Budget authority for {self.batch_id} is unreadable or corrupt: '
                                       f'{error}') from error
        if record['batchId'] != self.batch_id:
            raise BudgetAuthorityError(f'Budget authority for {self.batch_id} names another batch')
        return record

    def commit(self, record: dict, event: dict) -> None:
        """Append the transition first, then replace the record (the record is the authority).

        If the record cannot be replaced, a ``commit-failed`` event follows, so the
        trail never shows a transition as if it had happened. If it was replaced but
        the directory sync failed, ``commit-unsynced`` follows and the commit stands
        (past the reserve's stop that line is not written: it settles nothing).
        """
        try:
            validate_record(record)
        except ValueError as error:
            raise BudgetAuthorityError(f'Refusing to write invalid budget authority: {error}') from error
        data = canonical(record)
        if len(data) > MAX_RECORD_BYTES:
            raise BudgetAuthorityError('Budget authority record exceeds its size bound')
        if event.get('event') not in ROOM_EXEMPT and len(data) + settlement_reserve(record) > MAX_RECORD_BYTES:
            raise BudgetAuthorityError('The batch record has no room left for its open tasks to record their '
                                       'outcomes; no new work is admitted')
        # Same-state scheduler heartbeats update the bounded authority snapshot. State
        # transitions retain cumulative totals in the trail; polling itself is unbounded.
        heartbeat = event.get('event') in RECORD_ONLY
        if not heartbeat:
            self.event(event)
        try:
            write_pending_replace(self.dir_fd, (PENDING, AUTHORITY), data)
        except (OSError, DurableFileError) as error:
            self._settle_failed_write(None if heartbeat else event, data, error)

    def _settle_failed_write(self, event: dict | None, data: bytes, error: BaseException) -> None:
        """A replaced but unsynced record stands (recorded); an unreplaced one is a failed commit."""
        try:
            replaced = read_private_file(self.dir_fd, AUTHORITY, MAX_RECORD_BYTES) == data
        except (OSError, DurableFileError):
            replaced = False
        outcome = 'commit-unsynced' if replaced else 'commit-failed'
        if event is not None:
            with contextlib.suppress(BudgetAuthorityError):
                self.event({'event': outcome, 'failedEvent': event.get('event'), 'error': error_text(error)})
        if not replaced:
            raise BudgetAuthorityError(f'Budget authority for {self.batch_id} is unwritable: {error}') from error

    def event(self, value: dict) -> None:
        """Append one fsynced transition; the trail is bounded and never rewritten."""
        line = canonical(value)
        try:
            fd = open_private_file(self.dir_fd, EVENTS, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        except (OSError, DurableFileError) as error:
            raise BudgetAuthorityError(f'Budget event trail for {self.batch_id} is unusable: {error}') from error
        try:
            _append(fd, line, _terminal(value))
        finally:
            os.close(fd)


def _append(fd: int, line: bytes, terminal: bool) -> None:
    """Write one line (new work stops at the reserve; settling events always write) and flush it."""
    try:
        if not terminal and os.fstat(fd).st_size + len(line) > MAX_EVENT_BYTES - TERMINAL_RESERVE_BYTES:
            raise TrailFull('Budget event trail is full: no new work is admitted; close the batch')
        write_all(fd, line)
        os.fsync(fd)
    except (OSError, DurableFileError) as error:
        raise BudgetAuthorityError(f'Budget event trail is unwritable: {error}') from error


def batch_directory(root: Path, batch_id: str) -> Path:
    """A live batch's private directory path (existence is checked by callers)."""
    return root / 'batches' / require_batch_id(batch_id)


def archived_directory(root: Path, batch_id: str) -> Path:
    """Where an archived batch's unchanged record and trail are kept."""
    return root / 'archive' / require_batch_id(batch_id)


@contextlib.contextmanager
def _authority_lock(directory: Path, batch_id: str) -> Iterator[int]:
    """The private kernel lock; any durable-file failure is corrupt authority."""
    try:
        with locked_private_dir(str(directory), LOCK) as dir_fd:
            yield dir_fd
    except DurableFileError as error:
        raise BudgetAuthorityError(f'Budget authority lock for {batch_id} failed: {error}') from error


@contextlib.contextmanager
def locked_batch(root: Path, batch_id: str, create: bool = False, directory: Path | None = None) \
        -> Iterator[BatchSession]:
    """Hold the batch's exclusive kernel lock for one read-modify-write session."""
    directory = directory or batch_directory(root, batch_id)
    if not directory.is_dir():
        raise BudgetAuthorityError(f'Unknown or missing budget batch: {batch_id}')
    with _authority_lock(directory, batch_id) as dir_fd:
        session = BatchSession(dir_fd, batch_id)
        if not create:
            session.read()
        yield session


def read_batch(root: Path, batch_id: str) -> dict:
    """One locked, validated read of a live batch."""
    with locked_batch(root, batch_id) as session:
        return session.read()


def read_any_batch(root: Path, batch_id: str) -> dict:
    """A live or archived batch's validated record (continuity checks accept either)."""
    directory = batch_directory(root, batch_id)
    if not directory.is_dir():
        directory = archived_directory(root, batch_id)
    with locked_batch(root, batch_id, directory=directory) as session:
        return session.read()
