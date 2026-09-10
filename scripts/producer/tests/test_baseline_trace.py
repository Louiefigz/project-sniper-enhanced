"""Tests for truthful baseline trace classification."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import baseline_trace
import baseline_trace_validation
import current_full_path_baseline
from _baseline_trace_fixtures import (
    current_fixture as _current_fixture,
    current_output as _current_output,
    repeat_equivalence as _repeat_equivalence,
    set_output_sha as _set_output_sha,
)
from baseline_repeat_validation import PIXEL_IDENTICAL_CLASS
from current_render_oracle import CODEC_FLOOR_POLICY

FIXTURES = Path(__file__).parent / "fixtures"
COMMAND = FIXTURES / "p1_baseline_fixture_command.py"


class BaselineTraceTests(unittest.TestCase):
    """Exercise named short/LF14 harness fixtures without claiming media speed."""

    def test_named_synthetic_fixtures_are_not_full_path_evidence(self) -> None:
        for name in ("p1-baseline-short.json", "p1-baseline-lf14.json"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                fixture_path = root / name
                shutil.copyfile(FIXTURES / name, fixture_path)
                fixture = baseline_trace._load_fixture(fixture_path)
                trace = baseline_trace.capture_trace(baseline_trace.TraceConfig(
                    fixture=fixture,
                    command=(
                        sys.executable,
                        str(COMMAND),
                        "--fixture",
                        str(fixture_path),
                    ),
                    cwd=root,
                    timeout_s=10,
                ))
                self.assertEqual(
                    trace["classification"],
                    "synthetic-harness-validation",
                )
                self.assertEqual(
                    [run["cacheState"] for run in trace["runs"]],
                    ["cold", "warm"],
                )
                self.assertTrue(
                    baseline_trace_validation.validate_trace_document(trace))
                output = json.loads(
                    (root / fixture["outputPaths"][0]).read_text(
                        encoding="utf-8"))
                self.assertEqual(len(output["clauses"]), 20)

    def test_missing_cache_evidence_remains_unproved(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            fixture = baseline_trace._load_fixture(
                FIXTURES / "p1-baseline-short.json")
            trace = baseline_trace.capture_trace(baseline_trace.TraceConfig(
                fixture={**fixture, "outputPaths": []},
                command=(sys.executable, "-c", "print('no cache evidence')"),
                cwd=root,
                timeout_s=10,
            ))
            self.assertEqual(trace["classification"], "cache-state-unproved")

    def test_retained_trace_rehashes_its_direct_command_tools(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            fixture_path = root / "fixture.json"
            command_path = root / "fixture-command.py"
            shutil.copyfile(FIXTURES / "p1-baseline-short.json", fixture_path)
            shutil.copyfile(COMMAND, command_path)
            fixture = baseline_trace._load_fixture(fixture_path)
            trace = baseline_trace.capture_trace(baseline_trace.TraceConfig(
                fixture=fixture,
                command=(
                    sys.executable, str(command_path),
                    "--fixture", str(fixture_path),
                ),
                cwd=root,
                timeout_s=10,
            ))
            self.assertTrue(
                baseline_trace_validation.validate_trace_document(trace))
            command_path.write_text(
                command_path.read_text(encoding="utf-8") + "\n# drift\n",
                encoding="utf-8",
            )
            self.assertFalse(
                baseline_trace_validation.validate_trace_document(trace))

    def test_current_path_cache_claim_requires_observed_cut_behavior(self) -> None:
        rendered = [{"status": "stage_done", "stage": "cut_speed"}]
        skipped = [{"status": "stage_skipped", "stage": "cut_speed"}]
        self.assertEqual(
            current_full_path_baseline._cache_state("first-run", rendered),
            "cold",
        )
        self.assertEqual(
            current_full_path_baseline._cache_state(
                "immediate-repeat", skipped),
            "warm",
        )
        self.assertEqual(
            current_full_path_baseline._cache_state("first-run", skipped),
            "unproved",
        )
        self.assertEqual(
            current_full_path_baseline._cache_state(
                "immediate-repeat", rendered + skipped),
            "unproved",
        )
        durations = current_full_path_baseline._stage_durations([
            {"stage": "cut_speed", "event": "start", "mono": 1.0},
            {"stage": "cut_speed", "event": "end", "mono": 1.25},
        ])
        self.assertEqual(durations, {"cut_speed": 250})

    def test_current_full_path_label_requires_closed_input_authority(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = json.loads(
                (FIXTURES / "p1-baseline-lf14.json").read_text())
            fixture["evidenceClass"] = "current-full-path-baseline"
            path = Path(raw) / "unbound.json"
            path.write_text(json.dumps(fixture))
            with self.assertRaisesRegex(
                    baseline_trace.BaselineTraceError, "input authority"):
                baseline_trace._load_fixture(path)

    def test_current_classification_requires_matching_decoded_media(self) -> None:
        fixture = _current_fixture("short", 1350, ("30", "1"))
        runs = [
            {
                "exitCode": 0,
                "cacheState": state,
                "outputs": [_current_output(fixture)],
            }
            for state in ("cold", "warm")
        ]
        _set_output_sha(runs[1]["outputs"][0], "c" * 64)
        self.assertEqual(baseline_trace_validation.classify_execution(
            fixture, runs), "current-full-path-baseline")
        self.assertEqual(baseline_trace_validation.classify(
            fixture, runs), "repeat-equivalence-unproved")
        self.assertEqual(
            baseline_trace_validation.classify(
                fixture, runs, _repeat_equivalence(fixture, runs)),
            CODEC_FLOOR_POLICY["pictureClaim"],
        )
        self.assertEqual(
            baseline_trace_validation.classify(
                fixture, runs, _repeat_equivalence(
                    fixture, runs, exact=True)),
            PIXEL_IDENTICAL_CLASS,
        )
        runs[1]["outputs"][0]["media"]["fullDecode"]["videoSha256"] = "c" * 64
        self.assertEqual(
            baseline_trace_validation.classify(
                fixture, runs, _repeat_equivalence(fixture, runs)),
            CODEC_FLOOR_POLICY["pictureClaim"],
        )

    def test_current_classification_rejects_wrong_frame_count(self) -> None:
        fixture = _current_fixture("longform", 20, ("24000", "1001"))
        output = _current_output(fixture)
        output["media"]["video"]["decodedFrames"] = 19
        runs = [{
            "exitCode": 0,
            "cacheState": state,
            "outputs": [json.loads(json.dumps(output))],
        } for state in ("cold", "warm")]
        self.assertEqual(
            baseline_trace_validation.classify(fixture, runs),
            "media-proof-unproved",
        )

    def test_lf14_timeline_requires_unrounded_frame_duration(self) -> None:
        fixture = _current_fixture(
            "longform", 20_139, ("24000", "1001"))
        runs = [{
            "exitCode": 0,
            "cacheState": state,
            "outputs": [_current_output(fixture)],
        } for state in ("cold", "warm")]
        self.assertEqual(
            baseline_trace_validation.classify_execution(fixture, runs),
            "current-full-path-baseline",
        )
        runs[0]["outputs"][0]["media"]["qc"]["timelineMap"][
            "outputDuration"] = 839.9641
        self.assertEqual(
            baseline_trace_validation.classify_execution(fixture, runs),
            "media-proof-unproved",
        )

    def test_current_classification_rejects_unbound_qc_or_pcm_count(self) -> None:
        fixture = _current_fixture("short", 1350, ("30", "1"))
        output = _current_output(fixture)
        runs = [{
            "exitCode": 0, "cacheState": state,
            "outputs": [json.loads(json.dumps(output))],
        } for state in ("cold", "warm")]
        runs[1]["outputs"][0]["media"]["qc"]["finalSha256"] = "0" * 64
        self.assertEqual(
            baseline_trace_validation.classify(fixture, runs),
            "media-proof-unproved",
        )
        runs[1] = {
            "exitCode": 0, "cacheState": "warm",
            "outputs": [_current_output(fixture)],
        }
        runs[1]["outputs"][0]["media"]["fullDecode"]["audioPcmBytes"] = 399
        self.assertEqual(
            baseline_trace_validation.classify(fixture, runs),
            "media-proof-unproved",
        )

    def test_current_classification_separates_tool_and_media_mismatch(self) -> None:
        fixture = _current_fixture("short", 1350, ("30", "1"))
        runs = [{
            "exitCode": 0, "cacheState": state,
            "outputs": [_current_output(fixture)],
        } for state in ("cold", "warm")]
        runs[1]["outputs"][0]["media"]["tools"]["ffmpeg"]["sha256"] = "9" * 64
        self.assertEqual(
            baseline_trace_validation.classify(fixture, runs),
            "media-tool-mismatch",
        )

if __name__ == "__main__":
    unittest.main()
