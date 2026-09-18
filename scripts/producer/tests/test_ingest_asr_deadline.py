"""Shared source/worker/publication deadlines without models or media tools."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ingest
import ingest_scan
import local_asr_deadline as clocks
import transcript_source_authority as authority

PAYLOAD = {"status": "done", "duration": 1, "transcript": [{"words": [
    {"word": "TEST", "start": 0.1, "end": 0.5}]}]}


@contextlib.contextmanager
def _source_case():
    """Provide tiny immutable source bytes and a controlled ten-second clock."""
    with tempfile.TemporaryDirectory() as temporary, \
            mock.patch.dict(os.environ, {"WHISPER_CPP_TIMEOUT_SECONDS": "10"}, clear=True), \
            contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        root = Path(temporary)
        source = root / "source.media"
        source.write_bytes(b"TEST-source")
        expected = (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_size)
        context = ingest.TranscribeCtx(True, None, root, "/TEST/python", {str(source): expected})
        now = [100.0]
        with mock.patch.object(clocks.time, "monotonic", side_effect=lambda: now[0]):
            yield root, source, context, now


class IngestAsrDeadlineTests(unittest.TestCase):
    def test_source_hash_expiry_prevents_worker_launch(self) -> None:
        with _source_case() as (root, source, context, now):
            original = authority._read_guarded

            def slow_read(descriptor, guard):
                chunk = original(descriptor, guard)
                now[0] = 111
                return chunk

            with mock.patch.object(authority, "_read_guarded", side_effect=slow_read), \
                    mock.patch.object(ingest, "_run_transcribe") as worker:
                self.assertIsNone(ingest._transcribe_source(source, "raw-1", context))
            worker.assert_not_called()
            self.assertFalse((root / "raw-1.transcript.json").exists())

    def test_late_successful_worker_cannot_publish(self) -> None:
        with _source_case() as (root, source, context, now):
            def late_worker(*_args):
                now[0] = 111
                return PAYLOAD

            with mock.patch.object(ingest, "_run_transcribe", side_effect=late_worker):
                self.assertIsNone(ingest._transcribe_source(source, "raw-1", context))
            self.assertFalse((root / "raw-1.transcript.json").exists())

    def test_before_and_after_source_hashes_use_original_expiry(self) -> None:
        with _source_case() as (root, source, context, now):
            def worker(_source, _env, _interpreter, deadline):
                self.assertEqual(deadline.expires_at, 110)
                now[0] = 108
                return PAYLOAD

            with mock.patch.object(ingest, "_run_transcribe", side_effect=worker):
                result = ingest._transcribe_source(source, "raw-1", context)
            self.assertEqual(result, "raw-1.transcript.json")
            self.assertIn("sourceMediaAuthority", json.loads((root / result).read_text()))

    def test_parent_worker_gets_decreasing_budget_and_exact_expiry(self) -> None:
        with _source_case() as (_root, source, _context, now):
            deadline = clocks.LocalAsrDeadline.start()
            now[0] = 106
            proc = mock.Mock(returncode=0, stdout=json.dumps(PAYLOAD), stderr="")
            with mock.patch.object(ingest, "run_text", return_value=proc) as spawn:
                self.assertEqual(ingest._run_transcribe(source, {}, "/TEST/python", deadline), PAYLOAD)
            request = spawn.call_args.args[0]
            self.assertEqual(request.timeout_seconds, 4)
            self.assertEqual(request.max_output_bytes, 16 * 1024 * 1024)
            index = request.command.index("--local-asr-expires-at")
            self.assertEqual(float(request.command[index + 1]), 110)
            self.assertIn("--local-asr-owned-worker", request.command)

    def test_invalid_limit_rejects_before_observing_source(self) -> None:
        with _source_case() as (root, source, context, _now), \
                mock.patch.dict(os.environ, {"WHISPER_CPP_TIMEOUT_SECONDS": "3601"}), \
                mock.patch.object(ingest, "observe_source") as observe:
            self.assertIsNone(ingest._transcribe_source(source, "raw-1", context))
            observe.assert_not_called()
            self.assertFalse((root / "raw-1.transcript.json").exists())

    def test_expiry_during_serialization_preserves_existing_destination(self) -> None:
        with _source_case() as (root, _source, _context, now):
            destination = root / "existing.json"
            destination.write_text("prior bytes")
            deadline = clocks.LocalAsrDeadline.start()
            original = json.dump

            def late_dump(*args, **kwargs):
                original(*args, **kwargs)
                now[0] = 111

            with mock.patch.object(ingest_scan.json, "dump", side_effect=late_dump), \
                    self.assertRaises(clocks.LocalAsrDeadlineError):
                ingest_scan.atomic_write_json(destination, PAYLOAD, deadline.guard)
            self.assertEqual(destination.read_text(), "prior bytes")
            self.assertFalse(list(root.glob(".existing.json.*.tmp")))


if __name__ == "__main__":
    unittest.main()
