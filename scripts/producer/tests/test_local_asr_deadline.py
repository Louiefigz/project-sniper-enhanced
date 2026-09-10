"""Aggregate ASR clock admission without tools, models, media, or network."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import local_asr_deadline as clocks
import local_whisper as whisper


class AggregateDeadlineTests(unittest.TestCase):
    def test_default_cap_and_explicit_reduction(self) -> None:
        with mock.patch.object(clocks.time, "monotonic", return_value=100.0):
            self.assertEqual(clocks.LocalAsrDeadline.start({}).expires_at, 3700)
            self.assertEqual(clocks.LocalAsrDeadline.start({clocks.TIMEOUT_ENV: "20"}).expires_at, 120)

    def test_malformed_limit_rejects_before_source_or_runtime_reads(self) -> None:
        for value in ("", " ", "0", "-1", "3601", "999999999999", "1.5", "inf", "nan", "1e3", "١", "+1"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {clocks.TIMEOUT_ENV: value}), \
                    mock.patch.object(whisper.Path, "resolve") as source, \
                    mock.patch.object(whisper, "resolve_runtime") as runtime, \
                    self.assertRaises(whisper.LocalWhisperError):
                whisper.transcribe_media(whisper.LocalTranscribeRequest("/TEST/not-read"))
            source.assert_not_called()
            runtime.assert_not_called()

    def test_runtime_resolution_rejects_over_cap_before_model_lookup(self) -> None:
        with mock.patch.object(whisper, "resolve_whisper_model") as model, \
                mock.patch.object(whisper, "resolve_whisper_binary") as binary:
            with self.assertRaises(whisper.LocalWhisperError):
                whisper.resolve_runtime({clocks.TIMEOUT_ENV: "3601"})
            model.assert_not_called()
            binary.assert_not_called()

    def test_parent_only_shortens_and_expired_parent_never_renews(self) -> None:
        with mock.patch.object(clocks.time, "monotonic", return_value=100.0):
            short = clocks.LocalAsrDeadline.start({}, parent_expires_at=105)
            long = clocks.LocalAsrDeadline.start({}, parent_expires_at=10000)
            self.assertEqual(short.remaining(), 5)
            self.assertEqual(long.remaining(), 3600)
            with self.assertRaises(clocks.LocalAsrDeadlineError):
                clocks.LocalAsrDeadline.start({}, parent_expires_at=100)

    def test_invalid_parent_never_enters_work(self) -> None:
        for value in (True, "120", float("inf"), float("nan"), 0, -1):
            with self.subTest(value=value), self.assertRaises(whisper.LocalWhisperError):
                clocks.LocalAsrDeadline.start({}, parent_expires_at=value)

    def test_nested_scope_cannot_extend_and_resets_after_exception(self) -> None:
        with mock.patch.object(clocks.time, "monotonic", return_value=100.0), \
                clocks.use_local_asr_deadline(clocks.LocalAsrDeadline(110)):
            with clocks.use_local_asr_deadline(clocks.LocalAsrDeadline(120)) as inner:
                self.assertEqual(inner.expires_at, 110)
            self.assertEqual(clocks.current_local_asr_deadline().expires_at, 110)
        with self.assertRaisesRegex(whisper.LocalWhisperError, "active aggregate"):
            clocks.current_local_asr_deadline()

    def test_deadline_is_propagated_to_existing_clipper_thread_execution(self) -> None:
        async def observe() -> float:
            return await asyncio.to_thread(lambda: clocks.current_local_asr_deadline().expires_at)

        with clocks.use_local_asr_deadline(clocks.LocalAsrDeadline.start({})) as held:
            self.assertEqual(asyncio.run(observe()), held.expires_at)

    def test_expiry_is_terminal_and_catchable_by_existing_local_error_contract(self) -> None:
        with mock.patch.object(clocks.time, "monotonic", return_value=101):
            with self.assertRaises(whisper.LocalWhisperError) as caught:
                clocks.LocalAsrDeadline(101).guard()
            self.assertIsInstance(caught.exception, clocks.LocalAsrDeadlineError)


if __name__ == "__main__":
    unittest.main()
