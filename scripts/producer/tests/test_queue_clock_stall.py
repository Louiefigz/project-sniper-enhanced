"""M-050: the named ``capacity-stalled`` state (P1 Step B7 as X19 and G1 correct it; X95 O6, X98 M1, X102; X180 m7).

A verified capacity wait keeps earning credit past ``queue_stall.stall_seconds()``; only its state is named. The
stall clears when the occupants change or the verified wait ends; a truncated stall earns nothing; the operator's
one decision is ``cancel``, and a stalled Short that is not cancelled keeps its batch open. Most cases run in memory
through ``queue_authority._observe_locked`` (the committing path, with an in-memory session whose trail keeps every
event but heartbeats), polling every 5 s as the owner loop does; the cancel command runs on the test's private
authority root, and the stuck-holder case on a private pool namespace. No child process is started.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import unittest
from unittest import mock

import native_work_lease as work
import native_work_pool as pool
import native_work_pool_disk as disk
from native_render_resources import GIB
from native_work_pool_state import NativeWorkQueued
from _budget_fixture import FINGERPRINT, FakeClock, approval, fake_clock, task_spec
from _native_pool_fixture import isolate_pool, plan_project, qualify_fixture_host
from _production_task_flow_fixture import run_cli
from studio import native_budget_binding, native_budget_store
from studio.native_budget_batches import create_batch
from studio.native_budget_clock import start_anchor
from studio.native_budget_policy import BatchSpec, close_refusal, new_batch_record, phase_refusal
from studio.native_budget_report import clip_status
from studio.native_budget_schema import DEADLINES
from studio.native_budget_store import locked_batch, read_batch
from studio.native_queue_accounting import pool_evidence
from studio.production import api, queue_authority, queue_clock
from studio.production import queue_clock_schema as schema
from studio.production.claims import Enrollment
from studio.production.formats import LONG_POLICY, long_demand
from studio.production.queue_stall import stall_seconds
from test_queue_clock_v2 import OWNER, V1_CLOCK, short_record
from test_queue_clock_v2_c import MemorySession

BOUND = stall_seconds()
A = {'ticket': 7, 'occupants': ['a' * 32], 'waitClass': 'capacity'}
B = {'ticket': 7, 'occupants': ['b' * 32], 'waitClass': 'capacity'}
WAITING = {'state': 'waiting', 'resource': 'heavy-pool', 'evidence': '{}'}
INCONSISTENT = 'Short capacity clock stall: its state, time, occupants and decision disagree'
NAMES = [f'{index:02d}' for index in range(64)]   # 64 distinct names, already sorted


class Waiter:
    """Short A's render owner polling a full pool every 5 s through the committing path, in memory."""

    def __init__(self, test: unittest.TestCase, clock: dict | None = None) -> None:
        """A fresh record (Short A on a v2 clock unless ``clock`` is given) and its in-memory session."""
        self.session, self.now = MemorySession(short_record(clock)), [0.0]
        test.enterContext(mock.patch.object(native_budget_binding, 'advance_clock', self._advance))

    def _advance(self, record: dict) -> float:
        """The batch clock at ``now``, checkpointed as ``advance_clock`` does."""
        queue_clock.checkpoint(record, self.now[0])
        return self.now[0]

    def observe(self, state: str, evidence: dict | None = None, key: str = '/TEST/owner-a.json') -> None:
        """One committed observation of owner ``key`` at the current time."""
        context = {'clipId': 'A', 'workerId': key, 'taskId': None, 'attemptId': None, 'supervisor': OWNER,
                   'boot': 'TEST-boot'}
        observation = {**WAITING, 'state': state, 'ticket': None, 'occupants': [], 'waitClass': None,
                       **(evidence or {})}
        queue_authority._observe_locked(self.session, context, observation, queue_authority.Recovery({}, {}))

    def wait(self, seconds: float, evidence: dict = A) -> None:
        """Poll every 5 s for ``seconds`` with this pool evidence."""
        end = self.now[0] + seconds
        while self.now[0] < end:
            self.now[0] += 5.0
            self.observe('waiting', evidence)

    @property
    def clock(self) -> dict:
        """Short A's committed clock."""
        return self.session.record['clips']['A']['capacityClock']

    def states(self) -> list:
        """The capacity states the trail recorded, in order."""
        return [event['capacityState'] for event in self.session.trail if 'capacityState' in event]


class StallTests(unittest.TestCase):
    """The bound, the named state, and what clears it; credit never stops because time passed (X19)."""

    def stalled(self, evidence: dict = A) -> Waiter:
        """A waiter whose occupants have not changed for the bound (and one more poll)."""
        waiter = Waiter(self)
        waiter.wait(BOUND + 10.0, evidence)
        self.assertEqual(waiter.clock['stall']['state'], 'capacity-stalled')
        return waiter

    def test_stall_bound_is_derived_from_policy(self) -> None:
        """The longest admissible render (a Short's window, or a 900 s Long's final) plus cleanup."""
        final = long_demand(LONG_POLICY['maxOutputSeconds'])['finalSeconds']
        self.assertEqual(BOUND, max(DEADLINES['deliverySeconds'], final) + DEADLINES['cleanupReserveSeconds'])
        self.assertGreater(BOUND, DEADLINES['deliverySeconds'] + DEADLINES['cleanupReserveSeconds'])

    def test_credit_continues_past_the_bound_and_the_state_is_named(self) -> None:
        """Fixed occupants: credit keeps growing past the bound; the state is named in the record, status and trail,
        and the first next action names the holders and their watchdog."""
        waiter = Waiter(self)
        waiter.wait(BOUND + 300.0)
        clock = waiter.clock
        self.assertEqual(clock['excludedSeconds'], waiter.now[0] - 5.0)   # every interval after the first poll
        self.assertEqual((clock['stall']['occupants'], clock['stall']['truncated']), (['a' * 32], False))
        self.assertGreaterEqual(clock['stall']['sinceElapsed'] - clock['occupancy']['sinceElapsed'], BOUND)
        status = queue_clock.status(waiter.session.record['clips']['A'], waiter.now[0])
        self.assertEqual((status['capacityState'], status['stallBoundSeconds']), ('capacity-stalled', BOUND))
        self.assertEqual(waiter.states(), ['capacity-stalled'])
        first = clip_status(waiter.session.record, 'A', waiter.now[0])['actions'][0]
        self.assertRegex(first, rf'^Capacity stalled since \d+s behind {"a" * 32}: a holder past its grant .*watchdog')

    def test_changing_occupants_clear_the_stall(self) -> None:
        """A new occupant set starts a new window and clears the stall, occupants and truncation together."""
        waiter = self.stalled()
        credit = waiter.clock['excludedSeconds']
        waiter.wait(5.0, B)
        stall = waiter.clock['stall']
        self.assertEqual((stall['state'], stall['sinceElapsed'], stall['occupants'], stall['truncated']),
                         (None, None, [], False))
        self.assertEqual(waiter.clock['occupancy']['sinceElapsed'], waiter.now[0])
        self.assertEqual(waiter.clock['excludedSeconds'], credit + 5.0)
        self.assertEqual(waiter.states(), ['capacity-stalled', None])

    def test_the_end_of_the_verified_wait_clears_the_stall(self) -> None:
        """Admitted (working), the owner no longer waits: the stall clears and the window closes."""
        waiter = self.stalled()
        waiter.now[0] += 5.0
        waiter.observe('working')
        self.assertEqual((waiter.clock['stall']['state'], waiter.clock['occupancy']['fingerprint']), (None, None))

    def test_v1_clock_never_stalls(self) -> None:
        """A v1 clock is read-only: past the bound it is unchanged."""
        waiter = Waiter(self, V1_CLOCK)
        waiter.wait(BOUND + 10.0)
        self.assertEqual(waiter.clock, V1_CLOCK)

    def test_truncation_and_no_credit_at_the_worst_case_union(self) -> None:
        """64 waiting owners with 8 occupants each (512 names): the stall keeps the first 64, sorted, truncated, and
        earns nothing; a smaller set clears occupants and truncation together and credit resumes."""
        waiter = Waiter(self)
        keys = [f'/TEST/owner-{index:02d}.json' for index in range(schema.MAX_WORKERS)]
        rows = {key: {**A, 'occupants': [f'{index:02d}{slot}' for slot in range(8)]} for index, key in enumerate(keys)}
        waiter.now[0] = BOUND + 5.0
        for key in keys:
            waiter.observe('waiting', rows[key], key)
        waiter.clock['occupancy']['sinceElapsed'] = 5.0              # this union has held for the bound
        self.poll(waiter, keys, rows)
        stall = waiter.clock['stall']
        union = sorted(name for row in rows.values() for name in row['occupants'])
        self.assertEqual((stall['state'], stall['occupants'], stall['truncated']), ('capacity-stalled', union[:64], True))
        before = (waiter.clock['excludedSeconds'], waiter.clock['uncertainSeconds'])
        self.poll(waiter, keys, rows)
        self.assertEqual((waiter.clock['excludedSeconds'], waiter.clock['uncertainSeconds']),
                         (before[0], before[1] + 5.0))                 # counted, never credited (fail closed)
        self.poll(waiter, keys, {key: A for key in keys})
        self.assertEqual((waiter.clock['stall']['occupants'], waiter.clock['stall']['truncated']), ([], False))
        self.poll(waiter, keys, {key: A for key in keys})
        self.assertEqual(waiter.clock['excludedSeconds'], before[0] + 5.0)

    @staticmethod
    def poll(waiter: Waiter, keys: list[str], rows: dict) -> None:
        """One 5 s round in which every owner reports."""
        waiter.now[0] += 5.0
        for key in keys:
            waiter.observe('waiting', rows[key], key)


class DecisionTests(unittest.TestCase):
    """The operator's one decision (cancel), and closing while a Short is stalled."""

    def test_close_refused_while_a_stalled_short_is_uncancelled(self) -> None:
        """Even past its deadline, a stalled Short holds its batch open by name; once not stalled, it does not."""
        record = short_record()
        clock = record['clips']['A']['capacityClock']
        clock.update(excludedSeconds=100.0, observedElapsed=5000.0)
        clock['stall'].update(state='capacity-stalled', sinceElapsed=4000.0, occupants=['a' * 32])
        self.assertEqual(close_refusal(record, 5000.0),
                         'Short A is capacity-stalled with 4900s counted and its authorization intact: cancel it with '
                         'capacity-stall --clip A --decision cancel --reason …, or keep the batch open (it resumes '
                         'when capacity frees)')
        clock['stall'].update(state=None, sinceElapsed=None, occupants=[])
        self.assertIsNone(close_refusal(record, 5000.0))

    def test_cancel_is_a_recorded_terminal_outcome_and_the_batch_closes(self) -> None:
        """On the private root: the command records the cancel, freezes A's work, closes A out for new work and
        lets the batch close before A's deadline; a second decision and a decision on a Short that is not stalled
        are refused by name."""
        self.enterContext(fake_clock(FakeClock()))
        root = native_budget_store.default_root()
        create_batch(root, new_batch_record(BatchSpec('batch-auth', ('A',), (), 3, approvals={'A': approval('A')}),
                                            start_anchor()))
        api.enroll_director(root, 'batch-auth', Enrollment('director', {'type': 'host', 'host': 'codex',
                                                                        'thread': 'TEST-t', 'turn': 'TEST-u'},
                                                           'v1', FINGERPRINT))
        api.enqueue_tasks(root, 'batch-auth', (task_spec('author-a', 'author', parent='director'),))
        cancel = ('capacity-stall', '--batch', 'batch-auth', '--clip', 'A', '--decision', 'cancel', '--reason',
                  'TEST operator gives A up')
        code, out = run_cli(*cancel)
        self.assertEqual((code, out['reason']), (3, 'Short A is not capacity-stalled'))
        with locked_batch(root, 'batch-auth') as session:
            record = session.read()
            record['clips']['A']['capacityClock']['stall'].update(state='capacity-stalled', sinceElapsed=1.0,
                                                                  occupants=['a' * 32])
            session.commit(record, {'event': 'TEST-stalled'})
        self.assertEqual(run_cli(*cancel)[0], 0)
        record = read_batch(root, 'batch-auth')
        stall = record['clips']['A']['capacityClock']['stall']
        self.assertEqual((stall['state'], stall['decisions'][0]['kind'], stall['decisions'][0]['reason']),
                         ('cancelled', 'cancel', 'TEST operator gives A up'))
        self.assertEqual(record['production']['tasks']['author-a']['state'], 'cancelled')
        self.assertRegex(phase_refusal(record, record['clips']['A'], 10.0), 'stalled capacity wait was cancelled')
        self.assertEqual(run_cli(*cancel)[0], 3)
        self.assertEqual(api.close(root, 'batch-auth')['status'], 'closed')

    def test_contradictory_stall_rows_are_refused(self) -> None:
        """X180 m7: cancelled iff one cancel row; a time iff a state; no occupants without a state; occupants sorted
        and distinct. 64 distinct names are accepted, truncated or not (the cases moved from test_queue_clock_v2)."""
        cancel = {'kind': 'cancel', 'reason': 'TEST', 'elapsed': 1.0}
        named = {'state': 'capacity-stalled', 'sinceElapsed': 1.0, 'occupants': ['a'], 'truncated': False,
                 'decisions': []}
        cases = (('cancelled without its cancel', {**named, 'state': 'cancelled'}),
                 ('a cancel row on a live stall', {**named, 'decisions': [cancel]}),
                 ('a cancel row with no stall', {**named, 'state': None, 'sinceElapsed': None, 'occupants': [],
                                                 'decisions': [cancel]}),
                 ('a stall without its time', {**named, 'sinceElapsed': None}),
                 ('a time without a stall', {**named, 'state': None, 'occupants': []}),
                 ('occupants without a stall', {**named, 'state': None, 'sinceElapsed': None}),
                 ('unsorted occupants', {**named, 'occupants': ['b', 'a']}),
                 ('a repeated occupant', {**named, 'occupants': ['a', 'a']}))
        clip = short_record()['clips']['A']
        for name, stall in cases:
            with self.subTest(name):
                clock = {**copy.deepcopy(clip['capacityClock']), 'stall': stall}
                self.assertEqual(schema.problem({**clip, 'capacityClock': clock}), INCONSISTENT)
        for truncated in (False, True):
            clock = {**copy.deepcopy(clip['capacityClock']), 'stall': {**named, 'occupants': NAMES,
                                                                       'truncated': truncated}}
            self.assertIsNone(schema.problem({**clip, 'capacityClock': clock}))


class StuckHolderTests(unittest.TestCase):
    """G1: recovery targets the cause; the waiter's earned credit is kept whatever happens to the holders."""

    def test_stuck_holder_is_stopped_by_the_watchdog_and_waiter_credit_is_kept(self) -> None:
        """A real refusal behind three live holders stalls A. One holder stopped with unverified cleanup keeps its
        slot quarantined: the wait is no longer verified, the stall clears and nothing earned is lost. Another
        stopped with verified cleanup frees its slot, and A's render is admitted. (The watchdog's two outcomes are
        the pool member's own ``close`` and ``complete``; no watchdog process runs here.)"""
        isolate_pool(self)
        qualify_fixture_host(self, {'heavy': 3, 'audio': 1})
        self.enterContext(mock.patch.object(disk, 'filesystem', return_value=disk.Filesystem(8, 'filesystem:8',
                                                                                             500 * GIB)))
        holders = [self.member(plan_project(self, 'short', 45.0)) for _ in range(3)]
        project = plan_project(self, 'short', 45.0)
        request = self.pool_request(project)
        waiter = Waiter(self)
        waiter.wait(BOUND + 10.0, self.evidence(request))
        self.assertEqual(waiter.clock['stall']['occupants'], sorted(lease.nonce for lease in holders))
        earned = waiter.clock['excludedSeconds'] + 5.0      # the last verified poll interval settles next
        holders[0].close()                                  # stopped, cleanup unverified: quarantined
        waiter.wait(5.0, self.evidence(request))
        self.assertEqual((waiter.clock['stall']['state'], waiter.clock['excludedSeconds']), (None, earned))
        holders[1].complete()                               # stopped, cleanup verified: its slot is free
        lease = work.NativeWorkLease.acquire('heavy', str(project), request=request)
        self.addCleanup(lease.close)
        waiter.now[0] += 5.0
        waiter.observe('working')
        self.assertEqual((waiter.clock['stall']['state'], waiter.clock['excludedSeconds']), (None, earned))

    def member(self, project: object) -> object:
        """A live heavy member for ``project``, closed at cleanup."""
        lease = work.NativeWorkLease.acquire('heavy', str(project), request=self.pool_request(project))
        self.addCleanup(lease.close)
        return lease

    def pool_request(self, project: object) -> pool.PoolRequest:
        """One owner's heavy request, withdrawn at cleanup."""
        request = pool.PoolRequest('heavy', str(project), root=str(project), declares_launch=True,
                                   receipt=str(project / 'pipeline.render.json'))
        self.addCleanup(request.withdraw)
        return request

    def evidence(self, request: pool.PoolRequest) -> dict:
        """The pool evidence of this request's real refusal now."""
        with self.assertRaises(NativeWorkQueued) as caught:
            work.NativeWorkLease.acquire('heavy', request.project, request=request)
        found = pool_evidence(caught.exception)
        return {'ticket': found.ticket, 'occupants': list(found.occupants), 'waitClass': found.wait_class}


if __name__ == '__main__':
    unittest.main()
