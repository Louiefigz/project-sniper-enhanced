"""Transcript-to-admitted-media lineage and transplant rejection."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ingest
from transcript_source_authority import (
    bind_result,
    observe_source,
    verify_result,
)


def _result(word: str = "hello") -> dict:
    return {
        "status": "done",
        "transcript": [{
            "start": 0.0, "end": 0.4, "text": word,
            "words": [{"word": word, "start": 0.0, "end": 0.4}],
        }],
        "duration": 0.5,
        "model": "fixture",
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TranscriptSourceAuthorityTests(unittest.TestCase):
    def test_binding_matches_exact_source_and_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.media"
            transcript = root / "raw-1.transcript.json"
            source.write_bytes(b"exact admitted bytes")
            expected = (_sha(source), source.stat().st_size)
            bound = bind_result(_result(), observe_source(source, expected))
            transcript.write_text(json.dumps(bound))
            row = {
                "path": str(source), "sourceSha256": expected[0],
                "sourceSizeBytes": expected[1],
            }
            self.assertIsNone(verify_result(bound, row, str(transcript)))

    def test_transplanted_source_and_modified_result_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, second = root / "first.media", root / "second.media"
            transcript = root / "raw-1.transcript.json"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            expected = (_sha(first), first.stat().st_size)
            bound = bind_result(_result(), observe_source(first, expected))
            transplanted = {
                "path": str(second), "sourceSha256": _sha(second),
                "sourceSizeBytes": second.stat().st_size,
            }
            self.assertIn(
                "does not match",
                verify_result(bound, transplanted, str(transcript)) or "")
            modified = json.loads(json.dumps(bound))
            modified["transcript"][0]["words"][0]["word"] = "forged"
            row = {
                "path": str(first), "sourceSha256": expected[0],
                "sourceSizeBytes": expected[1],
            }
            self.assertIn(
                "result bytes",
                verify_result(modified, row, str(transcript)) or "")

    def test_ingest_observes_source_before_and_after_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.media"
            source.write_bytes(b"stable")
            expected = (_sha(source), source.stat().st_size)
            context = ingest.TranscribeCtx(
                True, None, root, "python",
                {str(source.absolute()): expected})
            with mock.patch.object(
                    ingest, "_run_transcribe", return_value=_result()):
                name = ingest._transcribe_source(source, "raw-1", context)
            self.assertEqual(name, "raw-1.transcript.json")
            payload = json.loads((root / name).read_text())
            self.assertEqual(
                payload["sourceMediaAuthority"]["sourceSha256"], expected[0])

    def test_source_mutation_during_worker_never_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.media"
            source.write_bytes(b"before")
            expected = (_sha(source), source.stat().st_size)
            context = ingest.TranscribeCtx(
                True, None, root, "python",
                {str(source.absolute()): expected})

            def mutate(*_args) -> dict:
                source.write_bytes(b"after!")
                return _result()

            with mock.patch.object(
                    ingest, "_run_transcribe", side_effect=mutate):
                name = ingest._transcribe_source(source, "raw-1", context)
            self.assertIsNone(name)
            self.assertFalse((root / "raw-1.transcript.json").exists())

    def test_collapsed_timing_never_publishes_from_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.media"
            source.write_bytes(b"stable")
            expected = (_sha(source), source.stat().st_size)
            context = ingest.TranscribeCtx(
                True, None, root, "python",
                {str(source.absolute()): expected})
            collapsed = _result()
            collapsed["transcript"][0]["words"] = [
                {"word": str(index), "start": 1.0, "end": 1.01}
                for index in range(9)
            ]
            with mock.patch.object(
                    ingest, "_run_transcribe", return_value=collapsed):
                name = ingest._transcribe_source(
                    source, "raw-1", context)
            self.assertIsNone(name)
            self.assertFalse((root / "raw-1.transcript.json").exists())


if __name__ == "__main__":
    unittest.main()
