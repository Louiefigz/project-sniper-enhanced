"""Liveness across engines: whenever a slot is free and some waiter is admissible, someone is admitted.

Four kinds of waiter share one private TEST pool (two heavy slots, a TEST schema-1 record):
  O  the unmodified base (4a15560) client, a separate process driven one attempt per line
     (tests/fixtures/base_pool_driver.py 'step');
  U  this engine, unfenced (a TEST non-APFS root, legacy-v1 profile);
  B  this engine, fenced (an APFS root on this Mac);
  X  this engine, exclusive (a Long no profile covers). X queues: it arrives while the holders
     are live, so its first result is 'queued' (a waitable mix, its ticket and fence kept), it
     holds later render requests back so the pool drains for it, and it must be admitted once
     the holders leave. These orders prove how a queued exclusive request is scheduled.
Two holders occupy the slots while the waiters arrive in a given order and make their first
attempt, then leave. Each round every pending waiter attempts once, in arrival order, and
whoever was admitted completes at the round's end, so every round starts with both slots free.
The property: every such round admits someone until nobody admissible waits. The exact
O -> U -> B cycle (U counted O, O waited for B's fence, B counted U) is also a named
regression, with a negative control that restores the old skip rule and finds the deadlock.
Nested work gets its own orders: a live holder (the parent) ends only after its own requests (S, a
render of its project; A, an audio owner of a shared source project) complete, while uncovered Longs
(X, Y), another project's render (V) and a Studio start (T) arrive around them. All 480 orders of 3
and 4 of {X, Y, V, S, A, T} make progress while each uncovered ticket's pass budget lasts (X107 B1:
nested work also passes the tickets a waiting uncovered ticket holds back; XVS is the named case;
X123 d2: A is another project's audio, so it passes only within that budget); the negative control
counts X ahead of audio and finds the deadlock. The base client meets a live Studio start as
quarantined (X107 M1).
"""
from __future__ import annotations

import itertools
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
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
        lane, project, root = case.kinds()[kind]
        self.request = pool.PoolRequest(lane, project, root=root, declares_launch=True)
        case.addCleanup(self.request.withdraw)

    def attempt(self) -> str:
        """One admission attempt; a refusal that waiting cannot clear retires the waiter."""
        if self.kind == 'O':
            self.case.send(self.process, 'try')
            event = self.case.event(self.process)
            self.last = event.get('reason')
            return 'admitted' if event['event'] == 'admitted' else 'queued'
        try:
            request = self.request
            self.lease = work.NativeWorkLease.acquire(request.lane, request.project, request=request)
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
        self.shared = str(plan_project(self, 'short', 45.0))  # a shared source the holder's work uses
        self.long2, self.other, self.view = (str(plan_project(self, *kind)) for kind in (
            ('long', 600.0), ('short', 45.0), ('short', 45.0)))
        self.unfenced, self.holder_root = str(project_dir(self, 'unfenced')), str(project_dir(self, 'holder'))
        real = disk.filesystem
        fake = {path: disk.Filesystem(8, 'filesystem:8', 500 * GIB) for path in (self.unfenced, self.holder_root)}
        self.enterContext(mock.patch.object(disk, 'filesystem', side_effect=lambda path: fake.get(path) or real(path)))

    def kinds(self) -> dict:
        """This engine's waiter kinds: kind -> (class, project, root)."""
        return {'U': ('heavy', self.short, self.unfenced), 'B': ('heavy', self.short, None),
                'X': ('heavy', self.long, None), 'Y': ('heavy', self.long2, self.unfenced),
                'V': ('heavy', self.other, self.unfenced), 'S': ('heavy', self.short, self.unfenced),
                'A': ('audio', self.shared, self.unfenced), 'T': ('studio', self.view, self.unfenced)}

    def holder(self) -> object:
        """A live heavy member of the TEST Short project on the TEST non-APFS holder root."""
        return work.NativeWorkLease.acquire('heavy', self.short, request=pool.PoolRequest(
            'heavy', self.short, root=self.holder_root, declares_launch=True))

    def run_order(self, order: tuple[str, ...]) -> list[str]:
        """Run one arrival order in a fresh namespace; return who was admitted in which round, or the stall."""
        self.root = Path(project_dir(self, 'registry-' + ''.join(order))) / 'registry'
        with mock.patch.object(work, 'state_root', return_value=self.root):
            holders = [self.holder() for _ in range(2)]
            waiters = [Waiter(self, kind) for kind in order]
            self.arrivals = {waiter.kind: waiter.attempt() for waiter in waiters}
            self.assertNotIn('admitted', self.arrivals.values(), 'the holders keep both slots')
            for holder in holders:
                holder.complete()
                holder.close()
            return self.rounds(waiters)

    def rounds(self, waiters: list[Waiter], parent: object = None, nested: str = '') -> list[str]:
        """Rounds until nobody waits; a round that admits nobody (and ends no parent) is recorded as a stall.

        With `parent` (a live holder) the parent ends ('+P') once every waiter of a `nested` kind is done.
        """
        history = []
        for _round in range(2 * len(waiters) + 3):
            pending = [waiter for waiter in waiters if not waiter.done]
            if not pending:
                return history
            admitted = [waiter for waiter in pending if waiter.attempt() == 'admitted']
            for waiter in admitted:
                waiter.complete()
            ended = parent is not None and not parent.completed and all(
                waiter.done for waiter in waiters if waiter.kind in nested)
            if ended:
                parent.complete()
                parent.close()
            if not admitted and not ended:
                return history + ['STALL ' + json.dumps({waiter.kind: waiter.last for waiter in pending})]
            history.append(''.join(waiter.kind for waiter in admitted) + ('+P' if ended else ''))
        return history + ['UNFINISHED']

    def explore(self, order: str, nested: str = 'SA') -> list[str]:
        """A live parent ends only after its own work (`nested` kinds); `order` arrives in the first round."""
        self.root = Path(project_dir(self, 'registry-nested-' + order)) / 'registry'
        with mock.patch.object(work, 'state_root', return_value=self.root):
            parent = self.holder()
            self.addCleanup(parent.close)
            return self.rounds([Waiter(self, kind) for kind in order], parent, nested)

    def test_every_arrival_order_makes_progress(self) -> None:
        """All orders of 3 and 4 of {O, U, B, X}: no round with a free slot and a waiter admits nobody."""
        orders = [order for size in (3, 4) for order in itertools.permutations('OUBX', size)]
        for order in orders:
            with self.subTest(order=''.join(order)):
                history = self.run_order(order)
                self.assertFalse([row for row in history if row.startswith(('STALL', 'UNFINISHED'))], history)
                self.assertEqual(sorted(''.join(history)), sorted(order))
                self.assertEqual(self.arrivals.get('X', 'queued'), 'queued')

    def test_queued_exclusive_does_not_block_nested_audio(self) -> None:
        """The holder's audio owner passes the waiting exclusive ticket; X runs once the holder ends.

        This holds only while X's pass budget lasts: A is audio of another project, so once X has been
        passed PASS_LIMIT times A queues behind X and the holder, which waits for A, never ends (X111's
        accepted residual, X123 d2; any nested owner must therefore use its parent's project).
        """
        self.assertEqual(self.explore('XA'), ['A+P', 'X'])

    def test_queued_exclusive_does_not_block_same_project_request(self) -> None:
        """A render of the live holder's own project passes the waiting exclusive ticket."""
        self.assertEqual(self.explore('XS'), ['S+P', 'X'])

    def test_nested_render_passes_a_render_the_exclusive_ticket_holds_back(self) -> None:
        """B1 (XVS): V queues behind X; the parent's own render S passes both, then X runs, then V."""
        self.assertEqual(self.explore('XVS'), ['S+P', 'X', 'V'])

    def test_every_nested_order_makes_progress(self) -> None:
        """All 480 orders of 3 and 4 of {X, Y, V, S, A, T} around a parent that waits for its S and A.

        Every ticket here is fresh, so this holds only while the 4-pass budget lasts: with the budget
        spent (PASS_LIMIT = 0) the 142 orders in which X or Y is older than A stall, since A (audio of
        another project) then queues behind the uncovered ticket (X111's accepted residual, X123 d2).
        """
        stalls = {}
        for order in (''.join(kinds) for size in (3, 4) for kinds in itertools.permutations('XYVSAT', size)):
            history = self.explore(order)
            if [row for row in history if row.startswith(('STALL', 'UNFINISHED'))] or \
                    sorted(''.join(history).replace('+P', '')) != sorted(order):
                stalls[order] = history
        self.assertEqual(stalls, {})

    def test_base_client_beside_queued_exclusive_is_live(self) -> None:
        """The base client queued before or after X: X runs first (its fence holds O), then O."""
        for order in (('O', 'X'), ('X', 'O')):
            with self.subTest(order=''.join(order)):
                self.assertEqual(self.run_order(order), ['X', 'O'])

    def test_without_the_audio_skip_the_nested_order_deadlocks(self) -> None:
        """Negative control: counting a waiting uncovered ticket ahead of audio stalls the nested order."""
        real = mix.may_pass
        def audio_blind(view: object, request: object, record: dict) -> bool:
            """The rule without the audio pass: the request is treated as a render of its project."""
            return real(view, SimpleNamespace(lane='heavy', project=request.project), record)
        with mock.patch.object(mix, 'may_pass', side_effect=audio_blind):
            history = self.explore('XA')
        self.assertTrue(history and history[0].startswith('STALL'), history)
        self.assertIn('queued behind 1', history[0])

    def test_base_client_is_refused_as_quarantined_beside_a_live_studio_start(self) -> None:
        """M1 (X107): the base client reads a live Studio member as quarantined (fail closed), then runs."""
        for path in Path(self.records).iterdir():  # no record: the base client's exclusive pool
            path.unlink()
        self.root = Path(project_dir(self, 'registry-base-studio')) / 'registry'
        with mock.patch.object(work, 'state_root', return_value=self.root):
            studio = Waiter(self, 'T')
            self.assertEqual(studio.attempt(), 'admitted', studio.last)
            base = self.base('step', 'heavy', self.short, stdin=True)
            events = [self.event(base)]
            self.send(base, 'try')
            events.append(self.event(base))
            studio.complete()
            for line in ('try', 'done'):
                self.send(base, line)
                events.append(self.event(base))
        self.assertEqual([event['event'] for event in events], ['ready', 'refused', 'admitted', 'completed'])
        self.assertEqual(events[1]['error'], 'NativeWorkQuarantined')
        self.assertIn(f'quarantined: {studio.lease.nonce}', events[1]['reason'])

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
