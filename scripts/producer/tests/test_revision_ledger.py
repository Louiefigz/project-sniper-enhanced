"""Output-bound review history never carries an earlier verdict to changed bytes."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fingerprint_io import file_sha256
from revision_ledger import current_observations, record_audit, record_render


class RevisionLedgerTests(unittest.TestCase):
    """Both current reads and audit publication bind the complete output digest."""

    def setUp(self) -> None:
        """Use byte fixtures because this contract concerns identity, not codecs."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.final = Path(self.temp.name) / "final.mp4"
        self.final.write_bytes(b"first-output")
        self.sha = file_sha256(str(self.final))

    def test_new_render_requires_full_review_after_base_reuse(self) -> None:
        """No existing render audit can waive editorial review."""
        record_render(str(self.final), {"cutTrack": []}, {"authorityHash": self.sha})
        record_audit(str(self.final), self.sha, {"overall": "pass", "frames": []})
        records = current_observations(str(self.final))
        self.assertEqual(len(records), 2)
        self.assertTrue(all(row["fullReviewRequired"] for row in records))
        self.assertTrue(all(not row["reviewCarryForward"] for row in records))
        self.final.write_bytes(b"revised-output")
        self.assertEqual(current_observations(str(self.final)), [])
        record_render(str(self.final), {"cutTrack": [1]}, {"authorityHash": file_sha256(str(self.final))})
        self.assertEqual(current_observations(str(self.final))[0]["reviewStatus"], "pending")

    def test_changed_media_refuses_old_audit(self) -> None:
        """A completed QC report cannot be published against replacement media."""
        self.final.write_bytes(b"replacement")
        with self.assertRaisesRegex(RuntimeError, "changed output bytes"):
            record_audit(str(self.final), self.sha, {"overall": "pass"})

    def test_sampled_frames_and_tampering_are_visible(self) -> None:
        """The observation retains actual image identity and verifies its own digest."""
        frame = self.final.with_suffix(".png")
        frame.write_bytes(b"sampled-picture")
        record = record_audit(str(self.final), self.sha,
            {"frames": [{"path": str(frame), "timestamp": .25, "label": "seam"}]})
        self.assertEqual(record["sampledFrames"][0]["sha256"], file_sha256(str(frame)))
        entry = next(Path(str(self.final) + ".review-ledger").glob("*.json"))
        changed = json.loads(entry.read_text())
        changed["fullReviewRequired"] = False
        entry.write_text(json.dumps(changed))
        with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
            current_observations(str(self.final))
