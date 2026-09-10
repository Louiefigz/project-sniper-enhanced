"""Coverage diagnostics survive baseline capture without claiming media quality."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import baseline_trace
from _baseline_trace_fixtures import current_fixture
from baseline_trace_validation import validate_trace_document

FIXTURES = Path(__file__).parent / "fixtures"


def _coverage() -> dict:
    """Representative partial journal with failed, interrupted and legacy work."""
    return {
        "event": "baseline_timing_coverage",
        "incompleteSpans": 2,
        "issues": [{"kind": "malformed-row"},
                   {"kind": "unmatched-or-invalid-end", "spanId": "missing"}],
        "executionStatusCounts": {
            "completed": 3, "failed": 1, "interrupted": 1, "unknown": 2,
        },
        "legacySpanCount": 2,
    }


def _capture(coverage: dict, exit_code: int) -> dict:
    """Use real, cheap child processes through the complete enclosing capture."""
    fixture = baseline_trace._load_fixture(FIXTURES / "p1-baseline-short.json")
    command = (
        sys.executable, "-c",
        "import json, os, sys; "
        "print(sys.argv[1]); "
        "print(json.dumps({'event': 'baseline_cache_state', 'state': "
        "'cold' if os.environ['SNIPER_BASELINE_RUN_LABEL'] == 'first-run' "
        "else 'warm'})); sys.exit(int(sys.argv[2]))",
        json.dumps(coverage), str(exit_code),
    )
    with tempfile.TemporaryDirectory() as directory:
        return baseline_trace.capture_trace(baseline_trace.TraceConfig(
            fixture={**fixture, "outputPaths": []}, command=command,
            cwd=Path(directory).resolve(), timeout_s=10,
        ))


def _timeout_command(coverage: dict) -> tuple[str, ...]:
    """Emit early diagnostics and unterminated work before a bounded timeout."""
    return (
        sys.executable, "-u", "-c",
        "import json, sys, time; print(sys.argv[1], flush=True); "
        "print('x' * 10000, flush=True); "
        "print(json.dumps({'event': 'start', 'stage': 'slow_render', "
        "'spanId': 'unterminated'}), flush=True); "
        "print('y' * 10000 + 'stderr-tail', file=sys.stderr, flush=True); "
        "time.sleep(10)",
        json.dumps(coverage),
    )


def _current_failure(exit_code: int | None) -> dict:
    """Isolate capture/validation from source admission and actual media work."""
    fixture = {**current_fixture("short", 1350, ("30", "1")),
               "outputPaths": ["final.mp4"]}
    result = (json.dumps(_coverage()).encode(), b"", exit_code)
    with tempfile.TemporaryDirectory() as directory:
        config = baseline_trace.TraceConfig(
            fixture=fixture,
            command=(sys.executable, str(FIXTURES / "p1_baseline_fixture_command.py")),
            cwd=Path(directory).resolve(), timeout_s=1,
        )
        with mock.patch.object(baseline_trace, "_verify_current_authority"), \
                mock.patch.object(baseline_trace, "_execute", return_value=result):
            return baseline_trace.capture_trace(config)


class BaselineTimingCoverageTests(unittest.TestCase):
    """Retain diagnostics and existing event fields on successful and failed runs."""

    def test_event_filter_keeps_coverage_without_broadening_other_events(self) -> None:
        coverage = _coverage()
        stage = {"event": "baseline_stage", "stage": "graphics", "wallMs": 15,
                 "measurement": "inclusive-stage-time"}
        cache = {"event": "baseline_cache_state", "state": "cold"}
        payload = "\n".join(("non-JSON log", json.dumps(stage),
                              json.dumps(coverage), json.dumps(cache),
                              '{"event":"unrelated","prompt":"private"}', "[]"))
        self.assertEqual(baseline_trace._events(payload.encode()),
                         [stage, coverage, cache])

    def test_diagnostics_survive_both_enclosing_runs(self) -> None:
        coverage = _coverage()
        trace = _capture(coverage, 0)
        for run in trace["runs"]:
            self.assertEqual([event for event in run["events"]
                              if event["event"] == "baseline_timing_coverage"],
                             [coverage])
        self.assertEqual([run["cacheState"] for run in trace["runs"]],
                         ["cold", "warm"])
        self.assertEqual(trace["classification"], "synthetic-harness-validation")
        self.assertTrue(validate_trace_document(trace))

    def test_failed_execution_retains_coverage_and_remains_failed(self) -> None:
        coverage = _coverage()
        trace = _capture(coverage, 7)
        self.assertEqual([run["exitCode"] for run in trace["runs"]], [7, 7])
        self.assertEqual(trace["classification"], "failed")
        self.assertFalse(trace["executionObserved"]["complete"])
        self.assertTrue(all(coverage in run["events"] for run in trace["runs"]))
        self.assertTrue(validate_trace_document(trace))

    def test_timeout_partial_trace_survives_roundtrip_without_repeat(self) -> None:
        coverage = _coverage()
        fixture = baseline_trace._load_fixture(FIXTURES / "p1-baseline-short.json")
        with tempfile.TemporaryDirectory() as directory:
            config = baseline_trace.TraceConfig(
                fixture=fixture, command=_timeout_command(coverage),
                cwd=Path(directory).resolve(), timeout_s=1,
            )
            with mock.patch.object(baseline_trace, "_artifact",
                                   side_effect=AssertionError("must not probe unfinished outputs")):
                trace = baseline_trace.capture_trace(config)
            path = Path(directory) / "timeout-trace.json"
            baseline_trace._write_json(path, trace)
            retained = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(retained["runs"]), 1)
        run = retained["runs"][0]
        self.assertEqual(run["status"], "timed_out")
        self.assertIsNone(run["exitCode"])
        self.assertFalse(run["terminalObserved"])
        self.assertEqual(run["descendantCleanup"], "unverified")
        self.assertGreaterEqual(run["wallMs"], 900)
        self.assertEqual(run["timeoutSeconds"], 1)
        self.assertIn(coverage, run["events"])
        self.assertIn('"event": "start"', run["partialStdout"]["tail"])
        self.assertNotIn('"event": "end"', run["partialStdout"]["tail"])
        self.assertTrue(run["partialStderr"]["tail"].endswith("stderr-tail\n"))
        for stream in ("partialStdout", "partialStderr"):
            self.assertTrue(run[stream]["truncated"])
            self.assertGreater(run[stream]["capturedBytes"], baseline_trace.PARTIAL_OUTPUT_BYTES)
            self.assertLessEqual(len(run[stream]["tail"]), baseline_trace.PARTIAL_OUTPUT_BYTES)
        self.assertEqual(run["outputs"][0]["status"], "not-observed")
        self.assertEqual(retained["classification"], "failed")
        self.assertFalse(retained["executionObserved"]["complete"])
        self.assertIsNone(retained["repeatEquivalence"])
        self.assertTrue(validate_trace_document(retained))

    def test_timeout_before_any_output_records_empty_partial_streams(self) -> None:
        fixture = baseline_trace._load_fixture(FIXTURES / "p1-baseline-short.json")
        with tempfile.TemporaryDirectory() as directory:
            config = baseline_trace.TraceConfig(
                fixture={**fixture, "outputPaths": []},
                command=(sys.executable, "-c", "pass"),
                cwd=Path(directory).resolve(), timeout_s=1,
            )
            timeout = baseline_trace.subprocess.TimeoutExpired(config.command, 1)
            with mock.patch.object(baseline_trace.subprocess, "run", side_effect=timeout):
                run = baseline_trace._run(config, "first-run")
        self.assertEqual(run["status"], "timed_out")
        self.assertEqual(run["events"], [])
        self.assertFalse(run["terminalObserved"])
        self.assertEqual(run["partialStdout"], {"tail": "", "capturedBytes": 0,
                                                "truncated": False})
        self.assertEqual(run["partialStderr"], run["partialStdout"])

    def test_current_failure_validates_without_success_receipt(self) -> None:
        for exit_code in (7, None):
            with self.subTest(exit_code=exit_code):
                trace = _current_failure(exit_code)
                self.assertEqual(trace["classification"], "failed")
                self.assertEqual(len(trace["runs"]), 1 if exit_code is None else 2)
                self.assertFalse(trace["executionObserved"]["complete"])
                self.assertIsNone(trace["repeatEquivalence"])
                self.assertTrue(validate_trace_document(trace))
                forged = json.loads(json.dumps(trace))
                forged["repeatEquivalence"] = {"classification": "success"}
                self.assertFalse(validate_trace_document(forged))
                forged = json.loads(json.dumps(trace))
                forged["classification"] = "current-full-path-baseline"
                forged["executionObserved"] = {
                    "complete": True, "classification": "current-full-path-baseline",
                }
                self.assertFalse(validate_trace_document(forged))


if __name__ == "__main__":
    unittest.main(verbosity=2)
