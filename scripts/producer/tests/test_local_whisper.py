"""Local whisper.cpp provider, parser, and fail-closed policy tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

import local_whisper as lw
from local_whisper_parser import WhisperParseError, parse_whisper_json


FIXTURE = Path(__file__).parent / "fixtures" / "whisper_words.json"


class ProviderSelectionTests(unittest.TestCase):
    def test_default_is_local_without_any_environment(self) -> None:
        self.assertEqual(lw.transcription_provider({}), lw.LOCAL_PROVIDER)

    def test_local_execution_defaults_to_local_whisper(self) -> None:
        env = {lw.EXECUTION_MODE_ENV: "local"}
        self.assertEqual(lw.transcription_provider(env), lw.LOCAL_PROVIDER)

    def test_environment_deepgram_never_authorizes_spending(self) -> None:
        env = {lw.EXECUTION_MODE_ENV: "local", lw.PROVIDER_ENV: "deepgram"}
        with self.assertRaises(lw.LocalWhisperError):
            lw.transcription_provider(env)

    def test_unknown_provider_fails_closed(self) -> None:
        with self.assertRaisesRegex(lw.LocalWhisperError, lw.PROVIDER_ENV):
            lw.transcription_provider({lw.PROVIDER_ENV: "automatic"})


class WhisperParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(FIXTURE.read_text())

    def test_legacy_fixture_preserves_row_uniform_times_confidence_and_speaker(self) -> None:
        utterances = parse_whisper_json(self.payload, timeline_offset=10.0, speaker=1)
        self.assertEqual([u["text"] for u in utterances],
                         ["Hello, world.", "Next two words final?"])
        words = [word for utterance in utterances for word in utterance["words"]]
        self.assertEqual([w["word"] for w in words],
                         ["Hello,", "world.", "Next", "two", "words", "final?"])
        self.assertEqual(words[0]["start"], 10.1)
        self.assertEqual(words[0]["end"], 10.35)
        self.assertEqual(words[3]["start"], 11.9)
        self.assertEqual(words[3]["end"], 12.1)
        self.assertTrue(all(w["speaker"] == 1 for w in words))
        self.assertAlmostEqual(words[0]["confidence"], .9)

    def test_missing_or_empty_transcription_fails(self) -> None:
        with self.assertRaises(WhisperParseError):
            parse_whisper_json({})
        with self.assertRaises(WhisperParseError):
            parse_whisper_json({"transcription": []})


class RuntimeResolutionTests(unittest.TestCase):
    def test_cached_hyperframes_model_is_autodetected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            model = home / ".cache/hyperframes/whisper/models/ggml-small.en.bin"
            model.parent.mkdir(parents=True)
            model.touch()
            with mock.patch.object(lw.Path, "home", return_value=home):
                self.assertEqual(lw.resolve_whisper_model({}), str(model))

    def test_explicit_model_never_falls_back_when_missing(self) -> None:
        with self.assertRaisesRegex(lw.LocalWhisperError, "does not exist"):
            lw.resolve_whisper_model({"WHISPER_CPP_MODEL": "/missing/model.bin"})

    def test_gpu_failure_retries_once_on_cpu(self) -> None:
        runtime = lw.WhisperRuntime("whisper-cli", "model.bin", "en", 4, 10, False)
        calls: list[bool] = []
        results = iter([(None, "Metal allocation failed"), ({"transcription": []}, "")])

        def fake_attempt(_runtime, _wav, _prefix, cpu):
            calls.append(cpu)
            return next(results)

        events: list[dict] = []
        with mock.patch.object(lw, "_attempt_whisper", side_effect=fake_attempt):
            payload, cpu = lw._run_whisper(
                runtime, "audio.wav", "/tmp/out", events.append)
        self.assertEqual(payload, {"transcription": []})
        self.assertTrue(cpu)
        self.assertEqual(calls, [False, True])
        self.assertEqual(events[0]["status"], "local_whisper_cpu_fallback")

    def test_transcription_pins_runtime_model_settings_and_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary, model, media = (
                root / "whisper-cli", root / "model.bin", root / "media.mov")
            binary.write_bytes(b"runtime")
            model.write_bytes(b"model")
            media.write_bytes(b"media")
            runtime = lw.WhisperRuntime(
                str(binary), str(model), "en", 2, 10, True)
            payload = json.loads(FIXTURE.read_text())
            with mock.patch.object(
                    lw, "resolve_runtime", return_value=runtime), \
                    mock.patch.object(
                        lw, "_probe_audio", return_value=(0.0, 2.0)), \
                    mock.patch.object(
                        lw, "_extract_pcm",
                        side_effect=lambda _source, wav: Path(wav).write_bytes(
                            b"pcm")), \
                    mock.patch.object(
                        lw, "_run_whisper", return_value=(payload, True)):
                result = lw.transcribe_media(
                    lw.LocalTranscribeRequest(str(media)))
            proof = result["provenance"]
            self.assertEqual(proof["runtimeSha256"],
                             lw.hashlib.sha256(b"runtime").hexdigest())
            self.assertEqual(proof["modelSha256"],
                             lw.hashlib.sha256(b"model").hexdigest())
            self.assertEqual(len(proof["settingsSha256"]), 64)
            self.assertEqual(len(proof["resultSha256"]), 64)
            self.assertEqual(proof["executionPath"], "cpu")
            self.assertEqual(
                proof["timingQualityPolicy"],
                "sniper-transcript-timing-quality-v1")
            self.assertEqual(proof["parserPolicy"], "sniper-whisper-row-uniform-compatibility-v1")

    def test_collapsed_gpu_timing_retries_cpu_and_binds_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary, model, media = (
                root / "whisper-cli", root / "model.bin", root / "media.mov")
            binary.write_bytes(b"runtime")
            model.write_bytes(b"model")
            media.write_bytes(b"media")
            runtime = lw.WhisperRuntime(
                str(binary), str(model), "en", 2, 10, False)
            good = json.loads(FIXTURE.read_text())
            bad = json.loads(FIXTURE.read_text())
            tokens = [{"text": " " + text, "p": .8,
                       "offsets": {"from": 1000 + index * 10, "to": 1010 + index * 10}}
                      for index, text in enumerate("words all collapse right here at once".split())]
            bad["transcription"] = [{"offsets": {"from": 1000, "to": 1070},
                                     "text": "".join(t["text"] for t in tokens), "tokens": tokens}]
            events: list[dict] = []
            with mock.patch.object(
                    lw, "resolve_runtime", return_value=runtime), \
                    mock.patch.object(
                        lw, "_probe_audio", return_value=(0.0, 2.0)), \
                    mock.patch.object(
                        lw, "_extract_pcm",
                        side_effect=lambda _source, wav: Path(wav).write_bytes(
                            b"pcm")), \
                    mock.patch.object(
                        lw, "_run_whisper", return_value=(bad, False)), \
                    mock.patch.object(
                        lw, "_attempt_whisper", return_value=(good, "")):
                result = lw.transcribe_media(
                    lw.LocalTranscribeRequest(str(media)), events.append)
            self.assertEqual(result["provenance"]["executionPath"], "cpu")
            self.assertTrue(any(
                event["status"] == "local_whisper_timing_retry"
                for event in events))
            self.assertGreater(len(result["transcript"]), 0)

    def test_transcription_rejects_runtime_or_model_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary, model, media = (
                root / "whisper-cli", root / "model.bin", root / "media.mov")
            binary.write_bytes(b"runtime")
            model.write_bytes(b"model-v1")
            media.write_bytes(b"media")
            runtime = lw.WhisperRuntime(
                str(binary), str(model), "en", 2, 10, True)
            payload = json.loads(FIXTURE.read_text())

            def mutate_model(*_args):
                model.write_bytes(b"model-v2")
                return payload

            with mock.patch.object(
                    lw, "resolve_runtime", return_value=runtime), \
                    mock.patch.object(
                        lw, "_probe_audio", return_value=(0.0, 2.0)), \
                    mock.patch.object(lw, "_extract_pcm"), \
                    mock.patch.object(lw, "_run_whisper",
                                      side_effect=lambda *_args: (
                                          mutate_model(), True)), \
                    self.assertRaisesRegex(
                        lw.LocalWhisperError, "changed during transcription"):
                lw.transcribe_media(lw.LocalTranscribeRequest(str(media)))


class ClipperFailClosedTests(unittest.TestCase):
    def test_single_audio_never_falls_back_to_deepgram(self) -> None:
        script = SCRIPTS_DIR / "clipper" / "clipper_transcribe.py"
        with tempfile.NamedTemporaryFile(suffix=".wav") as media:
            env = {**os.environ, lw.PROVIDER_ENV: lw.LOCAL_PROVIDER}
            env.pop("DEEPGRAM_API_KEY", None)
            proc = subprocess.run([sys.executable, str(script), media.name],
                                  capture_output=True, text=True, env=env)
        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertIn("requires two separate lav files", payload["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
