"""Exact-media transcript promotion, provenance, and rollback tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.producer.tests._ingest_admission_fixture import runner
from ingest_admission import admit_ingest_candidates, collect_ingest_candidates
import promote_transcript_authority as promotion
from transcript_source_authority import bind_result, observe_source, verify_result


def _result(collapsed: bool = False) -> dict:
    if collapsed:
        words = [
            {"word": str(index), "start": 1.0, "end": 1.01}
            for index in range(9)
        ]
    else:
        words = [
            {"word": "exact", "start": 0.0, "end": 0.3},
            {"word": "media", "start": 0.3, "end": 0.6},
            {"word": "words", "start": 0.6, "end": 1.0},
        ]
    return {
        "status": "done",
        "duration": 1.0,
        "model": "whisper.cpp:fixture",
        "provenance": {"provider": "local-whisper", "executionPath": "gpu"},
        "transcript": [{
            "start": words[0]["start"], "end": words[-1]["end"],
            "text": " ".join(word["word"] for word in words),
            "words": words,
        }],
    }


def _manifest(root: Path, data: bytes, collapsed: bool) -> Path:
    source_dir = root / "source"
    original = root / "original.mp4"
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(data)
    admitted = admit_ingest_candidates(
        collect_ingest_candidates([original], None, None), source_dir, runner)
    media = admitted.media_by_original[str(original)]
    row = {
        "id": "raw-1",
        "path": media.snapshot_path,
        "originalPath": media.original_path,
        "sourceSha256": media.sha256,
        "sourceSizeBytes": media.size_bytes,
        "admissionReceiptPath": media.receipt_path,
        "admissionReceiptSha256": media.receipt_sha256,
        "transcriptPath": "raw-1.transcript.json",
    }
    manifest = {
        "sources": [row], "broll": [], "music": [],
        "sourceSetAdmission": admitted.binding,
    }
    manifest_path = source_dir / "asset_manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    observed = observe_source(
        Path(media.snapshot_path), (media.sha256, media.size_bytes))
    transcript = bind_result(_result(collapsed), observed)
    (source_dir / "raw-1.transcript.json").write_text(
        json.dumps(transcript))
    return manifest_path


class PromoteTranscriptAuthorityTests(unittest.TestCase):
    def test_exact_admitted_media_rebinds_and_preserves_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _manifest(root / "target", b"same-media", True)
            candidate = _manifest(root / "candidate", b"same-media", False)
            result = promotion.promote(target, candidate, "raw-1")
            self.assertEqual(result["status"], "done")
            target_manifest = json.loads(target.read_text())
            row = target_manifest["sources"][0]
            output = json.loads(
                (target.parent / "raw-1.transcript.json").read_text())
            self.assertIsNone(verify_result(
                output, row, str(target.parent / "raw-1.transcript.json")))
            self.assertEqual(
                output["provenance"]["executionPath"], "gpu")
            proof = output["transcriptPromotionAuthority"]
            self.assertEqual(proof["sourceSha256"], row["sourceSha256"])
            self.assertEqual(proof["timingQuality"]["status"], "pass")
            self.assertEqual(
                output["sourceMediaAuthority"]["sourcePath"], row["path"])

    def test_different_media_and_tampered_candidate_preserve_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _manifest(root / "target", b"target-media", True)
            candidate = _manifest(root / "candidate", b"other-media", False)
            output = target.parent / "raw-1.transcript.json"
            before = output.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "SHA-256/size differ"):
                promotion.promote(target, candidate, "raw-1")
            self.assertEqual(output.read_bytes(), before)

            candidate = _manifest(root / "matching", b"target-media", False)
            forged_path = candidate.parent / "raw-1.transcript.json"
            forged = json.loads(forged_path.read_text())
            forged["transcript"][0]["words"][0]["word"] = "forged"
            forged_path.write_text(json.dumps(forged))
            with self.assertRaisesRegex(RuntimeError, "result bytes"):
                promotion.promote(target, candidate, "raw-1")
            self.assertEqual(output.read_bytes(), before)

    def test_failed_atomic_commit_rolls_back_to_prior_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _manifest(root / "target", b"same-media", True)
            candidate = _manifest(root / "candidate", b"same-media", False)
            output = target.parent / "raw-1.transcript.json"
            before = output.read_bytes()
            with mock.patch.object(
                    promotion.os, "replace",
                    side_effect=OSError("injected commit failure")):
                with self.assertRaisesRegex(OSError, "commit failure"):
                    promotion.promote(target, candidate, "raw-1")
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(
                list(target.parent.glob(".raw-1.transcript.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
