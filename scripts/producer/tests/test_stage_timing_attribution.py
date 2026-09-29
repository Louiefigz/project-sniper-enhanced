"""Handoff events and activity attribution: missing, replayed and nested evidence stays honest."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import *  # noqa: F401,F403
import stage_timing as st
from stage_timing_context import LINEAGE_VARIABLES
from stage_timing_report import summarize_timings
from test_stage_timing_v2 import SHA_A, SHA_B, _row

_HERMETIC = mock.patch.dict(os.environ)


def setUpModule() -> None:
    """Exported SNIPER_TIMING_* from the caller's shell must not change these results."""
    _HERMETIC.start()
    for name in LINEAGE_VARIABLES:
        os.environ.pop(name, None)


def tearDownModule() -> None:
    _HERMETIC.stop()


def _event(phase: str, ts: float, event_id: str | None = None, **fields: object) -> dict:
    """Construct one synthetic handoff event as another writer (host, dispatcher) would."""
    row = {**_row("", "handoff", ts, stage="clip_author", ts=ts), "handoffPhase": phase,
           "eventId": event_id or f"{phase}-{ts}", "taskId": "task-1"}
    epoch = {} if phase in ("dependencies-satisfied", "ready") else {"claimEpoch": 1}
    return {**row, **epoch, **fields}


def _span(span: str, start: float, end: float, activity: str | None) -> list[dict]:
    """One exact synthetic v2 span, optionally attributed to an activity category."""
    metadata = {"activity": activity} if activity else {}
    return [_row(span, "start", start, stage=span, metadata=metadata),
            _row(span, "end", end, stage=span, metadata=metadata, elapsedMs=(end - start) * 1000)]


LIFECYCLE = [_event("dependencies-satisfied", 0), _event("ready", 1), _event("claim-requested", 3),
             _event("host-accepted", 8, hostTurnId="turn-1"), _event("execution-started", 9),
             _event("artifact-published", 20, artifactSha256=SHA_A),
             _event("consumer-accepted", 26, artifactSha256=SHA_A, consumerId="clip-1-assembly"),
             _event("consumer-accepted", 30, artifactSha256=SHA_A, consumerId="clip-2-assembly"),
             _event("terminal-settlement", 31)]


class HandoffReportTests(unittest.TestCase):
    """Missing, replayed and reordered handoff events stay visible and never become zero."""

    def test_lifecycle_separates_each_phase_and_publication_delay(self) -> None:
        report = summarize_timings(LIFECYCLE)
        claim = report["handoffs"]["claims"][0]
        self.assertEqual(claim["gapsSeconds"]["ready→claim-requested"], 2)
        self.assertEqual(claim["gapsSeconds"]["claim-requested→host-accepted"], 5)
        self.assertEqual(claim["gapsSeconds"]["artifact-published→consumer-accepted"], 6)
        self.assertEqual(claim["unobservedPhases"], [])
        delays = [row["delaySeconds"] for row in report["handoffs"]["publications"][0]["acceptances"]]
        self.assertEqual(delays, [6, 10])
        category = report["attribution"]["categories"]["publicationToAcceptance"]
        self.assertEqual((category["unionSeconds"], category["summedSeconds"]), (10, 16))
        self.assertEqual(report["handoffs"]["issues"], [])

    def test_replayed_events_are_counted_once_and_first_observation_wins(self) -> None:
        replay = _event("artifact-published", 25, "replay", artifactSha256=SHA_A)
        replayed = [*LIFECYCLE[:6], LIFECYCLE[5], replay, _event("ready", 2, "r2"), *LIFECYCLE[6:], LIFECYCLE[-1]]
        report = summarize_timings(replayed)
        kinds = sorted(issue["kind"] for issue in report["handoffs"]["issues"])
        self.assertEqual(kinds, ["duplicate-handoff-event"] * 2 + ["replayed-handoff"])
        self.assertEqual(report["handoffs"]["publications"][0]["publishedAt"], 20)
        self.assertEqual(report["handoffs"]["claims"][0]["gapsSeconds"]["ready→claim-requested"], 1)

    def test_missing_events_leave_unknown_not_zero(self) -> None:
        rows = [_event("ready", 0, taskId="unclaimed"), _event("claim-requested", 1),
                _event("execution-started", 4), _event("artifact-published", 9, artifactSha256=SHA_A),
                _event("consumer-accepted", 12, artifactSha256=SHA_B)]
        report = summarize_timings(rows)
        claim, handoffs = report["handoffs"]["claims"][0], report["handoffs"]
        self.assertIsNone(claim["gapsSeconds"]["claim-requested→host-accepted"])
        self.assertIsNone(claim["gapsSeconds"]["host-accepted→execution-started"])
        self.assertIn("host-accepted", claim["unobservedPhases"])
        self.assertEqual(handoffs["publications"][0]["status"], "awaiting-acceptance")
        self.assertEqual([i["kind"] for i in handoffs["issues"]], ["acceptance-without-publication"])
        self.assertEqual([t["taskId"] for t in handoffs["readyWithoutObservedClaim"]], ["unclaimed"])
        category = report["attribution"]["categories"]["publicationToAcceptance"]
        self.assertEqual((category["status"], category["unionSeconds"], category["openIntervals"]),
                         ("unknown", None, 1))

    def test_reversed_clocks_stale_epochs_and_malformed_events_are_issues(self) -> None:
        rows = [_event("artifact-published", 10, artifactSha256=SHA_A, claimEpoch=2),
                _event("consumer-accepted", 8, artifactSha256=SHA_A, claimEpoch=2),
                _event("consumer-accepted", 11, "stale", artifactSha256=SHA_A),
                {**_event("host-accepted", 3), "claimEpoch": None},
                {**_event("ready", 1), "eventId": None}]
        report = summarize_timings(rows)
        kinds = sorted(issue["kind"] for issue in report["handoffs"]["issues"])
        self.assertEqual(kinds, ["acceptance-before-publication", "acceptance-without-publication",
                                 "handoff-missing-claim-epoch", "handoff-phase-order",
                                 "invalid-event-identity"])
        self.assertIsNone(report["handoffs"]["publications"][0]["acceptances"][0]["delaySeconds"])
        self.assertEqual(report["attribution"]["categories"]["publicationToAcceptance"]["status"], "unknown")

    def test_each_claim_epoch_keeps_its_own_timeline(self) -> None:
        rows = [_event("ready", 0), _event("claim-requested", 1), _event("terminal-settlement", 5),
                _event("ready", 6, "ready-again"), _event("claim-requested", 9, claimEpoch=2)]
        claims = summarize_timings(rows)["handoffs"]["claims"]
        self.assertEqual([c["claimEpoch"] for c in claims], [1, 2])
        self.assertEqual([c["gapsSeconds"]["ready→claim-requested"] for c in claims], [1, 3])


class ActivityAttributionTests(unittest.TestCase):
    """Categories are interval unions of explicit activity spans; absent means unknown."""

    def test_concurrent_agent_spans_never_add_up_to_wall_time(self) -> None:
        rows = [*_span("window", 0, 30, None)[:1], *_span("m1", 0, 10, "model"),
                *_span("m2", 5, 15, "model"), *_span("t1", 20, 22, "tool"),
                _row("m3", "start", 25, stage="m3", metadata={"activity": "model"}),
                {**_span("window", 0, 30, None)[1]}]
        rows[0]["stage"] = rows[-1]["stage"] = "production_total"
        for row in rows[1:-1]:
            row["parentSpanId"] = "window"
        report = summarize_timings(rows)
        categories = report["attribution"]["categories"]
        model = categories["modelExecution"]
        self.assertEqual((model["unionSeconds"], model["summedSeconds"]), (15, 20))
        self.assertEqual((model["intervals"], model["openIntervals"]), (2, 1))
        self.assertEqual(categories["toolExecution"]["unionSeconds"], 2)
        for name in ("hostSlotWaiting", "nativeQueueWaiting", "pressureWaiting"):
            self.assertEqual((categories[name]["status"], categories[name]["unionSeconds"]), ("unknown", None))
        self.assertEqual(report["attribution"]["categorizedUnionSeconds"], 17)
        self.assertEqual(report["recordedWindow"]["recordedSubstageSeconds"], 17)

    def test_nested_spans_are_neither_double_summed_nor_hidden_in_exclusive_time(self) -> None:
        rows = [*_span("tool", 0, 10, "tool"), *_span("queue", 2, 5, "native-queue-wait"),
                *_span("inner-tool", 6, 8, "tool")]
        rows[2]["parentSpanId"] = rows[3]["parentSpanId"] = "tool"
        rows[4]["parentSpanId"] = rows[5]["parentSpanId"] = "tool"
        categories = summarize_timings(rows)["attribution"]["categories"]
        tool, queue = categories["toolExecution"], categories["nativeQueueWaiting"]
        self.assertEqual((tool["unionSeconds"], tool["exclusiveSeconds"], tool["summedSeconds"]), (10, 7, 10))
        self.assertEqual((queue["unionSeconds"], queue["exclusiveSeconds"], queue["summedSeconds"]), (3, 3, 3))

    def test_exclusive_time_goes_to_the_innermost_category_and_sums_to_the_union(self) -> None:
        rows = [*_span("tool", 0, 10, "tool"), *_span("wait", 2, 8, "native-queue-wait"),
                *_span("inner-tool", 4, 6, "tool")]
        rows[2]["parentSpanId"] = rows[3]["parentSpanId"] = "tool"
        rows[4]["parentSpanId"] = rows[5]["parentSpanId"] = "wait"
        attribution = summarize_timings(rows)["attribution"]
        tool, wait = attribution["categories"]["toolExecution"], attribution["categories"]["nativeQueueWaiting"]
        self.assertEqual((tool["exclusiveSeconds"], wait["exclusiveSeconds"], tool["summedSeconds"]), (6, 4, 10))
        self.assertEqual((attribution["categorizedUnionSeconds"], attribution["concurrentOverlapSeconds"]), (10, 0))

    def test_unrelated_concurrent_categories_are_named_as_overlap(self) -> None:
        attribution = summarize_timings([*_span("m", 0, 10, "model"), *_span("t", 5, 15, "tool")])["attribution"]
        self.assertEqual((attribution["categorizedUnionSeconds"], attribution["concurrentOverlapSeconds"]), (15, 5))

    def test_only_completed_same_run_ancestors_hide_an_outermost_span(self) -> None:
        crashed = _row("parent", "start", 0, stage="parent", metadata={"activity": "tool"})
        child = _span("child", 2, 6, "tool")
        for row in child:
            row["parentSpanId"] = "parent"
        forged = _span("self", 10, 13, "tool")
        for row in forged:
            row["parentSpanId"] = "self"
        foreign_parent = [{**row, "runId": "other"} for row in _span("elsewhere", 20, 30, "tool")]
        guest = [{**row, "parentSpanId": "elsewhere"} for row in _span("guest", 22, 24, "tool")]
        tool = summarize_timings([crashed, *child, *forged, *foreign_parent, *guest])["attribution"][
            "categories"]["toolExecution"]
        self.assertEqual((tool["summedSeconds"], tool["openIntervals"]), (4 + 3 + 10 + 2, 1))

    def test_unknown_activity_is_not_recorded_or_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with st.stage_span(directory, "provider_call", {"activity": "thinking", "provider": "codex"}):
                pass
            rows = [json.loads(line) for line in Path(st.journal_path(directory)).read_text().splitlines()]
        self.assertEqual(rows[0]["metadata"], {"provider": "codex"})
        categories = summarize_timings(rows)["attribution"]["categories"]
        self.assertEqual(categories["modelExecution"]["status"], "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
