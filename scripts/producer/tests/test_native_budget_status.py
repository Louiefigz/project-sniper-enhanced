"""Render readiness, editorial approval and the forecast seam, each from its own evidence (unit A6 status).

Only check-final's editorial final over a delivered final MP4 that answers this batch's approved
content in force for that delivery is an approval; it is current only for the latest delivery
under the current approval, otherwise historical, and never human approval. check-final is
stubbed (TEST B2-shaped results); the A5 forecast is stubbed with its real return shape.
Requirement revision approved-content-production-2026-09-27: the approval compared is the one
handed over at batch start (or a later recorded change), never re-approved here.
"""
from __future__ import annotations

import subprocess
import threading
import time
import unittest
from unittest import mock

from _budget_fixture import approval
from _status_fixture import (
    approved_content, attempt, batch_record, checked, deliver, final_review, mp4, observe, packet_resolved,
    temporary_directory, write_json,
)
from studio import native_budget_evidence as evidence
from studio import native_budget_review_timing as timing_module
from studio import native_budget_forecast as forecast
from studio.native_budget_milestones import milestones
from studio.native_budget_outputs import forecast_path
from studio.native_budget_policy import change_approval

NONE = {'handoffs': [], 'finalReviews': []}
# The return shape of A5's latest_safe_launch at shorts-sla/a5-forecast b1fa4c04 (native_budget_paths.render_path).
A5_PATH = {'latestSafeStartElapsed': 1030.0, 'route': 'draft', 'fits': True, 'reason': 'fits the whole batch',
           'status': 'draft-fits', 'launchNow': True, 'draft': {'startElapsed': 1030.0}, 'final': None,
           'nextSlotFreeElapsed': 1000.0}


class RenderReadyTests(unittest.TestCase):
    """Render readiness from admitted launches that succeeded or still run; failures establish nothing."""

    def setUp(self) -> None:
        self.record = batch_record()
        deliver(self.record, 'A', attempt('draft', 600.0, completed=900.0), mp4('A-draft'))

    def test_draft_and_final_readiness_are_separate(self) -> None:
        clip = self.record['clips']['A']
        clip['attempts'].insert(0, attempt('draft', 300.0, status='failed', completed=320.0))
        clip['attempts'].append(attempt('promote', 1600.0, status='running'))
        found = milestones(self.record, 'A', 1700.0, NONE)
        self.assertEqual((found['timestamps']['draftRenderReadyAt'], found['timestamps']['finalRenderReadyAt']),
                         (600.0, 1600.0))
        self.assertEqual(found['preparation']['draft']['failedLaunches'], 1)
        self.assertTrue(found['preparation']['final']['provisional'])
        self.assertEqual(found['preparation']['status'], 'met')

    def test_preparation_is_late_or_missed_after_minute_25(self) -> None:
        self.record['clips']['A']['attempts'][0]['admittedElapsed'] = 1600.0
        self.assertEqual(milestones(self.record, 'A', 2000.0, NONE)['preparation']['status'], 'late')
        self.assertEqual(milestones(self.record, 'B', 1600.0, NONE)['preparation']['status'], 'missed')
        self.assertEqual(milestones(self.record, 'B', 1000.0, NONE)['preparation']['status'], 'pending')


class EditorialApprovalTests(unittest.TestCase):
    """check-final's editorial final, bound to this batch's approved content in force for the delivery."""

    def setUp(self) -> None:
        self.record, self.dir = observe(batch_record(), 2000.0), temporary_directory(self)
        self.first, self.second = mp4('A-final-1'), mp4('A-final-2')
        deliver(self.record, 'A', attempt('final', 600.0, completed=1200.0), self.first)
        self.review, self.review_sha = write_json(self.dir, 'FINAL-REVIEW.json', final_review(1500.0))
        self.events = (packet_resolved('A', 1380.0),)

    def verdict(self, video: tuple[str, str], content: dict | None = None, **result: object) -> dict:
        found = {**checked(video, self.review_sha, content or approved_content(self.record, 'A')), **result}
        with mock.patch.object(evidence, 'check_final', return_value=found):
            return evidence.final_review_verdict(self.record, self.review, events=self.events)

    def timed(self, events: tuple[dict, ...], name: str = 'variant', **timing: object) -> dict:
        """A current approval of the first MP4 from a review with these timing fields, against these trail events."""
        self.review, self.review_sha = write_json(self.dir, f'FINAL-REVIEW-{name}.json', final_review(1500.0, **timing))
        self.events = events
        return self.verdict(self.first)

    def approval(self, verdicts: list[dict]) -> dict:
        return milestones(self.record, 'A', 2000.0, {'handoffs': [], 'finalReviews': verdicts})['editorialApproval']

    def test_a_current_editorial_final_is_approved_but_never_human_approval(self) -> None:
        verdict = self.verdict(self.first, humanApproved=True)
        found = self.approval([verdict])
        self.assertEqual((found['status'], found['standing'], found['humanApproved']), ('approved', 'current', False))
        self.assertEqual(found['wall']['submittedAt'][:19], '2027-01-15T08:25:00')
        self.assertIsNone(milestones(self.record, 'A', 2000.0, NONE)['timestamps']['editoriallyApprovedAt'])

    def test_editorially_approved_at_is_the_declared_submission_with_the_trail_lower_bound(self) -> None:
        """Seam (e): submission.timing.submittedElapsed, cross-checked against the packet-resolved event."""
        found = milestones(self.record, 'A', 2000.0, {'handoffs': [], 'finalReviews': [self.verdict(self.first)]})
        self.assertEqual(found['timestamps']['editoriallyApprovedAt'], 1500.0)
        timing = found['editorialApproval']['timing']
        self.assertEqual((timing['basis'], timing['resolvedElapsed'], timing['aheadOfObservation']),
                         (timing_module.DECLARED, 1380.0, False))

    def test_a_recorded_review_submitted_event_is_preferred(self) -> None:
        recorded = {'event': 'review-submitted', 'clipId': 'A', 'recordSha256': self.review_sha, 'elapsed': 1510.0}
        self.events = (*self.events, recorded)
        timing = self.approval([self.verdict(self.first)])['timing']
        self.assertEqual((timing['approvedAt'], timing['basis'], timing['declaredSubmittedElapsed']),
                         (1510.0, timing_module.RECORDED, 1500.0))

    def test_a_review_not_timed_on_this_batchs_clock_for_this_clip_is_rejected(self) -> None:
        resolved = (packet_resolved('A', 1380.0),)
        cases = {'not timed on the batch clock': self.timed(resolved, 'declared', basis='declared-not-authenticated'),
                 "timed on batch 'another-batch'": self.timed(resolved, 'batch', batchId='another-batch'),
                 "timed for clip 'B'": self.timed(resolved, 'clip', clipId='B'),
                 'no packet-resolved event': self.timed((packet_resolved('A', 1380.0, sha256='d' * 64),), 'sha'),
                 "for 'plan-critic' on clip 'A'": self.timed((packet_resolved('A', 1380.0, 'plan-critic'),), 'role'),
                 'disagrees with the recorded packet-resolved': self.timed((packet_resolved('A', 1379.0),), 'at'),
                 'submission after the resolution': self.timed(resolved, 'order', submittedElapsed=1000.0)}
        for reason, verdict in cases.items():
            with self.subTest(reason):
                self.assertFalse(verdict['accepted'])
                self.assertIn(reason, verdict['reason'])

    def test_an_approval_of_a_superseded_mp4_is_historical(self) -> None:
        deliver(self.record, 'A', attempt('final', 1300.0, completed=1900.0), self.second)
        found = self.approval([self.verdict(self.first)])
        self.assertEqual((found['status'], found['historical'][0]['delivery']['output']),
                         ('historical-only', self.first[0]))

    def test_an_approval_of_content_superseded_by_a_recorded_change_is_historical(self) -> None:
        """probe_item6: a final built before the title change keeps its approval only as history."""
        content = approved_content(self.record, 'A')
        change_approval(self.record, 'A', approval('A', title='TEST changed title A', recorded_by='TEST operator'),
                        1300.0)
        content['proposedChanges'] = ['title: TEST better title']
        found = self.approval([self.verdict(self.first, content)])
        self.assertEqual(found['status'], 'historical-only')
        self.assertEqual(found['historical'][0]['approvedContent']['proposedChanges'], ['title: TEST better title'])
        self.assertFalse(found['historical'][0]['approvedContent']['currentApproval'])

    def test_contradictions_and_proposed_changes_travel_with_a_current_approval(self) -> None:
        content = {**approved_content(self.record, 'A'), 'contradictions': ['title-differs'],
                   'proposedChanges': ['title: shorter']}
        found = self.approval([self.verdict(self.first, content)])['approvedContent']
        self.assertEqual((found['contradictions'], found['proposedChanges']), (['title-differs'], ['title: shorter']))

    def test_what_is_never_an_editorial_final(self) -> None:
        draft = mp4('A-draft')
        deliver(self.record, 'A', attempt('draft', 1300.0, completed=1400.0), draft)
        cases = {'editorialFinal \'not-established\'': self.verdict(self.first, editorialFinal='not-established'),
                 'final delivery': self.verdict(draft),
                 'changed while it was checked': self.verdict(self.first, recordSha256='f' * 64),
                 'answered batch \'another-batch\'': self.verdict(
                     self.first, approved_content(self.record, 'A', batch='another-batch')),
                 'answered clip \'Z\'': self.verdict(self.first, approved_content(self.record, 'A', clip='Z')),
                 'not in force': self.verdict(self.first, approved_content(self.record, 'A', identity='f' * 64)),
                 'bound no approved content': self.verdict(self.first, {'approved': None}),
                 'editorialFinal None': self.verdict(self.first, editorialFinal=None)}
        for reason, verdict in cases.items():
            with self.subTest(reason):
                self.assertFalse(verdict['accepted'])
                self.assertIn(reason, verdict['reason'])
                self.assertEqual(self.approval([verdict])['status'], 'not-established')

    def test_a_wall_stamp_ahead_of_this_observation_is_flagged_not_rejected(self) -> None:
        """N2: after a one-hour wall-clock step back the submission's wall stamp is ahead; the verdict stands."""
        self.record['clock']['epoch'] -= 3600.0
        found = self.approval([self.verdict(self.first)])
        self.assertEqual((found['status'], found['at'], found['wall']['wallAheadOfObservation']),
                         ('approved', 1500.0, True))

    def test_a_closed_batchs_approval_is_not_verifiable_after_close(self) -> None:
        self.record['status'] = 'closed'
        with mock.patch.object(evidence, 'check_final') as check:
            rows = evidence.final_review_verdicts(self.record, (self.review,), self.events)
        check.assert_not_called()
        self.assertIn('not verifiable after close', rows[0]['reason'])
        found = self.approval(rows)
        self.assertEqual((found['status'], found['at']), ('not-verifiable-after-close', None))

    def test_the_seam_runs_check_final_on_the_exact_record_and_refuses_a_failure(self) -> None:
        node = self.wrapper('node-ok', 'printf \'{"editorialFinal": "approved", "args": "%s"}\' "$*"\n')
        with mock.patch('studio.native_run_config.local_environment', return_value=({'node': str(node)}, {})):
            self.assertTrue(evidence.check_final(self.review)['args'].endswith(f'check-final {self.review}'))
        refusing = self.wrapper('node-refuses', 'echo "Invalid native final review scope" >&2\nexit 1\n')
        with mock.patch('studio.native_run_config.local_environment', return_value=({'node': str(refusing)}, {})):
            rejected = evidence.final_review_verdict(self.record, self.review)
        self.assertIn('check-final refused the record: Invalid native final review scope', rejected['reason'])

    def test_a_check_out_of_time_is_killed_with_everything_it_started(self) -> None:
        """p18: check-final blocks on a child (context.py --given-check); the budget kills the whole group."""
        marker = f'{29 + time.time_ns() % 1_000_000 / 1_000_000:.6f}'   # a unique sleep, always past the budget
        hanging = self.wrapper('node-hangs', f'/bin/sleep {marker}\necho "{{}}"\n')
        with mock.patch('studio.native_run_config.local_environment', return_value=({'node': str(hanging)}, {})), \
                mock.patch.object(evidence, 'FINAL_CHECK_BUDGET_SECONDS', 1.0):
            started = time.monotonic()
            rows = evidence.final_review_verdicts(self.record, (self.review,) * 6, self.events)
        self.assertLess(time.monotonic() - started, 1.0 + evidence.KILL_GRACE_SECONDS)
        self.assertTrue(all(not row['accepted'] for row in rows))
        self.assertTrue(any('TimeoutExpired' in row['reason'] for row in rows))
        table = subprocess.run(['/bin/ps', '-axo', 'command='], capture_output=True, text=True, check=True).stdout
        self.assertNotIn(f'sleep {marker}', table)

    def wrapper(self, name: str, body: str) -> object:
        """A TEST stand-in for node: a shell script file (never a link to a real binary)."""
        path = self.dir / name
        path.write_text('#!/bin/sh\n' + body)
        path.chmod(0o700)
        return path

    def test_final_reviews_run_concurrently_inside_one_overall_budget(self) -> None:
        running, peak, lock = [0], [0], threading.Lock()

        def slow(record: dict, path: object, timeout: float, events: tuple) -> dict:
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            time.sleep(0.6 if str(path).endswith('slow') else 0.05)
            with lock:
                running[0] -= 1
            return {'file': str(path), 'accepted': True, 'timeout': timeout}
        files = tuple(self.dir / f'r{index}' for index in range(6)) + (self.dir / 'slow',)
        with mock.patch.object(evidence, 'final_review_verdict', side_effect=slow), \
                mock.patch.object(evidence, 'FINAL_CHECK_BUDGET_SECONDS', 0.3), \
                mock.patch.object(evidence, 'KILL_GRACE_SECONDS', 0.0):
            started = time.monotonic()
            rows = evidence.final_review_verdicts(self.record, files)
        self.assertLess(time.monotonic() - started, 0.6)
        self.assertEqual(peak[0], evidence.FINAL_CHECK_WORKERS)
        self.assertTrue(all(row['timeout'] <= 0.3 for row in rows[:6]))
        self.assertIn('not checked within', rows[-1]['reason'])


class ForecastSeamTests(unittest.TestCase):
    """The latest-safe render path is read from A5's forecast only, nested, and never swallowed."""

    def seam(self, **patch: object) -> dict:
        with mock.patch.object(forecast, 'latest_safe_launch', create=True, **patch):
            return forecast_path(batch_record(), 'A', 100.0)

    def test_unknown_until_the_forecast_exists(self) -> None:
        self.assertEqual(self.seam(new=None)['status'], 'unknown')

    def test_a5s_result_is_nested_as_its_path(self) -> None:
        result = self.seam(return_value=A5_PATH)
        self.assertEqual((result['status'], result['path']), ('forecast', A5_PATH))
        unknown = self.seam(return_value={**A5_PATH, 'status': 'duration-unknown', 'latestSafeStartElapsed': None})
        self.assertEqual((unknown['status'], unknown['path']['status']), ('forecast', 'duration-unknown'))

    def test_an_exception_is_a_named_forecast_defect(self) -> None:
        result = self.seam(side_effect=KeyError('clips'))
        self.assertEqual((result['status'], result['defect']), ('forecast-defect', "KeyError: 'clips'"))


if __name__ == '__main__':
    unittest.main()
