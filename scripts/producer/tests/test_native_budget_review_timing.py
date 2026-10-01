"""Plan critic time on the batch clock (P2-14, offline part): packets, early findings, the final record, lateness, tokens.

The trail rows are TEST events in the shapes ``studio.production.packets`` writes (the authority's own writer is
tested in ``test_production_packets``); records and tasks are in-memory TEST rows (``_status_fixture``). Nothing
here reads a live authority or a real host.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest

from _budget_fixture import host_turn
from _status_fixture import batch_record, enroll, observe, record_usage, run_task, usage
from studio.native_budget_review_timing import plan_review_timing

PACKET, OTHER, RECORD = 'a' * 64, 'b' * 64, 'c' * 64
BUDGET = {'kind': 'plan-critic', 'status': 'bounded', 'resolvedElapsed': 100.0, 'earlyBy': 520.0, 'hardBy': 700.0}


def resolved(elapsed: float, sha256: str = PACKET, **fields: object) -> dict:
    """A TEST plan-critic packet-resolved event of clip A; ``fields`` override or add (clipId, role, budget)."""
    return {'event': 'packet-resolved', 'clipId': 'A', 'role': 'plan-critic', 'packetSha256': sha256, 'elapsed': elapsed,
            **fields}


def early(index: int, elapsed: float, sha256: str = PACKET) -> dict:
    """A TEST review-early-findings event."""
    return {'event': 'review-early-findings', 'clipId': 'A', 'role': 'plan-critic', 'packetSha256': sha256,
            'issuesSha256': 'd' * 64, 'issues': index, 'index': index, 'elapsed': elapsed}


def submitted(elapsed: float, sha256: str = PACKET, **marks: object) -> dict:
    """A TEST plan-critic review-submitted event; ``marks`` are the authority's plan fields (none: an older engine)."""
    return {'event': 'review-submitted', 'clipId': 'A', 'role': 'plan-critic', 'recordSha256': RECORD,
            'elapsed': elapsed, **({'packetSha256': sha256, **marks} if marks else {})}


class PlanReviewTimingTests(unittest.TestCase):
    """One row per plan-critic packet of the output; other outputs, roles and packets never mix in."""

    def setUp(self) -> None:
        """A TEST batch observed at 900 s."""
        self.record = observe(batch_record(), 900.0)

    def test_plan_review_timing_from_events(self) -> None:
        """Resolution, budget, early findings and the final record of each packet, from the trail alone."""
        events = (resolved(100.0, budget=BUDGET), early(1, 300.0), resolved(120.0, OTHER, clipId='B', budget=BUDGET),
                  resolved(130.0, OTHER, role='motion-critic'), early(2, 450.5),
                  submitted(650.0, late=False, lateBasis='budget', hardBy=700.0), early(1, 310.0, OTHER))
        reviews = plan_review_timing(self.record, 'A', events)['reviews']
        self.assertEqual(len(reviews), 1)
        row = reviews[0]
        self.assertEqual((row['packetSha256'], row['resolvedElapsed'], row['budget']), (PACKET, 100.0, BUDGET))
        self.assertEqual([(item['index'], item['elapsed']) for item in row['earlyFindings']], [(1, 300.0), (2, 450.5)])
        self.assertEqual(row['resolutionToFirstEarlySeconds'], 200.0)
        self.assertEqual(row['final'], {'submittedElapsed': 650.0, 'recordSha256': RECORD, 'late': False,
                                        'lateBasis': 'budget', 'resolutionToFinalSeconds': 550.0})
        self.assertFalse(row['overdue'])
        self.assertEqual(plan_review_timing(self.record, 'B', events)['reviews'][0]['final'], None)

    def test_late_flag_from_budget(self) -> None:
        """The authority's late mark is shown as recorded; an unmarked event is late; hardBy passed unanswered is overdue."""
        marked = plan_review_timing(self.record, 'A', (resolved(100.0, budget=BUDGET),
                                                       submitted(700.5, late=True, lateBasis='budget', hardBy=700.0)))
        self.assertEqual((marked['reviews'][0]['final']['late'], marked['reviews'][0]['final']['lateBasis']), (True, 'budget'))
        unmarked = plan_review_timing(self.record, 'A', (resolved(100.0, budget=BUDGET), submitted(650.0)))
        self.assertEqual(unmarked['reviews'], [{**unmarked['reviews'][0], 'final': None}])  # unmarked names no packet
        for events, overdue in (((resolved(100.0, budget=BUDGET),), True),
                                ((resolved(100.0, budget={**BUDGET, 'hardBy': 950.0}),), False),
                                ((resolved(100.0),), False)):
            with self.subTest(events=events):
                row = plan_review_timing(self.record, 'A', events)['reviews'][0]
                self.assertEqual((row['overdue'], row['final'], row['resolutionToFirstEarlySeconds']), (overdue, None, None))
        unknown = plan_review_timing(self.record, 'A', (resolved(100.0), submitted(650.0, lateBasis='budget')))
        self.assertEqual((unknown['reviews'][0]['budget'], unknown['reviews'][0]['final']['late'],
                          unknown['reviews'][0]['final']['lateBasis']), (None, True, 'clock-unknown'))

    def test_overdue_boundary_and_the_latest_final(self) -> None:
        """At hardBy itself a packet is not yet overdue; of two final events naming it, the latest is its final."""
        for now, overdue in ((700.0, False), (700.001, True)):
            with self.subTest(now=now):
                row = plan_review_timing(observe(batch_record(), now), 'A', (resolved(100.0, budget=BUDGET),))
                self.assertEqual(row['reviews'][0]['overdue'], overdue)
        events = (resolved(100.0, budget=BUDGET), submitted(650.0, late=False, lateBasis='budget', hardBy=700.0),
                  submitted(720.0, late=True, lateBasis='budget', hardBy=700.0))
        final = plan_review_timing(self.record, 'A', events)['reviews'][0]['final']
        self.assertEqual((final['submittedElapsed'], final['late'], final['resolutionToFinalSeconds']), (720.0, True, 620.0))


class PlanReviewTokenTests(unittest.TestCase):
    """Tokens are the output's charged planReview tasks' own reports: exact, or unknown, never 0."""

    def setUp(self) -> None:
        """clip A's plan critic (no usage yet) and its author, both completed tasks with host turns."""
        self.record = batch_record()
        enroll(self.record)
        run_task(self.record, ('review-A', 'planReview', {}), host_turn('A'), (10.0, 400.0))
        run_task(self.record, ('author-A', 'author', {}), host_turn('author'), (10.0, 300.0))

    def test_missing_usage_is_unknown_not_zero(self) -> None:
        """No report leaves every total null with its reason; the author's report never counts as the critic's."""
        record_usage(self.record, 'author-A', usage(5000, 100, 50), 300.0)
        tokens = plan_review_timing(self.record, 'A', ())['tokens']
        self.assertEqual(tokens['executions'], 1)
        self.assertEqual(set(tokens['totals'].values()), {None})
        self.assertNotIn(0, tokens['totals'].values())
        self.assertEqual(plan_review_timing(self.record, 'B', ())['tokens']['unknownBecause'], ['no execution was observed'])
        record_usage(self.record, 'review-A', usage(1000, 800, 40), 400.0)
        exact = plan_review_timing(self.record, 'A', ())['tokens']['totals']
        self.assertEqual((exact['inputTokens'], exact['outputTokens']), (1000, 40))


if __name__ == '__main__':
    unittest.main()
