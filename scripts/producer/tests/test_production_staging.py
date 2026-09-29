"""Review round 4 regressions: staged starts and the clock (anomalies, settings, the deadline cliff, misses, races).

Several cases port the adversarial reviewer's probes (test_adv_a12_r3, test_adv_a12_r3b); where the round-4
rules decide differently from a probe's assertion (an undatable staging is refused by name instead of adopted,
an explicit discard lets a later start begin a new clock), the port asserts the rule and says so.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from _budget_fixture import approval
from _dispatch_fixture import start_args  # P0 adapt: thin CLI start
from test_native_budget_registry import ns
from test_production_tasks import BATCH, HERE, TaskCase
import native_batch
from studio import native_budget_forecast as forecast  # P0 adapt: the thin CLI reads it here
from studio import native_budget_batches as batches, native_budget_staging as staging
from studio.native_budget_forecast import route_seconds
from studio.native_budget_policy import BatchSpec
from studio.native_budget_store import BudgetAuthorityError
from studio.production import api
from studio.production.authorization import authorize, discard_staged
from studio.production.callbacks import TaskResult
from studio.production.claims import ClaimRef


def spec(**changes: object) -> BatchSpec:
    """batch-next with clip A's approval (the fixture's 60 approved seconds)."""
    return BatchSpec('batch-next', ('A',), (), 1, **{'approvals': {'A': approval('A')}, **changes})


class StagingCase(TaskCase):
    """batch-auth closes first; starts of batch-next are interrupted before their rename, then rerun."""

    def close_auth(self, advance: float = 2400) -> None:
        api.complete_task(self.root, BATCH, ClaimRef('director', 1, self.director['token']), TaskResult(()))
        self.clock.advance(advance)
        native_batch.cmd_close(ns(batch=BATCH))

    def interrupted(self, value: BatchSpec) -> str:
        with mock.patch('studio.native_budget_staging.os.rename', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                authorize(self.root, value)
        return next(row.path.name for row in staging.stagings(self.root) if row.batch_id == 'batch-next')

    def staged(self) -> list[str]:
        return sorted(entry.name for entry in (self.root / 'batches').iterdir() if entry.name.startswith('.creating'))


class ClockAnomalies(StagingCase):
    """An undatable staging is never discarded or replaced by a new clock: the operator decides."""

    def test_a_reboot_with_a_slow_wall_clock_is_refused_by_name(self) -> None:
        self.close_auth()
        name = self.interrupted(spec())
        self.clock.reboot(downtime=-5)                             # rebooted; the wall clock is 5 s behind
        with self.assertRaisesRegex(batches.BudgetRefused, f'{name} of batch batch-next cannot be dated'):
            authorize(self.root, spec())
        self.assertEqual(self.staged(), [name])
        self.assertEqual(api.staged_starts(self.root)[0]['state'], 'unprovable')
        api.discard_staged(self.root, name, 'clock was wrong after the reboot')
        started = authorize(self.root, spec())                     # the operator's decision: a new clock, and a miss
        self.assertEqual([(row['name'], row['cause']) for row in started['priorAuthorizations']], [(name, 'operator')])

    def test_a_forward_wall_jump_on_a_quick_retry_keeps_the_staging(self) -> None:
        self.close_auth()
        name = self.interrupted(spec())
        self.clock.advance(60, wall=3000)                          # 1 real minute; wall time jumps +50 min
        with self.assertRaisesRegex(batches.BudgetRefused, 'wall clock ran 2940 s ahead of the boot clock'):
            authorize(self.root, spec())
        self.assertEqual(self.staged(), [name])                    # never discarded, never a fresh clock


class SettingsAreNotAClockLever(StagingCase):
    """Same approved content with other AI settings is refused by name, never a new start."""

    def test_a_staged_authorization_with_other_ai_settings(self) -> None:
        self.close_auth()
        handover = self.clock.wall
        name = self.interrupted(spec())
        self.clock.advance(120)
        with self.assertRaisesRegex(batches.BudgetRefused, 'exists with other AI settings'):
            authorize(self.root, spec(ai_slots=3))
        self.assertEqual(self.staged(), [name])
        self.assertEqual(authorize(self.root, spec())['authorizedAtEpoch'], handover)

    def test_a_published_batch_with_pending_setup_and_other_ai_settings(self) -> None:
        self.close_auth()
        handover = authorize(self.root, spec())['authorizedAtEpoch']   # published, setup pending
        with self.assertRaisesRegex(batches.BudgetRefused, 'published, its setup pending'):
            authorize(self.root, spec(ai_slots=3))
        self.assertEqual(authorize(self.root, spec())['authorizedAtEpoch'], handover)

    def test_other_approved_content_is_a_new_hand_over_and_a_miss(self) -> None:
        self.close_auth()
        name = self.interrupted(spec())
        started = authorize(self.root, spec(approvals={'A': approval('A', title='TEST other title')}))
        self.assertEqual((started['resumed'], [row['cause'] for row in started['priorAuthorizations']]),
                         (False, ['replaced']))
        self.assertEqual([row['name'] for row in started['discardedStagings']], [name])


class DeadlineCliff(StagingCase):
    """A staging is adopted only while it still fits the minimal deliverable plus the reserves."""

    def test_the_floor_is_the_draft_forecast_of_the_longest_clip_plus_reserves(self) -> None:
        self.close_auth()
        self.interrupted(spec())
        raw = staging.stagings(self.root)[0].raw
        expected = route_seconds(raw['rates'], 'draft', 60.0) + 120 + 45       # approved A keeps 60 s
        self.assertAlmostEqual(staging.adoption_floor(raw), expected)
        self.assertAlmostEqual(expected, 790.0)

    def test_inside_the_floor_it_is_adopted(self) -> None:
        self.close_auth()
        handover = self.clock.wall
        self.interrupted(spec())
        self.clock.advance(2400 - 790)
        self.assertEqual((authorize(self.root, spec())['authorizedAtEpoch']), handover)

    def test_past_the_floor_it_expires_as_a_miss(self) -> None:
        self.close_auth()
        handover = self.clock.wall
        name = self.interrupted(spec())
        self.clock.advance(2400 - 789)                              # 789 s left: less than a minimal deliverable
        started = authorize(self.root, spec())
        self.assertEqual((started['resumed'], started['authorizedAtEpoch']), (False, self.clock.wall))
        miss = started['discardedStagings'][0]['miss']
        self.assertEqual((miss['name'], miss['cause'], miss['authorizedAtEpoch'], miss['deadlineEpoch']),
                         (name, 'expired', handover, handover + 2400))

    def test_a_published_batch_with_pending_setup_resumes_past_its_deadline(self) -> None:
        self.close_auth()
        with mock.patch.object(forecast, 'heavy_lane_capacity', side_effect=OSError('TEST capacity')):
            with self.assertRaises(OSError):
                native_batch.cmd_start(start_args(self.work, 'batch-next', 'A'))
        handover = batches.read_batch(self.root, 'batch-next')['startEpoch']
        self.clock.advance(3000)
        with mock.patch.object(forecast, 'heavy_lane_capacity', return_value=1):
            started = native_batch.cmd_start(start_args(self.work, 'batch-next', 'A'))
        self.assertEqual((started['resumed'], started['authorizedAtEpoch']), (True, handover))
        status = native_batch.cmd_status(ns(batch='batch-next'))
        self.assertEqual((status['phase'], status['slaMisses']), ('past-delivery-deadline', ['A']))


class MissesAreReported(StagingCase):
    """An expired authorization is a miss in the status of the batch that finally starts (reviewer r3 probe)."""

    def test_an_expired_authorization_is_reported_as_a_miss(self) -> None:
        with mock.patch.object(forecast, 'heavy_lane_capacity', return_value=1):
            with self.assertRaises(batches.PredecessorCurrent):
                native_batch.cmd_start(start_args(self.work, 'batch-next', 'A'))
            handover = self.clock.wall
            self.close_auth()
            self.clock.advance(2400)
            native_batch.cmd_start(start_args(self.work, 'batch-next', 'A'))
        status = native_batch.cmd_status(ns(batch='batch-next'))
        self.assertEqual([(row['cause'], row['authorizedAtEpoch']) for row in status['priorAuthorizations']],
                         [('expired', handover)])
        self.assertTrue(any(action.startswith('PRIOR AUTHORIZATION MISSED') for action in status['actions']))


class StagingRaces(StagingCase):
    """Resolution listing while stagings move; an adopting start and an operator discard in two processes."""

    def test_listing_during_publish_and_discard(self) -> None:
        stop, errors = threading.Event(), []

        def lister() -> None:
            while not stop.is_set():
                try:
                    batches.list_batches(self.root)
                except BudgetAuthorityError as error:
                    errors.append(str(error)[-140:])
        thread = threading.Thread(target=lister)
        thread.start()
        try:
            for index in range(40):
                with self.assertRaises(batches.PredecessorCurrent):
                    authorize(self.root, BatchSpec(f'batch-r{index:02d}', ('A',), (), 1,
                                                   approvals={'A': approval('A')}))
                for row in staging.stagings(self.root):
                    discard_staged(self.root, row.path.name, 'probe')
        finally:
            stop.set()
            thread.join()
        self.assertEqual(errors[:3], [], f'{len(errors)} listings failed while stagings moved')

    def test_discard_and_adopt_are_serialized(self) -> None:
        """Either the start adopts the staging (the discard then finds none) or the discard wins and the start
        begins a new clock that lists the discarded authorization as a miss; never both, never neither."""
        self.close_auth()
        name = self.interrupted(spec())
        clock = json.dumps([self.clock.wall, self.clock.continuous, self.clock.boot])
        go = time.monotonic() + 2.0
        processes = [subprocess.Popen([sys.executable, '-B', '-c', RACE, str(HERE), str(self.root), clock, role,
                                       name, str(go)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                     for role in ('adopt', 'discard')]
        adopt, discard = (json.loads(process.communicate(timeout=120)[0].strip().splitlines()[-1])
                          for process in processes)
        record = batches.read_batch(self.root, 'batch-next')
        prior = [row['name'] for row in record['production']['authorization']['prior']]
        if adopt['adopt'] is True:
            self.assertEqual((discard['discard'].startswith('BudgetRefused'), prior), (True, []))
        else:
            self.assertEqual((discard['discard'], prior), (name, [name]))
        batches.list_batches(self.root)


RACE = '''
import json, sys, time
from pathlib import Path
sys.path[:0] = [sys.argv[1], str(Path(sys.argv[1]) / "tests")]
from _budget_fixture import FakeClock, fake_clock, approval
from studio.native_budget_policy import BatchSpec
from studio.production.authorization import authorize, discard_staged
wall, continuous, boot = json.loads(sys.argv[3])
with fake_clock(FakeClock(wall, continuous, boot)):
    while time.monotonic() < float(sys.argv[6]):
        time.sleep(0.001)
    try:
        if sys.argv[4] == "adopt":
            result = authorize(Path(sys.argv[2]), BatchSpec("batch-next", ("A",), (), 1, approvals={"A": approval("A")}))
            print(json.dumps({"adopt": result["resumed"]}))
        else:
            print(json.dumps({"discard": discard_staged(Path(sys.argv[2]), sys.argv[5], "race")["name"]}))
    except Exception as error:
        print(json.dumps({sys.argv[4]: type(error).__name__ + ": " + str(error)[:120]}))
'''


if __name__ == '__main__':
    unittest.main()
