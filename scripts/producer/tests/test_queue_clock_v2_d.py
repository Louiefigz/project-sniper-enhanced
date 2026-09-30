"""Short capacity clock v2, continued (M-048 opens this module: ``_c`` would pass 300 lines with these, MA3).

OrphanTests (P1 Step B5; C7, P3, P6): a working owner whose supervisor is gone is orphaned, not left counting as
work; a dead prelaunch waiter is recovered even while its process group lives on, and an owner whose supervisor runs
is neither orphaned nor recovered (X183 m8: O3, O6); settling one task keeps another owner's pending interval.
Batches are ``test_queue_clock_v2_c.AuditCase`` (a private authority root, a fake clock, Short A, this process as
the observing owner) with a TEST process table; no child process is started.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest
from unittest import mock

from _budget_fixture import table
from studio import native_budget_launch
from studio.native_budget_binding import advance_clock
from studio.native_budget_store import locked_batch
from studio.production import queue_clock
from studio.production.queue_clock_schema import MAX_ORPHAN_ROWS, MAX_WORKERS, new_clock
from test_queue_clock_v2_c import BATCH, POOL, AuditCase
from test_queue_clock_v2 import V1_CLOCK, short_record

V1_KEYS = ('state', 'resource', 'evidence', 'seenElapsed', 'taskId', 'attemptId')

DEAD = {'pid': 424242, 'pgid': 424242, 'started': 'Sun Sep 27 09:00:00 2026'}
LIVE = {'pid': 525252, 'pgid': 525252, 'started': 'Sun Sep 27 09:30:00 2026'}   # a supervisor the TEST table runs
ROW = {'state': 'working', 'resource': 'native-owner', 'evidence': 'preparation', 'seenElapsed': 0.0,
       'taskId': None, 'attemptId': None, 'ticket': None, 'occupants': [], 'waitClass': None}
POOL_ROW = {'ticket': POOL.ticket, 'occupants': list(POOL.occupants), 'waitClass': POOL.wait_class}


class OrphanTests(AuditCase):
    """C7: a dead working owner no longer holds a Short's credit off or fills the owner cap; P3: a dead waiter."""

    def plant(self, count: int = 1, **changes: object) -> None:
        """Commit ``count`` owner rows of a supervisor that is gone (this boot unless ``changes`` say otherwise), in
        a transaction that first checkpoints the clock, as every authority transition does."""
        with locked_batch(self.root, BATCH) as session:
            record = session.read()
            advance_clock(record)
            workers = record['clips']['A']['capacityClock']['workers']
            for index in range(count):
                workers[f'/TEST/dead-{index:02d}.json'] = {**ROW, 'supervisor': DEAD, 'boot': self.clock.boot,
                                                           **changes}
            session.commit(record, {'event': 'TEST-plant'})

    def use_table(self, rows: dict | None) -> None:
        """The TEST process table recovery reads (None: unreadable)."""
        effect = OSError('TEST: ps failed') if rows is None else None
        self.enterContext(mock.patch.object(native_budget_launch, '_process_table', return_value=rows,
                                            side_effect=effect))

    def test_dead_working_owner_becomes_an_orphan_and_credit_resumes(self) -> None:
        """The dead row is orphaned at the next observation, and a 62 s capacity-only wait is credited in full."""
        self.plant()
        self.use_table(table())
        self.wait(62, POOL)
        clock = self.clock_of()
        self.assertEqual((clock['excludedSeconds'], clock['orphans']['count']), (62.0, 1))
        orphan = clock['orphans']['recent'][0]
        self.assertEqual((orphan['supervisor'], orphan['orphanedElapsed']), (DEAD, 0.0))
        self.assertEqual(list(clock['workers']), ['/TEST/owner-a.json'])

    def test_an_orphans_pending_interval_is_counted_uncertain(self) -> None:
        """4 s accrued pending before another owner registered (and died): orphaning it makes that interval
        uncertain, never credit, as removing an ended owner does."""
        self.use_table(table())
        self.observe('waiting', POOL)
        self.clock.advance(4.0)
        self.plant()                                   # its transaction checkpoints 4 s pending first
        self.clock.advance(2.0)
        self.observe('waiting', POOL)
        clock = self.clock_of()
        self.assertEqual((clock['excludedSeconds'], clock['uncertainSeconds'], clock['orphans']['count']),
                         (0.0, 4.0, 1))

    def test_recycled_pid_is_not_a_live_supervisor(self) -> None:
        """The dead owner's PID now belongs to a live process with another start time: still orphaned."""
        self.plant()
        self.use_table(table({**DEAD, 'started': 'Sun Sep 27 11:00:00 2026'}))
        self.observe('working')
        self.assertEqual(self.clock_of()['orphans']['count'], 1)

    def test_unreadable_process_table_changes_nothing(self) -> None:
        """No table, no proof: the dead row stays and keeps counting as work, so the wait earns nothing."""
        self.plant()
        self.use_table(None)
        self.wait(62, POOL)
        clock = self.clock_of()
        self.assertEqual((clock['orphans']['count'], clock['excludedSeconds']), (0, 0.0))
        self.assertIn('/TEST/dead-00.json', clock['workers'])

    def test_other_boot_row_is_ended_not_orphaned(self) -> None:
        """A row from another boot is removed as ended (a reboot ended it), never recorded as an orphan."""
        self.plant(boot='TEST-other-boot')
        self.use_table(table())
        self.observe('working')
        clock = self.clock_of()
        self.assertEqual((clock['orphans']['count'], sorted(clock['workers'])), (0, ['/TEST/owner-a.json']))

    def test_64_leaked_rows_no_longer_block_new_owners(self) -> None:
        """Sixty-four dead rows fill the owner cap; a new owner's first observation orphans them and registers."""
        self.plant(MAX_WORKERS)
        self.use_table(table())
        self.observe('working')
        clock = self.clock_of()
        self.assertEqual((clock['orphans']['count'], len(clock['orphans']['recent'])), (MAX_WORKERS, MAX_ORPHAN_ROWS))
        self.assertEqual(list(clock['workers']), ['/TEST/owner-a.json'])

    def test_dead_waiter_sharing_a_live_group_is_recoverable(self) -> None:
        """P3: a waiter launched nothing, so a live process in its old group is not its work: it is recovered as
        ended, and the restarted owner's wait is credited."""
        self.plant(state='waiting', resource='heavy-pool', evidence='{}', ticket=3, occupants=['b' * 32],
                   waitClass='capacity')
        self.use_table(table(survivors=(DEAD['pgid'],)))
        self.wait(62, POOL)
        clock = self.clock_of()
        self.assertEqual((clock['excludedSeconds'], clock['orphans']['count']), (62.0, 0))
        self.assertNotIn('/TEST/dead-00.json', clock['workers'])

    def test_a_live_working_owner_is_not_orphaned(self) -> None:
        """O6: a working owner whose supervisor still runs (planted under the dead-row name) stays the Short's work:
        no orphan, and the wait beside it earns nothing."""
        self.plant(supervisor=LIVE)
        self.use_table(table(LIVE))
        self.wait(62, POOL)
        clock = self.clock_of()
        self.assertEqual((clock['orphans']['count'], clock['excludedSeconds']), (0, 0.0))

    def test_a_live_waiter_is_not_recovered(self) -> None:
        """O3: another owner's waiting row whose supervisor still runs is kept by recovery."""
        self.plant(supervisor=LIVE, state='waiting', resource='heavy-pool', evidence='{}', **POOL_ROW)
        self.use_table(table(LIVE))
        self.observe('working')
        self.assertIn('/TEST/dead-00.json', self.clock_of()['workers'])

    def test_a_v1_clock_keeps_its_rows(self) -> None:
        """A v1 clock (the P0 engine's) has no orphan list and is never advanced: its dead working row stays."""
        with locked_batch(self.root, BATCH) as session:
            record = session.read()
            record['clips']['A']['capacityClock'] = {**V1_CLOCK, 'workers': {
                '/TEST/dead-00.json': {key: value for key, value in ROW.items() if key in V1_KEYS}
                | {'supervisor': DEAD, 'boot': self.clock.boot}}}
            session.commit(record, {'event': 'TEST-plant'})
        self.use_table(table())
        self.observe('working')
        self.assertEqual(list(self.clock_of()['workers']), ['/TEST/dead-00.json'])


class PendingOwnershipTests(unittest.TestCase):
    """P6: settling one task's owners keeps another task's waiting owner's pending interval."""

    def test_settling_one_task_keeps_another_owners_pending(self) -> None:
        """Two tasks' owners wait, 10 s pending: settling the first keeps it pending; the last makes it uncertain."""
        waiting = {**ROW, 'state': 'waiting', 'supervisor': DEAD, 'boot': 'TEST-boot', **POOL_ROW}
        workers = {f'/TEST/owner-{index}.json': {**waiting, 'taskId': f'media-{index}'} for index in (1, 2)}
        record = short_record({**new_clock(), 'observedElapsed': 20.0, 'pendingSeconds': 10.0, 'workers': workers})
        clock = record['clips']['A']['capacityClock']
        self.assertEqual(queue_clock.settle_task_workers(record, 'media-1'), ['/TEST/owner-1.json'])
        self.assertEqual((clock['pendingSeconds'], clock['uncertainSeconds']), (10.0, 0.0))
        self.assertEqual(queue_clock.settle_task_workers(record, 'media-2'), ['/TEST/owner-2.json'])
        self.assertEqual((clock['pendingSeconds'], clock['uncertainSeconds']), (0.0, 10.0))


if __name__ == '__main__':
    unittest.main()
