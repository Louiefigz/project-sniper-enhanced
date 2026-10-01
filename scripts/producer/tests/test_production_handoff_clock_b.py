"""C12 pins and fixes after P1-RP5 (X218): the hand-off's timing, its row's consistency and its evidence bounds.

The first four classes are the reviewer's trial pins (``reviews/P1-RP5B-evidence/test_rp5b_pins.py``, F-M1): the
hand-off is timed at the command's elapsed (K11), on the Short's own clock from its own authorization (K2-K4), with
the credit held then (K5, K6), and nothing grows after a late one (K10); the deadline itself is on time (K1).
``RowTests`` and ``OnceTests`` cover F-m1 and F-m2, ``BasisTests`` F-m3, and ``EvidenceBoundTests`` the hand-off
line's bounds for the trail's reserve (X217 M1). In-memory TEST records, plus one CLI hand-off on the fixture's
private root; no child process is started.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import tempfile
import unittest
from pathlib import Path

from _budget_fixture import b3_stand_in, handoff_confirmation, test_mp4
import native_batch
from studio import native_budget_binding as binding
from studio.native_budget_report import sla_miss
from studio.native_budget_status import SLA_BASIS
from studio.native_budget_store import read_batch
from studio.production import handoff, queue_clock
from studio.production.formats import clip_deadlines
from studio.production.queue_clock_schema import problem
from studio.production.queue_handoff import record_handoff
from test_native_budget_registry import RegistryCase, ns
from test_production_handoff_clock import FROZEN, delivered
from test_queue_clock_v2 import short_record


def deliver(clip: dict, elapsed: float, attempt: str) -> None:
    """A delivery of ``clip`` at ``elapsed`` with the credit it holds now."""
    queue_clock.record_delivery(clip, attempt)
    clip['deliveries'].append({'kind': 'draft', 'output': f'/TEST/{attempt}.mp4', 'sha256': 'e' * 64,
                               'attemptId': attempt, 'elapsed': elapsed})


def with_added_short(record: dict, authorized: float) -> dict:
    """``record`` plus Short B, authorized as its own output at ``authorized`` (M-052)."""
    clip = copy.deepcopy(record['clips']['A'])
    clip['output'] = {'format': 'short', 'authorizedElapsed': authorized, 'deadlineElapsed': authorized + 2400.0}
    record['clips']['B'] = clip
    return clip


class BoundaryTests(unittest.TestCase):
    """K1: a hand-off exactly at the deadline is on time (``<=``, as ``on_time`` and the milestone read it)."""

    def test_a_handoff_exactly_at_the_deadline_is_on_time(self) -> None:
        """K1: a hand-off at the deadline itself is on time."""
        record = short_record()
        clip = delivered(record, 1500.0, 0.0)
        deadline = clip_deadlines(record, clip)['deliverySeconds']
        self.assertIs(record_handoff(record, clip, deadline)['onTime'], True)


class AddedShortTests(unittest.TestCase):
    """K2-K4: an added Short's hand-off is timed on its own clock, from its own authorization."""

    def test_an_added_short_is_timed_from_its_own_authorization(self) -> None:
        """K2-K4: B, authorized at 600 s, is timed and judged from 600 s against its own 3000 s."""
        record = short_record()
        added = with_added_short(record, 600.0)
        deliver(added, 2000.0, 'TEST-b')
        row = record_handoff(record, added, 2900.0)
        self.assertEqual((row['totalSeconds'], row['countedSeconds'], row['deadlineElapsed'], row['onTime']),
                         (2300.0, 2300.0, 3000.0, True))
        self.assertEqual(queue_clock.status(added, 2900.0)['totalAtDeliverySeconds'], 1400.0)

    def test_a_declared_short_is_not_timed_against_a_later_added_one(self) -> None:
        """K2: A is judged against its own deadline, never the run's later one."""
        record = short_record()
        with_added_short(record, 600.0)
        clip = delivered(record, 1500.0, 0.0)
        self.assertIs(record_handoff(record, clip, 2500.0)['onTime'], False)


class FrozenTests(unittest.TestCase):
    """K5, K6, K10: the row's counted time uses the credit at the hand-off; nothing grows after a late one. X231 X-R6:
    the total at the hand-off is the hand-off's, never the delivery's."""

    def test_counted_to_handoff_uses_the_credit_held_then_and_delivery_time_stays(self) -> None:
        """K5, K6, X-R6: the row counts the credit held at the hand-off; delivery and hand-off totals stay apart."""
        record = short_record()
        clip = delivered(record, 1500.0, 120.0)
        clip['capacityClock'].update(excludedSeconds=300.0, observedElapsed=1900.0)
        self.assertEqual(record_handoff(record, clip, 2000.0)['countedSeconds'], 1700.0)
        row = queue_clock.status(clip, 2300.0)
        self.assertEqual(row['countedProductionSeconds'], 1380.0)
        self.assertEqual((row['totalAtHandoffSeconds'], row['totalAtDeliverySeconds']), (2000.0, 1500.0))

    def test_a_late_handoff_is_frozen_too(self) -> None:
        """K10: after a late hand-off nothing grows either."""
        record = short_record()
        clip = delivered(record, 1500.0, 0.0)
        late = clip_deadlines(record, clip)['deliverySeconds'] + 60.0
        record_handoff(record, clip, late)
        now, later = queue_clock.status(clip, late), queue_clock.status(clip, late + 300.0)
        self.assertEqual({key: later[key] for key in FROZEN}, {key: now[key] for key in FROZEN})


class LateCommandTests(RegistryCase):
    """K11 (X191): ``handoff`` is timed at the command's elapsed, never at the export it hands off."""

    def test_a_late_handoff_of_an_on_time_export_is_an_sla_miss(self) -> None:
        """K11: an export on time, handed off 30 s past the deadline, is timed at the command and missed."""
        budget = self.reserve(self.project, route='draft')
        mp4 = test_mp4(self.work / 'attempt')
        binding.record_request_outcome({'productionBudget': budget}, {
            'status': 'native-short-review-draft', 'output': mp4[0], 'sha256': mp4[1]})
        record = read_batch(self.root, 'batch-auth')
        deadline = clip_deadlines(record, record['clips']['A'])['deliverySeconds']
        self.assertLess(record['clips']['A']['deliveries'][0]['elapsed'], deadline)      # an on-time export
        self.clock.advance(deadline + 30.0 - (self.clock.wall - record['startEpoch']))
        confirmation = handoff_confirmation(self.work / 'handoff', mp4, at=self.clock.wall)
        with b3_stand_in():
            handed = native_batch.cmd_handoff(ns(batch='batch-auth', clip='A', confirmation=confirmation))
        self.assertEqual((handed['clock']['onTime'], handed['clock']['deadlineElapsed']), (False, deadline))
        self.assertGreater(handed['clock']['elapsed'], deadline)
        self.assertTrue(sla_miss(read_batch(self.root, 'batch-auth'), 'A', handed['clock']['elapsed']))


class RowTests(unittest.TestCase):
    """F-m1: the schema refuses a hand-off row whose verdict or times disagree, or on a clip not handed off."""

    def handed(self) -> dict:
        """A Short handed off 600 s late, as ``cmd_handoff`` leaves it."""
        record = short_record()
        clip = delivered(record, 1500.0, 0.0)
        record_handoff(record, clip, clip_deadlines(record, clip)['deliverySeconds'] + 600.0)
        clip['state'] = 'handed-off'
        self.assertIsNone(problem(clip))
        return clip

    def test_a_handoff_exactly_at_the_deadline_validates(self) -> None:
        """X238: the validator's boundary is ``<=``, as ``record_handoff``'s is."""
        record = short_record()
        clip = delivered(record, 1500.0, 0.0)
        row = record_handoff(record, clip, clip_deadlines(record, clip)['deliverySeconds'])
        clip['state'] = 'handed-off'
        self.assertEqual((row['elapsed'], row['onTime']), (row['deadlineElapsed'], True))
        self.assertIsNone(problem(clip))

    def test_a_forged_on_time_verdict_is_refused(self) -> None:
        """An onTime flag set against its own times is refused by name."""
        clip = self.handed()
        clip['capacityClock']['handoff']['onTime'] = True
        self.assertEqual(problem(clip), 'Short capacity clock hand-off: its times and its on-time verdict disagree')

    def test_counted_above_total_or_total_above_elapsed_is_refused(self) -> None:
        """A row whose counted time exceeds its total, or total its elapsed, is refused by name."""
        for field, delta in (('countedSeconds', 1e6), ('totalSeconds', 1e6)):
            with self.subTest(field=field):
                clip = self.handed()
                clip['capacityClock']['handoff'][field] += delta
                self.assertEqual(problem(clip),
                                 'Short capacity clock hand-off: its times and its on-time verdict disagree')

    def test_a_row_on_a_clip_not_handed_off_is_refused(self) -> None:
        """A hand-off row on an active clip is refused by name."""
        clip = self.handed()
        clip['state'] = 'active'
        self.assertEqual(problem(clip), 'Short capacity clock hand-off on a clip that is not handed off')


class OnceTests(unittest.TestCase):
    """F-m2: ``record_handoff`` refuses to replace a recorded row by name (a clock is never reset)."""

    def test_a_second_record_is_refused(self) -> None:
        """A second hand-off row is refused by name and the first one stays."""
        record = short_record()
        clip = delivered(record, 1500.0, 0.0)
        deadline = clip_deadlines(record, clip)['deliverySeconds']
        record_handoff(record, clip, deadline + 60.0)
        with self.assertRaisesRegex(ValueError, "^This Short's hand-off is already timed on its clock; a clip is "
                                                'handed off once$'):
            record_handoff(record, clip, deadline - 60.0)
        self.assertIs(clip['capacityClock']['handoff']['onTime'], False)


class BasisTests(unittest.TestCase):
    """F-m3: status names what ``slaMisses`` holds since M-054: a recorded late hand-off, else no MP4 in time."""

    def test_the_sla_basis_names_the_recorded_handoff(self) -> None:
        """The slaMisses basis names the recorded hand-off first, then the export rule."""
        self.assertIn("a v2 Short's recorded visible hand-off after its delivery deadline", SLA_BASIS['slaMisses'])
        self.assertIn('otherwise no complete MP4 encoded by the delivery deadline', SLA_BASIS['slaMisses'])


class EvidenceBoundTests(unittest.TestCase):
    """X217 M1: the ``clip-handed-off`` line carries the evidence's paths and times, so both are bounded."""

    def test_a_time_longer_than_its_bound_is_refused(self) -> None:
        """A valid ISO time is read; one with 100 fractional digits is refused by name."""
        self.assertIsNotNone(handoff._time('2026-09-30T12:00:00.123456+00:00', 'visibleHandoffAt'))
        with self.assertRaisesRegex(handoff.HandoffEvidenceError, r'\(at most 64 encoded bytes\)$'):
            handoff._time('2026-09-30T12:00:00.' + '1' * 100 + '+00:00', 'visibleHandoffAt')
        astral = '2026-09-30\U0001F600' + '12:00:00.' + '1' * 33 + '+00:00'   # 59 characters, 70 encoded bytes
        self.assertLessEqual(len(astral), 64)
        with self.assertRaisesRegex(handoff.HandoffEvidenceError, r'\(at most 64 encoded bytes\)$'):
            handoff._time(astral, 'visibleHandoffAt')   # X246 n1: the bound is in encoded bytes

    def test_a_path_longer_than_its_encoded_bound_is_refused(self) -> None:
        """A 780-byte path of control characters encodes past 4096 bytes and is refused by name."""
        holder = tempfile.TemporaryDirectory(prefix='sniper-test-handoff-')
        self.addCleanup(holder.cleanup)
        folder = Path(holder.name).resolve()
        for _ in range(4):                       # each control character encodes as six bytes (\u0001)
            folder = folder / ('\x01' * 170)
        folder.mkdir(parents=True)
        (folder / 'record.json').write_text('{}')
        with self.assertRaisesRegex(handoff.HandoffEvidenceError, 'longer than 4096 encoded bytes'):
            handoff._read(folder / 'record.json')


if __name__ == '__main__':
    unittest.main()
