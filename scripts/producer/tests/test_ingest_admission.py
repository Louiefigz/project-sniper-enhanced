"""Mandatory Producer-ingest sandbox admission and source-set binding."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ingest
from _ingest_admission_fixture import probe as _probe
from _ingest_admission_fixture import runner as _runner
from ingest_admission import (
    SOURCE_SETS_NAME,
    admit_ingest_candidates,
    collect_ingest_candidates,
    verify_source_set_binding,
)
from ingest_admission_contract import receipt_snapshot


class IngestAdmissionTests(unittest.TestCase):
    def test_collects_all_canonical_ingest_lanes_and_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "take.mp4"
            broll = root / "broll"
            music = root / "music"
            broll.mkdir()
            music.mkdir()
            raw.write_bytes(b"raw")
            (broll / "cutaway.png").write_bytes(b"image")
            (music / "bed.wav").write_bytes(b"music")
            candidates = collect_ingest_candidates([raw], broll, music)
            self.assertEqual([row.lane for row in candidates],
                             ["source", "broll", "music"])
            linked = root / "linked.mp4"
            linked.symlink_to(raw)
            with self.assertRaisesRegex(RuntimeError, "non-symlink"):
                collect_ingest_candidates([linked], None, None)
            linked_dir = broll / "linked-dir"
            linked_dir.symlink_to(music, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "tree cannot contain symlinks"):
                collect_ingest_candidates([raw], broll, music)

    def test_admission_publishes_and_reverifies_exact_source_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "take.mp4"
            out = root / "out"
            media.write_bytes(b"video")
            candidates = collect_ingest_candidates([media], None, None)
            admitted = admit_ingest_candidates(candidates, out, _runner)
            manifest = {"sourceSetAdmission": admitted.binding}
            verify_source_set_binding(manifest, out)
            row = admitted.media_by_original[str(media)]
            self.assertNotEqual(row.snapshot_path, str(media))
            self.assertTrue(Path(row.snapshot_path).is_file())
            receipt_path = out / admitted.binding["receiptPath"]
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["entries"][0]["sha256"], row.sha256)
            boolean_count = json.loads(json.dumps(manifest))
            boolean_count["sourceSetAdmission"]["entryCount"] = True
            with self.assertRaisesRegex(
                    RuntimeError, "entry count mismatch"):
                verify_source_set_binding(boolean_count, out)
            media.write_bytes(b"changed original")
            verify_source_set_binding(manifest, out)
            Path(row.snapshot_path).write_bytes(b"changed snapshot")
            with self.assertRaisesRegex(RuntimeError, "corrupt"):
                verify_source_set_binding(manifest, out)

    def test_retained_receipt_rejects_non_integer_decode_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "take.mp4"
            store = root / "store"
            media.write_bytes(b"video")
            store.mkdir()
            receipt = _runner(str(media), str(store))
            receipt["limits"]["max_decode_seconds"] = True
            with self.assertRaisesRegex(RuntimeError, "decode proof"):
                receipt_snapshot(receipt, store)

    def test_partial_failure_never_publishes_source_set_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "one.mp4"
            second = root / "two.mp4"
            out = root / "out"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            calls = 0

            def fail_second(source: str, store: str) -> dict:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("decode rejected")
                return _runner(source, store)

            candidates = collect_ingest_candidates([first, second], None, None)
            with self.assertRaisesRegex(RuntimeError, "decode rejected"):
                admit_ingest_candidates(candidates, out, fail_second)
            receipts = out / SOURCE_SETS_NAME
            self.assertFalse(receipts.exists() and any(receipts.iterdir()))

    def test_symlinked_snapshot_store_rejects_before_admission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "take.mp4"
            out = root / "out"
            external = root / "external-store"
            media.write_bytes(b"video")
            out.mkdir()
            external.mkdir()
            (out / ".sniper-external-media").symlink_to(
                external, target_is_directory=True)
            candidates = collect_ingest_candidates([media], None, None)
            with self.assertRaisesRegex(RuntimeError, "real directory"):
                admit_ingest_candidates(candidates, out, _runner)
            self.assertEqual(list(external.iterdir()), [])

    def test_failed_reingest_cannot_break_last_good_source_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "one.mp4"
            second = root / "two.mp4"
            out = root / "out"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            initial = admit_ingest_candidates(
                collect_ingest_candidates([first], None, None), out, _runner)
            manifest = {"sourceSetAdmission": initial.binding}

            def fail_second(source: str, store: str) -> dict:
                if source == str(second):
                    raise RuntimeError("decode rejected")
                return _runner(source, store)

            candidates = collect_ingest_candidates([first, second], None, None)
            with self.assertRaisesRegex(RuntimeError, "decode rejected"):
                admit_ingest_candidates(candidates, out, fail_second)
            verify_source_set_binding(manifest, out)
            self.assertTrue((out / initial.binding["receiptPath"]).is_file())

    def test_retained_authority_rejects_symlinked_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "take.mp4"
            out = root / "out"
            media.write_bytes(b"video")
            admitted = admit_ingest_candidates(
                collect_ingest_candidates([media], None, None), out, _runner)
            manifest = {"sourceSetAdmission": admitted.binding}
            receipt = out / admitted.binding["receiptPath"]
            payload = receipt.read_bytes()
            external = root / "forged-source-set.json"
            external.write_bytes(payload)
            receipt.unlink()
            receipt.symlink_to(external)
            with self.assertRaisesRegex(
                    RuntimeError, "source-set receipt is unavailable"):
                verify_source_set_binding(manifest, out)

    def test_manifest_consumes_snapshots_for_source_broll_and_music(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "output"
            (root / "broll").mkdir()
            (root / "music").mkdir()
            (root / "take.mp4").write_bytes(b"video")
            (root / "broll" / "shot.png").write_bytes(b"image")
            (root / "music" / "bed.wav").write_bytes(b"music")
            with patch("ingest_admission.admit_external_media", side_effect=_runner), \
                    patch("ingest_admitted_sources.probe_media", side_effect=_probe), \
                    patch("ingest_admitted_scan.probe_media", side_effect=_probe), \
                    patch("ingest.scan_builtin_music", return_value=[]):
                manifest = ingest.build_manifest(root, out, no_transcribe=True)
            verify_source_set_binding(manifest, out)
            rows = [*manifest["sources"], *manifest["broll"], *manifest["music"]]
            self.assertEqual(manifest["sourceSetAdmission"]["entryCount"], 3)
            self.assertTrue(all(".sniper-external-media" in row["path"]
                                for row in rows))
            self.assertTrue(all("sourceSha256" in row for row in rows))

if __name__ == "__main__":
    unittest.main()
