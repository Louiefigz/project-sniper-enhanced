"""Palmier export hygiene tests — tmp wait, ffprobe gate, atomic publish."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palmier import export as palmier_export
from audit.audit_checks import CheckResult, FAIL, PASS
from palmier.audio_finish import FinishReport
from palmier.export import (ExportProbe, ExportRequest, export_timeline,
                            verify_export, wait_for_export)
from palmier.mcp_client import PalmierError


class FakeClient:
    """Palmier client that materializes the requested background output."""

    def __init__(self, payload: bytes = b"new-video") -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []

    def call(self, tool: str, arguments: dict | None = None) -> str:
        args = arguments or {}
        self.calls.append((tool, args))
        Path(args["outputPath"]).write_bytes(self.payload)
        return "export started"


def _request(out_dir: str) -> ExportRequest:
    """A compact valid export request for transaction tests."""
    return ExportRequest(out_dir=out_dir, timeline_id="timeline-shadow-7",
                         expected_end_frame=300, fps=30.0,
                         plan_hash="plan-deadbeef",
                         authority_hash="authority-deadbeef", poll_s=0.0)


def _fake_probe(duration: float) -> subprocess.CompletedProcess[str]:
    """Create a successful ffprobe process result with one video stream."""
    payload = {"streams": [{"codec_type": "video",
                             "duration": str(duration)}],
               "format": {"duration": str(duration)}}
    return subprocess.CompletedProcess([], 0, json.dumps(payload), "")


class ExportWaitTests(unittest.TestCase):
    def test_requires_new_mtime_and_two_equal_nonzero_sizes(self) -> None:
        old = SimpleNamespace(st_mtime_ns=100, st_size=90)
        growing = SimpleNamespace(st_mtime_ns=101, st_size=120)
        stable = SimpleNamespace(st_mtime_ns=101, st_size=120)
        with patch.object(palmier_export.os, "stat",
                          side_effect=[old, growing, stable]), \
                patch.object(palmier_export.time, "monotonic",
                             return_value=0.0), \
                patch.object(palmier_export.time, "sleep") as sleep:
            result = wait_for_export("/tmp/new.mp4", 100, 1.0, 0.01)
        self.assertIs(result, stable)
        self.assertEqual(sleep.call_count, 3)


class ExportVerificationTests(unittest.TestCase):
    def test_accepts_duration_at_two_frame_boundary(self) -> None:
        with patch.object(palmier_export.subprocess, "run",
                          return_value=_fake_probe(302 / 30)):
            probe = verify_export("/tmp/export.mp4", 300, 30.0)
        self.assertAlmostEqual(probe.frame_error, 2.0)

    def test_rejects_duration_beyond_two_frames(self) -> None:
        with patch.object(palmier_export.subprocess, "run",
                          return_value=_fake_probe(302.1 / 30)):
            with self.assertRaisesRegex(PalmierError,
                                        "duration mismatch"):
                verify_export("/tmp/export.mp4", 300, 30.0)

    def test_rejects_container_without_video(self) -> None:
        payload = subprocess.CompletedProcess(
            [], 0, json.dumps({"streams": [],
                               "format": {"duration": "10"}}), "")
        with patch.object(palmier_export.subprocess, "run",
                          return_value=payload):
            with self.assertRaisesRegex(PalmierError, "no video stream"):
                verify_export("/tmp/export.mp4", 300, 30.0)


class ExportTransactionTests(unittest.TestCase):
    def _run_patched(self, client: FakeClient,
                     request: ExportRequest, quality: str = PASS,
                     quality_plans: list[dict] | None = None):
        probe = ExportProbe(duration_s=10.0, frame_error=0.0)

        def finish_audio(spec):
            Path(spec.staging_output_path).write_bytes(
                Path(spec.visual_path).read_bytes())
            return FinishReport(spec.staging_output_path, 10.0, 10.0, 0.0,
                                -14.0, -1.8, 0.0)

        check = CheckResult("audio_tonal_hum", quality, "clean", "")

        def check_quality(_path, plan):
            if quality_plans is not None:
                quality_plans.append(plan)
            return [check]

        with patch.object(palmier_export, "wait_for_export",
                          side_effect=lambda path, *_: os.stat(path)), \
                patch.object(palmier_export, "verify_export",
                             return_value=probe), \
                patch.object(palmier_export, "finish_authoritative_audio",
                             side_effect=finish_audio), \
                patch.object(palmier_export, "check_audio_quality",
                             side_effect=check_quality):
            return export_timeline(client, request)

    def test_exports_specific_timeline_and_publishes_verified_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp, palmier_export.FINAL_NAME)
            meta = Path(tmp, palmier_export.META_NAME)
            final.write_bytes(b"old-video")
            meta.write_text('{"old": true}')
            client = FakeClient()
            quality_plans: list[dict] = []

            request = _request(tmp)
            request = ExportRequest(**{**request.__dict__,
                                       "music_enabled": True})
            result = self._run_patched(
                client, request, quality_plans=quality_plans)

            self.assertEqual(client.calls, [("export_project", {
                "timelineId": "timeline-shadow-7",
                "outputPath": str(Path(tmp, palmier_export.TEMP_NAME))})])
            self.assertEqual(final.read_bytes(), b"new-video")
            metadata = json.loads(meta.read_text())
            self.assertEqual(metadata["planHash"], "plan-deadbeef")
            self.assertEqual(metadata["authorityHash"],
                             "authority-deadbeef")
            self.assertTrue(metadata["exportVerified"])
            self.assertTrue(metadata["audioVerified"])
            self.assertEqual(metadata["audioQc"]["finish"]["integrated_lufs"],
                             -14.0)
            self.assertTrue(metadata["pushedAt"].endswith("Z"))
            self.assertEqual(result.bytes, len(b"new-video"))
            self.assertEqual(quality_plans,
                             [{"music": {"enabled": True}}])
            self.assertFalse(Path(tmp, palmier_export.TEMP_NAME).exists())

    def test_audio_qc_failure_preserves_prior_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp, palmier_export.FINAL_NAME)
            meta = Path(tmp, palmier_export.META_NAME)
            final.write_bytes(b"known-good")
            meta.write_text('{"planHash": "known-good"}')
            with self.assertRaisesRegex(PalmierError, "audio QC failed"):
                self._run_patched(FakeClient(), _request(tmp), FAIL)
            self.assertEqual(final.read_bytes(), b"known-good")
            self.assertEqual(meta.read_text(), '{"planHash": "known-good"}')
            self.assertFalse(Path(tmp, palmier_export.TEMP_NAME).exists())
            self.assertFalse(Path(tmp, palmier_export.AUDIO_TEMP_NAME).exists())

    def test_verification_failure_preserves_old_final_and_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp, palmier_export.FINAL_NAME)
            meta = Path(tmp, palmier_export.META_NAME)
            final.write_bytes(b"old-video")
            meta.write_text('{"planHash": "old"}')
            client = FakeClient()
            with patch.object(palmier_export, "wait_for_export",
                              side_effect=lambda path, *_: os.stat(path)), \
                    patch.object(palmier_export, "verify_export",
                                 side_effect=PalmierError("bad duration")):
                with self.assertRaisesRegex(PalmierError, "bad duration"):
                    export_timeline(client, _request(tmp))
            self.assertEqual(final.read_bytes(), b"old-video")
            self.assertEqual(meta.read_text(), '{"planHash": "old"}')
            self.assertFalse(Path(tmp, palmier_export.TEMP_NAME).exists())

    def test_meta_replace_failure_rolls_back_promoted_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp, palmier_export.FINAL_NAME)
            meta = Path(tmp, palmier_export.META_NAME)
            final.write_bytes(b"old-video")
            meta.write_text('{"planHash": "old"}')
            real_replace = os.replace

            def fail_meta_replace(source: str, destination: str) -> None:
                if destination == str(meta):
                    raise OSError("metadata disk failure")
                real_replace(source, destination)

            with patch.object(palmier_export.os, "replace",
                              side_effect=fail_meta_replace):
                with self.assertRaisesRegex(PalmierError,
                                            "metadata disk failure"):
                    self._run_patched(FakeClient(), _request(tmp))
            self.assertEqual(final.read_bytes(), b"old-video")
            self.assertEqual(meta.read_text(), '{"planHash": "old"}')
            self.assertFalse(Path(tmp, palmier_export.TEMP_NAME).exists())
            self.assertEqual(list(Path(tmp).glob("*.rollback-*")), [])


if __name__ == "__main__":
    unittest.main()
