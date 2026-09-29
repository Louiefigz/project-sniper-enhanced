"""Controller-owned native program premaster and resumability regressions."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import native_program_audio as command
from audio.native_program_audio import publish_float_copy
from cut_preview_io import digest, file_hash


class NativeProgramAudioTests(unittest.TestCase):
    """No model path or mutable project file may select the executable WAV."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sniper-native-program-", dir="/private/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.producer, self.project = self.root / "producer", self.root / "project"
        self.producer.mkdir()
        self.project.mkdir()
        self.plan_path, self.manifest_path = self.producer / "edit_plan.json", self.root / "manifest.json"
        self.plan_path.write_text('{"cutTrack":[]}', encoding="utf-8")
        self.manifest_path.write_text('{"sources":[]}', encoding="utf-8")
        self.request = command._request(self.producer, self.manifest_path)
        self.owned = self.root / "owned"
        self.owned.mkdir()
        (self.owned / "result.json").write_text("{}\n", encoding="utf-8")
        self.audio = self.owned / "program.wav"
        self.audio.write_bytes(b"TEST synthetic float authority bytes")
        self.authority = {"path": str(self.owned / "result.json"),
            "sha256": "a" * 64, "owner": str(self.owned / "owner.json"), "ownerSha256": "b" * 64}
        clock = {"codec": "pcm_f32le", "sampleFormat": "flt", "sampleRate": 48000,
            "channels": 2, "startPts": 0, "timeBase": "1/48000", "samples": 48000}
        body = {"schemaVersion": 1, "kind": "native-program-audio-authority",
            "status": "native-program-audio-prepared",
            "scope": "complete-program-native-premaster-not-review-or-delivery",
            "humanListeningApproved": False, "nativeExportApproved": False,
            "project": str(self.producer),
            "plan": {"path": str(self.plan_path), "sha256": file_hash(self.plan_path)},
            "manifest": {"path": str(self.manifest_path), "sha256": file_hash(self.manifest_path),
                "sourceSetDigest": "c" * 64}, "sourceBusReceiptHash": "d" * 64,
            "audioProgramInputHash": "e" * 64, "finishing": None, "music": None,
            "detectorReference": None,
            "audio": {"path": str(self.audio), "sha256": file_hash(self.audio),
                "sizeBytes": self.audio.stat().st_size, **clock},
            "frameRate": "30/1", "videoFrames": 30,
            "tools": {"ffprobe": {"path": "/TEST/ffprobe"}}, "code": []}
        self.record = {**body, "receiptHash": digest(body)}

    def test_reader_rejects_changed_program_bytes_and_accepts_exact_clock(self) -> None:
        with patch.object(command, "read_inspection", return_value=self.record), \
                patch.object(command, "exact_float_audio_clock",
                    return_value={key: self.record["audio"][key] for key in
                        ("codec", "sampleFormat", "sampleRate", "channels", "startPts", "timeBase", "samples")}):
            self.assertEqual(command.read_preparation(self.authority, self.request), self.record)
            self.audio.write_bytes(b"TEST substituted bytes")
            with self.assertRaisesRegex(ValueError, "bytes changed"):
                command.read_preparation(self.authority, self.request)

    def test_install_is_exact_resumable_and_refuses_substitution(self) -> None:
        first = command.install_native_program_audio(
            self.project, self.request, self.authority, self.record)
        self.assertEqual(first["audio"]["file"], "assets/program.wav")
        self.assertEqual(first["authority"]["owner"], self.authority["owner"])
        self.assertEqual(first["authority"]["ownerSha256"], self.authority["ownerSha256"])
        self.assertEqual(file_hash(self.project / "assets/program.wav"), self.record["audio"]["sha256"])
        self.assertEqual(command.install_native_program_audio(
            self.project, self.request, self.authority, self.record), first)
        target = self.project / "assets/program.wav"
        target.unlink()
        target.write_bytes(b"TEST provider supplied substitute")
        with self.assertRaisesRegex(RuntimeError, "different program WAV"):
            command.install_native_program_audio(self.project, self.request, self.authority, self.record)

    def test_installation_reader_rechecks_owned_authority_current_inputs_and_local_clock(self) -> None:
        """The Native Long reader cannot trust only editable installation JSON."""
        installed = command.install_native_program_audio(
            self.project, self.request, self.authority, self.record)
        clock = {key: self.record["audio"][key] for key in
            ("codec", "sampleFormat", "sampleRate", "channels", "startPts", "timeBase", "samples")}
        with patch.object(command, "read_preparation", return_value=self.record) as read, \
                patch.object(command, "exact_float_audio_clock", return_value=clock):
            self.assertEqual(command.read_native_program_audio_installation(
                self.project, self.producer, self.manifest_path), installed)
        read.assert_called_once_with(installed["authority"], self.request)
        self.plan_path.write_text('{"cutTrack":[],"changed":true}', encoding="utf-8")
        with patch.object(command, "read_preparation", return_value=self.record), \
                patch.object(command, "exact_float_audio_clock", return_value=clock), \
                self.assertRaisesRegex(ValueError, "installation changed"):
            command.read_native_program_audio_installation(
                self.project, self.producer, self.manifest_path)

    def test_public_attempt_resumes_without_repeating_media_work(self) -> None:
        output = self.root / "attempt"
        with patch.object(command, "run_inspection", return_value=self.authority) as run, \
                patch.object(command, "read_preparation", return_value=self.record):
            first = command.prepare(self.producer, self.manifest_path, self.project, output)
            second = command.prepare(self.producer, self.manifest_path, self.project, output)
        self.assertEqual(first["status"], "native-program-audio-prepared")
        self.assertEqual(second["status"], "native-program-audio-reused")
        run.assert_called_once()

    def test_copy_rejects_linked_source_and_preserves_exact_bytes(self) -> None:
        source, target = self.root / "source.wav", self.root / "target.wav"
        source.write_bytes(b"TEST exact program")
        expected = file_hash(source)
        self.assertEqual(publish_float_copy(source, target, expected), expected)
        linked = self.root / "linked.wav"
        os.link(source, linked)
        with self.assertRaisesRegex(RuntimeError, "unsafe"):
            publish_float_copy(source, self.root / "rejected.wav", expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
