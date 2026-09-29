"""The named credit aborts reach the receipt, the watchdog and the retry rule (P1 B10; X143 M1, m1, m2, m5).

The owner's monitor stops by name at once. The export watchdog is the backstop: it names the stop only after
``DEADLINE_GRACE_SECONDS`` of its own, on its graceful path (SIGTERM and the cleanup grace), never by an exception
that goes straight to the group kill. The category survives the owner's publication, whatever the clip id says, and
on the admission path too. A published ``capacity-credit-unavailable`` gets the one transient retry (L-J J1) and a
``capacity-credit-regressed`` never does. Private TEST authority roots only; nothing signals or starts a child
(``process_group`` is mocked wherever the watchdog would act).
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import signal
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from _queue_credit_fixture import TORN, CreditCase
from studio import native_budget_launch as launch
from studio.native_budget_launch import LaunchRequest
from studio.native_run import NativeRun
from studio.native_run_lifecycle import failure_category, monitor_limits, require_production_time
from studio.production import process, process_group, process_watch, queue_credit
from studio.production.queue_credit import CapacityCreditRegressed, CapacityCreditUnavailable

GRACE = process.DEADLINE_GRACE_SECONDS
TOLERANCE = queue_credit.CREDIT_READ_TOLERANCE_SECONDS


class WatchCase(CreditCase):
    """The grant bound to Short A as the watchdog's deadline, with no task; credit 30 read by the watchdog at 0."""

    def setUp(self) -> None:
        """Read 30 s of credit once, as the watchdog's first poll does."""
        super().setUp()
        directory = self.root / 'watch'
        directory.mkdir()
        self.watch = process_watch.ExportWatch(None, directory, self.grant, time.monotonic(), time.time())
        self.stops = SimpleNamespace(reason=None)
        self.put(self.credit_record(30.0))
        self.assertIsNone(process_watch._reason(self.watch, self.stops))

    def reason(self, now: float) -> tuple[str, str] | None:
        """The watchdog's answer at monotonic time ``now``."""
        self.now = now
        return process_watch._reason(self.watch, self.stops)


class WatchdogBackstopTests(WatchCase):
    """``process_watch._reason`` and ``_supervised_end`` on a named credit error."""

    def test_a_regression_is_named_by_the_watchdog_only_after_the_grace(self) -> None:
        """First seen at 1: no stop through 1 + grace, then the named reason, also with a published grant."""
        self.put(self.credit_record(20.0))
        for now in (1.0, 8.0, 1.0 + GRACE):
            self.assertIsNone(self.reason(now))
        category, detail = self.reason(1.5 + GRACE)
        self.assertEqual(category, 'capacity-credit-regressed')
        self.assertIn('went down from 30.0s to 20.0s', detail)
        (self.watch.directory / process.GRANT).write_text(json.dumps(self.grant))
        self.assertEqual(self.reason(2.0 + GRACE)[0], 'capacity-credit-regressed')

    def test_an_unavailable_authority_is_named_by_the_watchdog_after_the_tolerance_and_the_grace(self) -> None:
        """Unreadable from 1: held through 1 + tolerance, an error from then, named only past a further grace."""
        self.path.write_bytes(TORN)
        for now in (1.0, 1.0 + TOLERANCE, 1.5 + TOLERANCE, 1.0 + TOLERANCE + GRACE):
            self.assertIsNone(self.reason(now))
        category, detail = self.reason(1.5 + TOLERANCE + GRACE)
        self.assertEqual(category, 'capacity-credit-unavailable')
        self.assertIn('Short A capacity credit has been unreadable for', detail)

    def test_a_good_read_restarts_the_watchdogs_grace(self) -> None:
        """A regression seen at 1, the record back at 30 by 5 (a good read), a new drop at 10: the watchdog names it
        only a grace after 10, never on the first sight's clock."""
        self.put(self.credit_record(20.0))
        self.assertIsNone(self.reason(1.0))
        self.put(self.credit_record(30.0))
        self.assertIsNone(self.reason(5.0))
        self.put(self.credit_record(25.0))
        for now in (10.0, 10.0 + GRACE):
            self.assertIsNone(self.reason(now))
        self.assertEqual(self.reason(10.5 + GRACE)[0], 'capacity-credit-regressed')

    def test_a_stuck_owner_is_stopped_gracefully_and_only_after_the_grace(self) -> None:
        """The child never exits: the watchdog terminates it (SIGTERM path) once the grace is over, and only then
        ends its group; the reason is named."""
        self.put(self.credit_record(20.0))
        calls, ending = self.supervise(exits_at=None)
        self.assertEqual(ending.reason[0], 'capacity-credit-regressed')
        self.assertEqual([name for name, _ in calls], ['terminate', 'end_group'])
        self.assertTrue(all(now > 1.0 + GRACE for _, now in calls), calls)

    def test_an_owner_that_stops_by_name_within_the_grace_is_never_stopped_by_the_watchdog(self) -> None:
        """The owner exits (named abort published) at 6: no terminate, and the watchdog reports no reason."""
        self.put(self.credit_record(20.0))
        calls, ending = self.supervise(exits_at=6.0)
        self.assertIsNone(ending.reason)
        self.assertEqual([name for name, _ in calls], ['end_group'])

    def supervise(self, exits_at: float | None) -> tuple[list, object]:
        """Run ``_supervised_end`` from monotonic 0 with one poll a second; every signalling call is mocked."""
        calls: list[tuple[str, float]] = []

        def poll(_timeout: float) -> None:
            """One watchdog poll interval."""
            self.now += 1.0

        relay = SimpleNamespace(pump=poll, drain=lambda: None)
        with mock.patch.object(process_watch, 'OutputRelay', return_value=relay), \
                mock.patch.object(process_group, 'exited', side_effect=lambda _pid: exits_at is not None
                                  and self.now >= exits_at), \
                mock.patch.object(process_group, 'terminate', side_effect=lambda *_: calls.append(('terminate',
                                                                                                    self.now))), \
                mock.patch.object(process_group, 'end_group', side_effect=lambda *_: calls.append(('end_group',
                                                                                                   self.now)) or []):
            ending = process_watch._supervised_end(SimpleNamespace(pid=2 ** 22 + 1), self.watch, self.stops)
        return calls, ending


class NamedCategoryTests(CreditCase):
    """The owner's published category and the retry decision it leads to."""

    def aborted_owner(self, error: type) -> SimpleNamespace:
        """An owner whose monitor stopped on ``error``: 30 read at 0, then a regression or an unreadable record."""
        self.put(self.credit_record(30.0))
        self.assertEqual(self.delta(), 30.0)
        if error is CapacityCreditRegressed:
            self.put(self.credit_record(20.0))
            self.now = 1.0
        else:
            self.path.write_bytes(TORN)
            self.now = 1.0
            self.delta()
            self.now = 1.5 + TOLERANCE
        owner = self.owner()
        self.assertTrue(monitor_limits(owner))
        return owner

    def test_the_receipt_keeps_the_category_through_the_watchdogs_sigterm(self) -> None:
        """A later SIGTERM keeps the owner's abort reason, and publication keeps the named category."""
        for error, category in ((CapacityCreditRegressed, 'capacity-credit-regressed'),
                                (CapacityCreditUnavailable, 'capacity-credit-unavailable')):
            with self.subTest(category):
                queue_credit._CREDIT.clear()
                self.now = 0.0
                owner = self.aborted_owner(error)
                reason = owner.abort_reason
                NativeRun.request_abort(owner, signal.SIGTERM, None)
                self.assertEqual(owner.abort_reason, reason)
                result = {'status': 'failed', 'cleanup': {'verified': True}, 'abortReason': owner.abort_reason,
                          'failureCategory': owner.result['failureCategory']}
                self.assertEqual(failure_category(result), category)

    def test_a_clip_id_naming_a_signal_cannot_rename_a_credit_category(self) -> None:
        """m1: the credit categories are read before the abort-text heuristics; other categories keep them."""
        for text in ('Short signal-2 capacity credit went down from 30.0s to 20.0s', 'KeyboardInterrupt-3 short'):
            for category in queue_credit.CREDIT_CATEGORIES:
                result = {'status': 'failed', 'cleanup': {'verified': True}, 'abortReason': text,
                          'failureCategory': category}
                self.assertEqual(failure_category(result), category)
        result = {'status': 'failed', 'cleanup': {'verified': True}, 'abortReason': 'supervisor received SIGTERM',
                  'failureCategory': 'budget-exhausted'}
        self.assertEqual(failure_category(result), 'cancelled')

    def test_the_admission_path_records_the_category_before_it_propagates(self) -> None:
        """m2: ``require_production_time`` raises (admission refuses) with the category already on the owner, and
        the published receipt keeps it under the executor's text abort reason."""
        self.put(self.credit_record(30.0))
        self.assertEqual(self.delta(), 30.0)
        self.put(self.credit_record(20.0))
        self.now = 1.0
        owner = self.owner()
        with self.assertRaises(CapacityCreditRegressed) as caught:
            require_production_time(owner)
        self.assertEqual(owner.result['failureCategory'], 'capacity-credit-regressed')
        result = {'status': 'failed', 'cleanup': {'verified': True, 'childNeverLaunched': True},
                  'abortReason': f'{type(caught.exception).__name__}: {caught.exception}',
                  'failureCategory': owner.result['failureCategory']}
        self.assertEqual(failure_category(result), 'capacity-credit-regressed')

    def test_a_published_unavailable_is_retried_once_and_a_regression_never(self) -> None:
        """m5 (J1 + OQ-1 end to end): the category the owner publishes, and the one the watchdog closes a launch
        with, decide the retry: unavailable is TRANSIENT (J1), regressed is an unchanged deterministic failure."""
        for error, retried in ((CapacityCreditUnavailable, True), (CapacityCreditRegressed, False)):
            with self.subTest(error.__name__):
                queue_credit._CREDIT.clear()
                self.now = 0.0
                owner = self.aborted_owner(error)
                published = failure_category({'status': 'failed', 'cleanup': {'verified': True},
                                              'abortReason': owner.abort_reason,
                                              'failureCategory': owner.result['failureCategory']})
                watchdog = queue_credit.watchdog_stop(error('TEST', since=-GRACE - 1.0))[0]
                self.assert_retry(published, retried)
                self.assert_retry(watchdog, retried)

    def assert_retry(self, category: str, retried: bool) -> None:
        """A launch that failed under ``category``: the same launch again gets the one transient retry, or not."""
        clip = {'counters': {'transientRetry': 0},
                'attempts': [{'id': 'a1', 'route': 'draft', 'status': 'failed', 'identity': 'TEST-id',
                              'failure': {'category': category, 'signature': 'TEST'}}]}
        request = LaunchRequest('A', 'draft', 'TEST-id', ('/TEST/project', '/TEST/output'), 60.0)
        decision = launch._retry_decision(clip, request)
        self.assertEqual(decision.allowed, retried, (category, decision.reason))


if __name__ == '__main__':
    unittest.main()
