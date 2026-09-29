"""Host-level record of executions still unresolved when their batch closed (X37, G9).

``<budget root>/unresolved-executions.jsonl`` sits beside ``batches/`` and ``archive/``, so archiving a
batch never moves or removes it. It is append-only. At closure, M-043 appends one
``execution-unresolved`` line for each task that still held a slot or an unresolved resource. Later,
termination evidence appends one ``execution-resolved`` line for it (M-102). No line is ever rewritten
or removed. Every admission reads the open rows of its host (M-100); a row whose host is null (a
process handle or process claimer) is open for every host, so it counts everywhere (fail closed,
X85). The record holds no batch state and is not a task store: a row names the execution (batch id
and task id) and what closure saw. Every line carries this record's own ``schema: 1``.

It fails closed. A record that is unreadable, corrupt, torn or inconsistent raises
``BudgetAuthorityError``, which callers treat as "refuse new work". An operator's statement is never
evidence here (G9): a resolution names a G9 basis, the host's end event (a) or the verified absence
of the process and its descendants (b). Limits:
- this module cannot check that a resolution's detail identifies the execution (a row carries no
  handle to compare against); M-102 must bind the evidence to the execution before calling ``resolve``;
- new rows stop ``RESOLUTION_RESERVE_BYTES`` (1 MiB) below the size bound; that reserve holds about
  1,300 worst-case resolution lines (~780 bytes each), so a resolution is sure to fit only while
  fewer than that many rows are open when the record reaches the bound;
- a torn last line (a crash during an append) must be repaired by hand;
- a closure row already recorded for an execution is never appended again, even if a retried
  closure computed it differently.
"""
from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from headless.durable_files import DurableFileError, locked_private_dir, open_private_file, read_private_file, write_all
from studio.native_budget_schema import BOUNDS
from studio.native_budget_store import BudgetAuthorityError, canonical, ensure_root, require_batch_id
from studio.production.host_contract import HOSTS, encoded_length, valid_handle
from studio.production.task_schema import TASK_ID, TASK_KINDS, TASK_STATES

RECORD, LOCK = 'unresolved-executions.jsonl', 'unresolved-executions.lock'
SCHEMA = 1
MAX_RECORD_BYTES = 16 * 1024 ** 2
RESOLUTION_RESERVE_BYTES = 1024 ** 2
UNRESOLVED, RESOLVED = 'execution-unresolved', 'execution-resolved'
EVIDENCE_BASES = ('host-end', 'process-absent')   # G9 (a) and (b)
ROW_KEYS = frozenset({'taskId', 'kind', 'state', 'host', 'hostProcess', 'reason'})
RESOLVED_KEYS = frozenset({'schema', 'event', 'batchId', 'taskId', 'evidence'})


@dataclass(frozen=True)
class Execution:
    """One recorded execution: the task of a batch."""

    batch_id: str
    task_id: str


def _bounded(value: object) -> bool:
    """A string of at most 512 encoded bytes."""
    return type(value) is str and encoded_length(value) <= 512


def row_problem(row: object) -> str | None:
    """Why a closure row cannot be recorded, or None."""
    if type(row) is not dict or set(row) != ROW_KEYS:
        return 'a row has exactly taskId, kind, state, host, hostProcess and reason'
    if type(row['taskId']) is not str or TASK_ID.fullmatch(row['taskId']) is None or type(row['kind']) is not str \
            or row['kind'] not in TASK_KINDS or row['state'] not in TASK_STATES:
        return 'a row names a task id, a task kind and a task state'
    if row['host'] is not None and row['host'] not in HOSTS:
        return "a row's host is a known host or null"
    process = row['hostProcess']
    if process is not None and (type(process) is not dict or 'type' in process
                                or not valid_handle({**process, 'type': 'process'})):
        return 'hostProcess is null or {pid, pgid, started}'
    if row['reason'] is not None and not _bounded(row['reason']):
        return 'a reason is null or at most 512 bytes'
    return None


def _evidence_problem(evidence: object) -> str | None:
    """Why evidence cannot resolve an execution, or None."""
    if type(evidence) is not dict or set(evidence) != {'basis', 'detail'} or evidence['basis'] not in EVIDENCE_BASES:
        return ('Evidence is {basis, detail} with basis host-end (G9 a) or process-absent (G9 b); an operator '
                'statement is never evidence')
    if not _bounded(evidence['detail']) or not evidence['detail'].strip():
        return 'Evidence detail is 1-512 bytes'
    return None


def _line_problem(line: object) -> str | None:
    """Why one stored line is not a schema-1 row or resolution, or None."""
    if type(line) is not dict or type(line.get('schema')) is not int or line['schema'] != SCHEMA \
            or line.get('event') not in (UNRESOLVED, RESOLVED):
        return 'not a schema-1 execution line'
    try:
        require_batch_id(line.get('batchId'))
    except ValueError as error:
        return str(error)
    if line['event'] == UNRESOLVED:
        return row_problem({key: value for key, value in line.items() if key not in ('schema', 'event', 'batchId')})
    if set(line) != RESOLVED_KEYS or type(line['taskId']) is not str or TASK_ID.fullmatch(line['taskId']) is None:
        return 'a resolution names its batch and task'
    return _evidence_problem(line['evidence'])


@contextlib.contextmanager
def _locked(root: Path) -> Iterator[int]:
    """The record's own kernel lock (a leaf: no other lock is taken while it is held)."""
    ensure_root(root)
    try:
        with locked_private_dir(str(root), LOCK) as dir_fd:
            yield dir_fd
    except (OSError, DurableFileError) as error:
        raise BudgetAuthorityError(f'Host record {RECORD} is unusable: {error}') from error


def _read(dir_fd: int) -> list[dict]:
    """Every validated line, oldest first; a missing record is empty."""
    try:
        os.stat(RECORD, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return []
    raw = read_private_file(dir_fd, RECORD, MAX_RECORD_BYTES)
    if raw and not raw.endswith(b'\n'):
        raise BudgetAuthorityError(f'Host record {RECORD} ends in a torn line; repair it before any admission')
    try:
        lines = [json.loads(text) for text in raw.decode('utf-8').split('\n')[:-1]]
    except (UnicodeError, ValueError) as error:
        raise BudgetAuthorityError(f'Host record {RECORD} is corrupt: {error}') from error
    problem = next(filter(None, map(_line_problem, lines)), None)
    if problem:
        raise BudgetAuthorityError(f'Host record {RECORD} is corrupt: {problem}')
    return lines


def _executions(lines: list[dict]) -> dict[tuple[str, str], dict]:
    """Each recorded execution's row and whether evidence resolved it; any other sequence is corrupt."""
    table: dict[tuple[str, str], dict] = {}
    for line in lines:
        key = (line['batchId'], line['taskId'])
        known = table.get(key)
        if line['event'] == UNRESOLVED and known is None:
            table[key] = {'line': line, 'resolved': False}
        elif line['event'] == RESOLVED and known is not None and not known['resolved']:
            known['resolved'] = True
        else:
            raise BudgetAuthorityError(f'Host record {RECORD} is inconsistent at execution {key[0]}/{key[1]}')
    return table


def _append(dir_fd: int, lines: list[dict], resolution: bool) -> None:
    """Append fsynced lines; new rows stop at the resolution reserve, resolutions use it."""
    data = b''.join(map(canonical, lines))
    limit = MAX_RECORD_BYTES - (0 if resolution else RESOLUTION_RESERVE_BYTES)
    fd = open_private_file(dir_fd, RECORD, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
    try:
        if os.fstat(fd).st_size + len(data) > limit:
            raise BudgetAuthorityError(f'Host record {RECORD} is full: no batch holding unresolved work can close')
        write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(dir_fd)


def append_unresolved(root: Path, batch_id: str, rows: list[dict]) -> int:
    """Record a closing batch's unresolved rows.

    Retrying after a crash appends nothing twice: an execution already recorded (open or resolved)
    is skipped. Every row is validated before anything is written.

    Args:
        root: The budget authority root.
        batch_id: The closing batch.
        rows: ``production.closure.unresolvedAtClose`` rows (``ROW_KEYS``).

    Returns:
        How many rows were new.

    Raises:
        ValueError: A malformed batch id or row, repeated task ids, or more than ``BOUNDS['tasks']`` rows.
        BudgetAuthorityError: The record is unusable, corrupt or full.
    """
    require_batch_id(batch_id)
    if type(rows) is not list or len(rows) > BOUNDS['tasks']:
        raise ValueError(f'A closure lists at most {BOUNDS["tasks"]} rows')
    if problem := next(filter(None, map(row_problem, rows)), None):
        raise ValueError(f'Closure row refused: {problem}')
    if len({row['taskId'] for row in rows}) != len(rows):
        raise ValueError('A closure lists each task once')
    with _locked(root) as dir_fd:
        known = _executions(_read(dir_fd))
        new = [{'schema': SCHEMA, 'event': UNRESOLVED, 'batchId': batch_id, **row}
               for row in rows if (batch_id, row['taskId']) not in known]
        if new:
            _append(dir_fd, new, False)
    return len(new)


def resolve(root: Path, execution: Execution, evidence: dict) -> bool:
    """Append the termination evidence that resolves one recorded execution.

    Args:
        root: The budget authority root.
        execution: The recorded execution.
        evidence: ``{basis: host-end | process-absent, detail: 1-512 bytes}``; the caller (M-102) has
            already bound it to this execution, which this module cannot check.

    Returns:
        True when appended; False when the execution was already resolved.

    Raises:
        ValueError: Malformed evidence (an operator statement included) or an unrecorded execution.
        BudgetAuthorityError: The record is unusable, corrupt or full.
    """
    if problem := _evidence_problem(evidence):
        raise ValueError(problem)
    with _locked(root) as dir_fd:
        known = _executions(_read(dir_fd)).get((execution.batch_id, execution.task_id))
        if known is None:
            raise ValueError(f'No unresolved execution {execution.batch_id}/{execution.task_id} is recorded here')
        if known['resolved']:
            return False
        _append(dir_fd, [{'schema': SCHEMA, 'event': RESOLVED, 'batchId': execution.batch_id,
                          'taskId': execution.task_id, 'evidence': dict(evidence)}], True)
    return True


def open_rows(root: Path, host: str) -> list[dict]:
    """The rows of ``host``, and the null-host rows, that no evidence has resolved, oldest first.

    A null-host row counts against every host (fail closed, X85); M-100 still counts only the AI kinds.
    """
    if host not in HOSTS:
        raise ValueError(f'Unknown host {host!r}')
    with _locked(root) as dir_fd:
        table = _executions(_read(dir_fd))
    return [dict(entry['line']) for entry in table.values()
            if not entry['resolved'] and entry['line']['host'] in (host, None)]


def recorded_task_ids(root: Path, batch_id: str) -> frozenset[str]:
    """Every task of ``batch_id`` the record lists, open or resolved (M-043's archive check)."""
    require_batch_id(batch_id)
    with _locked(root) as dir_fd:
        table = _executions(_read(dir_fd))
    return frozenset(task_id for batch, task_id in table if batch == batch_id)
