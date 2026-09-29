"""Exact nested/concurrent timing identity; no claims about editorial approval."""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import *  # noqa: F401,F403
import stage_timing as st
from stage_timing_context import LINEAGE_VARIABLES, lineage_environment, task_scope, timing_context
from stage_timing_report import summarize_timings

SHA_A, SHA_B = "a" * 64, "b" * 64
_HERMETIC = mock.patch.dict(os.environ)


def setUpModule() -> None:
    """Exported SNIPER_TIMING_* from the caller's shell must not change these results."""
    _HERMETIC.start()
    for name in LINEAGE_VARIABLES:
        os.environ.pop(name, None)


def tearDownModule() -> None:
    _HERMETIC.stop()


def _row(span: str, event: str, mono: float, **fields: object) -> dict:
    """Construct a complete synthetic v2 event for reader contract tests."""
    return {"schemaVersion": 2, "stage": "critic_plan", "event": event,
            "mono": mono, "ts": mono + 1000, "runId": "run", "attemptId": "a1",
            "attemptNo": 1, "writerId": "writer", "writerPid": 1,
            "clock": "process-monotonic", "spanId": span,
            "status": "completed", **fields}


class HandoffWriterTests(unittest.TestCase):
    """Real writers bind task lineage and refuse incomplete events before writing."""

    def test_handoff_rows_carry_task_claim_and_host_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with task_scope("task-a", 2, "turn-1"), st.stage_span(directory, "author"):
                result = st.record_handoff(directory, st.HandoffEvent("author", "artifact-published", SHA_A))
            rows = [json.loads(line) for line in Path(st.journal_path(directory)).read_text().splitlines()]
        self.assertTrue(result["recorded"])
        row = result["row"]
        self.assertEqual(rows[1], row)
        self.assertEqual((row["taskId"], row["claimEpoch"], row["hostTurnId"]), ("task-a", 2, "turn-1"))
        self.assertEqual(row["parentSpanId"], rows[0]["spanId"])
        self.assertTrue(all(r["taskId"] == "task-a" for r in rows))
        self.assertNotIn("taskId", timing_context(), "the scope ends with its block")

    def test_incomplete_handoffs_are_refused_without_writing_or_raising(self) -> None:
        cases = ((None, st.HandoffEvent("x", "ready"), "handoff-missing-task"),
                 (("t",), st.HandoffEvent("x", "host-accepted"), "handoff-missing-claim-epoch"),
                 (("t", 1), st.HandoffEvent("x", "artifact-published"), "handoff-missing-artifact"),
                 (("t", 1), st.HandoffEvent("x", "published"), "unknown-handoff-phase"),
                 (("t", 1), st.HandoffEvent("x", "artifact-published", SHA_A, "c"), "handoff-invalid-consumer"),
                 (("t", 1), st.HandoffEvent("", "ready"), "invalid-stage-label"))
        with tempfile.TemporaryDirectory() as directory:
            for scope, event, reason in cases:
                with self.subTest(reason=reason), task_scope(*scope) if scope else contextlib.nullcontext():
                    self.assertEqual(st.record_handoff(directory, event), {"recorded": False, "reason": reason})
            self.assertFalse(Path(st.journal_path(directory)).exists())
            with task_scope("t"):
                unwritable = st.record_handoff(str(Path(directory) / "missing"), st.HandoffEvent("x", "ready"))
        self.assertEqual(unwritable, {"recorded": False, "reason": st.JOURNAL_UNWRITABLE})

    def test_a_malformed_handoff_inside_a_timed_stage_never_fails_the_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with st.stage_span(directory, "author"):
                refused = st.record_handoff(directory, st.HandoffEvent("author", "artifact-published"))
                value = 42  # the measured work continues after the refused handoff
            rows = [json.loads(line) for line in Path(st.journal_path(directory)).read_text().splitlines()]
        self.assertEqual(value, 42)
        self.assertEqual(refused, {"recorded": False, "reason": "handoff-missing-task"})
        self.assertEqual([(r["event"], r.get("status")) for r in rows], [("start", None), ("end", "completed")])

    def test_malformed_task_lineage_is_named_never_raised(self) -> None:
        bad = {"SNIPER_TIMING_TASK_ID": "bad id", "SNIPER_TIMING_CLAIM_EPOCH": "-1"}
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, bad):
            with st.stage_span(directory, "root"):
                pass
            with task_scope("good-task"):
                self.assertNotIn("lineageRejected", timing_context())
            with task_scope("bad id", 3, "turn"), st.stage_span(directory, "scoped"):
                value = 7
            rows = [json.loads(line) for line in Path(st.journal_path(directory)).read_text().splitlines()]
        self.assertEqual(value, 7, "timing never fails the work it measures")
        self.assertEqual(rows[0]["lineageRejected"], ["taskId", "claimEpoch"])
        self.assertEqual(rows[2]["lineageRejected"], ["taskId", "claimEpoch", "hostTurnId"])
        self.assertFalse({"taskId", "claimEpoch", "hostTurnId"} & (set(rows[0]) | set(rows[2])))
        self.assertEqual(summarize_timings(rows)["lineageRejectedSpans"], 2)

    def test_claim_epoch_or_host_turn_without_a_task_is_rejected_not_forwarded(self) -> None:
        partial = {"SNIPER_TIMING_RUN_ID": "run-p", "SNIPER_TIMING_CLAIM_EPOCH": "3",
                   "SNIPER_TIMING_HOST_TURN_ID": "turn-3"}
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, partial):
            with st.stage_span(directory, "root"):
                forwarded = lineage_environment()
            row = json.loads(Path(st.journal_path(directory)).read_text().splitlines()[0])
        self.assertEqual(row["lineageRejected"], ["claimEpoch", "hostTurnId"])
        self.assertEqual(row["runId"], "run-p")
        self.assertNotIn("SNIPER_TIMING_CLAIM_EPOCH", forwarded)
        self.assertNotIn("SNIPER_TIMING_HOST_TURN_ID", forwarded)


class TimingWriterV2Tests(unittest.TestCase):
    """Real writers preserve lineage and never leak content or swallow errors."""

    def test_nested_identity_and_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"SNIPER_TIMING_RUN_ID": "r",
                                              "SNIPER_TIMING_ATTEMPT_ID": "a2",
                                              "SNIPER_TIMING_ATTEMPT_NO": "2"}):
                with st.stage_span(directory, "root"):
                    with self.assertRaisesRegex(RuntimeError, "never log"):
                        with st.stage_span(directory, "child", {"packetBytes": 10,
                                                                 "prompt": "private"}):
                            raise RuntimeError("never log this message")
            text = Path(st.journal_path(directory)).read_text()
        rows = [json.loads(line) for line in text.splitlines()]
        self.assertEqual(rows[1]["parentSpanId"], rows[0]["spanId"])
        self.assertEqual(rows[2]["status"], "failed")
        self.assertEqual(rows[3]["status"], "completed")
        self.assertTrue(all(r["attemptId"] == "a2" and r["attemptNo"] == 2 for r in rows))
        self.assertNotIn("private", text)
        self.assertNotIn("never log", text)
        report = summarize_timings(rows)
        self.assertTrue(report["allRecordedSpansPaired"])
        self.assertEqual(len(report["spans"]), 2)

    def test_wall_clock_regression_does_not_change_elapsed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(st.time, "time", side_effect=[1000.0, 900.0]):
                with mock.patch.object(st.time, "monotonic", side_effect=[10.0, 12.0]):
                    with st.stage_span(directory, "root"):
                        pass
            rows = [json.loads(line) for line in Path(st.journal_path(directory)).read_text().splitlines()]
        self.assertEqual(summarize_timings(rows)["stagesInclusiveMs"], {"root": 2000})

    def test_interrupt_writes_terminal_status_and_propagates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(KeyboardInterrupt):
                with st.stage_span(directory, "root"):
                    raise KeyboardInterrupt()
            rows = [json.loads(line) for line in Path(st.journal_path(directory)).read_text().splitlines()]
        self.assertEqual(rows[-1]["status"], "interrupted")

    def test_system_exit_is_not_always_an_interruption(self) -> None:
        for code, status in ((None, "completed"), (0, "completed"),
                             (1, "failed"), ("failure", "failed")):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(SystemExit) as caught:
                    with st.stage_span(directory, "root"):
                        raise SystemExit(code)
                self.assertEqual(caught.exception.code, code)
                rows = [json.loads(line) for line in Path(st.journal_path(directory)).read_text().splitlines()]
                self.assertEqual(rows[-1]["status"], status)

    def test_bad_metadata_and_unwritable_journal_do_not_change_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with st.stage_span(directory, "root", {"packetBytes": 10**1000}):
                pass
            with st.stage_span(directory, "bad-unicode", {"phase": "\ud800"}):
                pass
            with st.stage_span(str(Path(directory) / "missing"), "unwritable"):
                value = 7
        self.assertEqual(value, 7)


class TimingReaderV2Tests(unittest.TestCase):
    """Concurrency, resume clocks and incomplete work cannot be silently conflated."""

    def test_same_name_out_of_order_spans_are_paired_by_identity(self) -> None:
        rows = [_row("A", "start", 0), _row("B", "start", 1),
                _row("A", "end", 5, elapsedMs=5000),
                _row("B", "end", 9, elapsedMs=8000)]
        report = summarize_timings(rows)
        self.assertEqual([(r["spanId"], r["elapsedMs"]) for r in report["spans"]],
                         [("A", 5000), ("B", 8000)])
        self.assertEqual(report["stagesInclusiveMs"], {"critic_plan": 13000})
        self.assertNotIn("requestElapsedMs", report)

    def test_different_process_and_resume_clock_domains_are_isolated(self) -> None:
        rows = [_row("A", "start", 9000),
                _row("A", "start", 1, writerId="other", attemptId="a2", attemptNo=2),
                _row("A", "end", 9002, elapsedMs=2000),
                _row("A", "end", 4, writerId="other", attemptId="a2", attemptNo=2,
                     elapsedMs=3000)]
        report = summarize_timings(rows)
        self.assertEqual(len(report["spans"]), 2)
        self.assertEqual(report["issues"], [])

    def test_missing_and_mismatched_end_is_not_invented(self) -> None:
        report = summarize_timings([_row("A", "start", 1),
                                    _row("A", "end", 3, writerId="other", elapsedMs=2000)])
        self.assertFalse(report["allRecordedSpansPaired"])
        self.assertEqual(len(report["incompleteSpans"]), 1)
        self.assertEqual(report["spans"], [])

    def test_duplicate_and_invalid_duration_are_observable(self) -> None:
        start = _row("A", "start", 1)
        report = summarize_timings([start, start, _row("A", "end", 3, elapsedMs=9999)])
        self.assertFalse(report["allRecordedSpansPaired"])
        self.assertEqual(len(report["issues"]), 2)
        self.assertEqual(report["spans"], [])

    def test_legacy_rows_are_explicitly_weaker_evidence(self) -> None:
        report = summarize_timings([{"stage": "old", "event": "start", "mono": 1},
                                    {"stage": "old", "event": "end", "mono": 2}])
        self.assertEqual(report["legacySpanCount"], 1)
        self.assertEqual(report["spans"][0]["status"], "unknown")
        self.assertEqual(report["workflowCoverage"], "not-established-by-telemetry-alone")


if __name__ == "__main__":
    unittest.main(verbosity=2)
