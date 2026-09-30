"""Unlocked, cached, tolerant credit and task-row reads (P1 Step B10, C9; MASTER-PLAN M-053).

Owner monitors (``NativeRun.monitor``, every 0.5 s), the export watchdog (every second) and grant checks read a
Short's settled capacity credit through ``queue_authority.credit_delta``; the watchdog also reads its task row.
None of them takes the batch lock. The store replaces ``authority.json`` atomically (``write_pending_replace``),
so an unlocked read sees one whole committed record, and a lock held by a reconcile or by another owner's commit
no longer stalls a monitor. Each read checks only what it uses: the batch status and the clip's clock under its
own policy (``queue_clock_schema.problem``), or the task table. The full closed validation still runs on every
locked read and commit.

Credit only grows, so a value already read is conservative:

- A credit read is cached per (authority, batch, clip) for ``CREDIT_CACHE_SECONDS`` of monotonic time.
- A read that fails returns the last value read (with none yet, the grant's ``atGrant``: no credit) while the
  run of failures is at most ``CREDIT_READ_TOLERANCE_SECONDS`` old. After that it raises
  ``CapacityCreditUnavailable``. The tolerance is the watchdog's grace past a launch grant, so a read gap no
  longer than it extends nothing that grant does not already allow.
- Credit smaller than the grant's ``atGrant`` or than the last credit read raises ``CapacityCreditRegressed``: the
  authority was rolled back or edited. It is never tolerated. ``atGrant`` is itself a credit read (under the lock,
  when the grant was bound) and credit only grows, so a fresh process's first read is checked against it too.

A batch that is not active, or a clip without an enabled clock, gives no credit (today's rule); that is not a
regression. The task-row read has the same tolerance and no cache. Readings are kept per process.

Both named errors record when this process first met them (``since``). The owner's monitor stops on them at once,
by name. The export watchdog is the backstop: ``watchdog_stop`` names the stop only after
``process.DEADLINE_GRACE_SECONDS`` more, as the watchdog backs up a launch grant, so the owner names, cleans up and
publishes first, and the watchdog still stops a stuck owner on its graceful path.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from headless.durable_files import DurableFileError, open_private_dir, read_private_file
from studio.native_budget_schema import BATCH_STATES
from studio.native_budget_store import AUTHORITY, MAX_RECORD_BYTES, BudgetAuthorityError, batch_directory
from studio.production import process, queue_clock
from studio.production.queue_clock_schema import problem

CREDIT_CACHE_SECONDS = 1.0
CREDIT_READ_TOLERANCE_SECONDS = process.DEADLINE_GRACE_SECONDS
# What an unreadable authority raises. DurableFileError is how the durable-file layer reports an OSError (a
# missing, unsafe or unreadable directory or file); shape faults below are raised as ValueError.
UNREADABLE = (OSError, ValueError, KeyError, DurableFileError)


class NamedCreditError(BudgetAuthorityError):
    """A credit read that stops the render by name, with when this process first met the condition."""

    def __init__(self, message: str, since: float) -> None:
        """Keep the message and ``since``, the monotonic time this process first met the condition as this error.

        Args:
            message: The named abort's text.
            since: Monotonic seconds when the condition began to be this error in this process.
        """
        super().__init__(message)
        self.since = since

    @property
    def category(self) -> str:
        """The named failure category, for the processes that publish ``getattr(error, 'category', …)``: the native
        pipeline and the section supervisor, whose stage allocations carry the credit reference (X158 D2)."""
        return credit_category(self)


class CapacityCreditUnavailable(NamedCreditError):
    """The authority stayed unreadable past the read tolerance: the render stops by name (this can clear)."""


class CapacityCreditRegressed(NamedCreditError):
    """Settled credit went down: the authority was rolled back or edited (never transient)."""


CREDIT_ERRORS = (CapacityCreditUnavailable, CapacityCreditRegressed)
CREDIT_CATEGORIES = ('capacity-credit-unavailable', 'capacity-credit-regressed')


@dataclass
class Reading:
    """One key's last value read, when it was read, the last credit read, when the current failures began, and when
    this process first met a regression it still sees."""

    value: object = None
    read_at: float | None = None
    credit: float | None = None
    failed_since: float | None = None
    regressed_since: float | None = None


_CREDIT: dict[tuple[str, str, str], Reading] = {}
_TASKS: dict[tuple[str, str, str], Reading] = {}


def snapshot(root: Path, batch_id: str) -> dict:
    """The batch's committed record, read without the batch lock and without full validation.

    Args:
        root: The budget authority root.
        batch_id: The live batch to read.

    Returns:
        The decoded record.

    Raises:
        DurableFileError: The batch directory or its record is missing or unsafe.
        ValueError: The record is not JSON, or not a JSON object.
    """
    dir_fd = open_private_dir(str(batch_directory(root, batch_id)))
    try:
        raw = read_private_file(dir_fd, AUTHORITY, MAX_RECORD_BYTES)
    finally:
        os.close(dir_fd)
    record = json.loads(raw.decode('utf-8'))
    if type(record) is not dict:
        raise ValueError(f'Budget authority for {batch_id} is not a record')
    return record


def settled_credit(ref: dict) -> float:
    """The clip's settled credit, read without the batch lock; cached, tolerant and never lower than before.

    Args:
        ref: A validated ``capacityCredit`` allocation reference (``queue_authority.validate_reference``).

    Returns:
        The clip's ``excludedSeconds``; ``ref['atGrant']`` (no credit) while the batch is not active, the clip's
        clock is not enabled, or the first reads have all failed within the tolerance.

    Raises:
        CapacityCreditUnavailable: Every read has failed for longer than ``CREDIT_READ_TOLERANCE_SECONDS``.
        CapacityCreditRegressed: The credit read is below the grant's ``atGrant`` or the last credit read.
    """
    reading = _CREDIT.setdefault((ref['authority'], ref['batchId'], ref['clipId']), Reading())
    credit = _tolerant(reading, lambda: _read_credit(ref, reading), f'Short {ref["clipId"]} capacity credit',
                       CREDIT_CACHE_SECONDS)
    return ref['atGrant'] if credit is None else credit


def _read_credit(ref: dict, reading: Reading) -> float | None:
    """One snapshot's credit for the clip, or None when no credit applies; checks the status and the clip's clock."""
    record = snapshot(Path(ref['authority']), ref['batchId'])
    clips = record['clips']
    clip = clips[ref['clipId']] if type(clips) is dict else None
    issue = problem(clip) if type(clip) is dict and type(clip.get('output', {})) is dict else 'clip shape'
    if issue or record['status'] not in BATCH_STATES:
        raise ValueError(f'Short {ref["clipId"]} capacity credit cannot be read: {issue or "batch status"}')
    if record['status'] != 'active' or not queue_clock.enabled(clip):
        return None
    credit = queue_clock.excluded(clip)
    _require_no_regression(ref, reading, credit)
    reading.credit = credit
    return credit


def _require_no_regression(ref: dict, reading: Reading, credit: float) -> None:
    """Refuse credit below the grant's ``atGrant`` or the last credit read in this process (fail closed, OQ-2).

    Args:
        ref: The grant's validated credit reference (its ``atGrant`` was read when the grant was bound).
        reading: The clip's reading; ``regressed_since`` keeps when this process first met the regression.
        credit: The credit just read.

    Raises:
        CapacityCreditRegressed: The credit is below either value; ``since`` is the first sight in this process.
    """
    floor = max(ref['atGrant'], reading.credit or 0.0)
    if credit >= floor:
        return
    reading.regressed_since = monotonic() if reading.regressed_since is None else reading.regressed_since
    raise CapacityCreditRegressed(f'Short {ref["clipId"]} capacity credit went down from {floor:.1f}s to '
                                  f'{credit:.1f}s; the authority was rolled back or edited', reading.regressed_since)


def task_row(root: Path, batch_id: str, task_id: str) -> dict | None:
    """The task's row from an unlocked snapshot, for the watchdog's claim and cancel check; same tolerance.

    Args:
        root: The budget authority root.
        batch_id: The task's batch.
        task_id: The task.

    Returns:
        The row; None when a readable record has no such task, or when every read so far has failed (within
        the tolerance). A failed read after a good one returns the last row read.

    Raises:
        CapacityCreditUnavailable: Every read has failed for longer than ``CREDIT_READ_TOLERANCE_SECONDS``.
    """
    reading = _TASKS.setdefault((str(root), batch_id, task_id), Reading())
    return _tolerant(reading, lambda: _row(snapshot(root, batch_id), task_id), f'Task {task_id} of batch {batch_id}',
                     0.0)


def _row(record: dict, task_id: str) -> dict | None:
    """One task row, or None when the task table has no such task; a table or row of the wrong shape is unreadable."""
    production = record['production']
    tasks = production['tasks'] if type(production) is dict else None
    if type(tasks) is not dict or type(tasks.get(task_id, {})) is not dict:
        raise ValueError(f'Task {task_id} cannot be read: task table shape')
    return tasks.get(task_id)


def _tolerant(reading: Reading, read: Callable[[], object], label: str, cache: float) -> object:
    """Run ``read`` unless the last value is younger than ``cache`` seconds; hold the last value through failures.

    Args:
        reading: The key's reading, updated in place.
        read: One unlocked read; it raises one of ``UNREADABLE`` when the authority cannot be read.
        label: What was read, for the unavailable message.
        cache: Seconds a value read stays fresh (0.0 reads every time).

    Returns:
        The value read, or while failures are no older than the tolerance the last value read (None before any).

    Raises:
        CapacityCreditUnavailable: The failures are older than ``CREDIT_READ_TOLERANCE_SECONDS``.
    """
    now = monotonic()
    if reading.read_at is not None and now - reading.read_at < cache:
        return reading.value
    try:
        value = read()
    except UNREADABLE as error:
        reading.failed_since = now if reading.failed_since is None else reading.failed_since
        if now - reading.failed_since > CREDIT_READ_TOLERANCE_SECONDS:
            raise CapacityCreditUnavailable(f'{label} has been unreadable for {now - reading.failed_since:.1f}s',
                                            reading.failed_since + CREDIT_READ_TOLERANCE_SECONDS) from error
        return reading.value
    reading.value, reading.read_at, reading.failed_since = value, now, None
    reading.regressed_since = None     # a good read is no regression: the next one starts a new watchdog grace
    return value


def credit_category(error: NamedCreditError) -> str:
    """The failure category a named credit error is recorded and published under (P1 B10).

    Args:
        error: ``CapacityCreditUnavailable`` or ``CapacityCreditRegressed``.

    Returns:
        ``capacity-credit-regressed`` for a regression, else ``capacity-credit-unavailable``.
    """
    return 'capacity-credit-regressed' if isinstance(error, CapacityCreditRegressed) else 'capacity-credit-unavailable'


def watchdog_stop(error: NamedCreditError) -> tuple[str, str] | None:
    """The export watchdog's backstop for a named credit error, the way it backs up a launch grant (X143).

    The owner's monitor meets the same condition within about its own poll and stops by name at once. The watchdog
    waits ``process.DEADLINE_GRACE_SECONDS`` past its own first sight (``error.since``, in its process), so the owner
    names, cleans up and publishes first. After that it returns the named stop, which it takes on its graceful path
    (SIGTERM and the cleanup grace), never the unnamed hard kill of an exception.

    Args:
        error: ``CapacityCreditUnavailable`` or ``CapacityCreditRegressed`` raised by the watchdog's own credit read.

    Returns:
        None within the grace; afterwards (category, detail).
    """
    waited = monotonic() - error.since
    if waited <= process.DEADLINE_GRACE_SECONDS:
        return None
    return credit_category(error), f'{error} (the owner had not stopped {waited:.1f}s after the watchdog saw it)'
