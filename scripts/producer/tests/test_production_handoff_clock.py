"""C12 (M-054, P1 Step B11): a Short's counted time stops at its first delivery and at its visible hand-off.

A v2 Short's ``countedProductionSeconds`` is frozen at its first delivery, from the credit ``record_delivery`` froze
there; ``countedToHandoffSeconds`` runs until the visible hand-off, which ``commands.cmd_handoff`` records on the
clock (``queue_handoff.record_handoff``) with the delivery deadline the Short's credit gives it then. After the hand-off
nothing grows, and the hand-off, not the export, decides ``slaMiss`` (minute 40 is the visible hand-off). A v1 clock
and a Long keep their rules. The first four classes use in-memory TEST records; the last hands off through the CLI on
the test's private authority root, as ``test_production_formats`` does. No child process is started.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import json
import unittest

from _budget_fixture import b3_stand_in, handoff_confirmation, test_mp4
import native_batch
from studio import native_budget_binding as binding
from studio.native_budget_report import sla_miss
from studio.production import queue_clock
from studio.production.queue_handoff import record_handoff
from studio.production.formats import clip_deadlines
from studio.production.queue_clock_schema import problem
from test_native_budget_registry import RegistryCase, ns
from test_queue_clock_v2 import V1_CLOCK, short_record

FROZEN = ('totalElapsedSeconds', 'countedProductionSeconds', 'countedAtDeliverySeconds', 'totalAtDeliverySeconds',
          'countedToHandoffSeconds', 'totalAtHandoffSeconds', 'handoffOnTime')


def delivered(record: dict, elapsed: float, credit: float) -> dict:
    """Short A of ``record`` delivered at ``elapsed`` holding ``credit`` seconds, as a successful outcome records it."""
    clip = record['clips']['A']
    clip['capacityClock'].update(excludedSeconds=credit, observedElapsed=elapsed)   # credit settled by observations
    queue_clock.record_delivery(clip, 'TEST-attempt')
    clip['deliveries'].append({'kind': 'draft', 'output': '/TEST/a.mp4', 'sha256': 'e' * 64,
                               'attemptId': 'TEST-attempt', 'elapsed': elapsed})
    return clip


class DeliveryFreezeTests(unittest.TestCase):
    """The counted time of a delivered Short is the time at its first delivery, whatever credit comes later."""

    def test_counted_time_freezes_at_first_delivery(self) -> None:
        """Counted time is the first delivery's, while the time to hand-off keeps running."""
        clip = delivered(short_record(), 1500.0, 120.0)
        clip['capacityClock']['excludedSeconds'] = 300.0              # credit earned after the delivery
        row = queue_clock.status(clip, 2000.0)
        self.assertEqual((row['totalAtDeliverySeconds'], row['countedAtDeliverySeconds']), (1500.0, 1380.0))
        self.assertEqual(row['countedProductionSeconds'], 1380.0)
        self.assertEqual((row['countedToHandoffSeconds'], row['totalElapsedSeconds']), (1700.0, 2000.0))  # running
        self.assertIsNone(row['handoffOnTime'])

    def test_a_later_delivery_does_not_move_the_frozen_time(self) -> None:
        """A second delivery, with more credit, leaves the first delivery's counted time."""
        clip = delivered(short_record(), 1500.0, 120.0)
        clip['capacityClock'].update(excludedSeconds=300.0, observedElapsed=1900.0)
        queue_clock.record_delivery(clip, 'TEST-attempt-2')
        clip['deliveries'].append({**clip['deliveries'][0], 'attemptId': 'TEST-attempt-2', 'elapsed': 1900.0})
        self.assertEqual(queue_clock.status(clip, 2000.0)['countedAtDeliverySeconds'], 1380.0)

    def test_before_any_delivery_every_time_runs(self) -> None:
        """Undelivered, the counted time and the time to hand-off run; nothing is frozen yet."""
        clip = short_record()['clips']['A']
        clip['capacityClock']['excludedSeconds'] = 60.0
        row = queue_clock.status(clip, 900.0)
        self.assertEqual((row['countedProductionSeconds'], row['countedToHandoffSeconds']), (840.0, 840.0))
        self.assertEqual((row['countedAtDeliverySeconds'], row['totalAtHandoffSeconds']), (None, None))


class HandoffClockTests(unittest.TestCase):
    """``record_handoff`` times the visible hand-off against the Short's deadline with the credit it has then."""

    def test_handoff_on_time_is_recorded_and_frozen(self) -> None:
        """The row is stored on the clock and validates; five minutes later nothing has grown."""
        record = short_record()
        clip = delivered(record, 1500.0, 120.0)
        deadline = clip_deadlines(record, clip)['deliverySeconds']
        row = record_handoff(record, clip, 1800.0)
        self.assertEqual(row, {'elapsed': 1800.0, 'countedSeconds': 1680.0, 'totalSeconds': 1800.0,
                               'deadlineElapsed': deadline, 'onTime': True})
        self.assertEqual(clip['capacityClock']['handoff'], row)
        self.assertIsNone(problem(clip))                               # the schema-8 hand-off row validates
        now, later = queue_clock.status(clip, 1800.0), queue_clock.status(clip, 2100.0)   # five minutes on
        self.assertEqual({key: later[key] for key in FROZEN}, {key: now[key] for key in FROZEN})
        self.assertEqual((later['totalElapsedSeconds'], later['countedToHandoffSeconds']), (1800.0, 1680.0))

    def test_credit_held_at_the_handoff_moves_its_deadline(self) -> None:
        """E-CLOCK-6: the deadline is the one the Short's settled credit gives it at the hand-off."""
        record = short_record()
        clip = delivered(record, 1500.0, 0.0)
        base = clip_deadlines(record, clip)['deliverySeconds']
        clip['capacityClock']['excludedSeconds'] = 120.0
        row = record_handoff(record, clip, base + 60.0)
        self.assertEqual((row['deadlineElapsed'], row['onTime']), (base + 120.0, True))


class SlaMissTests(unittest.TestCase):
    """The visible hand-off, not the export, decides a v2 Short's SLA."""

    def test_late_handoff_is_an_sla_miss_even_with_an_on_time_export(self) -> None:
        """An on-time export is no SLA until the late visible hand-off, which misses."""
        record = short_record()
        clip = delivered(record, 1500.0, 0.0)
        late = clip_deadlines(record, clip)['deliverySeconds'] + 60.0
        self.assertFalse(sla_miss(record, 'A', late))                   # before the hand-off: the on-time export
        self.assertIs(record_handoff(record, clip, late)['onTime'], False)
        self.assertTrue(sla_miss(record, 'A', late))
        self.assertIs(queue_clock.status(clip, late)['handoffOnTime'], False)


class UnchangedClockTests(unittest.TestCase):
    """E-LS-1: a v1 clock and a clip without a clock (a Long) keep their status and record no hand-off."""

    def test_v1_clock_status_unchanged(self) -> None:
        """A v1 clock records no hand-off and its status keeps the pre-M-054 keys and values."""
        record = short_record(V1_CLOCK)
        clip = record['clips']['A']
        before = copy.deepcopy(clip)
        self.assertIsNone(record_handoff(record, clip, 1800.0))
        self.assertEqual(clip, before)
        row = queue_clock.status(clip, 1800.0)
        self.assertFalse(set(FROZEN[2:]) & set(row))
        self.assertEqual((row['totalElapsedSeconds'], row['countedProductionSeconds']), (1800.0, 1680.0))

    def test_a_clip_without_a_clock_records_nothing(self) -> None:
        """A clip without a capacity clock (a Long, a historical Short) records nothing."""
        record = short_record()
        clip = record['clips']['A']
        del clip['capacityClock']
        self.assertIsNone(record_handoff(record, clip, 1800.0))
        self.assertNotIn('capacityClock', clip)


class CommandTests(RegistryCase):
    """``handoff`` records the clock row on the clip, its ``clip-handed-off`` event and its answer."""

    def test_cmd_handoff_records_the_clock(self) -> None:
        """The CLI hand-off records the row on the clip and its event; status then stays frozen."""
        budget = self.reserve(self.project, route='draft')
        mp4 = test_mp4(self.work / 'attempt')
        binding.record_request_outcome({'productionBudget': budget}, {
            'status': 'native-short-review-draft', 'output': mp4[0], 'sha256': mp4[1]})
        self.clock.advance(30)
        confirmation = handoff_confirmation(self.work / 'handoff', mp4, at=self.clock.wall)
        with b3_stand_in():
            handed = native_batch.cmd_handoff(ns(batch='batch-auth', clip='A', confirmation=confirmation))
        clock = handed['clock']
        self.assertIs(clock['onTime'], True)
        self.assertEqual(self.record()['clips']['A']['capacityClock']['handoff'], clock)
        trail = (self.root / 'batches' / 'batch-auth' / 'events.jsonl').read_text().splitlines()
        event = next(json.loads(line) for line in trail if json.loads(line).get('event') == 'clip-handed-off')
        self.assertEqual(event['clock'], clock)
        self.clock.advance(300)
        status = native_batch.cmd_status(ns(batch='batch-auth'))['clips']['A']
        self.assertEqual((status['totalElapsedSeconds'], status['handoffOnTime'], status['slaMiss']),
                         (clock['totalSeconds'], True, False))


if __name__ == '__main__':
    unittest.main()
