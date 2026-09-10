"""Retry transcription from immutable admitted media without re-admission."""

from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import resume_ingest_transcription as retry
from transcript_source_authority import bind_result, observe_source


def _manifest(source: Path, transcript: str | None = None) -> dict:
    return {
        "sources": [{
            "id": "raw-1", "path": str(source),
            "transcriptPath": transcript,
        }],
        "broll": [], "music": [], "sourceSetAdmission": {},
    }


class ResumeIngestTranscriptionTests(unittest.TestCase):
    def test_reverifies_authority_before_retry_and_persists_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.media"
            manifest_path = root / "asset_manifest.json"
            source.write_bytes(b"admitted")
            manifest_path.write_text(json.dumps(_manifest(source)))
            order = []

            def verify(*_args) -> bool:
                order.append("verify")
                return True

            def transcribe(_path, source_id, _context) -> str:
                order.append("transcribe")
                name = f"{source_id}.transcript.json"
                (root / name).write_text("{}")
                return name

            with mock.patch.object(
                    retry, "verify_execution_media_authority",
                    side_effect=verify), \
                    mock.patch.object(retry, "_context", return_value=object()), \
                    mock.patch.object(
                        retry, "_transcribe_source", side_effect=transcribe):
                result = retry.resume(manifest_path)
            self.assertEqual(order, ["verify", "transcribe"])
            self.assertEqual(result["transcribed"], ["raw-1"])
            saved = json.loads(manifest_path.read_text())
            self.assertEqual(
                saved["sources"][0]["transcriptPath"],
                "raw-1.transcript.json")

    def test_authority_failure_prevents_transcription(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.media"
            manifest_path = root / "asset_manifest.json"
            source.write_bytes(b"untrusted")
            manifest_path.write_text(json.dumps(_manifest(source)))
            with mock.patch.object(
                    retry, "verify_execution_media_authority",
                    side_effect=RuntimeError("bad authority")), \
                    mock.patch.object(retry, "_transcribe_source") as transcribe:
                with self.assertRaisesRegex(RuntimeError, "bad authority"):
                    retry.resume(manifest_path)
            transcribe.assert_not_called()

    def test_missing_admission_authority_prevents_transcription(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.media"
            manifest_path = root / "asset_manifest.json"
            source.write_bytes(b"legacy")
            manifest_path.write_text(json.dumps(_manifest(source)))
            with mock.patch.object(
                    retry, "verify_execution_media_authority",
                    return_value=False), \
                    mock.patch.object(retry, "_transcribe_source") as transcribe:
                with self.assertRaisesRegex(
                        RuntimeError, "requires admitted source-set"):
                    retry.resume(manifest_path)
            transcribe.assert_not_called()

    def test_existing_transcript_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.media"
            transcript = root / "raw-1.transcript.json"
            manifest_path = root / "asset_manifest.json"
            source.write_bytes(b"admitted")
            transcript.write_text("{}")
            manifest_path.write_text(json.dumps(
                _manifest(source, transcript.name)))
            with mock.patch.object(
                    retry, "verify_execution_media_authority",
                    return_value=True), \
                    mock.patch.object(retry, "_context", return_value=object()), \
                    mock.patch.object(retry, "_transcribe_source") as transcribe:
                result = retry.resume(manifest_path)
            self.assertTrue(result["alreadyComplete"])
            transcribe.assert_not_called()

    def test_admitted_transcript_requires_current_source_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.media"
            transcript = root / "raw-1.transcript.json"
            manifest_path = root / "asset_manifest.json"
            source.write_bytes(b"admitted")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            row = _manifest(source, transcript.name)["sources"][0]
            row.update(
                sourceSha256=digest,
                sourceSizeBytes=source.stat().st_size)
            manifest_path.write_text(json.dumps({
                "sources": [row], "broll": [], "music": [],
                "sourceSetAdmission": {},
            }))
            transcript.write_text(json.dumps({"transcript": []}))

            def transcribe(_path, source_id, _context) -> str:
                name = f"{source_id}.transcript.json"
                result = {"status": "done", "transcript": []}
                observed = observe_source(
                    source, (digest, source.stat().st_size))
                (root / name).write_text(json.dumps(
                    bind_result(result, observed)))
                return name

            with mock.patch.object(
                    retry, "verify_execution_media_authority",
                    return_value=True), \
                    mock.patch.object(retry, "_context", return_value=object()), \
                    mock.patch.object(
                        retry, "_transcribe_source", side_effect=transcribe):
                result = retry.resume(manifest_path)
            self.assertEqual(result["transcribed"], ["raw-1"])
            self.assertFalse(result["alreadyComplete"])

    def test_bound_but_collapsed_transcript_is_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.media"
            manifest_path = root / "asset_manifest.json"
            source.write_bytes(b"admitted")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            row = _manifest(source, "raw-1.transcript.json")["sources"][0]
            row.update(
                sourceSha256=digest,
                sourceSizeBytes=source.stat().st_size)
            manifest_path.write_text(json.dumps({
                "sources": [row], "broll": [], "music": [],
                "sourceSetAdmission": {},
            }))
            collapsed = {
                "status": "done",
                "transcript": [{
                    "start": 1.0, "end": 1.01, "text": "collapsed",
                    "words": [
                        {"word": str(index), "start": 1.0, "end": 1.01}
                        for index in range(9)
                    ],
                }],
            }
            observed = observe_source(
                source, (digest, source.stat().st_size))
            (root / "raw-1.transcript.json").write_text(json.dumps(
                bind_result(collapsed, observed)))
            calls = []

            def transcribe(_path, source_id, _context) -> str:
                calls.append(source_id)
                return "raw-1.transcript.json"

            with mock.patch.object(
                    retry, "verify_execution_media_authority",
                    return_value=True), \
                    mock.patch.object(retry, "_context", return_value=object()), \
                    mock.patch.object(
                        retry, "_transcribe_source", side_effect=transcribe):
                result = retry.resume(manifest_path)
            self.assertEqual(calls, ["raw-1"])
            self.assertEqual(result["transcribed"], ["raw-1"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
