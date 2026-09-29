"""A6u status adapted to src's counted clock and hand-off (P0 Step 4.3, adaptations 1-5; TEST records only).

1. The compact per-output view carries the counted clock. 2. The visible hand-off SLA and the preparation target
use each output's own counted deadlines (``formats.clip_deadlines``). 3. Hand-off content fields are the ones
src's hand-off checks (``native_handoff_content.MATERIAL``). 4. The default status reads the recorded hand-off
from the trail and never re-verifies a live page. 5. A closed batch's final reviews are not verifiable.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from _status_fixture import (
    attempt, batch_record, deliver, handed_off, handoff_summary, mp4, observe, temporary_directory, views_record,
)
from test_native_budget_run_status import Case as RunCase
from studio import native_budget_handoffs as handoffs
from studio.native_budget_evidence import CLOSED, final_review_verdicts
from studio.native_budget_milestones import milestones
from studio.native_budget_status import StatusInputs, production_status
from studio.native_handoff_content import MATERIAL


class CompactClockTests(RunCase):
    """(1) The default view shows counted and total time next to the settled render-queue credit."""

    def test_compact_status_shows_counted_and_total_time(self) -> None:
        """A Short with 60 s of settled credit: total 2500 s, counted 2440 s, excluded 60 s."""
        self.record['clips']['A']['capacityClock'].update(excludedSeconds=60.0, observedElapsed=2500.0)
        clock = production_status(self.record, 2500.0, StatusInputs())['clips']['A']['production']['clock']
        self.assertEqual((clock['timingPolicy'], clock['totalElapsedSeconds'], clock['countedProductionSeconds'],
                          clock['excludedRenderQueueSeconds'], clock['uncertainQueueSeconds'], clock['capacityWaits']),
                         (self.record['clips']['A']['capacityClock']['policy'], 2500.0, 2440.0, 60.0, 0.0, []))


class CountedDeadlineTests(unittest.TestCase):
    """(2)-(4) One Short authorized at 600 s with 120 s of settled credit, delivered and handed off."""

    def setUp(self) -> None:
        """Clip A: an own-clock Short (output row) authorized at 600 s, 120 s of settled credit, a delivered draft."""
        self.record, self.dir = batch_record(), temporary_directory(self)
        clip = self.record['clips']['A']
        clip['output'] = {'format': 'short', 'authorizedElapsed': 600.0}
        clip['capacityClock'].update(excludedSeconds=120.0, observedElapsed=3000.0)
        self.video = mp4('A-draft')
        deliver(self.record, 'A', attempt('draft', 700.0, completed=900.0), self.video)

    def found(self, at: float, content: dict | None = None) -> dict:
        """Milestones of A with its hand-off recorded on the batch clock at ``at``, observed just after."""
        bound = views_record(self.dir, self.video, content)
        event = handed_off('A', handoff_summary(self.video, (950.0, 990.0), bound), at)
        observe(self.record, at + 1.0)
        verdicts = {'handoffs': handoffs.handoff_verdicts(self.record, (event,), (), at + 1.0), 'finalReviews': []}
        return milestones(self.record, 'A', at + 1.0, verdicts)

    def test_visible_handoff_sla_uses_the_shorts_counted_deadline(self) -> None:
        """Deadline 600 + 2400 + 120 = 3120 s: a hand-off at 3050 s meets it, at 3130 s misses it."""
        met, missed = self.found(3050.0)['slaMiss'], self.found(3130.0)['slaMiss']
        self.assertEqual((met['deadlineElapsed'], met['status'], missed['status']), (3120.0, 'met', 'missed'))
        self.assertEqual(self.found(3050.0)['preparation']['targetElapsed'], 1500.0 + 720.0)

    def test_status_reports_every_content_mismatch_the_handoff_checks(self) -> None:
        """Every field src's hand-off compares is reported; A6u's clipMatchesApproval is not."""
        content = {'operatorApproval': {'status': 'supplied'}, 'title': 'exact', 'missingWords': [], 'extraWords': [],
                   'displayCorrections': [], **{key: True for key in MATERIAL},
                   'secondsMatchApproval': False, 'timingMatchesApproval': False}
        summary = self.found(3050.0, content)['visibleMp4']['approvedContent']
        self.assertEqual(summary['mismatches'], ['secondsMatchApproval', 'timingMatchesApproval'])
        self.assertEqual(set(MATERIAL) - set(summary), set())
        self.assertNotIn('clipMatchesApproval', summary)

    def test_default_status_needs_no_live_page(self) -> None:
        """The recorded trail event decides; the live hand-off reader is never called."""
        with mock.patch.object(handoffs, 'handoff_reader', side_effect=AssertionError('TEST: live re-verification')):
            found = self.found(3050.0)
        self.assertEqual((found['visibleMp4']['status'], found['timestamps']['visibleHandoffAt']), ('visible', 3050.0))


class ClosedBatchTests(unittest.TestCase):
    """(5) After close no final review is checked: approved content binds nothing in a closed batch."""

    def test_a_closed_batch_never_verifies_a_final_review(self) -> None:
        """check-final is never run for a closed batch; every named review is rejected with the reason."""
        record = batch_record()
        record['status'] = 'closed'
        with mock.patch('studio.native_budget_evidence.check_final', side_effect=AssertionError('TEST: not run')):
            rows = final_review_verdicts(record, (Path('/TEST/FINAL-REVIEW.json'),))
        self.assertEqual(rows, [{'file': '/TEST/FINAL-REVIEW.json', 'accepted': False, 'reason': CLOSED}])


if __name__ == '__main__':
    unittest.main()
