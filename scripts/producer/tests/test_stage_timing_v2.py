"""Exact nested/concurrent timing identity; no claims about editorial approval."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import *  # noqa: F401,F403
import stage_timing as st
from stage_timing_report import summarize_timings


def _row(span: str, event: str, mono: float, **fields: object) -> dict:
    """Construct a complete synthetic v2 event for reader contract tests."""
    return {"schemaVersion": 2, "stage": "critic_plan", "event": event,
            "mono": mono, "ts": mono + 1000, "runId": "run", "attemptId": "a1",
            "attemptNo": 1, "writerId": "writer", "writerPid": 1,
            "clock": "process-monotonic", "spanId": span,
            "status": "completed", **fields}


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
