"""A pool mix refusal is waitable: before any stage it relaunches without the clip's one transient retry (M-058).

Real launch admission and outcome recording on a TEST batch record in memory; the process table, the
supervisor identity and the host identity are TEST values, so no process is started and no host record is read.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest
from unittest import mock

from _budget_fixture import FakeClock, approval, fake_clock
from _native_pool_fixture import TEST_HOST
from studio.native_budget_clock import start_anchor
from studio.native_budget_family_reservation import validate_invocation
from studio.native_budget_launch import TRANSIENT, WAITABLE, LaunchRequest, admit_launch, record_outcome
from studio.native_budget_policy import BatchSpec, new_batch_record
from studio.native_budget_registry import BudgetRefused
from studio.native_segments.long_plan import identity

SUPERVISOR = {'pid': 7001, 'pgid': 7001, 'started': 'TEST supervisor'}
SUCCESS = ('native-short-checked-for-review',)
MIX = 'pool-unsupported-mix'
SCOPE = {'sectionId': 'section-1', 'generation': 1}


def family_case(category: str) -> tuple[dict, dict, dict]:
    """(clip, family, settings): a synthetic Long family whose section-1 child failed with ``category``."""
    row = {'sectionId': 'section-1', 'status': 'failed', 'failure': {'category': category},
           'planSha256': 'a' * 64, 'scopeSha256': identity(SCOPE), 'output': '/TEST/child-1'}
    family = {'state': 'awaiting-sections', 'invocations': [row]}
    clip = {'sectionFamilies': [family], 'counters': {'transientRetry': 0},
            'output': {'format': 'long', 'policy': {'limits': {'transientRetry': 1}}}}
    settings = {'options': {'sectionId': 'section-1', 'snapshotScope': SCOPE}, 'output': '/TEST/child-2',
                'longOutput': {'planSha256': 'a' * 64}, 'repair': None}
    return clip, family, settings


class MixTransientTests(unittest.TestCase):
    """The same-identity relaunch after a mix refusal, against the clip's shared transient retry."""

    def setUp(self) -> None:
        """TEST supervisor, process table and host identity; a fresh one-Short batch."""
        for target, value in (('studio.native_budget_launch.own_identity', dict(SUPERVISOR)),
                              ('studio.native_budget_launch._process_table', {7001: (1, 7001, 'TEST supervisor')}),
                              ('native_work_pool_policy.host_identity', dict(TEST_HOST))):
            self.enterContext(mock.patch(target, return_value=value))
        self.reset()

    def reset(self) -> None:
        """A fresh one-Short TEST batch record (held in memory only)."""
        with fake_clock(FakeClock()):
            self.record = new_batch_record(BatchSpec('batch-mix', ('A',), (), 1, approvals={'A': approval('A')}),
                                           start_anchor())
        self.clip = self.record['clips']['A']

    def launch(self, route: str = 'draft') -> LaunchRequest:
        """The same TEST identity every time: an unchanged relaunch."""
        return LaunchRequest('A', route, 'd' * 64, ('/TEST/project', '/TEST/output'), 45.0)

    def fail(self, route: str, failure: tuple[str, list], at: float) -> dict:
        """Admit one launch at ``at`` and record its failure: failure = (category, stages that ran)."""
        decision = admit_launch(self.record, self.launch(route), at)
        self.assertTrue(decision.allowed, decision.reason)
        outcome = {'status': 'failed', 'successStatuses': SUCCESS, 'failureCategory': failure[0],
                   'stages': failure[1], 'errorType': 'TEST', 'error': f'TEST {failure[0]}'}
        return record_outcome(self.record, {'clipId': 'A', 'attemptId': decision.detail['attempt']['id']},
                              outcome, at + 5.0)

    def test_mix_refusal_before_any_stage_relaunches_without_using_the_retry(self) -> None:
        """No stage ran: the relaunch is fresh, the launch counter is charged, the transient retry is not."""
        self.fail('draft', (MIX, []), 10.0)
        decision = admit_launch(self.record, self.launch(), 30.0)
        self.assertTrue(decision.allowed, decision.reason)
        self.assertIsNone(decision.detail['attempt']['transientRetryOf'])
        self.assertEqual((self.clip['counters']['exportAttempt'], self.clip['counters']['transientRetry']), (2, 0))

    def test_mix_refusal_after_a_stage_uses_the_shared_retry(self) -> None:
        """A stage ran: the relaunch is the clip's one transient retry."""
        first = self.fail('draft', (MIX, ['capture']), 10.0)
        decision = admit_launch(self.record, self.launch(), 30.0)
        self.assertTrue(decision.allowed, decision.reason)
        self.assertEqual(decision.detail['attempt']['transientRetryOf'], first['id'])
        self.assertEqual((self.clip['counters']['exportAttempt'], self.clip['counters']['transientRetry']), (2, 1))

    def test_second_transient_retry_is_refused_by_name(self) -> None:
        """Once the draft used the retry, the preview's staged mix failure cannot take a second one."""
        self.fail('draft', ('capacity-timeout', []), 10.0)
        self.assertTrue(admit_launch(self.record, self.launch(), 30.0).allowed)
        self.fail('preview', (MIX, ['capture']), 40.0)
        decision = admit_launch(self.record, self.launch('preview'), 60.0)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, 'The clip already used its one transient-failure retry')
        self.assertEqual((self.clip['counters']['previewLaunch'], self.clip['counters']['transientRetry']), (1, 1))

    def test_mix_refusal_before_any_stage_needs_no_retry_after_it_is_used(self) -> None:
        """The waitable relaunch never depends on the shared retry still being available."""
        self.fail('draft', ('capacity-timeout', []), 10.0)
        self.assertTrue(admit_launch(self.record, self.launch(), 30.0).allowed)
        self.fail('preview', (MIX, []), 40.0)
        decision = admit_launch(self.record, self.launch('preview'), 60.0)
        self.assertTrue(decision.allowed, decision.reason)
        self.assertEqual((self.clip['counters']['previewLaunch'], self.clip['counters']['transientRetry']), (2, 1))

    def test_family_section_reinvocation_after_mix_refusal(self) -> None:
        """A section child refused for a mix may be invoked again; a deterministic failure may not."""
        self.assertIsNone(validate_invocation(*family_case(MIX)))
        with self.assertRaisesRegex(BudgetRefused, 'failed deterministically'):
            validate_invocation(*family_case('renderer-failure'))

    def test_capacity_credit_unavailable_is_transient_and_regressed_is_not(self) -> None:
        """An unreadable credit can clear, so it takes the retry; a rolled-back credit is deterministic."""
        self.assertLessEqual(WAITABLE, TRANSIENT)
        self.assertEqual((('capacity-credit-unavailable' in TRANSIENT), ('capacity-credit-regressed' in TRANSIENT)),
                         (True, False))
        for category, allowed in (('capacity-credit-unavailable', True), ('capacity-credit-regressed', False)):
            self.reset()
            self.fail('draft', (category, ['capture']), 10.0)
            decision = admit_launch(self.record, self.launch(), 30.0)
            with self.subTest(category=category):
                self.assertEqual(decision.allowed, allowed, decision.reason)
                self.assertEqual(self.clip['counters']['transientRetry'], int(allowed))


if __name__ == '__main__':
    unittest.main()
