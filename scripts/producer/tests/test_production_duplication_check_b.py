"""C-2 and the decision lines after P1-RP5a (X217 m4, m6): one job never runs on two clocks, and owed lines are kept.

ChangeIntoAnotherJobTests (m4): ``change-approval`` refuses, by name, a change that makes a clip another clip's job,
current or in its lineage; nothing is written, and a clip may still return to its own earlier revision (M-162 keeps
revision semantics). DecisionLineGapTests (m6, the reviewer's K2 and K3): a draining batch still owes its decision
line, and overlap is read against the other clip's current approval. On the fixture's private root; no child process.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest
from unittest import mock

from _budget_fixture import CHANGE_REASON, approval
from test_native_budget_registry import ns
import test_production_add_clip_clock as add_clip_tests   # its AddClipCase and script(), never its tests
import native_batch
from studio.native_budget_store import BatchSession, TrailFull
from studio.production import api
from studio.production.approvals import ApprovalChange
from studio.production.tasks import TaskRefused


class ChangeIntoAnotherJobTests(add_clip_tests.AddClipCase):
    """m4: a rename of one clip into another clip's job is refused like an add of it."""

    def test_a_change_into_another_clips_job_is_refused_by_name(self) -> None:
        self.clock.advance(1200)
        self.add('C', approval('C'))
        authority = self.root / 'batches' / 'batch-auth' / 'authority.json'
        before = authority.read_bytes()
        with self.assertRaisesRegex(TaskRefused, '^' + add_clip_tests.SAME_JOB.format('A')):
            api.record_script_change(self.root, 'batch-auth', 'C', ApprovalChange(approval('A'), CHANGE_REASON))
        self.assertEqual(authority.read_bytes(), before)
        self.assertEqual(self.trail('approval-changed'), [])

    def test_a_clip_may_return_to_its_own_earlier_revision(self) -> None:
        api.record_script_change(self.root, 'batch-auth', 'A', ApprovalChange(approval('A', title='TEST renamed A'),
                                                                              CHANGE_REASON))
        back = api.record_script_change(self.root, 'batch-auth', 'A', ApprovalChange(approval('A'), CHANGE_REASON))
        self.assertEqual(back['changed'], ['title'])


class DecisionLineGapTests(add_clip_tests.AddClipCase):
    """m6: K2, a draining batch is not closed, so status still writes an owed line; K3, overlap is read against the
    other clip's current approval (D-P-4), not its first (``reviews/P1-RP5A-evidence/gaps_rp5a.py``)."""

    def test_status_writes_an_owed_line_on_a_draining_batch(self) -> None:
        original = BatchSession.event

        def event(session: BatchSession, value: dict) -> None:
            if value.get('event') == 'coordination-decision':
                raise TrailFull('Budget event trail is full: TEST')
            original(session, value)
        with mock.patch.object(BatchSession, 'event', event):
            self.add('T', approval('T', title='TEST trim of A', **add_clip_tests.script(12, 39, (50, 79))))
        self.clock.advance(2500)
        api.drain(self.root, 'batch-auth', 'TEST drain')
        self.assertEqual(native_batch.cmd_status(ns(batch='batch-auth'))['pendingDecisions'], [])
        self.assertEqual(len(self.trail('coordination-decision')), 1)

    def test_overlap_is_against_the_current_approval(self) -> None:
        api.record_script_change(self.root, 'batch-auth', 'A', ApprovalChange(
            approval('A', **add_clip_tests.script(500, 529)), CHANGE_REASON))
        added = self.add('T', approval('T', title='TEST trim of A', **add_clip_tests.script(12, 39, (50, 79))))
        self.assertIsNone(added['duplicationCheck'])

    def test_the_check_compares_with_the_other_clips_current_title(self) -> None:
        """Found while pinning K3: a row's identity is read against the other clip's current approval too."""
        api.record_script_change(self.root, 'batch-auth', 'A', ApprovalChange(approval('A', title='TEST renamed A'),
                                                                              CHANGE_REASON))
        added = self.add('T', approval('T', title='TEST title A', **add_clip_tests.script(12, 39, (50, 79))))
        self.assertEqual([(row['clip'], row['identity']['title']) for row in added['duplicationCheck']],
                         [('A', 'different')])


if __name__ == '__main__':
    unittest.main()
