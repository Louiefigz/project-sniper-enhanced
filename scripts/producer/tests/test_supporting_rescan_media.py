"""Opt-in real admission/rescan regressions; run only inside the held NativeRun.

Set RUN_SUPPORTING_RESCAN_MEDIA_TESTS=1 in the owner's closed child environment.
The owner must also supply the approved four SNIPER_DOCKER/RENDER variables and
allow its resolved local Docker socket through the outer process sandbox.
No media, probes or containers run on import. Fixture words are TEST-ONLY
synthetic timing data over a tone, never an ASR result or editorial approval.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ingest
from fingerprints import file_sha256
from ingest_admission_contract import verify_source_set_binding
from ingest_execution_authority import verify_execution_media_authority
from ingest_transcript_reuse import rescan_with_transcripts
from transcript_source_authority import bind_result, observe_source, verify_result


def _ffmpeg(arguments: list[str]) -> None:
    """Generate tiny known media only after explicit test admission by the owner."""
    subprocess.run(
        [shutil.which("ffmpeg") or "ffmpeg", "-nostdin", "-v", "error", "-n",
         "-filter_threads", "1", *arguments],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=30, check=True,
    )


def _recording(path: Path, color: str = "blue") -> None:
    """Create one second of real H.264 picture and AAC tone, without speech."""
    _ffmpeg([
        "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=25:d=1",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
        "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1",
        "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    ])


def _png(path: Path, color: str) -> None:
    """Create a real independently decodable raster for supplied B-roll ingress."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(["-f", "lavfi", "-i", f"color=c={color}:s=80x80",
             "-frames:v", "1", "-threads", "1", str(path)])


@unittest.skipUnless(os.environ.get("RUN_SUPPORTING_RESCAN_MEDIA_TESTS") == "1",
                     "opt-in supervised Docker/FFmpeg supporting rescan acceptance")
class SupportingRescanMediaTests(unittest.TestCase):
    """Exercise actual full-decode admission and exact transcript preservation."""

    def setUp(self) -> None:
        """Require explicit runtime configuration, then isolate fixture media."""
        for tool in ("ffmpeg", "ffprobe"):
            self.assertIsNotNone(shutil.which(tool), f"Acceptance requires {tool}")
        for name in ("SNIPER_DOCKER_PATH", "SNIPER_DOCKER_SOCKET",
                     "SNIPER_RENDER_IMAGE_ID", "SNIPER_RENDER_UID_GID"):
            self.assertTrue(os.environ.get(name), f"Acceptance requires {name}")
        scratch = tempfile.TemporaryDirectory(prefix="supporting-rescan-media-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve()
        self.incoming = self.root / "incoming"
        self.source = self.root / "project" / "source"
        self.incoming.mkdir()
        self.source.mkdir(parents=True)
        self.manifest_path = self.source / "asset_manifest.json"
        # Exclude unrelated bundled music; admission and supplied scans stay real.
        self.enterContext(patch("ingest.scan_builtin_music", return_value=[]))
        for name in ("_run_transcribe", "_spawn_transcribe", "load_deepgram_key",
                     "transcription_provider"):
            forbidden = self.enterContext(patch(
                f"ingest.{name}", side_effect=AssertionError("ASR/provider call forbidden")))
            self.addCleanup(forbidden.assert_not_called)

    def _seed_manifest(self, input_path: Path) -> None:
        """Bind clearly synthetic words to the actual admitted immutable snapshot."""
        previous = ingest.build_manifest(input_path, self.source, no_transcribe=True)
        self.assertEqual(len(previous["sources"]), 1)
        row = previous["sources"][0]
        self.assertIsNone(row["transcriptPath"])
        self.assertTrue(row["audio"]["present"])
        self.assertGreaterEqual(row["duration"], 1)
        snapshot = Path(row["path"])
        observation = observe_source(snapshot, (row["sourceSha256"], row["sourceSizeBytes"]))
        result = bind_result({
            "status": "done", "fixturePurpose": "TEST-ONLY synthetic transcript over tone",
            "speechAccuracyVerified": False, "editorialApproved": False,
            "transcript": [{"start": 0.1, "end": 0.8, "text": "Test fixture",
                            "words": [{"word": "Test", "start": 0.1, "end": 0.4},
                                      {"word": "fixture", "start": 0.5, "end": 0.8}]}],
        }, observation)
        row["transcriptPath"] = f"{row['id']}.transcript.json"
        self.transcript_path = self.source / row["transcriptPath"]
        self.transcript_path.write_text(json.dumps(result, indent=2) + "\n")
        self.manifest_path.write_text(json.dumps(previous, indent=2) + "\n")
        self.previous = previous
        self.transcript_before = self.transcript_path.read_bytes()
        self.manifest_before = self.manifest_path.read_bytes()
        self.assertTrue(verify_execution_media_authority({}, previous, str(self.manifest_path)))

    def _assert_unpublished_and_retained(self) -> None:
        """A rescan result must never overwrite the caller's old durable files."""
        self.assertEqual(self.manifest_path.read_bytes(), self.manifest_before)
        self.assertEqual(self.transcript_path.read_bytes(), self.transcript_before)
        self.assertTrue(verify_execution_media_authority(
            {}, self.previous, str(self.manifest_path)))
        payload = json.loads(self.transcript_before)
        self.assertIsNone(verify_result(
            payload, self.previous["sources"][0], str(self.transcript_path)))

    def _assert_rescan(self, current: dict, originals: set[Path]) -> None:
        """Prove new inventory bytes, admission closure and unchanged source words."""
        self._assert_unpublished_and_retained()
        self.assertTrue(verify_execution_media_authority({}, current, str(self.manifest_path)))
        entries = verify_source_set_binding(current, self.source)
        self.assertEqual({Path(row["originalPath"]) for row in entries}, originals)
        self.assertEqual(current["sourceSetAdmission"]["entryCount"], len(originals))
        for key in ("sourceSetDigest", "receiptSha256", "receiptPath"):
            self.assertNotEqual(current["sourceSetAdmission"][key],
                                self.previous["sourceSetAdmission"][key])
        prior_source, source = self.previous["sources"][0], current["sources"][0]
        self.assertEqual(len(current["sources"]), 1)
        refreshed_proof = {"admissionReceiptPath", "admissionReceiptSha256"}
        self.assertEqual({key: value for key, value in source.items() if key not in refreshed_proof},
                         {key: value for key, value in prior_source.items() if key not in refreshed_proof})
        self.assertIsNone(verify_result(json.loads(self.transcript_before), source,
                                       str(self.transcript_path)))
        for row in current["broll"]:
            self.assertEqual(row["kind"], "image")
            self.assertEqual(row["sourceSha256"], file_sha256(row["originalPath"]))
            self.assertEqual(row["sourceSha256"], file_sha256(row["path"]))
            self.assertNotEqual(row["path"], row["originalPath"])
        self.assertEqual(len({row["id"] for row in current["broll"]}), len(current["broll"]))

    def test_copied_primary_adds_real_supplied_png_without_retranscription(self) -> None:
        """A copied recording keeps exact transcript bytes when supplied media grows."""
        original, copied = self.incoming / "take.mp4", self.source / "take.mp4"
        _recording(original)
        shutil.copyfile(original, copied)
        self.assertEqual(file_sha256(str(original)), file_sha256(str(copied)))
        self._seed_manifest(self.source)
        self.assertEqual(self.previous["broll"], [])
        supporting = self.source / "broll" / "supplied.png"
        _png(supporting, "red")
        current = rescan_with_transcripts(self.source, self.manifest_path, ingest.build_manifest)
        self._assert_rescan(current, {copied, supporting})
        self.assertEqual(len(current["broll"]), 1)
        self.assertEqual(current["sources"][0]["originalPath"], str(copied))

    def test_referenced_primary_preserves_reclassified_and_external_broll(self) -> None:
        """Changing scan folders must retain external ingress and existing asset IDs."""
        original = self.incoming / "take.mp4"
        reclassified = self.incoming / "top-level.png"
        external_broll = self.incoming / "broll" / "old.png"
        _recording(original)
        _png(reclassified, "green")
        _png(external_broll, "yellow")
        self._seed_manifest(self.incoming)
        self.assertEqual(len(self.previous["broll"]), 2)
        self.assertFalse((self.source / "take.mp4").exists())
        prior_entries = verify_source_set_binding(self.previous, self.source)
        lanes = {row["originalPath"]: row["lane"] for row in prior_entries}
        self.assertEqual(lanes[str(reclassified)], "source")
        self.assertEqual(lanes[str(external_broll)], "broll")
        old_by_origin = {row["originalPath"]: row for row in self.previous["broll"]}
        supporting = self.source / "broll" / "a-new.png"
        _png(supporting, "red")
        current = rescan_with_transcripts(self.source, self.manifest_path, ingest.build_manifest)
        self._assert_rescan(current, {original, reclassified, external_broll, supporting})
        self.assertEqual(len(current["broll"]), 3)
        current_by_origin = {row["originalPath"]: row for row in current["broll"]}
        for origin, old in old_by_origin.items():
            for key in ("id", "path", "sourceSha256", "sourceSizeBytes", "kind", "resolution"):
                self.assertEqual(current_by_origin[origin].get(key), old.get(key), key)

    def test_bad_asset_and_changed_original_leave_prior_manifest_and_words(self) -> None:
        """Decode rejection and valid replacement media cannot publish stale words."""
        original = self.source / "take.mp4"
        _recording(original)
        self._seed_manifest(self.source)
        bad = self.source / "broll" / "bad.png"
        bad.parent.mkdir()
        bad.write_bytes(b"TEST-ONLY invalid raster bytes; never an admitted PNG")
        with self.subTest(failure="invalid supporting raster"):
            with self.assertRaisesRegex(RuntimeError, "external-media decode rejected"):
                rescan_with_transcripts(self.source, self.manifest_path, ingest.build_manifest)
            self._assert_unpublished_and_retained()
        bad.unlink()
        replacement = self.incoming / "replacement.mp4"
        _recording(replacement, "red")
        self.assertNotEqual(file_sha256(str(replacement)), self.previous["sources"][0]["sourceSha256"])
        os.replace(replacement, original)
        with self.subTest(failure="changed original recording"):
            with self.assertRaisesRegex(RuntimeError, "changed|differ|identity"):
                rescan_with_transcripts(self.source, self.manifest_path, ingest.build_manifest)
            self._assert_unpublished_and_retained()


if __name__ == "__main__":
    unittest.main()
