"""Ephemeral source-set capture over real sentinel receipts, never real decode/admission."""
from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from _guided_music_documents import admitted_values
from headless import external_media_snapshot as snapshot_module
from headless.external_media_verification import SourceVerificationRuntime, snapshot_stat_identity
from ingest_admission_contract import canonical_bytes
from ingest_execution_authority import execution_media_authority_entries
from ingest_media_observation import SourceVerificationCapture


class IngestMediaObservationTests(unittest.TestCase):
    """Actual snapshot hashes are reused once; only the original admission decoder is fake."""

    def setUp(self) -> None:
        """Create two TEST sentinel sources with the existing real receipt/source-set writer."""
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-source-capture-", dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan, _candidate, _packet, self.manifest = admitted_values(self.root)
        self.manifest_path = str(self.root / "documents/asset_manifest.json")
        self.runtime = SourceVerificationRuntime(Mock(return_value=30.0))
        self.capture = SourceVerificationCapture(self.runtime)

    def verify(self, manifest: dict | None = None) -> list[dict]:
        """Use the original actual admission/projection reader with its optional collector."""
        return execution_media_authority_entries(self.plan, manifest or self.manifest, self.manifest_path, self.capture)

    def test_exact_eight_field_entries_and_two_hash_passes_are_preserved(self) -> None:
        """Each original source hash returns its identity; completion never hashes again."""
        files = list((self.root / "documents").rglob("*.json"))
        before = {str(path): path.read_bytes() for path in files}
        with patch.object(snapshot_module, "_hash_descriptor", wraps=snapshot_module._hash_descriptor) as hashes:
            entries = self.verify()
            result = self.capture.finish(entries)
        self.assertEqual(hashes.call_count, 2)
        self.assertEqual(result.entries_json, canonical_bytes(entries))
        self.assertEqual(result.entries(), entries)
        self.assertEqual(len(result.snapshots), 2)
        self.assertEqual({str(path): path.read_bytes() for path in files}, before)
        for row in result.snapshots:
            self.assertEqual(row.stat_identity, snapshot_stat_identity(Path(row.path).lstat()))
        self.assertTrue(all(len(entry) == 8 for entry in entries))

    def test_result_entries_are_fresh_copies_not_mutable_retained_json(self) -> None:
        """A consumer cannot change the retained initial entry bytes through its copy."""
        result = self.capture.finish(self.verify())
        changed = result.entries()
        changed[0]["sha256"] = "f" * 64
        self.assertNotEqual(changed, result.entries())
        with self.assertRaisesRegex(RuntimeError, "twice"):
            self.capture.finish(result.entries())

    def test_late_projection_failure_fences_all_partial_snapshots(self) -> None:
        """Successful individual hashes are not a successful executable source-set read."""
        changed = deepcopy(self.manifest)
        changed["sources"][0]["path"] = "/TEST/outside.media"
        with self.assertRaisesRegex(RuntimeError, "disagrees"):
            self.verify(changed)
        with self.assertRaisesRegex(RuntimeError, "twice"):
            self.capture.finish([])

    def test_one_corrupt_source_fences_previously_observed_siblings(self) -> None:
        """A failed complete-set verification cannot expose a partial successful record."""
        Path(self.manifest["sources"][0]["path"]).write_bytes(b"TEST changed")
        with self.assertRaisesRegex(RuntimeError, "corrupt"):
            self.verify()
        with self.assertRaisesRegex(RuntimeError, "twice"):
            self.capture.finish([])

    def test_final_callback_source_change_cannot_commit_a_late_stat_baseline(self) -> None:
        """Final clock/identity checks compare against the original descriptor observation."""
        entries = self.verify()
        changed = False

        def clock() -> float:
            """Inject after original verification and before final capture publication."""
            nonlocal changed
            if not changed:
                changed = True
                Path(entries[0]["snapshotPath"]).write_bytes(b"TEST late mutation")
            return 20.0

        self.runtime.remaining.side_effect = clock
        with self.assertRaisesRegex(RuntimeError, "identity changed"):
            self.capture.finish(entries)

    def test_final_clock_expiry_cannot_commit_or_renew_capture(self) -> None:
        """The original runtime supplies the terminal failure; no local timer is started."""
        entries = self.verify()
        self.runtime.remaining.side_effect = RuntimeError("TEST original expiry")
        with patch("signal.setitimer", side_effect=AssertionError("unexpected new clock")):
            with self.assertRaisesRegex(RuntimeError, "original expiry"):
                self.capture.finish(entries)
        with self.assertRaisesRegex(RuntimeError, "twice"):
            self.capture.finish(entries)

    def test_missing_or_extra_entry_cannot_be_committed(self) -> None:
        """The ephemeral identity collection must cover exactly the verified source set."""
        entries = self.verify()
        with self.assertRaisesRegex(RuntimeError, "complete source set"):
            self.capture.finish(entries[:1])


if __name__ == "__main__":
    unittest.main()
