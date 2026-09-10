"""Real local-ASR control flow with fake tools/clock; never invokes a model."""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import local_asr_deadline as clocks
import local_whisper as whisper
import local_whisper_io as local_io
import asr_policy
from producer.headless.process_runner import ProcessDeadlineError

FIXTURE = Path(__file__).parent / "fixtures" / "whisper_token_envelopes.json"


class CoreDeadlineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.now = 100.0
        self.calls = []
        self.good = json.loads(FIXTURE.read_text())
        self.runtime = whisper.WhisperRuntime(str(self.root / "whisper"), str(self.root / "model"), "en", 8, 10, False)
        for name in ("whisper", "model", "input"):
            (self.root / name).write_bytes(name.encode())
        self.stack.enter_context(mock.patch.dict(os.environ, {clocks.TIMEOUT_ENV: "10"}))
        self.stack.enter_context(mock.patch.object(clocks.time, "monotonic", side_effect=lambda: self.now))
        self.stack.enter_context(mock.patch.object(whisper, "resolve_runtime", return_value=self.runtime))
        self.stack.enter_context(mock.patch.object(local_io.shutil, "which", side_effect=lambda name: "/TEST/" + Path(name).name))
        paid = self.stack.enter_context(mock.patch.object(asr_policy, "paid_deepgram_client",
                                                         side_effect=AssertionError("NO PAID SDK")))
        self.addCleanup(paid.assert_not_called)

    def run_transcription(self, execute) -> dict:
        with mock.patch.object(local_io, "run_local_asr_leaf", side_effect=execute):
            return whisper.transcribe_media(whisper.LocalTranscribeRequest(str(self.root / "input")))

    def fake_tool(self, request) -> subprocess.CompletedProcess:
        self.calls.append(request)
        self.assertEqual(request.max_output_bytes, 16 * 1024 * 1024)
        self.assertEqual(request.stdin_text, "")
        if request.command[0].endswith("ffprobe"):
            self.now += 1
            stdout = json.dumps({"format": {"duration": "3"}, "streams": [{"codec_type": "audio", "start_time": "0"}]})
            return subprocess.CompletedProcess(request.command, 0, stdout, "")
        if request.command[0].endswith("ffmpeg"):
            self.now += 2
            Path(request.command[-1]).write_bytes(b"TEST-not-media")
            return subprocess.CompletedProcess(request.command, 0, "", "")
        self.now += 3 if "--no-gpu" not in request.command else 1
        prefix = request.command[request.command.index("-of") + 1]
        Path(prefix + ".json").write_text(json.dumps(self.good))
        return subprocess.CompletedProcess(request.command, 0, "", "")

    def test_gpu_failure_and_cpu_share_probe_and_extraction_budget(self) -> None:
        def execute(request):
            result = self.fake_tool(request)
            if request.command[0].endswith("whisper") and "--no-gpu" not in request.command:
                return subprocess.CompletedProcess(request.command, 1, "", "TEST GPU unavailable")
            return result

        result = self.run_transcription(execute)
        self.assertEqual([request.timeout_seconds for request in self.calls], [10, 9, 7, 4])
        self.assertEqual(result["provenance"]["executionPath"], "cpu")
        self.assertEqual(result["provenance"]["modelSha256"], hashlib.sha256(b"model").hexdigest())
        self.assertEqual(self.calls[1].command[-8:], ("-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", self.calls[1].command[-1]))

    def test_unsafe_gpu_timing_cpu_retry_uses_same_deadline(self) -> None:
        def execute(request):
            result = self.fake_tool(request)
            if request.command[0].endswith("whisper") and "--no-gpu" not in request.command:
                prefix = request.command[request.command.index("-of") + 1]
                tokens = [{"text": " " + text, "p": .8,
                           "offsets": {"from": 1000 + i * 10, "to": 1010 + i * 10}}
                          for i, text in enumerate("words all collapse right here at once".split())]
                bad = {"transcription": [{"offsets": {"from": 1000, "to": 1070},
                       "text": "".join(t["text"] for t in tokens), "tokens": tokens}]}
                Path(prefix + ".json").write_text(json.dumps(bad))
            return result

        result = self.run_transcription(execute)
        self.assertEqual([request.timeout_seconds for request in self.calls], [10, 9, 7, 4])
        self.assertEqual(result["provenance"]["executionPath"], "cpu")

    def test_extraction_expiry_never_starts_whisper(self) -> None:
        def execute(request):
            result = self.fake_tool(request)
            if request.command[0].endswith("ffmpeg"):
                self.now = 110
            return result

        with self.assertRaises(clocks.LocalAsrDeadlineError):
            self.run_transcription(execute)
        self.assertEqual(len(self.calls), 2)

    def test_gpu_timeout_is_terminal_not_cpu_fallback(self) -> None:
        def execute(request):
            if request.command[0].endswith("whisper"):
                self.calls.append(request)
                raise ProcessDeadlineError("TEST owned group reaped")
            return self.fake_tool(request)

        with self.assertRaises(clocks.LocalAsrDeadlineError):
            self.run_transcription(execute)
        self.assertEqual(len(self.calls), 3)

    def test_late_successful_gpu_output_is_not_accepted_or_retried(self) -> None:
        def execute(request):
            result = self.fake_tool(request)
            if request.command[0].endswith("whisper"):
                self.now = 110
            return result

        with self.assertRaises(clocks.LocalAsrDeadlineError):
            self.run_transcription(execute)
        self.assertEqual(len(self.calls), 3)

    def test_owned_process_failure_is_terminal_even_when_work_time_remains(self) -> None:
        def execute(request):
            if request.command[0].endswith("whisper"):
                self.calls.append(request)
                raise RuntimeError("TEST ownership could not be proved")
            return self.fake_tool(request)

        with self.assertRaisesRegex(whisper.LocalWhisperError, "ownership"):
            self.run_transcription(execute)
        self.assertEqual(len(self.calls), 3)

    def test_invalid_gpu_json_retains_single_cpu_retry_without_new_time(self) -> None:
        def execute(request):
            result = self.fake_tool(request)
            if request.command[0].endswith("whisper") and "--no-gpu" not in request.command:
                prefix = request.command[request.command.index("-of") + 1]
                Path(prefix + ".json").write_text('{"incomplete":')
            return result

        result = self.run_transcription(execute)
        self.assertEqual([request.timeout_seconds for request in self.calls], [10, 9, 7, 4])
        self.assertEqual(result["provenance"]["executionPath"], "cpu")

    def test_final_provenance_hash_expiry_rejects_done_result(self) -> None:
        original = local_io._hash_stream
        hashes = []

        def read(stream, deadline):
            result = original(stream, deadline)
            hashes.append(result)
            if len(hashes) == 3:
                self.now = 110
            return result

        with mock.patch.object(local_io, "_hash_stream", side_effect=read):
            with self.assertRaises(clocks.LocalAsrDeadlineError):
                self.run_transcription(self.fake_tool)
        self.assertEqual(len(self.calls), 3)

    def test_parent_expiry_is_not_replenished_at_core_entry(self) -> None:
        with mock.patch.object(local_io, "run_local_asr_leaf", side_effect=self.fake_tool):
            with self.assertRaises(clocks.LocalAsrDeadlineError):
                whisper.transcribe_media(whisper.LocalTranscribeRequest(str(self.root / "input")),
                                         deadline=clocks.LocalAsrDeadline(103))
        self.assertEqual([request.timeout_seconds for request in self.calls], [3, 2])

    def test_hash_checks_time_after_each_blocking_read(self) -> None:
        class SlowRead(io.BytesIO):
            def read(inner, size):
                value = super().read(size)
                self.now = 110
                return value

        with self.assertRaises(clocks.LocalAsrDeadlineError):
            local_io._hash_stream(SlowRead(b"TEST"), clocks.LocalAsrDeadline(110))

    def test_json_size_overflow_and_late_parse_fail_closed(self) -> None:
        path = self.root / "result.json"
        path.write_text('{"transcription":[]}')
        original = json.loads

        def parse(value):
            result = original(value)
            self.now = 110
            return result

        with clocks.use_local_asr_deadline(clocks.LocalAsrDeadline(110)):
            with mock.patch.object(local_io, "MAX_WHISPER_JSON_BYTES", 4), \
                    self.assertRaisesRegex(whisper.LocalWhisperError, "64 MiB"):
                local_io.read_whisper_json(path)
            with mock.patch.object(local_io.json, "loads", side_effect=parse), \
                    self.assertRaises(clocks.LocalAsrDeadlineError):
                local_io.read_whisper_json(path)
            self.now = 109


if __name__ == "__main__":
    unittest.main()
