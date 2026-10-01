"""M-050's named stall and the full trail, continued (the P1 fix round M-RPIF: X189 F1 as X190 widens it, X190 s1,
s2 and the section 2 nits; ``_stall_b`` holds X184's cases).

FullTrailTests: at a trail full of valid lines, ``status`` and ``wait`` still answer (an observation that marked
nothing commits the record alone), an observation that marked a dead launch abandoned still writes its line, only a
heartbeat's stall change is committed record-only, and only a full trail, never an unwritable one. On the test's
private authority root; the process table is a TEST table. StallViewTests (in memory, ``Waiter``): a handed-off Short
is not shown stalled, a settlement never names a stall, a copied clip is named, and the CLI keeps the base error
class. No child process is started.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import json
import os
import unittest
from unittest import mock

from _budget_fixture import FakeClock, approval, fake_clock, table
from _production_task_flow_fixture import run_cli
from studio import native_budget_launch, native_budget_store as store
from studio.native_budget_batches import create_batch
from studio.native_budget_clock import start_anchor
from studio.native_budget_policy import BatchSpec, new_batch_record, phase_refusal
from studio.native_budget_report import clip_status
from studio.native_budget_store import BudgetAuthorityError, TrailFull, locked_batch, read_batch
from studio.production import api, cli, queue_clock, queue_stall
from studio.production.queue_authority import PoolEvidence, record_observation
from studio.production.queue_stall import StallDecision
from test_budget_schema_shapes import ATTEMPT
from test_queue_clock_stall import BOUND, Waiter

BATCH = 'batch-auth'
CANCEL = ('capacity-stall', '--batch', BATCH, '--clip', 'A', '--decision', 'cancel', '--reason', 'TEST give A up')


class FullTrailCase(unittest.TestCase):
    """Batch ``batch-auth`` with Short A, a trail that can be filled, and its TEST process table (no tests here)."""

    def setUp(self) -> None:
        """Batch ``batch-auth`` with Short A on the private root; the process table is unreadable unless a test
        sets one."""
        self.clock = self.enterContext(fake_clock(FakeClock()))
        self.table = self.enterContext(mock.patch.object(native_budget_launch, '_process_table',
                                                         side_effect=OSError('TEST')))
        self.root = store.default_root()
        create_batch(self.root, new_batch_record(BatchSpec(BATCH, ('A',), (), 3, approvals={'A': approval('A')}),
                                                 start_anchor()))
        self.trail = self.root / 'batches' / BATCH / 'events.jsonl'
        self.context = {'authority': str(self.root), 'batchId': BATCH, 'clipId': 'A', 'workerId': '/TEST/o.json',
                        'supervisor': {'pid': os.getpid(), 'pgid': os.getpgid(0), 'started': 'TEST start'},
                        'boot': self.clock.boot, 'taskId': None, 'attemptId': None}
        self.pool = PoolEvidence(4, ('a' * 32,), 'capacity')

    def fill(self) -> None:
        """Valid JSON pad lines up to 10 bytes below the point where new work stops (the trail stays readable)."""
        target = store.MAX_EVENT_BYTES - store.TERMINAL_RESERVE_BYTES - 10
        with self.trail.open('ab') as handle:
            while (room := target - handle.tell()) > 0:
                body = min(room, 1_000_000) - len('{"event":"TEST-pad","pad":""}\n')
                handle.write(('{"event":"TEST-pad","pad":"' + 'x' * max(body, 0) + '"}\n').encode())

    def commit(self, change: object) -> None:
        """One TEST change of the record, committed through the store."""
        with locked_batch(self.root, BATCH) as session:
            record = session.read()
            change(record)
            session.commit(record, {'event': 'TEST-change'})

    def status(self) -> dict:
        """The status command's answer (it must succeed)."""
        code, result = run_cli('status', '--batch', BATCH)
        self.assertEqual(code, 0, result)
        return result


class FullTrailTests(FullTrailCase):
    """X189 F1 (status, wait, and an abandoning observation) and X190 s2 (B1, B2) at a full trail."""

    def test_status_answers_at_a_full_trail_before_and_after_the_cancel_and_after_close(self) -> None:
        """Stalled, then cancelled, then closed: status answers each time, and names the stall first."""
        self.commit(lambda record: record['clips']['A']['capacityClock']['stall'].update(
            state='capacity-stalled', sinceElapsed=0.0, occupants=['a' * 32]))
        self.clock.advance(3000.0)
        self.fill()
        self.assertEqual(self.status()['clips']['A']['capacityState'], 'capacity-stalled')
        self.assertEqual(run_cli(*CANCEL)[0], 0)
        self.assertEqual(self.status()['clips']['A']['capacityState'], 'cancelled')
        self.assertEqual(api.close(self.root, BATCH)['status'], 'closed')
        self.assertEqual(self.status()['status'], 'closed')

    def test_wait_answers_at_a_full_trail(self) -> None:
        """``wait`` commits the same observation, record-only at a full trail."""
        self.fill()
        size = self.trail.stat().st_size
        code, result = run_cli('wait', '--batch', BATCH, '--timeout', '0')
        self.assertEqual((code, result['waitResult'], self.trail.stat().st_size), (0, 'timeout', size))

    def test_an_abandoning_observation_still_writes_its_line(self) -> None:
        """A dead launch's abandonment is a launch outcome (G9): at a full trail status still writes its line."""
        running = {**ATTEMPT, 'status': 'running', 'resultStatus': None, 'completedElapsed': None}
        self.commit(lambda record: record['clips']['A'].update(attempts=[running]))
        self.table.side_effect, self.table.return_value = None, table()
        self.fill()
        self.status()
        last = json.loads(self.trail.read_text().splitlines()[-1])
        self.assertEqual((last['event'], last['abandoned']), ('observed', [ATTEMPT['id']]))
        self.assertEqual(read_batch(self.root, BATCH)['clips']['A']['attempts'][0]['status'], 'abandoned')

    def stalled_at_a_full_trail(self) -> None:
        """A's owner waits; its window has held for the bound; at a full trail its heartbeat names the stall."""
        for _ in range(2):
            self.clock.advance(5.0)
            record_observation(self.context, 'waiting', ('heavy-pool', '{}'), self.pool)
        self.commit(lambda record: record['clips']['A']['capacityClock']['occupancy'].update(sinceElapsed=0.0))
        self.fill()
        self.clock.advance(BOUND)
        record_observation(self.context, 'waiting', ('heavy-pool', '{}'), self.pool)
        self.assertEqual(queue_stall.state(read_batch(self.root, BATCH)['clips']['A']), 'capacity-stalled')

    def test_a_transition_that_clears_the_stall_still_fails_at_a_full_trail(self) -> None:
        """s2 (B1): only a heartbeat's stall change is committed record-only; a transition raises TrailFull."""
        self.stalled_at_a_full_trail()
        self.clock.advance(2.0)
        with self.assertRaises(TrailFull):
            record_observation(self.context, 'working', ('heavy-pool', '{}'))
        self.assertEqual(queue_stall.state(read_batch(self.root, BATCH)['clips']['A']), 'capacity-stalled')

    def test_an_unwritable_trail_is_never_committed_record_only(self) -> None:
        """s2 (B2): a failed append that is not TrailFull raises and commits nothing, even for a stall heartbeat."""
        for _ in range(2):
            self.clock.advance(5.0)
            record_observation(self.context, 'waiting', ('heavy-pool', '{}'), self.pool)
        self.commit(lambda record: record['clips']['A']['capacityClock']['occupancy'].update(sinceElapsed=0.0))
        self.clock.advance(BOUND)
        original = store._append

        def unwritable(fd: int, line: bytes, terminal: bool) -> None:
            """A non-settling append fails as an unwritable trail would."""
            if not terminal:
                raise BudgetAuthorityError('Budget event trail is unwritable: TEST')
            original(fd, line, terminal)

        with mock.patch.object(store, '_append', unwritable), \
                self.assertRaisesRegex(BudgetAuthorityError, 'unwritable'):
            record_observation(self.context, 'waiting', ('heavy-pool', '{}'), self.pool)
        self.assertIsNone(queue_stall.state(read_batch(self.root, BATCH)['clips']['A']))


class StallViewTests(unittest.TestCase):
    """X190 s1, section 2 n1, n3 and n6."""

    def test_status_shows_a_handed_off_short_not_stalled(self) -> None:
        """s1: after hand-off, status agrees with close and the actions; the raw row stays under ``stall``."""
        waiter = Waiter(self)
        waiter.wait(BOUND + 10.0)
        record = waiter.session.record
        record['clips']['A']['state'] = 'handed-off'
        status = clip_status(record, 'A', waiter.now[0])
        self.assertEqual((status['capacityState'], status['stall']['state']), (None, 'capacity-stalled'))

    def test_a_settlement_never_names_a_stall_and_the_next_observation_writes_it(self) -> None:
        """n1: another task's working owner is settled after the window crossed the bound: the settlement leaves
        the stall unnamed, and the waiter's next observation names it with its own trail line."""
        waiter = Waiter(self)
        waiter.observe('working', key='/TEST/owner-2.json')
        waiter.clock['workers']['/TEST/owner-2.json']['taskId'] = 'task-2'
        waiter.wait(BOUND - 10.0)
        record = waiter.session.read()
        record['clips']['A']['capacityClock']['observedElapsed'] = waiter.now[0] + 20.0
        self.assertEqual(queue_clock.settle_task_workers(record, 'task-2'), ['/TEST/owner-2.json'])
        self.assertIsNone(record['clips']['A']['capacityClock']['stall']['state'])
        waiter.session.record = record
        waiter.now[0] += 20.0
        waiter.wait(10.0)
        self.assertEqual(waiter.states(), ['capacity-stalled'])

    def test_a_copied_cancelled_clip_is_named(self) -> None:
        """n3: the refusal names the Short even for a copy of its clip."""
        waiter = Waiter(self)
        waiter.wait(BOUND + 10.0)
        record = waiter.session.read()
        queue_stall.decide(record, 'A', StallDecision('cancel', 'TEST'), waiter.now[0])
        refusal = phase_refusal(record, copy.deepcopy(record['clips']['A']), waiter.now[0])
        self.assertRegex(refusal, "^Short A's stalled capacity wait was cancelled")

    def test_the_cli_keeps_the_base_error_class(self) -> None:
        """n6: a TrailFull refusal reads as the BudgetAuthorityError it is, as before M-RP3BF."""
        full = TrailFull('Budget event trail is full: no new work is admitted; close the batch')
        with mock.patch.dict(cli.HANDLERS, {'status': mock.Mock(side_effect=full)}):
            code, result = run_cli('status', '--batch', BATCH)
        self.assertEqual((code, result['error']), (2, f'BudgetAuthorityError: {full}'))


if __name__ == '__main__':
    unittest.main()
