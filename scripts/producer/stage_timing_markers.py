"""Manual work markers and task handoff events in the shared version-2 journal.

Operator and agent phases (source review, authoring, critics) are marked by separate
command invocations. A manual start and its end come from different processes, so they
share one span id, the ``manual-marker`` writer and the wall clock (``wall-epoch``);
monotonic readings are never subtracted across processes. The end copies the start's
identity from the journal, so the pair is exact or refused, never guessed. Every marker
belongs to an explicit run (``--run-id``, ``SNIPER_TIMING_RUN_ID`` or a recorded
``--parent-span-id``); marker commands on one journal are serialized by a kernel lock.

Diagnostics only: ``recorded`` is never quality approval, a task transition or a claim.
"""
from __future__ import annotations

import argparse
import contextlib
import errno
import json
import math
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Iterator

from stage_timing import JOURNAL_UNWRITABLE, HandoffEvent, append_row, journal_path, record_handoff
from stage_timing_context import (
    ACTIVITIES, HANDOFF_PHASES, LINEAGE_ENV, LINEAGE_VARIABLES, MAX_EPOCH, TASK_FIELDS, bounded_id,
    handover_problem, task_scope, timing_context, timing_metadata,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'infra'))
import sniper_file_lock  # noqa: E402  (stdlib-only cross-platform kernel lock)

MANUAL_WRITER = "manual-marker"
WALL_CLOCK = "wall-epoch"
_IDENTITY = ("schemaVersion", "runId", "attemptId", "attemptNo", "writerId", "clock", "spanId",
             "stage", "parentSpanId", *TASK_FIELDS, "metadata", "lineageRejected")
_RUN = ("runId", "attemptId", "attemptNo")
_SCOPE = 'manual stage markers; use unique labels for parallel work'
_LOCK_WAIT_SECONDS = 10


class MarkerRefused(ValueError):
    """A marker cannot be paired or linked exactly, so nothing is written."""


def _parser() -> argparse.ArgumentParser:
    """Keep the documented three positional arguments; every lineage flag is optional."""
    parser = argparse.ArgumentParser(description='Record actual production work, including editorial phases')
    parser.add_argument('directory', type=Path)
    parser.add_argument('stage', help='Unique stage label; production_total surrounds the complete task')
    parser.add_argument('event', choices=('start', 'end', 'handoff'))
    parser.add_argument('--run-id', help='the run this marker belongs to (or SNIPER_TIMING_RUN_ID)')
    parser.add_argument('--span-id', help='end: the span printed by its start (default: the one open start of this label)')
    parser.add_argument('--parent-span-id', help='start/handoff: nest under this recorded span and join its run')
    parser.add_argument('--handover', action='append', metavar='LABEL=SHA256',
                        help='start: an approved input handed over at this start (repeat per title/script)')
    parser.add_argument('--status', choices=('completed', 'failed', 'interrupted'), default='completed')
    parser.add_argument('--activity', choices=ACTIVITIES, help='start: attribute this span (model, tool or a wait)')
    parser.add_argument('--phase', choices=HANDOFF_PHASES, help='handoff: the observed task phase')
    parser.add_argument('--artifact-sha256', help='handoff: the published or accepted artifact')
    parser.add_argument('--consumer-id', help='handoff consumer-accepted: which consumer accepted it')
    parser.add_argument('--task-id')
    parser.add_argument('--claim-epoch', type=int)
    parser.add_argument('--host-turn-id')
    return parser


def _rows(directory: Path) -> list[dict]:
    """Read existing journal rows; malformed lines cannot select a marker."""
    try:
        lines = Path(journal_path(str(directory))).read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return []
    rows = []
    for line in lines:
        with contextlib.suppress(json.JSONDecodeError):
            rows.append(json.loads(line))
    return [row for row in rows if isinstance(row, dict)]


def _find_start(rows: list[dict], span_id: str) -> dict:
    """Resolve one recorded version-2 start by exact span id."""
    found = [row for row in rows if row.get('schemaVersion') == 2
             and row.get('event') == 'start' and row.get('spanId') == span_id]
    if len(found) != 1:
        raise MarkerRefused(f'No single recorded start has span id {span_id!r}')
    return found[0]


def explicit_run(args: argparse.Namespace) -> str | None:
    """The run named by --run-id, else a valid inherited SNIPER_TIMING_RUN_ID, else None."""
    inherited = os.environ.get(LINEAGE_ENV['runId'])
    return args.run_id or (inherited if bounded_id(inherited) else None)


def open_marker(rows: list[dict], stage: str, span_id: str | None, run_id: str | None) -> dict:
    """Return the one open manual start of this label (or span); ambiguity is refused.

    A named run only closes its own starts; without one, starts of several runs need --span-id.
    """
    manual = [row for row in rows if row.get('writerId') == MANUAL_WRITER and row.get('clock') == WALL_CLOCK]
    ended = {row.get('spanId') for row in manual if row.get('event') == 'end'}
    open_starts = [row for row in manual if row.get('event') == 'start' and row.get('stage') == stage
                   and row.get('spanId') not in ended and span_id in (None, row.get('spanId'))
                   and run_id in (None, row.get('runId'))]
    runs = {row.get('runId') for row in open_starts}
    if len(open_starts) != 1 or (span_id is None and run_id is None and len(runs) > 1):
        raise MarkerRefused(f'{len(open_starts)} open manual starts match {stage!r} in {len(runs)} run(s); '
                            'pass --span-id from the start output, name the run, or use unique labels')
    return open_starts[0]


def _try_lock(descriptor: int) -> bool:
    """One nonblocking attempt; only a busy lock returns False."""
    try:
        sniper_file_lock.try_lock(descriptor, 'exclusive')
    except OSError as error:
        if error.errno not in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES):
            raise
        return False
    return True


def _acquire(descriptor: int) -> None:
    """Wait a bounded time for other marker commands on this journal."""
    deadline = time.monotonic() + _LOCK_WAIT_SECONDS
    while not _try_lock(descriptor):
        if time.monotonic() >= deadline:
            raise MarkerRefused('Another marker command held the journal lock for too long')
        time.sleep(0.05)


@contextlib.contextmanager
def journal_lock(directory: Path) -> Iterator[None]:
    """Serialize marker commands that read then append (a sibling lock file, never the journal)."""
    # O_NOFOLLOW: a planted (even dangling) symlink never redirects the lock file's creation.
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(f'{journal_path(str(directory))}.lock', flags, 0o600)
    try:
        sniper_file_lock.prepare(descriptor)
        _acquire(descriptor)
        try:
            yield
        finally:
            sniper_file_lock.unlock(descriptor)
    finally:
        os.close(descriptor)


def _task_scope(args: argparse.Namespace) -> contextlib.AbstractContextManager:
    """Explicit task flags override inherited task lineage for this one marker."""
    if args.task_id is None:
        if args.claim_epoch is not None or args.host_turn_id is not None:
            raise MarkerRefused('--claim-epoch and --host-turn-id require --task-id')
        return contextlib.nullcontext()
    return task_scope(args.task_id, args.claim_epoch, args.host_turn_id)


def _refuse_mixed_run(args: argparse.Namespace) -> None:
    """--run-id never adopts inherited attempt, parent or task lineage of another (or no) run."""
    if args.run_id is None:
        return
    inherited = os.environ.get(LINEAGE_ENV['runId'])
    others = [name for name in LINEAGE_VARIABLES if name != LINEAGE_ENV['runId'] and os.environ.get(name)]
    if (inherited and inherited != args.run_id) or (others and not inherited):
        raise MarkerRefused('--run-id disagrees with the SNIPER_TIMING_* lineage in the environment; '
                            'unset it or omit --run-id')


def _lineage(args: argparse.Namespace, rows: list[dict]) -> dict:
    """The named run's lineage, or the recorded parent's run joined by span id.

    A marker with neither would get its own standalone run and could never pair or link,
    so it is refused.
    """
    _refuse_mixed_run(args)
    with _task_scope(args):
        context = timing_context()
    run_id = explicit_run(args)
    if args.parent_span_id is None:
        if run_id is None:
            raise MarkerRefused('A marker needs its run: pass --run-id (or set SNIPER_TIMING_RUN_ID) '
                                'or --parent-span-id of a recorded span')
        return {**context, 'runId': run_id}
    parent = _find_start(rows, args.parent_span_id)
    if args.run_id is not None and args.run_id != parent.get('runId'):
        raise MarkerRefused('--run-id disagrees with the run of --parent-span-id')
    inherited = (*_RUN, *(TASK_FIELDS if args.task_id is None else ()))
    context = {key: value for key, value in context.items() if key not in inherited}
    context.update({key: parent[key] for key in inherited if key in parent},
                   parentSpanId=args.parent_span_id)
    return context


def _handover(values: list[str] | None) -> list[dict] | None:
    """Parse repeated LABEL=SHA256 identities of the approved titles/scripts handed over."""
    if values is None:
        return None
    entries = [dict(zip(('label', 'sha256'), value.split('=', 1))) for value in values]
    problem = handover_problem(entries)
    if problem:
        raise MarkerRefused(problem)
    return entries


def start(args: argparse.Namespace, rows: list[dict]) -> dict:
    """Open a manual span in the current (or parent's) run with the given task lineage."""
    if args.artifact_sha256 is not None or args.consumer_id is not None:
        raise MarkerRefused('--artifact-sha256 and --consumer-id belong to a handoff event')
    context = _lineage(args, rows)
    context.pop('writerPid')
    handover = _handover(args.handover)
    row = {**context, 'writerId': MANUAL_WRITER, 'clock': WALL_CLOCK, 'stage': args.stage,
           'spanId': str(uuid.uuid4()), 'metadata': timing_metadata({'activity': args.activity}),
           'event': 'start', 'ts': time.time(), 'mono': time.monotonic()}
    return {**row, 'handover': handover} if handover else row


def end(args: argparse.Namespace, rows: list[dict]) -> dict:
    """Close exactly the resolved start, copying its identity so the pair is exact."""
    if any(value is not None for value in (args.parent_span_id, args.activity, args.task_id,
                                           args.claim_epoch, args.host_turn_id, args.artifact_sha256,
                                           args.consumer_id, args.handover)):
        raise MarkerRefused('end copies the identity recorded by its start; pass only --run-id/--span-id/--status')
    # An exact --span-id is narrowed only by an explicit --run-id, never by the environment.
    run_id = args.run_id if args.span_id is not None else explicit_run(args)
    opened = open_marker(rows, args.stage, args.span_id, run_id)
    started = opened.get('ts')
    if isinstance(started, bool) or not isinstance(started, (int, float)) or not math.isfinite(started):
        raise MarkerRefused('The recorded start has no numeric wall-clock time; it cannot be closed')
    now = time.time()
    if now < started:
        raise MarkerRefused('The wall clock is earlier than this start (it stepped back); '
                            'the start stays open rather than record a negative span')
    identity = {key: opened[key] for key in _IDENTITY if key in opened}
    return {**identity, 'event': 'end', 'status': args.status, 'ts': now, 'mono': time.monotonic(),
            'elapsedMs': (now - opened['ts']) * 1000}


def _validate(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Bounded labels and identifiers; the documented directory rule is unchanged."""
    if not args.directory.is_dir() or not 1 <= len(args.stage) <= 128 \
            or any(not (char.isascii() and (char.isalnum() or char in '_-')) for char in args.stage):
        parser.error('Use an existing directory and a bounded ASCII stage identifier')
    for name in ('run_id', 'span_id', 'parent_span_id', 'task_id', 'host_turn_id', 'consumer_id'):
        value = getattr(args, name)
        if value is not None and not bounded_id(value):
            parser.error(f'--{name.replace("_", "-")} must be a bounded identifier')
    if args.claim_epoch is not None and not 0 <= args.claim_epoch <= MAX_EPOCH:
        parser.error(f'--claim-epoch must be an integer from 0 to {MAX_EPOCH}')
    if (args.event == 'handoff') != (args.phase is not None):
        parser.error('--phase is required for, and only valid with, handoff')


def _record(args: argparse.Namespace) -> dict:
    """Write one row and return the printed outcome; refusal raises MarkerRefused."""
    directory = str(args.directory.resolve())
    rows = _rows(args.directory)  # read under journal_lock, so a concurrent end cannot double-close
    if args.event == 'handoff':
        if args.handover is not None or args.activity is not None:
            raise MarkerRefused('--handover and --activity belong to a start marker')
        event = HandoffEvent(args.stage, args.phase, args.artifact_sha256, args.consumer_id)
        result = record_handoff(directory, event, _lineage(args, rows))
        if not result['recorded'] and result['reason'] != JOURNAL_UNWRITABLE:
            raise MarkerRefused(f"Handoff event refused: {result['reason']}")  # the operator sees exit 1
        return {'recorded': result['recorded'], 'eventId': result['row']['eventId'] if result['recorded'] else None}
    row = start(args, rows) if args.event == 'start' else end(args, rows)
    return {'recorded': append_row(directory, row), 'spanId': row['spanId']}


def main(argv: list[str] | None = None) -> None:
    """Print one bounded JSON outcome; a refused marker exits 1 without writing."""
    parser = _parser()
    args = parser.parse_args(argv)
    _validate(parser, args)
    try:
        with journal_lock(args.directory.resolve()):
            outcome = _record(args)
    except ValueError as error:  # MarkerRefused (including a refused handoff)
        print(json.dumps({'recorded': False, 'reason': str(error), 'qualityApproved': False}))
        raise SystemExit(1) from None
    except OSError as error:  # read-only folder, unsupported lock, symlinked lock: telemetry only
        print(json.dumps({'recorded': False, 'reason': f'{JOURNAL_UNWRITABLE}: {error.strerror or error}',
                          'qualityApproved': False}))
        return
    print(json.dumps({**outcome, 'qualityApproved': False, 'authoritative': False, 'scope': _SCOPE}))


if __name__ == '__main__':
    main()
