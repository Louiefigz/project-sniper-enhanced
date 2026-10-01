"""Short capacity clock v2, continued (the P1 fix round M-RPIF opens this module: X189 as X190 widens it, X190, X192).

RunScopedDeadlineTests (X190 m1, m3): a run-scoped task's deadline never passes the run's delivery deadline, and
follows the largest credit of any Short. AuditChainTests (m2, n2, s2): the audit checks every capacity row against its
predecessor, names a malformed row, and reads committed events only. FailedCheckpointTests (n6): a checkpoint whose
record replace failed is written once. GrantDeltaTests (M-053): a grant gains only the credit since it was bound.
SecondOwnerTests (n1): pending credit settled after another owner's event is no false alarm. SettlementAuditTests
(X189 F2, X192): a watchdog or reconcile settlement writes the removed owners and the settled credit on its own
terminal event, which closes the audit's window; a removal no row explains is named. On private authority roots and
fake clocks (``AuditCase``, ``CreditCase``, ``_production_task_flow_fixture``) or in memory
(``test_queue_clock_v2_b.Run``, ``test_queue_clock_stall.Waiter``); no child process is started.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from _budget_fixture import CHILD, DISPATCHER, receipt, task_spec
from _queue_credit_fixture import CreditCase
from _production_task_flow_fixture import BATCH as FLOW_BATCH, Batch, run_cli
from studio import native_budget_binding, native_budget_store
from studio.native_budget_store import BudgetAuthorityError, locked_batch, read_batch
from studio.production import api, callbacks, process_settle, queue_clock
from studio.production.director_activity import DirectorActivity
from studio.production.formats import clip_deadlines
from studio.production.queue_audit import _audit_clip, _waiting_after, audit_record, capacity_audit
from studio.production.queue_authority import PoolEvidence, record_observation
from studio.production.tasks import enqueue
from test_queue_clock_stall import BOUND, Waiter
from test_queue_clock_v2_b import Run, turn
from test_queue_clock_v2_c import BATCH, POOL, AuditCase

SURVIVOR = {'type': 'process', 'pid': 7003, 'pgid': 7002, 'started': 'Sun Sep 27 10:00:06 2026'}


def row(worker: str, state: str, **extra: object) -> dict:
    """One capacity event of Short A."""
    return {'event': 'capacity-observed', 'clipId': 'A', 'worker': worker, 'state': state, 'elapsed': 0.0,
            'excludedSeconds': 0.0, **extra}


class RunScopedDeadlineTests(unittest.TestCase):
    """X190 m1: never past the run's delivery deadline; m3: the largest credit, of every writable Short."""

    def shared(self, run: Run, deadline: float) -> dict:
        """A shared review under the director, due at ``deadline``, waiting for both Shorts' media."""
        enqueue(run.record, (task_spec('shared', 'review', prerequisites=('media-a', 'media-b'), parent='director',
                                       deadline_elapsed=deadline),), run.elapsed)
        return run.record['production']['tasks']['shared']

    def test_a_run_scoped_deadline_stops_at_the_runs_and_a_later_completion_is_late(self) -> None:
        """A earns 1000 s, then a shared review is due at the run's delivery (3400); B earns 800 s more. The
        shared deadline stays 3400, not 4200, and a completion at 3700 records as late."""
        run = Run()
        run.declare(False)
        run.wait('A', 1000.0)
        run_delivery = clip_deadlines(run.record, None)['deliverySeconds']
        task = self.shared(run, run_delivery)
        run.wait('B', 800.0)
        self.assertEqual(queue_clock.task_deadline(run.record, task), run_delivery)
        for media in ('media-a', 'media-b'):
            run.record['production']['tasks'][media].update(state='completed', terminalElapsed=run.elapsed)
        from studio.production.dependencies import refresh
        refresh(run.record, run.elapsed)
        run.elapsed = run_delivery - 200.0
        ref = run.claim('shared', turn('shared'))
        callbacks.complete(run.record, ref, callbacks.TaskResult((receipt('shared'),)), run_delivery + 300.0)
        self.assertEqual((task['state'], task['failure']['category']), ('failed', 'deadline-expired'))

    def test_the_largest_of_two_earning_shorts_not_their_sum(self) -> None:
        """m3 (RS1, RS2): A earns 100 s and B 300 s after the shared task exists: it gains 300."""
        run = Run()
        run.declare(False)
        task = self.shared(run, 2300.0)
        run.wait('A', 100.0)
        run.wait('B', 300.0)
        self.assertEqual(queue_clock.task_deadline(run.record, task), 2600.0)

    def test_a_handed_off_shorts_earlier_credit_still_counts(self) -> None:
        """m3 (RS4): the credit A earned before its hand-off still moved the shared task."""
        run = Run()
        run.declare(False)
        task = self.shared(run, 2300.0)
        run.wait('A', 300.0)
        run.record['clips']['A']['state'] = 'handed-off'
        run.wait('B', 100.0)
        self.assertEqual(queue_clock.task_deadline(run.record, task), 2600.0)

    def test_waiting_replays_every_owner(self) -> None:
        """m3 (A1, A2, A11): a waiter that starts working closes the window; another owner's event keeps it open;
        a recovered or orphaned waiter closes it."""
        cases = (([row('w1', 'waiting'), row('w1', 'working')], False),
                 ([row('w1', 'waiting'), row('w2', 'working')], True),
                 ([row('w1', 'waiting'), row('w2', 'working', recoveredWorkers=['w1'])], False),
                 ([row('w1', 'waiting'), row('w2', 'working', orphanedWorkers=['w1'])], False))
        for trail, expected in cases:
            with self.subTest(trail=trail):
                self.assertIs(_waiting_after(trail), expected)


class AuditChainTests(AuditCase):
    """X190 m2: the engine's next event carrying a hand-edited total does not launder it; n1, n2, s2."""

    def edit(self, seconds: float) -> None:
        """Raise the committed credit by ``seconds`` through the store (a hand edit)."""
        with locked_batch(self.root, BATCH) as session:
            edited = session.read()
            native_budget_binding.advance_clock(edited)
            edited['clips']['A']['capacityClock']['excludedSeconds'] += seconds
            session.commit(edited, {'event': 'TEST-hand-edit'})

    def audit(self) -> dict:
        """Short A's audit on the committed trail."""
        return capacity_audit(self.root, BATCH, read_batch(self.root, BATCH))['A']

    def test_a_checkpoint_after_a_hand_edit_does_not_launder_it(self) -> None:
        """+600 s while the owner waits: the next heartbeat writes a checkpoint carrying the edited total, and the
        audit still says exceeds-trail."""
        self.observe('working')
        self.clock.advance(1000.0)
        self.wait(20, POOL)
        self.observe('waiting', POOL)
        self.edit(600.0)
        self.clock.advance(2.0)
        self.observe('waiting', POOL)
        self.assertEqual(self.audit()['status'], 'exceeds-trail')

    def test_a_finished_event_after_a_hand_edit_does_not_launder_it(self) -> None:
        """+1100 s after 20 min of work: the owner's finished event carries 1100, and the audit still says so."""
        self.observe('working')
        self.clock.advance(1200.0)
        self.edit(1100.0)
        self.observe('finished')
        self.assertEqual((self.audit()['status'], self.audit()['recordedSeconds']), ('exceeds-trail', 1100.0))

    def test_a_malformed_row_is_named_not_raised(self) -> None:
        """n2: a capacity line whose owner is a list is ``malformed-trail`` in status, never a traceback."""
        self.wait(10, POOL)
        line = row(['x'], 'waiting')
        with open(self.root / 'batches' / BATCH / 'events.jsonl', 'a', encoding='utf-8') as trail:
            trail.write(json.dumps(line) + '\n')
        code, status = run_cli('status', '--batch', BATCH)
        self.assertEqual((code, status['capacityAudit']['A']['status']), (0, 'malformed-trail'))

    def test_a_failed_capacity_commit_is_not_the_audits_last_event(self) -> None:
        """s2 (B4): an event followed by its own commit-failed never happened, for status's audit too."""
        self.wait(10, POOL)
        lines = [{**row('/TEST/owner-a.json', 'working'), 'elapsed': 1.0, 'excludedSeconds': 9999.0},
                 {'event': 'commit-failed', 'failedEvent': 'capacity-observed', 'error': 'TEST'}]
        with open(self.root / 'batches' / BATCH / 'events.jsonl', 'a', encoding='utf-8') as trail:
            trail.write(''.join(json.dumps(line) + '\n' for line in lines))
        code, status = run_cli('status', '--batch', BATCH)
        self.assertEqual((code, status['capacityAudit']['A']['status']), (0, 'consistent'))


class FailedCheckpointTests(AuditCase):
    """X190 n6: a checkpoint whose record replace failed is not appended again at every heartbeat."""

    def test_a_failed_checkpoint_is_written_once(self) -> None:
        """A hand edit makes a checkpoint due; while the record cannot be replaced, two heartbeats fail, and the
        trail holds that checkpoint and its commit-failed once (read from the trail since X246 m2)."""
        self.observe('working')
        self.clock.advance(1000.0)
        self.observe('waiting', POOL)
        AuditChainTests.edit(self, 600.0)
        with mock.patch.object(native_budget_store, 'write_pending_replace', side_effect=OSError('TEST replace')):
            for _ in range(2):
                self.clock.advance(2.0)
                self.assertRaises(BudgetAuthorityError, self.observe, 'waiting', POOL)
        lines = (self.root / 'batches' / BATCH / 'events.jsonl').read_text().splitlines()
        names = [json.loads(line)['event'] for line in lines if line.strip()]
        self.assertEqual((names.count('capacity-checkpoint'), names.count('commit-failed')), (1, 1))


class GrantDeltaTests(CreditCase):
    """M-053: the owner's lock-free credit read gains only the credit settled since its grant (``atGrant``)."""

    def test_a_grant_gains_only_the_credit_since_it_was_bound(self) -> None:
        """A grant bound when A held 40 s reads 60 once A holds 100 s, never the 100 A holds in all."""
        self.grant = self.bind(self.credit_record(40.0), 'A')
        self.put(self.credit_record(100.0))
        self.assertEqual((self.grant['capacityCredit']['atGrant'], self.delta()), (40.0, 60.0))


class SecondOwnerTests(unittest.TestCase):
    """X190 n1: pending credit accrued before a second owner's event settles after it, within the poll bound."""

    def test_a_second_owner_joining_a_wait_is_no_false_alarm(self) -> None:
        """Owner 1 waits 0-20 s, owner 2 registers working at 44.9 s, owner 1 beats at 45.0 s: the 24.9 s pending
        settles after owner 2's event, within the poll bound (M-055), so the audit says consistent."""
        waiter = Waiter(self)
        for step in range(11):
            waiter.now[0] = 2.0 * step
            waiter.observe('waiting', {'ticket': 1, 'occupants': ['a' * 32], 'waitClass': 'capacity'},
                           '/TEST/owner-1.json')
        waiter.now[0] = 44.9
        waiter.observe('working', key='/TEST/owner-2.json')
        waiter.now[0] = 45.0
        waiter.observe('waiting', {'ticket': 1, 'occupants': ['a' * 32], 'waitClass': 'capacity'},
                       '/TEST/owner-1.json')
        clip = waiter.session.record['clips']['A']
        self.assertEqual(_audit_clip(clip, waiter.session.trail)['status'], 'consistent')


class SettlementAuditTests(unittest.TestCase):
    """X189 F2 (watchdog and reconcile) and X192: a settlement's credit and removed owners reach the trail."""

    def batch_waiting(self) -> tuple:
        """A batch whose media task's owner waited 60 s, verified; returns (batch, the task's claim)."""
        batch = Batch(self)
        api.declare_director_activity(batch.root, FLOW_BATCH, batch.director, DirectorActivity(None, False))
        batch.enqueue(('media-a', 'media', ()))
        claim = batch.claim('media-a', CHILD, DISPATCHER)
        context = {'authority': str(batch.root), 'batchId': FLOW_BATCH, 'clipId': 'A', 'workerId': '/TEST/owner.json',
                   'taskId': 'media-a', 'attemptId': None, 'boot': batch.clock.boot,
                   'supervisor': {'pid': os.getpid(), 'pgid': os.getpgid(0), 'started': 'TEST start'}}
        pool = PoolEvidence(1, ('a' * 32,), 'capacity')
        record_observation(context, 'waiting', ('heavy-pool', '{}'), pool)
        for _ in range(30):
            batch.clock.advance(2)
            record_observation(context, 'waiting', ('heavy-pool', '{}'), pool)
        return batch, SimpleNamespace(batch_id=FLOW_BATCH, task_id=claim.task_id, epoch=claim.epoch, token=claim.token)

    def edited_status(self, batch: Batch) -> str:
        """After 1200 s, raise A's credit by 1100 through the store; the status command's audit verdict."""
        batch.clock.advance(1200)
        with locked_batch(batch.root, FLOW_BATCH) as session:
            record = session.read()
            native_budget_binding.advance_clock(record)
            self.assertEqual(record['clips']['A']['capacityClock']['excludedSeconds'], 60.0)
            record['clips']['A']['capacityClock']['excludedSeconds'] += 1100
            session.commit(record, {'event': 'TEST-hand-edit'})
        code, result = run_cli('status', '--batch', FLOW_BATCH)
        self.assertEqual(code, 0, result)
        return result['capacityAudit']['A']['status']

    def test_a_watchdog_settlement_closes_the_window(self) -> None:
        """The reviewer's first probe: process_settle.settle proves cleanup; the edit is exceeds-trail."""
        batch, claim = self.batch_waiting()
        self.assertTrue(process_settle.settle(claim, process_settle.Ending(CHILD['pid'], None, (), None))['settled'])
        self.assertEqual(batch.record()['clips']['A']['capacityClock']['workers'], {})
        self.assertEqual(self.edited_status(batch), 'exceeds-trail')

    def test_a_reconcile_settlement_closes_the_window(self) -> None:
        """A survivor keeps the task unresolved; reconcile later sees it gone and settles the owners; the edit is
        exceeds-trail."""
        batch, claim = self.batch_waiting()
        process_settle.settle(claim, process_settle.Ending(CHILD['pid'], None, (SURVIVOR,), None))
        self.assertIn('/TEST/owner.json', batch.record()['clips']['A']['capacityClock']['workers'])
        api.reconcile(batch.root, FLOW_BATCH)
        self.assertEqual(batch.record()['clips']['A']['capacityClock']['workers'], {})
        self.assertEqual(self.edited_status(batch), 'exceeds-trail')

    def test_a_settlement_entry_on_the_trail_closes_the_window_in_memory(self) -> None:
        """The reviewer's second probe with the settling event the engine now writes: exceeds-trail."""
        waiter = Waiter(self)
        waiter.wait(BOUND + 10)
        record = copy.deepcopy(waiter.session.record)
        clock = record['clips']['A']['capacityClock']
        clock['workers']['/TEST/owner-a.json']['taskId'] = 'media-a'
        entries = queue_clock.settle_task_capacity(record, 'media-a')
        trail = [*waiter.session.trail, {'event': 'task-completed', 'taskId': 'media-a', queue_clock.SETTLED: entries}]
        queue_clock.checkpoint(record, waiter.now[0] + 1200)
        clock['excludedSeconds'] += 1100
        self.assertEqual(audit_record(record, trail)['A']['status'], 'exceeds-trail')

    def test_a_removal_no_row_explains_is_named(self) -> None:
        """X192: the reviewer's second probe as written (a settlement with no settling event): the record lost an
        owner the trail leaves waiting, which is ``unexplained-removal``, never consistent."""
        waiter = Waiter(self)
        waiter.wait(BOUND + 10)
        record = copy.deepcopy(waiter.session.record)
        clock = record['clips']['A']['capacityClock']
        clock['workers']['/TEST/owner-a.json']['taskId'] = 'media-a'
        queue_clock.settle_task_workers(record, 'media-a')
        queue_clock.checkpoint(record, waiter.now[0] + 1200)
        clock['excludedSeconds'] += 1100
        self.assertEqual(audit_record(record, waiter.session.trail)['A']['status'], 'unexplained-removal')


if __name__ == '__main__':
    unittest.main()
