"""Batch-clock review events (studio/production/packets.py): bounded, admitted by batch status, read back by hash.

Fixture: the authority test case (private root, fake batch clock, batch-auth with clips A and B).
"""
from __future__ import annotations

import json

from test_native_budget_authority import AuthorityCase
from _budget_fixture import CHANGE_REASON, approval
from studio.production.approvals import ApprovalChange  # P0 adapt: src takes one typed change (WAVES:186)
from studio import native_budget_store as store
from studio.native_budget_batches import archive_batch
from studio.native_budget_store import BudgetAuthorityError, locked_batch
from studio.production import api as authority
from studio.production.packets import (
    EVENT_BYTES, PACKET_EVENT, REVIEW_EVENT, ResolvedPacket, SubmittedReview, packet_resolution, record_packet_resolved,
    record_review_submitted, review_submission,
)

BATCH, SHA, RECORD = 'batch-auth', 'a' * 64, 'c' * 64
PACKET = ResolvedPacket(BATCH, 'A', 'plan-critic', SHA)


def submitted(elapsed: float, record: str = RECORD, packet: ResolvedPacket = PACKET) -> SubmittedReview:
    """A TEST submission of ``record`` answering ``packet`` at ``elapsed`` batch-clock seconds."""
    return SubmittedReview(packet, record, elapsed)


class PacketResolutionTests(AuthorityCase):
    """The event is the batch clock's record of a packet; it changes no record field and eats no settling room."""

    def test_the_resolution_is_recorded_on_the_batch_clock_and_read_back_by_hash(self) -> None:
        self.clock.advance(120)
        event = record_packet_resolved(self.root, PACKET)
        before = self.record()
        self.assertEqual((event['event'], event['elapsed'], event['clipId']), (PACKET_EVENT, 120.0, 'A'))
        self.assertLessEqual(len(store.canonical(event)), EVENT_BYTES)
        self.clock.advance(30)
        found = packet_resolution(self.root, BATCH, SHA)
        self.assertEqual((found['resolvedElapsed'], found['nowElapsed'], found['role']), (120.0, 150.0, 'plan-critic'))
        self.assertEqual(self.record()['production'], before['production'])  # no record field changed
        with self.assertRaisesRegex(BudgetAuthorityError, 'did not record the resolution'):
            packet_resolution(self.root, BATCH, 'b' * 64)

    def test_malformed_unknown_draining_or_closed_requests_are_refused(self) -> None:
        for packet, message in ((ResolvedPacket(BATCH, 'A', 'author', SHA), 'unknown packet role'),
                                (ResolvedPacket(BATCH, 'Z', 'plan-critic', SHA), 'not part of batch'),
                                (ResolvedPacket(BATCH, 'A', 'plan-critic', 'A' * 64), 'lowercase SHA-256')):
            with self.subTest(packet=packet), self.assertRaisesRegex(BudgetAuthorityError, message):
                record_packet_resolved(self.root, packet)
        self.clock.advance(2400)
        authority.drain(self.root, BATCH, 'TEST deadline passed')
        with self.assertRaisesRegex(BudgetAuthorityError, 'is draining; no new review packet is admitted'):
            record_packet_resolved(self.root, PACKET)
        self.mutate(BATCH, lambda record: record.update(status='closed', closedAtElapsed=5.0))
        with self.assertRaisesRegex(BudgetAuthorityError, 'is closed; no new review packet is admitted'):
            record_packet_resolved(self.root, PACKET)

    def test_a_trail_at_its_reserve_refuses_the_event_so_settlement_keeps_its_room(self) -> None:
        trail = self.root / 'batches' / BATCH / 'events.jsonl'
        room = store.MAX_EVENT_BYTES - store.TERMINAL_RESERVE_BYTES - trail.stat().st_size
        with trail.open('ab') as handle:
            handle.write((json.dumps({'event': 'TEST-filler', 'pad': 'x' * (room - 40)}) + '\n').encode())
        with self.assertRaisesRegex(BudgetAuthorityError, 'event trail is full'):
            record_packet_resolved(self.root, PACKET)
        with locked_batch(self.root, BATCH) as session:
            session.event({'event': 'task-completed', 'taskId': 'TEST'})  # settling events still write


class ReviewSubmittedTests(AuthorityCase):
    """review-submitted: the record's own bytes at the time it states, between resolution and now, once."""

    def setUp(self) -> None:
        super().setUp()
        self.clock.advance(100)
        record_packet_resolved(self.root, PACKET)
        self.clock.advance(50)

    def test_a_submission_is_recorded_once_at_its_stated_time_and_read_back_by_record_hash(self) -> None:
        event = record_review_submitted(self.root, submitted(140.25))
        self.assertEqual(event, {'event': REVIEW_EVENT, 'clipId': 'A', 'role': 'plan-critic', 'recordSha256': RECORD,
                                 'elapsed': 140.25})
        self.assertLessEqual(len(store.canonical(event)), EVENT_BYTES)
        self.assertEqual(record_review_submitted(self.root, submitted(140.25)), event)  # identical replay: no-op
        with self.assertRaisesRegex(BudgetAuthorityError, 'already recorded with other facts'):
            record_review_submitted(self.root, submitted(141.0))
        trail = (self.root / 'batches' / BATCH / 'events.jsonl').read_text()
        self.assertEqual(trail.count(REVIEW_EVENT), 1)
        self.assertEqual(review_submission(self.root, BATCH, RECORD),
                         {'clipId': 'A', 'role': 'plan-critic', 'recordSha256': RECORD, 'elapsed': 140.25})
        with self.assertRaisesRegex(BudgetAuthorityError, 'did not record the submission'):
            review_submission(self.root, BATCH, 'd' * 64)

    def test_a_time_outside_resolution_and_now_or_before_an_approval_change_is_refused(self) -> None:
        other = ResolvedPacket(BATCH, 'A', 'plan-critic', 'e' * 64)
        for review, message in ((submitted(99.0), 'is not between the packet resolution'),
                                (submitted(151.0), 'is not between the packet resolution'),
                                (submitted(120.0, packet=other), 'did not record the resolution'),
                                (submitted(120.0, packet=ResolvedPacket(BATCH, 'B', 'plan-critic', SHA)), 'another clip'),
                                (submitted(120.0, packet=ResolvedPacket(BATCH, 'A', 'clip-owner', SHA)), 'critic role')):
            with self.subTest(message=message), self.assertRaisesRegex(BudgetAuthorityError, message):
                record_review_submitted(self.root, review)
        authority.record_script_change(self.root, BATCH, 'A', ApprovalChange(approval('A', title='TEST operator changed title'), CHANGE_REASON))
        with self.assertRaisesRegex(BudgetAuthorityError, 'changed at 150.0 s, after this review was checked at 120.0 s'):
            record_review_submitted(self.root, submitted(120.0))

    def test_draining_records_a_submission_closed_refuses_it_and_both_still_read_back(self) -> None:
        self.clock.advance(2400)
        authority.drain(self.root, BATCH, 'TEST deadline passed')
        record_review_submitted(self.root, submitted(140.0))
        authority.close(self.root, BATCH)
        self.assertEqual(self.record()['status'], 'closed')
        with self.assertRaisesRegex(BudgetAuthorityError, 'is closed; no review submission is recorded'):
            record_review_submitted(self.root, submitted(145.0, record='d' * 64))
        archive_batch(self.root, BATCH, 'TEST archive after close')
        self.assertFalse((self.root / 'batches' / BATCH).exists())
        self.assertEqual(review_submission(self.root, BATCH, RECORD)['elapsed'], 140.0)
        self.assertEqual(packet_resolution(self.root, BATCH, SHA)['resolvedElapsed'], 100.0)


if __name__ == '__main__':
    import unittest
    unittest.main()
