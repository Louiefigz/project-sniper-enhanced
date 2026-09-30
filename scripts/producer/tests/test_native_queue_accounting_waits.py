"""C3 (P1 Step B6, M-049): a bound Short owner's pool wait extends only by its settled credit.

The owner admission loop (``native_run_admission.join_queue`` and ``attempt_pool_admission``), the pool
(``NativeWorkLease.acquire``) and the batch authority are real: a private pool namespace whose three heavy slots are
held by three live TEST members, and a private authority root with Short A. Only the owner is a TEST stand-in, and
one fake clock drives the batch clock, the loop's monotonic time and its sleeps (probe p14_owner_wait's sequences).
No child process is started and nothing really waits.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import native_work_lease as work
import native_work_pool as pool
import native_work_pool_disk as disk
from native_render_resources import GIB
from _budget_fixture import FINGERPRINT, FakeClock, approval, fake_clock, task_spec
from _native_pool_fixture import isolate_pool, plan_project, qualify_fixture_host
from studio import native_budget_store, native_queue_accounting, native_run_admission as admission
from studio.native_budget_batches import create_batch
from studio.native_budget_clock import ClockAnchor, allocation, start_anchor
from studio.native_budget_policy import BatchSpec, new_batch_record
from studio.native_budget_store import read_batch
from studio.native_run_lifecycle import failure_category, production_remaining
from studio.production import api
from studio.production.claims import Enrollment
from studio.production.queue_authority import bind_allocation

BATCH = 'batch-auth'            # task_spec's run id
GRANTED, RESERVE, PATIENCE = 2280.0, 45.0, 600.0
HOST = {'type': 'host', 'host': 'codex', 'thread': 'TEST-thread', 'turn': 'TEST-turn'}


class CapReached(Exception):
    """The test's own bound on fake time: the owner was still waiting."""


class LoopTime:
    """The admission loop's ``time``: monotonic is the fake clock's; sleep advances it, up to ``cap`` seconds."""

    def __init__(self, clock: FakeClock, cap: float) -> None:
        """Start at the clock's current time."""
        self.clock, self.start, self.cap = clock, clock.continuous, cap

    def monotonic(self) -> float:
        """The fake boot-continuous time."""
        return self.clock.continuous

    def sleep(self, seconds: float) -> None:
        """Advance the fake clock, or stop the test once ``cap`` seconds have passed."""
        if self.clock.continuous + seconds - self.start > self.cap:
            raise CapReached()
        self.clock.advance(seconds)


class OwnerWaitTests(unittest.TestCase):
    """The loop extends its wait by settled credit only; productive overlap earns none, so patience ends it."""

    def setUp(self) -> None:
        """Fill the three heavy slots with live members; create batch A on the private authority root."""
        self.clock = self.enterContext(fake_clock(FakeClock()))
        isolate_pool(self)
        qualify_fixture_host(self, {'heavy': 3, 'audio': 1})
        self.enterContext(mock.patch.object(disk, 'filesystem', return_value=disk.Filesystem(8, 'filesystem:8',
                                                                                             500 * GIB)))
        for _ in range(3):
            holder = plan_project(self, 'short', 45.0)
            request = pool.PoolRequest('heavy', str(holder), root=str(holder), declares_launch=True,
                                       receipt=str(holder / 'pipeline.render.json'))
            self.addCleanup(request.withdraw)
            lease = work.NativeWorkLease.acquire('heavy', str(holder), request=request)
            self.addCleanup(lease.close)
        self.root = native_budget_store.default_root()
        create_batch(self.root, new_batch_record(BatchSpec(BATCH, ('A',), (), 3, ai_slots=4,
                                                           approvals={'A': approval('A')}), start_anchor()))

    def owner(self) -> SimpleNamespace:
        """A TEST owner of Short A's render, bound to a fresh grant, with this process as its supervisor."""
        project = plan_project(self, 'short', 45.0)
        record = read_batch(self.root, BATCH)
        grant = bind_allocation(allocation(ClockAnchor.from_record(record['clock']), GRANTED, RESERVE), record,
                                {'authority': str(self.root), 'batchId': BATCH, 'clipId': 'A'})
        context = {**grant['capacityCredit'], 'supervisor': {'pid': os.getpid(), 'pgid': os.getpgid(0),
                                                             'started': 'TEST start'},
                   'boot': self.clock.boot, 'workerId': str(project / 'pipeline.render.json'), 'taskId': None,
                   'attemptId': None}
        settings = SimpleNamespace(capacity_wait_seconds=PATIENCE, lane='heavy', policy=None,
                                   disk_reservation_bytes=None, disk_expansion=False)
        return SimpleNamespace(settings=settings, project=project, root=project, path=Path(context['workerId']),
                               started=self.clock.continuous, deadline=GRANTED, hard_deadline=grant, lease=None,
                               abort_reason=None, capacity_context=context, capacity_credit=0.0,
                               supporting_contexts=[], capacity_wait_started=None, result={}, persist=lambda: None)

    def join(self, owner: SimpleNamespace, cap: float) -> tuple[list[float], float, BaseException | None]:
        """Run the real loop until it ends or ``cap`` fake seconds pass; (each attempt's until, first, error)."""
        loop, untils, original = LoopTime(self.clock, cap), [], admission.attempt_pool_admission

        def recorded(*args: object) -> float:
            """The real attempt, its returned ``until`` kept."""
            untils.append(original(*args))
            return untils[-1]

        first = min(owner.started + owner.deadline, loop.monotonic() + PATIENCE)
        with mock.patch.object(admission, 'time', loop), mock.patch.object(native_queue_accounting, 'time', loop), \
                mock.patch.object(admission, 'attempt_pool_admission', recorded), mock.patch('builtins.print'):
            try:
                admission.join_queue(owner, first)
            except (CapReached, RuntimeError) as error:
                return untils, first, error
        return untils, first, None

    def credit(self) -> float:
        """Short A's settled render-queue credit."""
        return read_batch(self.root, BATCH)['clips']['A']['capacityClock']['excludedSeconds']

    def test_credited_wait_extends_until_by_settled_credit_only(self) -> None:
        """Capacity-only and nothing else working for A: after 1,000 s the owner still waits, and its deadline has
        moved by exactly the credit its batch settled (within one 2 s poll)."""
        owner = self.owner()
        untils, first, error = self.join(owner, 1000.0)
        self.assertIsInstance(error, CapReached)
        self.assertIsNone(owner.lease)
        credit = self.credit()
        self.assertGreater(credit, 990.0)
        self.assertLessEqual(abs((untils[-1] - first) - credit), 2.0)
        self.assertEqual(owner.capacity_credit, credit)

    def test_productive_overlap_gives_up_after_uncredited_patience(self) -> None:
        """A claimed author of A works during the wait: nothing is credited, and the owner gives up after its
        600 s patience with a named capacity-timeout, leaving the Short its allowance less that wait."""
        api.enroll_director(self.root, BATCH, Enrollment('director', HOST, 'v1', FINGERPRINT))
        api.enqueue_tasks(self.root, BATCH, (task_spec('author-a', 'author', parent='director'),))
        api.claim_task(self.root, BATCH, 'author-a', {**HOST, 'turn': 'TEST-turn-author'})
        owner = self.owner()
        started = self.clock.continuous
        _untils, _first, error = self.join(owner, 1000.0)
        self.assertIsInstance(error, RuntimeError)
        self.assertRegex(str(error), r'^Admission refused: Native heavy work is already active: ')
        self.assertLessEqual(abs(self.clock.continuous - started - PATIENCE), 2.0)
        owner.result.update(status='failed', abortReason=str(error), cleanup={'verified': True})
        self.assertEqual(failure_category(owner.result), 'capacity-timeout')
        self.assertEqual(self.credit(), 0.0)
        self.assertGreaterEqual(production_remaining(owner), GRANTED - RESERVE - PATIENCE - 2.0)


if __name__ == '__main__':
    unittest.main()
