"""Original production clocks govern queueing, launch charges and live media owners."""
from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from studio.native_run import NativeRun
from studio.native_run_lifecycle import bind_launch_allocation, monitor_limits
from studio.native_runtime import digest
from test_native_baseline_admission import NativeBaselineAdmissionTests


class ProductionAdmissionTests(unittest.TestCase):
    """Reuse the existing no-media owner fixture without duplicating its test suite."""

    def setUp(self) -> None:
        """Use a fixed boot and absolute clock; all children and telemetry are mocked."""
        self.fixture = NativeBaselineAdmissionTests('test_prior_receipt_is_not_overwritten_or_reused')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.enterContext(patch('studio.native_budget_clock.boot_id', return_value='fixture-boot'))
        self.continuous = self.enterContext(patch('studio.native_budget_clock.continuous_now', return_value=100))
        self.wall = self.enterContext(patch('studio.native_budget_clock.time.time', return_value=1000))
        self.fixture.snapshot = replace(self.fixture.snapshot, measured_at=1000)
        self.grant = {'boot': 'fixture-boot', 'continuousDeadline': 200, 'epochDeadline': 1100,
                      'grantedSeconds': 100, 'cleanupReserveSeconds': 10}
        self.charge = Mock(return_value=dict(self.grant))
        file = self.fixture.output / 'export-request.json'
        file.write_text('{"TEST": "no media"}')
        self.binding = {'request': str(file), 'requestSha256': digest(file), 'phase': 'segment-picture-0',
                        'output': self.fixture.settings.admission['output'], 'owner': 'a' * 32}
        self.charge.__self__ = SimpleNamespace(launch_binding=self.binding)
        settings = replace(self.fixture.settings, hard_deadline=self.grant, before_launch=self.charge,
                           additional_pins={str(file): digest(file)},
                           command=['TEST-NO-LAUNCH', str(file), 'segment-picture-0'])
        self.fixture.run = NativeRun('segment-picture-0', settings)

    def execute(self) -> tuple:
        """Run the actual owner lifecycle with the existing mock child/output writer."""
        return self.fixture.execute([self.fixture.snapshot])

    def test_expired_allocation_does_not_charge_or_enter_pool(self) -> None:
        """A queue cannot reset the original production clock or spend a launch."""
        self.continuous.return_value = 191
        success, read, launch = self.execute()
        self.assertFalse(success)
        self.charge.assert_not_called()
        self.fixture.acquire.assert_not_called()
        read.assert_not_called()
        launch.assert_not_called()
        self.assertEqual(self.fixture.receipt()['failureCategory'], 'budget-exhausted')

    def test_expiry_after_admission_prevents_charge_and_launch(self) -> None:
        """Time spent validating pins and preparing files never buys another grant."""
        owner = self.fixture.run
        original = owner.launch
        def expire() -> None:
            """Advance time only after the real admission and preparation finish."""
            self.continuous.return_value = 191
            original()
        with patch.object(owner, 'launch', side_effect=expire):
            success, _read, launch = self.execute()
        self.assertFalse(success)
        self.fixture.acquire.assert_called_once()
        self.charge.assert_not_called()
        launch.assert_not_called()
        self.assertTrue(self.fixture.receipt()['cleanup']['verified'])

    def test_charge_occurs_with_lease_and_is_persisted_before_child(self) -> None:
        """Actual post-pool launch intent is durable before invoking Popen."""
        def charged() -> dict:
            """Observe the boundary rather than merely counting the callback."""
            self.assertIs(self.fixture.run.lease, self.fixture.lease)
            self.assertTrue(self.fixture.receipt()['productionLaunchReservationStarted'])
            return dict(self.grant)
        self.charge.side_effect = charged
        success, _read, launch = self.execute()
        self.assertTrue(success, self.fixture.run.result.get('abortReason'))
        self.charge.assert_called_once()
        launch.assert_called_once()
        self.assertTrue(self.fixture.receipt()['productionLaunchReserved'])
        self.assertLessEqual(self.fixture.run.deadline, 91)

    def test_extended_grant_refuses_child_and_cannot_charge_twice(self) -> None:
        """Even a faulty adapter cannot extend time or retry its charge callback."""
        self.charge.return_value['continuousDeadline'] += 1
        success, _read, launch = self.execute()
        self.assertFalse(success)
        launch.assert_not_called()
        self.fixture.run.lease = self.fixture.lease
        with self.assertRaisesRegex(RuntimeError, 'uncharged owner'):
            bind_launch_allocation(self.fixture.run)
        self.charge.assert_called_once()

    def test_wall_rollback_cannot_extend_live_media(self) -> None:
        """Continuous expiry stops the owner even if wall time moves backward."""
        self.wall.return_value = 950
        self.continuous.return_value = 191
        self.assertTrue(monitor_limits(self.fixture.run))
        self.assertEqual(self.fixture.run.result['failureCategory'], 'budget-exhausted')

    def test_new_boot_refuses_launch(self) -> None:
        """An inherited allocation is never restarted on a different host boot."""
        with patch('studio.native_budget_clock.boot_id', return_value='next-boot'):
            success, _read, launch = self.execute()
        self.assertFalse(success)
        launch.assert_not_called()
        self.charge.assert_not_called()

    def test_borrowed_section_callback_cannot_charge_or_launch(self) -> None:
        """A valid allocation for A does not admit B's child under A's debit."""
        self.binding['phase'] = 'segment-picture-1'
        success, _read, launch = self.execute()
        self.assertFalse(success)
        self.charge.assert_not_called()
        launch.assert_not_called()
        self.assertIn('another section', self.fixture.run.result['abortReason'])

    def test_mutating_owner_allocation_cannot_extend_grant(self) -> None:
        """Compare a callback's grant against values frozen before the callback."""
        def tamper() -> dict:
            """Attempt to alter the comparison baseline in place."""
            self.fixture.run.hard_deadline['continuousDeadline'] += 1
            return dict(self.fixture.run.hard_deadline)
        self.charge.side_effect = tamper
        success, _read, launch = self.execute()
        self.assertFalse(success)
        launch.assert_not_called()
        self.assertIn('cannot extend', self.fixture.run.result['abortReason'])

    def test_slow_callback_cannot_launch_after_stage_deadline(self) -> None:
        """A valid production grant does not replace the shorter independent stage clock."""
        def slow() -> dict:
            """Simulate elapsed stage time after initial launch checks have passed."""
            self.fixture.run.started -= 601
            return dict(self.grant)
        self.charge.side_effect = slow
        success, _read, launch = self.execute()
        self.assertFalse(success)
        launch.assert_not_called()
        self.assertIn('Independent render-only deadline', self.fixture.run.result['abortReason'])
