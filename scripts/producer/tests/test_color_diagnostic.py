"""Private diagnostic write/failure contracts with inert worker boundaries."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from color.diagnostic import run_diagnostic
from color.model import DiagnosticRequest
from headless.color_diagnostic_policy import container_command
from headless.container_policy import DockerRuntime
from test_color_sampling import declared, probe, sample_statistics


class ColorDiagnosticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.producer = self.root / "producer"
        self.producer.mkdir()
        self.plan = {"planVersion": 1, "cutTrack": [{"sourceId": "raw-1", "start": 0, "end": 600}]}
        self.source = {"id": "raw-1", "duration": 600, "fps": 30}
        self.raw = json.dumps(self.plan).encode()
        (self.producer / "edit_plan.json").write_bytes(self.raw)
        self.request = DiagnosticRequest(self.producer, hashlib.sha256(self.raw).hexdigest(), "b" * 64, [declared()])
        self.observed = {"plan": self.plan, "manifest": {}, "bindings": {"planHash": self.request.plan_hash},
                         "sources": [{"sourceId": "raw-1", "path": "/inert-test-boundary",
                                      "sha256": "a" * 64, "manifestRow": self.source}]}
        self.observer = patch("color.diagnostic.observe", return_value=self.observed).start()
        patch("color.diagnostic.toolchain", return_value={"sha256": "c" * 64}).start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.temp.cleanup)

    def worker(self, _source: str, request: dict) -> dict:
        return {"syntheticBoundaryTest": True, "worker": {
            "schemaVersion": 1, "status": "complete", "sourceSha256": request["sourceSha256"],
            "probe": probe(), "samples": [
                {"id": row["id"], "requestedTime": row["sourceTime"], "actualSourceTime": row["sourceTime"],
                 "status": "sampled", "statistics": sample_statistics(), "elapsedMs": 1}
                | {"frameMetadata": {"pixelFormat": "yuv420p", "range": "tv", "matrix": "bt709",
                                      "primaries": "bt709", "transfer": "bt709", "hdrSignaled": False}}
                for row in request["samples"]], "timing": {"elapsedMs": 21}}}

    def test_final_revalidation_over_budget_discards_success_and_suggestions(self) -> None:
        ticks = [0.0]
        def observe(_request: DiagnosticRequest) -> dict:
            if self.observer.call_count > 1:
                ticks[0] = 121.0
            return self.observed
        self.observer.side_effect = observe
        with patch("color.diagnostic.time.monotonic", side_effect=lambda: ticks[0]):
            result = run_diagnostic(self.request, self.worker)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["elapsedMs"], 121000)

    def test_new_only_artifacts_and_no_canonical_grade_or_approval_writes(self) -> None:
        result = run_diagnostic(self.request, self.worker)
        self.assertEqual(result["state"], "complete")
        self.assertFalse(result["deliveryApproved"])
        self.assertFalse(result["writesGrade"])
        self.assertEqual((self.producer / "edit_plan.json").read_bytes(), self.raw)
        attempt = Path(result["artifactDir"])
        self.assertEqual({row.name for row in attempt.iterdir()}, {"request.json", "result.json"})
        self.assertEqual(attempt.stat().st_mode & 0o777, 0o700)
        self.assertEqual((attempt / "result.json").stat().st_mode & 0o777, 0o400)
        second = run_diagnostic(self.request, self.worker)
        self.assertNotEqual(result["diagnosticId"], second["diagnosticId"])

    def test_failed_worker_keeps_timing_and_has_no_proposal(self) -> None:
        def fail(_source: str, _request: dict) -> dict:
            raise subprocess.TimeoutExpired("inert-worker", 1)
        result = run_diagnostic(self.request, fail)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["groups"], [])
        self.assertGreaterEqual(result["elapsedMs"], 0)
        self.assertEqual(result["workers"][0]["status"], "failed")
        self.assertTrue((Path(result["artifactDir"]) / "result.json").is_file())

    def test_legacy_admission_failure_is_retained_without_running_worker(self) -> None:
        self.observer.side_effect = RuntimeError("requires current admitted sources")
        worker = unittest.mock.Mock()
        result = run_diagnostic(self.request, worker)
        self.assertEqual(result["state"], "failed")
        self.assertIn("admitted", result["error"])
        worker.assert_not_called()

    def test_changed_parent_discards_suggestions_not_human_edits(self) -> None:
        changed = copy.deepcopy(self.observed)
        changed["bindings"]["projectHash"] = "d" * 64
        self.observer.side_effect = [self.observed, changed]
        result = run_diagnostic(self.request, self.worker)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["groups"], [])
        self.assertEqual((self.producer / "edit_plan.json").read_bytes(), self.raw)

    def test_source_identity_and_duplicate_sample_closure_fail(self) -> None:
        def mismatch(source: str, request: dict) -> dict:
            result = self.worker(source, request)
            result["worker"]["sourceSha256"] = "0" * 64
            return result
        result = run_diagnostic(self.request, mismatch)
        self.assertEqual(result["state"], "failed")
        def duplicate(source: str, request: dict) -> dict:
            result = self.worker(source, request)
            result["worker"]["samples"][-1] = result["worker"]["samples"][0]
            return result
        self.assertEqual(run_diagnostic(self.request, duplicate)["state"], "failed")

    def test_unknown_profile_and_partial_failures_do_not_suggest(self) -> None:
        self.request.contexts[0]["sourceProfile"] = "unknown"
        result = run_diagnostic(self.request, self.worker)
        self.assertEqual(result["groups"][0]["suggestions"], [])
        def partial(source: str, request: dict) -> dict:
            result = self.worker(source, request)
            result["worker"]["status"] = "partial"
            row = result["worker"]["samples"][-1]
            row.update(status="failed", error="ETIMEDOUT", elapsedMs=8000)
            return result
        result = run_diagnostic(self.request, partial)
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["groups"][0]["suggestions"], [])
        self.assertEqual(result["groups"][0]["observations"][-1]["elapsedMs"], 8000)

    def test_private_store_symlink_is_refused(self) -> None:
        (self.producer / ".sniper-color-diagnostics").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            run_diagnostic(self.request, self.worker)

    def test_policy_retains_exact_mounts_network_memory_and_no_pull(self) -> None:
        runtime = DockerRuntime("/fixed/docker", "/fixed/socket", "sha256:" + "a" * 64,
                                "501:20", {"config": {"environment": []}})
        name, command = container_command(runtime, str(self.root), "/admitted/snapshot", {
            "sourceSha256": "b" * 64, "samples": [{"id": "one", "sourceTime": 70}], "timeoutSeconds": 120})
        self.assertTrue(name.startswith("sniper-color-diagnostic-"))
        for option, value in (("--network", "none"), ("--pull", "never"), ("--memory", "768m"),
                              ("--cpus", "4"), ("--entrypoint", "/usr/bin/node")):
            self.assertEqual(command[command.index(option) + 1], value)
        self.assertIn("type=bind,src=/admitted/snapshot,dst=/input/media,readonly", command)
        self.assertEqual(command.count("--mount"), 2)
        self.assertEqual(json.loads(command[-1])["samples"][0]["sourceTime"], 70)


if __name__ == "__main__":
    unittest.main()
