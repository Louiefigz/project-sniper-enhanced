"""Opt-in real ingest.main parsing/publication, without HTTP or speech-accuracy claims."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import ingest
import test_supporting_rescan_media as fixture
from fingerprints import file_sha256
from ingest_admission_contract import verify_source_set_binding
from ingest_execution_authority import verify_execution_media_authority
from transcript_source_authority import verify_result


@unittest.skipUnless(os.environ.get("RUN_SUPPORTING_RESCAN_MEDIA_TESTS") == "1",
                     "opt-in supervised Docker/FFmpeg publication acceptance")
class SupportingRescanPublicationMediaTests(unittest.TestCase):
    """Reuse fixture helpers only; the three prior media test methods are not inherited."""

    setUp = fixture.SupportingRescanMediaTests.setUp
    _seed_manifest = fixture.SupportingRescanMediaTests._seed_manifest
    _assert_unpublished_and_retained = fixture.SupportingRescanMediaTests._assert_unpublished_and_retained

    def _invoke_main(self, output: io.StringIO) -> None:
        """Exercise actual argument parsing, rescan and atomic publication in-process."""
        arguments = [str(Path(ingest.__file__)), str(self.source), "--out",
                     str(self.manifest_path), "--reuse-transcripts"]
        with patch.object(sys, "argv", arguments), contextlib.redirect_stdout(output):
            ingest.main()

    def _assert_published(self, manifest: dict, supporting: Path) -> None:
        """Cold-read output remains source-bound and includes actual admitted PNG bytes."""
        self.assertEqual(self.transcript_path.read_bytes(), self.transcript_before)
        self.assertTrue(verify_execution_media_authority({}, manifest, str(self.manifest_path)))
        entries = verify_source_set_binding(manifest, self.source)
        self.assertEqual({row["originalPath"] for row in entries},
                         {self.previous["sources"][0]["originalPath"], str(supporting)})
        self.assertEqual(manifest["sourceSetAdmission"]["entryCount"], 2)
        self.assertNotEqual(manifest["sourceSetAdmission"]["sourceSetDigest"],
                            self.previous["sourceSetAdmission"]["sourceSetDigest"])
        self.assertEqual(len(manifest["sources"]), 1)
        proof = {"admissionReceiptPath", "admissionReceiptSha256"}
        self.assertEqual({key: value for key, value in manifest["sources"][0].items() if key not in proof},
                         {key: value for key, value in self.previous["sources"][0].items() if key not in proof})
        self.assertIsNone(verify_result(json.loads(self.transcript_before), manifest["sources"][0],
                                       str(self.transcript_path)))
        self.assertEqual(len(manifest["broll"]), 1)
        row = manifest["broll"][0]
        self.assertEqual(row["kind"], "image")
        self.assertEqual(row["originalPath"], str(supporting))
        self.assertEqual(row["sourceSha256"], file_sha256(str(supporting)))
        self.assertEqual(row["sourceSha256"], file_sha256(row["path"]))

    def test_main_atomically_publishes_admitted_png_with_exact_retained_transcript(self) -> None:
        """The real main entry replaces the manifest once and emits done after publication."""
        fixture._recording(self.source / "take.mp4")
        self._seed_manifest(self.source)
        supporting = self.source / "broll" / "supplied.png"
        fixture._png(supporting, "red")
        output = io.StringIO()
        with self.manifest_path.open("rb") as old_handle:
            old_identity = os.fstat(old_handle.fileno())
            self._invoke_main(output)
            new_identity = self.manifest_path.stat()
            self.assertNotEqual((new_identity.st_dev, new_identity.st_ino),
                                (old_identity.st_dev, old_identity.st_ino))
            self.assertEqual(old_handle.read(), self.manifest_before)
        self.assertNotEqual(self.manifest_path.read_bytes(), self.manifest_before)
        self._assert_published(json.loads(self.manifest_path.read_bytes()), supporting)
        events = [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]
        done = [row for row in events if row.get("status") == "done"]
        self.assertEqual(done, [{"status": "done", "manifest": str(self.manifest_path),
                                "sources": 1, "broll": 1, "music": 0}])
        self.assertEqual(events[-1], done[0])
        self.assertEqual(list(self.source.glob(".asset_manifest.json.*.tmp")), [])

    def test_main_rejects_invalid_png_without_publishing_or_emitting_done(self) -> None:
        """A real decoder rejection exits nonzero while the previous edit remains intact."""
        fixture._recording(self.source / "take.mp4")
        self._seed_manifest(self.source)
        bad = self.source / "broll" / "invalid.png"
        bad.parent.mkdir()
        bad.write_bytes(b"TEST-ONLY invalid PNG bytes; not admitted media")
        previous_identity = self.manifest_path.stat()
        output = io.StringIO()
        with self.assertRaises(SystemExit) as failure:
            self._invoke_main(output)
        self.assertIsInstance(failure.exception.code, int)
        self.assertNotEqual(failure.exception.code, 0)
        self._assert_unpublished_and_retained()
        current_identity = self.manifest_path.stat()
        self.assertEqual((current_identity.st_dev, current_identity.st_ino),
                         (previous_identity.st_dev, previous_identity.st_ino))
        events = [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]
        self.assertFalse(any(row.get("status") in {"done", "success"} for row in events))
        errors = [row["error"] for row in events if "error" in row]
        self.assertEqual(len(errors), 1)
        self.assertIn("external-media decode rejected", errors[0])
        self.assertEqual(list(self.source.glob(".asset_manifest.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
