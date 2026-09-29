"""Visible hand-off milestones come only from a recorded hand-off on the batch clock (unit A6 status).

A media receipt never marks a visible hand-off; a views-ready record verifies Studio but is not
visible; a recorded confirmation is judged by its event's batch time (never a wall stamp, which a
clock rollback can move, and which is flagged, never a reason to reject); a hand-off file named
with --handoff is real but off the batch clock and never meets the SLA. The shared reader is unit
A3's real ``studio.production.handoff`` with TEST records written by its fixture; the batch record
is in memory.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from _budget_fixture import FakeClock, fake_clock, handoff_confirmation
from _status_fixture import (
    attempt, batch_record, deliver, handed_off, handoff_summary, mp4, observe, temporary_directory, views_record,
)
from studio import native_budget_handoffs as handoffs
from studio.native_budget_binding import advance_clock
from studio.native_budget_milestones import milestones
from studio.native_budget_outputs import output_status


class Case(unittest.TestCase):
    """A two-clip TEST batch whose clip A delivered a draft at 900 s, observed at 1100 s."""

    def setUp(self) -> None:
        self.record, self.dir = observe(batch_record(), 1100.0), temporary_directory(self)
        self.video = mp4('A-draft')
        self.draft = deliver(self.record, 'A', attempt('draft', 600.0, completed=900.0), self.video)

    def verdicts(self, events: tuple = (), files: tuple = ()) -> dict:
        now = self.record['clock']['elapsed']
        return {'handoffs': handoffs.handoff_verdicts(self.record, events, files, now), 'finalReviews': []}

    def found(self, verdicts: dict | None = None) -> dict:
        return milestones(self.record, 'A', self.record['clock']['elapsed'], verdicts or self.verdicts())

    def recorded(self, at: float = 1001.0, **changes: object) -> dict:
        summary = {**handoff_summary(self.video, (950.0, 990.0), views_record(self.dir, self.video)), **changes}
        return handed_off('A', summary, at)


class MediaReceiptTests(Case):
    """An encoded MP4 is encoding, nothing more."""

    def test_a_delivery_alone_is_encoded_not_visible(self) -> None:
        found = self.found()
        self.assertEqual((found['timestamps']['encodedAt'], found['timestamps']['visibleHandoffAt']), (900.0, None))
        self.assertIn('media receipt', found['visibleMp4']['reason'])
        self.assertEqual(found['matchingStudio']['status'], 'not-established')

    def test_after_the_deadline_an_encoded_but_unrecorded_hand_off_is_a_miss(self) -> None:
        observe(self.record, 2500.0)
        sla = self.found()['slaMiss']
        self.assertEqual((sla['status'], sla['miss'], sla['encodedByDeadline']), ('missed', True, True))


class TrailTests(Case):
    """The recorded hand-off: judged by its event's batch time, its wall stamps only reported."""

    def test_a_recorded_confirmation_is_visible_at_its_event_time(self) -> None:
        found = self.found(self.verdicts((self.recorded(1001.0),)))
        self.assertEqual((found['timestamps']['visibleHandoffAt'], found['visibleMp4']['status']), (1001.0, 'visible'))
        self.assertEqual(found['visibleMp4']['wall']['visibleHandoffAt'][:19], '2027-01-15T08:16:30')
        self.assertEqual((found['matchingStudio']['status'], found['slaMiss']['status']), ('attested', 'met'))
        self.assertEqual(found['visibleMp4']['approvedContent']['mismatches'], [])

    def test_a_wall_clock_rollback_cannot_turn_a_late_hand_off_into_a_met_sla(self) -> None:
        """probe_milestones.Rollback: the confirmation was stamped while the wall clock ran 600 s behind."""
        record, clock = batch_record(), FakeClock()
        with fake_clock(clock):
            clock.advance(2000.0)
            clock.advance(0.0, wall=-600.0)                 # the wall clock steps back 600 s
            clock.advance(300.0)
            video = mp4('A-draft')
            deliver(record, 'A', attempt('draft', 1500.0, completed=advance_clock(record)), video)
            clock.advance(350.0)
            verified = clock.wall
            clock.advance(50.0)                              # true 2700 s: after the 2400 s deadline
            visible = clock.wall
            clock.advance(10.0)
            event = handed_off('A', {**handoff_summary(video, (0.0, 0.0)), 'viewsVerifiedAt': _wall(verified),
                                     'visibleHandoffAt': _wall(visible)}, advance_clock(record))
            clock.advance(90.0, wall=690.0)                  # NTP corrects the wall clock forward
            clock.advance(100.0)
            now = advance_clock(record)
        found = milestones(record, 'A', now, {'handoffs': handoffs.handoff_verdicts(record, (event,), (), now),
                                              'finalReviews': []})
        self.assertAlmostEqual(found['timestamps']['visibleHandoffAt'], 2710.0, places=3)
        self.assertEqual(found['slaMiss']['status'], 'missed')

    def test_an_event_later_than_this_observation_on_the_batch_clock_is_rejected(self) -> None:
        verdict = self.verdicts((self.recorded(1200.0),))['handoffs'][0]
        self.assertFalse(verdict['accepted'])
        self.assertIn('future-dated evidence: the hand-off event at 1200.0s is later', verdict['reason'])

    def test_display_wall_stamps_never_reject_a_recorded_hand_off(self) -> None:
        """N2: a stamp ahead of this observation is flagged, an unreadable one named; the event's time decides."""
        ahead = self.recorded(visibleHandoffAt=_wall(self.record['clock']['epoch'] + 60))
        unreadable = self.recorded(viewsVerifiedAt=5)
        for event, flag, names in ((ahead, True, []), (unreadable, False, ['viewsVerifiedAt'])):
            with self.subTest(flag=flag):
                found = self.found(self.verdicts((event,)))
                wall = found['visibleMp4']['wall']
                self.assertEqual((found['timestamps']['visibleHandoffAt'], found['slaMiss']['status']), (1001.0, 'met'))
                self.assertEqual((wall['wallAheadOfObservation'], wall['wallUnreadable']), (flag, names))

    def test_a_wall_step_back_after_an_on_time_hand_off_keeps_it_met(self) -> None:
        """probe_v2 step-back: recorded at a true 995 s, then the wall clock steps back an hour before status."""
        record, clock = batch_record(), FakeClock()
        with fake_clock(clock):
            clock.advance(900.0)
            video = mp4('A-draft')
            deliver(record, 'A', attempt('draft', 500.0, completed=advance_clock(record)), video)
            clock.advance(60.0)
            verified = clock.wall
            clock.advance(30.0)
            visible = clock.wall
            clock.advance(5.0)
            at = advance_clock(record)
            event = handed_off('A', {**handoff_summary(video, (0.0, 0.0)), 'viewsVerifiedAt': _wall(verified),
                                     'visibleHandoffAt': _wall(visible)}, at)
            clock.advance(100.0)
            clock.advance(0.0, wall=-3600.0)                 # a one-hour wall-clock step back
            clock.advance(1500.0)                            # true 2595 s: past the deadline
            now = advance_clock(record)
        verdict = handoffs.handoff_verdicts(record, (event,), (), now)[0]
        found = milestones(record, 'A', now, {'handoffs': [verdict], 'finalReviews': []})
        self.assertTrue(verdict['accepted'])
        self.assertTrue(verdict['wall']['wallAheadOfObservation'])
        self.assertAlmostEqual(found['timestamps']['visibleHandoffAt'], 995.0, places=3)
        self.assertEqual(found['slaMiss']['status'], 'met')

    def test_only_a3s_exact_summary_shape_is_accepted_and_nothing_malformed_crashes(self) -> None:
        other = mp4('B-draft')
        deliver(self.record, 'B', attempt('draft', 600.0, completed=950.0), other)
        cases = {'not a {path, sha256} binding': [self.recorded(confirmation='x'), self.recorded(confirmation=True),
                                                  self.recorded(record={'path': '/x'})],
                 'names no delivery of clip A': [self.recorded(mp4={'path': other[0], 'sha256': other[1]}),
                                                 self.recorded(mp4=None)],
                 'unknown clip': [{**self.recorded(), 'clipId': 'Q'}],
                 'before its MP4 was delivered': [self.recorded(800.0)]}
        for reason, event in ((reason, event) for reason, events in cases.items() for event in events):
            with self.subTest(reason, event=event['handoff'].get('confirmation')):
                verdict = self.verdicts((event,))['handoffs'][0]
                self.assertFalse(verdict['accepted'])
                self.assertIn(reason, verdict['reason'])

    def test_a_views_ready_summary_verifies_studio_only(self) -> None:
        event = handed_off('A', handoff_summary(self.video, (950.0, None)), 1001.0)
        found = self.found(self.verdicts((event,)))
        self.assertEqual((found['visibleMp4']['status'], found['matchingStudio']['status']),
                         ('not-established', 'server-verified'))

    def test_the_views_ready_records_approved_content_comparison_travels_with_it(self) -> None:
        differs = {'operatorApproval': {'status': 'supplied'}, 'title': 'normalization-only',
                   'titleMatchesApproval': True,
                   'sourceMatchesApproval': True, 'wordsMatchApproval': False, 'wordTextsMatchApproval': True,
                   'clipMatchesApproval': True, 'missingWords': [12], 'extraWords': [], 'displayCorrections': [{}]}
        bound = views_record(self.dir, self.video, differs)
        event = handed_off('A', handoff_summary(self.video, (950.0, 990.0), bound), 1001.0)
        content = self.found(self.verdicts((event,)))['visibleMp4']['approvedContent']
        self.assertEqual((content['mismatches'], content['title'], content['displayCorrections']),
                         (['wordsMatchApproval'], 'normalization-only', 1))
        gone = handed_off('A', handoff_summary(self.video, (950.0, 990.0)), 1001.0)
        self.assertEqual(self.found(self.verdicts((gone,)))['visibleMp4']['approvedContent']['status'], 'unavailable')


class FileTests(Case):
    """A hand-off file (unit A3's real reader, TEST B3 records) is real but never on the batch clock."""

    def test_a_confirmation_file_is_off_the_batch_clock_and_never_meets_the_sla(self) -> None:
        file = handoff_confirmation(self.dir / 'handoff', self.video)
        found = self.found(self.verdicts(files=(file,)))
        self.assertEqual((found['visibleMp4']['status'], found['timestamps']['visibleHandoffAt']),
                         ('confirmed-not-on-batch-clock', None))
        self.assertEqual(found['visibleMp4']['wall']['visibleHandoffAt'], '2026-09-27T10:00:09.000+00:00')
        observe(self.record, 2500.0)
        late = self.found(self.verdicts(files=(file,)))['slaMiss']
        self.assertEqual(late['status'], 'missed')
        self.assertIn('never meets the SLA', late['offClock'])
        row = output_status(self.record, 'A', 2500.0, {'verdicts': self.verdicts(files=(file,)), 'transcripts': None,
                                                        'timing': None, 'events': (), 'actions': []})
        self.assertIn(f'native_batch.py handoff --clip A --confirmation {file}', row['nextActions'][0])

    def test_views_ready_and_refused_files(self) -> None:
        views = handoff_confirmation(self.dir / 'views', self.video, visible=False)
        self.assertEqual(self.found(self.verdicts(files=(views,)))['matchingStudio']['status'], 'server-verified')
        other = handoff_confirmation(self.dir / 'other', (self.video[0], 'e' * 64))
        verdict = self.verdicts(files=(other,))['handoffs'][0]
        self.assertFalse(verdict['accepted'])
        self.assertIn('not a recorded delivery', verdict['reason'])

    def test_without_the_shared_reader_a_file_is_rejected(self) -> None:
        with mock.patch.object(handoffs, 'handoff_reader', return_value=None):
            verdict = self.verdicts(files=(self.dir / 'x.json',))['handoffs'][0]
        self.assertEqual((verdict['accepted'], verdict['reason']), (False, handoffs.READER_MISSING))


def _wall(epoch: float) -> str:
    """A wall-clock stamp as B3 writes it."""
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec='milliseconds')


if __name__ == '__main__':
    unittest.main()
