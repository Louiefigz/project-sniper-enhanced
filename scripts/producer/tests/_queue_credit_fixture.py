"""Shared fixture for the unlocked credit and task-row reads (``test_queue_credit_snapshot``; P1 Step B10, M-053).

One private TEST batch with Shorts A and B (v2 capacity clocks with no credit at grant) and one check task, a 600 s
grant bound to A's clock, and a controlled monotonic clock for ``queue_credit``'s cache and tolerance. Records
are replaced the way the store leaves them after a commit (whole, private, one link). ``lock_held_by_a_thread``
holds the batch's real kernel lock from another thread of this process: no child process is started here.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import contextlib
import copy
import json
import os
import threading
import time
import unittest
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _budget_fixture import FakeClock, fake_clock, private_root, task_spec
from studio.native_budget_batches import create_batch
from studio.native_budget_clock import allocation, start_anchor
from studio.native_budget_policy import BatchSpec, new_batch_record
from studio.native_budget_store import canonical, locked_batch
from studio.production import queue_authority, queue_credit
from studio.production.process import TaskClaim
from studio.production.tasks import new_row

BATCH = 'credit-snapshot'
GRANTED = 600.0
CLAIM = TaskClaim(BATCH, 'check-1', 0, 'TEST-token', 'e' * 64)
TORN = b'{"batchId": '   # a record cut short: not JSON


@contextlib.contextmanager
def lock_held_by_a_thread(root: Path) -> Iterator[None]:
    """Hold the batch's kernel lock from another thread (an flock conflicts across open files in one process)."""
    held, release = threading.Event(), threading.Event()
    thread = threading.Thread(target=_hold, args=(root, held, release))
    thread.start()
    try:
        if not held.wait(5):
            raise AssertionError('the TEST lock holder never took the batch lock')
        yield
    finally:
        release.set()
        thread.join()


def _hold(root: Path, held: threading.Event, release: threading.Event) -> None:
    """Take the batch lock, say so, and keep it until released (at most 4 s)."""
    with locked_batch(root, BATCH):
        held.set()
        release.wait(4)


def clip_row(record: dict) -> dict:
    """Short A's clip row."""
    return record['clips']['A']


def rewrite(path: Path, change: Callable[[dict], None]) -> None:
    """Change the record in place (the file keeps its mode)."""
    record = json.loads(path.read_bytes())
    change(record)
    path.write_bytes(canonical(record))


# Ways an authority becomes unreadable to an unlocked read; each raises one of queue_credit.UNREADABLE.
DAMAGE: dict[str, Callable[[Path], None]] = {
    'not JSON': lambda path: path.write_bytes(TORN),
    'not a record': lambda path: path.write_bytes(b'[]'),
    'no record file': lambda path: path.unlink(),
    'a record file nobody may read': lambda path: os.chmod(path, 0o000),
    'a record file that is not private': lambda path: os.chmod(path, 0o644),
    'no clip A': lambda path: rewrite(path, lambda record: record.update(clips={})),
    'no batch status': lambda path: rewrite(path, lambda record: record.pop('status')),
    'an unknown batch status': lambda path: rewrite(path, lambda record: record.update(status='paused')),
    'a clock its policy refuses': lambda path: rewrite(
        path, lambda record: clip_row(record)['capacityClock'].update(excludedSeconds=-1.0)),
}


class CreditCase(unittest.TestCase):
    """Shorts A and B of a private TEST batch: v2 clocks with no credit at grant, and a 600 s grant bound to A."""

    def setUp(self) -> None:
        """Create the batch (one check task) and the grant; readings start empty, the monotonic clock at 0."""
        self.root, self.now = private_root(self), 0.0
        self.enterContext(fake_clock(FakeClock()))
        self.enterContext(mock.patch.object(queue_credit, 'monotonic', lambda: self.now))
        self.enterContext(mock.patch.dict(queue_credit._CREDIT, clear=True))
        self.enterContext(mock.patch.dict(queue_credit._TASKS, clear=True))
        anchor = self.anchor = start_anchor()
        record = new_batch_record(BatchSpec(BATCH, ('A', 'B'), (), 1), anchor)
        record['production']['tasks']['check-1'] = new_row(record, task_spec('check-1', 'check', run_id=BATCH), [],
                                                           (0, 0.0))
        create_batch(self.root, record)
        self.record = record
        self.grant = self.bind(record, 'A')
        self.path = self.root / 'batches' / BATCH / 'authority.json'

    def bind(self, record: dict, clip: str) -> dict:
        """A 600 s grant bound to ``clip``'s clock in ``record`` (its ``atGrant`` is that clock's credit)."""
        reference = {'authority': str(self.root), 'batchId': BATCH, 'clipId': clip}
        return queue_authority.bind_allocation(allocation(self.anchor, GRANTED, 45.0), record, reference)

    def credit_record(self, seconds: float, status: str = 'active') -> dict:
        """The batch's record with ``seconds`` of settled credit on A's clock (observed time covers it)."""
        record = copy.deepcopy(self.record)
        clip_row(record)['capacityClock'].update(excludedSeconds=seconds, observedElapsed=seconds)
        record['status'] = status
        return record

    def put(self, record: dict) -> None:
        """Replace the record file as the store leaves it after a commit: whole, private, one link."""
        self.path.unlink(missing_ok=True)
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as file:
            file.write(canonical(record))

    def delta(self) -> float:
        """The monitor path's credit read."""
        return queue_authority.credit_delta(self.grant)

    def owner(self) -> SimpleNamespace:
        """A TEST native owner holding the grant, with an hour of independent stage time."""
        return SimpleNamespace(hard_deadline=self.grant, result={}, abort_reason=None, started=time.monotonic(),
                               deadline=3600.0)
