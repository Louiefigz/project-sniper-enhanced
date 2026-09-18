"""Local transcript-preserving rescan; admission is mocked, source binding is real."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ingest_transcript_reuse import rescan_with_transcripts
from ingest_retained_inventory import retained_primary_files
from transcript_source_authority import bind_result, observe_source


class TranscriptReuseTests(unittest.TestCase):
    """Exercise retained bytes, source identity and no-ASR builder dispatch."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "primary.media"
        self.source.write_bytes(b"TEST original admitted source")
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.row = {"id": "raw-1", "path": str(self.source),
                    "originalPath": str(self.source), "sourceSha256": digest,
                    "sourceSizeBytes": self.source.stat().st_size,
                    "duration": 3, "fps": 25, "resolution": [1920, 1080],
                    "transcriptPath": "raw-1.transcript.json"}
        result = {"status": "done", "transcript": [{"start": 0, "end": 1,
                  "text": "Useful example", "words": [
                      {"word": "Useful", "start": 0, "end": 0.4},
                      {"word": "example", "start": 0.5, "end": 1}]}]}
        bound = bind_result(result, observe_source(
            self.source, (digest, self.source.stat().st_size)))
        self.transcript = self.root / self.row["transcriptPath"]
        self.transcript.write_text(json.dumps(bound))
        self.previous = {"sources": [self.row], "broll": [], "music": []}
        self.manifest = self.root / "asset_manifest.json"
        self.manifest.write_text(json.dumps(self.previous))
        self.current = copy.deepcopy(self.previous)
        self.current["sources"][0]["transcriptPath"] = None
        self.current["broll"] = [{"id": "supplied", "path": "new.png"}]
        self.builder = Mock(return_value=self.current)
        self.verify = patch("ingest_transcript_reuse.execution_media_authority_entries", return_value=[])
        self.verify.start()
        self.addCleanup(self.verify.stop)

    def run_rescan(self) -> dict:
        """Run the shared function without external media or provider processes."""
        return rescan_with_transcripts(self.root, self.manifest, self.builder)

    def test_retains_verified_speech_and_calls_builder_with_asr_disabled(self) -> None:
        before = self.transcript.read_bytes(), self.manifest.read_bytes()
        result = self.run_rescan()
        self.assertEqual(self.builder.call_count, 1)
        self.assertEqual(self.builder.call_args.args[:3], (self.root, self.root, True))
        self.assertEqual(retained_primary_files(self.builder.call_args.args[3]), [self.source])
        self.assertEqual(result["sources"][0]["transcriptPath"], self.row["transcriptPath"])
        self.assertEqual(len(result["broll"]), 1)
        self.assertEqual((self.transcript.read_bytes(), self.manifest.read_bytes()), before)

    def test_missing_or_modified_transcript_stops_before_media_builder(self) -> None:
        self.transcript.write_text('{"transcript":[]}')
        with self.assertRaisesRegex(RuntimeError, "Cannot reuse transcript"):
            self.run_rescan()
        self.builder.assert_not_called()
        self.transcript.unlink()
        with self.assertRaises(OSError):
            self.run_rescan()

    def test_unknown_source_authority_cannot_be_reused(self) -> None:
        with patch("ingest_transcript_reuse.execution_media_authority_entries", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "admitted source-set"):
                self.run_rescan()
        self.builder.assert_not_called()

    def test_source_identity_timing_or_order_changes_are_rejected(self) -> None:
        for field, value in [("id", "raw-2"), ("sourceSha256", "b" * 64),
                             ("duration", 4), ("fps", 30), ("path", "/tmp/other")]:
            with self.subTest(field=field):
                changed = copy.deepcopy(self.current)
                changed["sources"][0][field] = value
                self.builder.return_value = changed
                with self.assertRaisesRegex(RuntimeError, "source identity, order or timing"):
                    self.run_rescan()

    def test_added_primary_source_is_not_a_broll_only_rescan(self) -> None:
        self.current["sources"].append({**self.row, "id": "raw-2"})
        with self.assertRaisesRegex(RuntimeError, "changed primary sources"):
            self.run_rescan()

    def test_concurrent_transcript_or_manifest_edit_is_not_overwritten(self) -> None:
        for file in [self.transcript, self.manifest]:
            original = file.read_bytes()
            def change(*_args):
                file.write_bytes(original + b"\n")
                return self.current
            self.builder.side_effect = change
            with self.assertRaisesRegex(RuntimeError, "changed during"):
                self.run_rescan()
            self.assertEqual(file.read_bytes(), original + b"\n")
            file.write_bytes(original)

    def test_missing_speech_is_explicit_and_no_asr_is_attempted(self) -> None:
        self.previous["sources"][0]["transcriptPath"] = None
        self.manifest.write_text(json.dumps(self.previous))
        with self.assertRaisesRegex(RuntimeError, "Analyze missing speech"):
            self.run_rescan()
        self.builder.assert_not_called()

    def test_transcript_symlink_or_escape_is_rejected(self) -> None:
        self.transcript.unlink()
        self.transcript.symlink_to(self.manifest)
        with self.assertRaisesRegex(RuntimeError, "canonical source directory"):
            self.run_rescan()
        self.builder.assert_not_called()

    def test_referenced_ingress_is_retained_even_without_primary_folder_files(self) -> None:
        referenced = self.root.parent / "TEST-external-recording.mp4"
        self.previous["sources"][0]["originalPath"] = str(referenced)
        self.current["sources"][0]["originalPath"] = str(referenced)
        self.manifest.write_text(json.dumps(self.previous))
        result = self.run_rescan()
        self.assertEqual(retained_primary_files(self.builder.call_args.args[3]), [referenced])
        self.assertEqual(result["sources"][0]["path"], str(self.source))

    def test_missing_primary_ingress_does_not_fall_back_to_folder_discovery(self) -> None:
        del self.previous["sources"][0]["originalPath"]
        self.manifest.write_text(json.dumps(self.previous))
        with self.assertRaisesRegex(RuntimeError, "original source ingress"):
            self.run_rescan()
        self.builder.assert_not_called()


if __name__ == "__main__":
    unittest.main()
