"""Liveness across engines: whenever a slot is free and some waiter is admissible, someone is admitted.

Four kinds of waiter share one private TEST pool (two heavy slots, a TEST schema-1 record):
  O  the unmodified base (4a15560) client, a separate process driven one attempt per line
     (tests/fixtures/base_pool_driver.py 'step');
  U  this engine, unfenced (a TEST non-APFS root, legacy-v1 profile);
  B  this engine, fenced (an APFS root on this Mac);
  X  this engine, exclusive (a Long no profile covers). X is only ever checked as an
     immediate refusal: it always arrives while the holders are live, so in all 48 orders it
     is refused at once (NativeWorkUnsupportedMix, its ticket withdrawn) and never queues.
     These orders therefore prove that an exclusive request never holds others back, not
     how a queued exclusive request is scheduled.
Two holders occupy the slots while the waiters arrive in a given order and make their first
attempt, then leave. Each round every pending waiter attempts once, in arrival order, and
whoever was admitted completes at the round's end, so every round starts with both slots free.
The property: every such round admits someone until nobody admissible waits. The exact
O -> U -> B cycle (U counted O, O waited for B's fence, B counted U) is also a named
regression, with a negative control that restores the old skip rule and finds the deadlock.
"""
from __future__ import annotations

import itertools
import json
import unittest
from pathlib import Path
from unittest import mock

import native_work_lease as work
import native_work_pool as pool
import native_work_pool_disk as disk
import native_work_pool_fence as fence
import native_work_pool_mix as mix
from native_render_resources import GIB
from _native_pool_fixture import BasePoolClient, isolate_pool, plan_project, project_dir, qualify_fixture_host


class Waiter:
    """One waiter of any kind: attempt() -> 'admitted' | 'queued' | 'refused'; complete() frees its slot."""

    def __init__(self, case: 'LivenessTests', kind: str) -> None:
        """Create the waiter (a base process for O) without attempting."""
        self.case, self.kind, self.lease, self.done, self.last = case, kind, None, False, None
        if kind == 'O':
            self.process = case.base('step', 'heavy', case.short, stdin=True)
            assert case.event(self.process)['event'] == 'ready'
            return
        project, root = {'U': (case.short, case.unfenced), 'B': (case.short, None), 'X': (case.long, None)}[kind]
        self.request = pool.PoolRequest('heavy', project, root=root, declares_launch=True)
        case.addCleanup(self.request.withdraw)

    def attempt(self) -> str:
        """One admission attempt; a refusal that waiting cannot clear retires the waiter."""
        if self.kind == 'O':
            self.case.send(self.process, 'try')
            event = self.case.event(self.process)
            self.last = event.get('reason')
            return 'admitted' if event['event'] == 'admitted' else 'queued'
        try:
            self.lease = work.NativeWorkLease.acquire('heavy', self.request.project, request=self.request)
        except work.NativeWorkBusy as error:
            self.last = f'{type(error).__name__}: {error}'
            if 'already active' in str(error):
                return 'queued'
            self.done = True
            self.request.withdraw()  # a refused request holds no place in the queue
            return 'refused'
        return 'admitted'

    def complete(self) -> None:
        """Complete the admitted member."""
        self.done = True
        if self.kind == 'O':
            self.case.send(self.process, 'done')
            assert self.case.event(self.process)['event'] == 'completed'
            return
        self.lease.complete()
        self.lease.close()


class LivenessTests(BasePoolClient, unittest.TestCase):
    """Every arrival order of the four kinds makes progress; the old skip rule deadlocks O -> U -> B."""

    def setUp(self) -> None:
        """TEST record (2 heavy, 1 audio), projects, and a TEST non-APFS root for unfenced members."""
        isolate_pool(self)
        self.records = qualify_fixture_host(self, {'heavy': 2, 'audio': 1})
        self.short = str(plan_project(self, 'short', 45.0))
        self.long = str(plan_project(self, 'long', 600.0))
        self.unfenced, self.holder_root = str(project_dir(self, 'unfenced')), str(project_dir(self, 'holder'))
        real = disk.filesystem
        fake = {path: disk.Filesystem(8, 'filesystem:8', 500 * GIB) for path in (self.unfenced, self.holder_root)}
        self.enterContext(mock.patch.object(disk, 'filesystem', side_effect=lambda path: fake.get(path) or real(path)))

    def run_order(self, order: tuple[str, ...]) -> list[str]:
        """Run one arrival order in a fresh namespace; return who was admitted in which round, or the stall."""
        self.root = Path(project_dir(self, 'registry-' + ''.join(order))) / 'registry'
        with mock.patch.object(work, 'state_root', return_value=self.root):
            holders = [work.NativeWorkLease.acquire('heavy', self.short, request=pool.PoolRequest(
                'heavy', self.short, root=self.holder_root, declares_launch=True)) for _ in range(2)]
            waiters = [Waiter(self, kind) for kind in order]
            arrivals = [waiter.attempt() for waiter in waiters]
            self.assertNotIn('admitted', arrivals, 'the holders keep both slots')
            for holder in holders:
                holder.complete()
                holder.close()
            return self.rounds(waiters)

    def rounds(self, waiters: list[Waiter]) -> list[str]:
        """Rounds until nobody waits; a round that admits nobody while someone waits is recorded as a stall."""
        history = []
        for _round in range(len(waiters) + 1):
            pending = [waiter for waiter in waiters if not waiter.done]
            if not pending:
                return history
            admitted = [waiter for waiter in pending if waiter.attempt() == 'admitted']
            if not admitted:
                return history + ['STALL ' + json.dumps({waiter.kind: waiter.last for waiter in pending})]
            history.append(''.join(waiter.kind for waiter in admitted))
            for waiter in admitted:
                waiter.complete()
        return history + ['UNFINISHED']

    def test_every_arrival_order_makes_progress(self) -> None:
        """All orders of 3 and 4 of {O, U, B, X}: no round with a free slot and a waiter admits nobody."""
        orders = [order for size in (3, 4) for order in itertools.permutations('OUBX', size)]
        for order in orders:
            with self.subTest(order=''.join(order)):
                history = self.run_order(order)
                self.assertFalse([row for row in history if row.startswith(('STALL', 'UNFINISHED'))], history)
                self.assertEqual(sorted(''.join(history)), sorted(kind for kind in order if kind != 'X'))

    def test_older_then_unfenced_then_fenced_regression(self) -> None:
        """The reported cycle: O queues, then U, then B. U and B run at once; O runs once no fence is held."""
        self.assertEqual(self.run_order(('O', 'U', 'B')), ['UB', 'O'])

    def test_skipping_older_requests_only_when_fenced_deadlocks(self) -> None:
        """Negative control: the previous rule (only a fenced request skips older ones) stalls O -> U -> B."""
        def fenced_only(view: object, fenced: bool) -> list[dict]:
            """The 4deaa04 rule."""
            tickets = fence.request_tickets(view)
            return [ticket for ticket in tickets if fence.is_current(ticket['record'])] if fenced else tickets
        with mock.patch.object(mix, 'competing', side_effect=fenced_only):
            history = self.run_order(('O', 'U', 'B'))
        self.assertTrue(history and history[0].startswith('STALL'), history)
        self.assertIn('queued behind', history[0])


if __name__ == '__main__':
    unittest.main()
