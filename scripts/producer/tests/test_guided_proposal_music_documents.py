"""Music rederivation through real fourteen-document/source-byte read boundaries."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from _guided_music_documents import admitted_values, publish, read
from guided_opening_inputs import DOCUMENTS, observe_inputs, read_current_inputs
from guided_proposal_music import guided_music_policy


class MusicDocumentTests(unittest.TestCase):
    """Private sentinel files prove relational validation, never actual media or approval."""

    def setUp(self) -> None:
        """Every case starts new and retains no source or authority from another attempt."""
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-music-documents-", dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.rows = admitted_values(self.root)

    def test_real_current_reader_and_repeated_source_read_accept_exact_selection(self) -> None:
        """All fourteen raw documents and both sentinel snapshots are independently read."""
        held = read(self.root, self.rows)
        self.assertEqual(set(held.documents), DOCUMENTS)
        self.assertEqual(held.documents["readinessPacket"]["proposal"]["schemaVersion"], 7)
        self.assertEqual(len(observe_inputs(held)), 2)

    def test_rehashed_candidate_music_still_rejects_before_any_media(self) -> None:
        """Even a coherent packet/draft/authority hash graph cannot add an unrequested knob."""
        self.rows[1]["music"]["gapDb"] = 12
        with self.assertRaisesRegex(RuntimeError, "requested music projection"):
            read(self.root, self.rows)

    def test_rehashed_policy_size_is_checked_against_real_source_set(self) -> None:
        """Manifest/policy size agreement alone cannot replace the original admission size."""
        plan, _result, packet, manifest = self.rows
        manifest["music"][0]["sourceSizeBytes"] += 1
        packet["evidence"]["musicPolicy"] = guided_music_policy(plan, manifest)
        with self.assertRaisesRegex(RuntimeError, "verified source-set"):
            read(self.root, self.rows)

    def test_rehashed_music_row_cannot_borrow_source_lane(self) -> None:
        """A source snapshot is not music merely because new manifest/policy hashes agree."""
        plan, _result, packet, manifest = self.rows
        source = deepcopy(manifest["sources"][0])
        source["id"] = manifest["music"][0]["id"]
        manifest["music"][0] = source
        packet["evidence"]["musicPolicy"] = guided_music_policy(plan, manifest)
        with self.assertRaisesRegex(RuntimeError, "absent from its source set"):
            read(self.root, self.rows)

    def test_snapshot_byte_drift_rejects_on_real_reader(self) -> None:
        """A retained source-set receipt cannot grant authority to replaced snapshot bytes."""
        path, sha256 = publish(self.root, self.rows)
        snapshot = Path(self.rows[3]["music"][0]["path"])
        snapshot.write_bytes(b"TEST swapped source bytes")
        with self.assertRaises(RuntimeError):
            read_current_inputs(path, sha256)

    def test_historical_rehashed_candidate_injection_rejects(self) -> None:
        """V5 retains the old music-preservation rule even if every dependent hash is fresh."""
        self.rows[2]["proposal"]["schemaVersion"] = 5
        with self.assertRaisesRegex(RuntimeError, "inherited music authority"):
            read(self.root, self.rows)


if __name__ == "__main__":
    unittest.main()
