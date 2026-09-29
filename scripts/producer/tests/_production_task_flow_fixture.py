"""TEST batches for the production-task flow tests (M-042, M-043): one batch driven through the locked API.

Each ``Batch`` lives on a private root (the test's own ``native_budget_store.default_root()`` unless another is
given), on the test's fake clock, with clip A's TEST approval and a TEST process table holding only pid 1. A test
that needs the real process table sets ``batch.table = None``. Handles and receipts are TEST values; no host is
called. The settle and close helpers are the M-043 paths: closing waits for the delivery deadline, because clip A
is never handed off.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import contextlib
import io
import json
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from _budget_fixture import FINGERPRINT, FakeClock, approval, fake_clock, receipt, table, task_spec
from studio import native_budget_launch, native_budget_store
from studio.native_budget_batches import create_batch
from studio.native_budget_clock import start_anchor
from studio.native_budget_policy import BatchSpec, new_batch_record
from studio.native_budget_store import locked_batch, read_batch
from studio.production import api
from studio.production.callbacks import TaskResult
from studio.production.claims import ClaimRef, Enrollment

BATCH = 'batch-auth'            # _budget_fixture.task_spec's run id
REAL_TABLE = native_budget_launch._process_table
CLOSE_AFTER_SECONDS = 2500      # past the Short's delivery deadline (2400 s), so close_refusal passes


def host(name: str, kind: str = 'codex') -> dict:
    """A TEST host turn of ``kind`` (codex or claude-code)."""
    return {'type': 'host', 'host': kind, 'thread': f'TEST-thread-{name}', 'turn': f'TEST-turn-{name}'}


class Batch:
    """One TEST batch with an enrolled director, driven through the locked production API."""

    def __init__(self, test: unittest.TestCase, director: str = 'codex', slots: int = 4,
                 root: Path | None = None) -> None:
        """Create the batch on ``root`` (default: the test's private root) and enroll its director.

        Args:
            test: The running test; the clock and process-table patches end with it.
            director: The director's host (``codex`` or ``claude-code``).
            slots: The batch's declared AI slots, the director included.
            root: A private authority root; each batch in one test needs its own.
        """
        self.root, self.table = root or native_budget_store.default_root(), table()
        self.clock = getattr(test, 'flow_clock', None)   # one fake clock per test, shared by its batches
        if self.clock is None:
            self.clock = test.flow_clock = test.enterContext(fake_clock(FakeClock()))
        test.enterContext(patch.object(native_budget_launch, '_process_table', self._process_table))
        spec = BatchSpec(BATCH, ('A',), (), 1, ai_slots=slots, approvals={'A': approval('A')})
        create_batch(self.root, new_batch_record(spec, start_anchor()))
        enrollment = Enrollment('director', host('director', director), 'v1', FINGERPRINT)
        claimed = api.enroll_director(self.root, BATCH, enrollment)
        self.director = ClaimRef('director', claimed['epoch'], claimed['token'])

    def _process_table(self) -> dict:
        """The TEST table, or the real one when ``table`` is None."""
        return REAL_TABLE() if self.table is None else self.table

    def enqueue(self, *tasks: tuple[str, str, tuple[str, ...]]) -> None:
        """Enqueue (id, kind, prerequisites) tasks under the director (due at 1800 s; media on clip A)."""
        specs = [task_spec(task_id, kind, prerequisites=prerequisites, parent='director')
                 for task_id, kind, prerequisites in tasks]
        api.enqueue_tasks(self.root, BATCH, tuple(specs))

    def claim(self, task_id: str, handle: dict | None = None, claimer: dict | None = None) -> ClaimRef:
        """Claim a ready task (for the director unless ``claimer`` is given), then attach ``handle`` if given."""
        claimed = api.claim_task(self.root, BATCH, task_id, claimer or host('director'))
        ref = ClaimRef(task_id, claimed['epoch'], claimed['token'])
        if handle is not None:
            api.attach_task(self.root, BATCH, ref, handle)
        return ref

    def host_event(self, ref: ClaimRef, kind: str, handle: dict) -> dict:
        """Apply one TEST host event of ``kind``; a completion carries ``receipt(task id)``."""
        event = {'type': kind, 'taskId': ref.task_id, 'epoch': ref.epoch, 'token': ref.token, 'handle': handle,
                 'sequence': 1, 'receipts': [], 'failure': None, 'usage': None}
        if kind == 'failed':
            event['failure'] = {'category': 'host-failure', 'detail': 'turn errored'}
        if kind == 'completed':
            event['receipts'] = [receipt(ref.task_id)]
        return api.host_event(self.root, BATCH, event)

    def record(self) -> dict:
        """The batch's validated record."""
        return read_batch(self.root, BATCH)

    def row(self, task_id: str) -> dict:
        """One task row of the validated record."""
        return self.record()['production']['tasks'][task_id]

    def events(self) -> list[dict]:
        """The batch's event trail, oldest first."""
        trail = self.root / 'batches' / BATCH / 'events.jsonl'
        return [json.loads(line) for line in trail.read_text().splitlines()]


def finish(batch: Batch, task_id: str) -> None:
    """Claim, attach on a codex turn and complete: the completion holds its slot (G9: no host end evidence)."""
    ref = batch.claim(task_id, host(task_id))
    api.complete_task(batch.root, BATCH, ref, TaskResult((receipt(task_id),)))


def held_batch(test: unittest.TestCase, root: Path | None = None) -> Batch:
    """A batch whose ``critic`` completed on a codex turn: ended, with its slot held."""
    batch = Batch(test, root=root)
    batch.enqueue(('critic', 'specialist', ()))
    finish(batch, 'critic')
    return batch


def rewrite(batch: Batch, change: Callable[[dict], object]) -> None:
    """Commit a TEST change straight to the record: a shape an older engine or a hand edit left."""
    with locked_batch(batch.root, BATCH) as session:
        record = session.read()
        change(record)
        session.commit(record, {'event': 'TEST-rewrite'})


def close(batch: Batch, on_commit: Callable[[], object] | None = None) -> dict:
    """Close the batch after its delivery deadline.

    Args:
        batch: The TEST batch.
        on_commit: Called inside the closing transaction just before the close's own commit; if it raises,
            nothing is committed (a refused commit).

    Returns:
        ``api.close``'s result.
    """
    batch.clock.advance(CLOSE_AFTER_SECONDS)
    commit = native_budget_store.BatchSession.commit

    def observed_commit(session: object, record: dict, event: dict) -> None:
        """Run ``on_commit`` before the close's own commit; every other commit is unchanged."""
        if on_commit is not None and event['event'] == 'batch-closed':
            on_commit()
        commit(session, record, event)

    with patch.object(native_budget_store.BatchSession, 'commit', observed_commit):
        return api.close(batch.root, BATCH)


def closure_rows(batch: Batch) -> list[tuple]:
    """(taskId, kind, state, host) of each ``production.closure.unresolvedAtClose`` row."""
    rows = batch.record()['production']['closure']['unresolvedAtClose']
    return [(row['taskId'], row['kind'], row['state'], row['host']) for row in rows]


def run_cli(*argv: str) -> tuple[int, dict]:
    """Run ``native_batch.py``'s command vocabulary in this process; returns (exit code, printed JSON)."""
    from studio.production import cli
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            cli.main('TEST native_batch', list(argv))
        except SystemExit as stop:
            return stop.code, json.loads(out.getvalue())
    return 0, json.loads(out.getvalue())
