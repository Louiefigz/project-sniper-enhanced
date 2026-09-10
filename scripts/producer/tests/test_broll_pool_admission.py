"""Fail-closed authority tests for late b-roll pool cataloging."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from _ingest_admission_fixture import probe as admission_probe
from _broll_pool_authority_fixture import build_pool_authority
from broll import broll_pool
from broll.pool_frames import extract_frames
from broll.pool_admission import open_pool
from broll.pool_views import manifest_entries
from ingest_execution_authority import verify_execution_media_authority


class BrollPoolAdmissionTests(unittest.TestCase):
    def _pool(self, root: Path) -> Path:
        pool = root / "broll"
        pool.mkdir()
        (pool / "clip.mp4").write_bytes(b"fixture-video")
        return pool

    def test_new_media_requires_canonical_reingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(Path(tmp))
            manifest, _ = build_pool_authority(pool)
            (pool / "late.mp4").write_bytes(b"late-video")
            with self.assertRaisesRegex(
                    RuntimeError, "re-run canonical ingest"):
                open_pool(pool, manifest)

    def test_snapshot_tamper_rejects_before_catalog_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(Path(tmp))
            manifest, authority = build_pool_authority(pool)
            asset = next(iter(authority.assets.values()))
            Path(asset.snapshot_path).write_bytes(b"tampered")
            with patch("broll.broll_pool.probe_media") as probe:
                with self.assertRaisesRegex(RuntimeError, "corrupt"):
                    broll_pool._dispatch(Namespace(
                        cmd="scan", broll_dir=str(pool),
                        manifest=str(manifest)))
            probe.assert_not_called()

    def test_catalog_cannot_substitute_unbound_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(Path(tmp))
            _, authority = build_pool_authority(pool)
            asset = next(iter(authority.assets.values()))
            row = {
                "id": "clip",
                "path": asset.snapshot_path,
                "originalPath": asset.original_path,
                "sourceSha256": "0" * 64,
                "admissionReceiptPath": asset.receipt_path,
                "admissionReceiptSha256": asset.receipt_sha256,
                "cataloged": True,
            }
            (pool / "broll_catalog.json").write_text(json.dumps([row]))
            with self.assertRaisesRegex(
                    RuntimeError, "disagrees with admission"):
                broll_pool.load_catalog(authority)

    def test_dispatch_rejects_symlinked_pool_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(Path(tmp))
            manifest, _ = build_pool_authority(pool)
            alias = Path(tmp) / "pool-alias"
            os.symlink(pool, alias)
            args = Namespace(
                cmd="scan", broll_dir=str(alias), manifest=str(manifest))
            with self.assertRaisesRegex(RuntimeError, "non-symlink"):
                broll_pool._dispatch(args)

    def test_duplicate_catalog_identity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(Path(tmp))
            _, authority = build_pool_authority(pool)
            asset = next(iter(authority.assets.values()))
            row = {
                "id": "clip",
                "path": asset.snapshot_path,
                "originalPath": asset.original_path,
                "sourceSha256": asset.sha256,
                "admissionReceiptPath": asset.receipt_path,
                "admissionReceiptSha256": asset.receipt_sha256,
                "cataloged": True,
            }
            duplicate = {
                **row,
                "id": "alternate",
                "path": str(pool / "already-missing.media"),
            }
            (pool / "broll_catalog.json").write_text(
                json.dumps([duplicate, row]))
            with self.assertRaisesRegex(RuntimeError, "repeats an originalPath"):
                broll_pool.load_catalog(authority)

    def test_scan_probes_and_extracts_only_from_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(Path(tmp))
            _, authority = build_pool_authority(pool)
            asset = next(iter(authority.assets.values()))
            with patch(
                    "broll.broll_pool.probe_media",
                    side_effect=admission_probe) as probe, patch(
                    "broll.broll_pool.extract_frames",
                    return_value=[]) as extract:
                broll_pool.scan_pool(authority)
            probe.assert_called_once_with(asset.snapshot_path)
            self.assertEqual(extract.call_args.args[0], Path(asset.snapshot_path))
            self.assertNotEqual(asset.original_path, asset.snapshot_path)

    def test_emitted_manifest_row_passes_execution_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(Path(tmp))
            manifest_path, authority = build_pool_authority(pool)
            asset = next(iter(authority.assets.values()))
            row = {
                "id": "clip",
                "path": asset.snapshot_path,
                "originalPath": asset.original_path,
                "sourceSha256": asset.sha256,
                "admissionReceiptPath": asset.receipt_path,
                "admissionReceiptSha256": asset.receipt_sha256,
                "kind": "video",
                "cataloged": True,
            }
            manifest = json.loads(manifest_path.read_text())
            manifest["broll"] = manifest_entries([row])
            self.assertTrue(verify_execution_media_authority(
                {}, manifest, str(manifest_path)))

    def test_open_pool_hashes_each_snapshot_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool = self._pool(Path(tmp))
            manifest, _ = build_pool_authority(pool)
            with patch(
                "ingest_admission_contract.verify_external_media_snapshot"
            ) as snapshot_check:
                open_pool(pool, manifest)
            self.assertEqual(snapshot_check.call_count, 1)

    def test_frame_output_rejects_poisoned_id_and_symlink_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "snapshot.media"
            snapshot.write_bytes(b"video")
            poisoned = {
                "id": "../../escape", "kind": "video", "duration": 1.0}
            with self.assertRaisesRegex(RuntimeError, "unsafe asset id"):
                extract_frames(snapshot, poisoned, root)
            outside = root / "outside"
            outside.mkdir()
            os.symlink(outside, root / ".frames")
            safe = {"id": "safe-id", "kind": "video", "duration": 1.0}
            with self.assertRaisesRegex(RuntimeError, "must not be a symlink"):
                extract_frames(snapshot, safe, root)
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
