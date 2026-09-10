"""TEST ONLY publication of simulated correction; no real creator approval."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from _corrected_manifest_fixture import CorrectedManifestFixture
from ingest_execution_authority import execution_media_authority_entries
import publish_corrected_transcript_manifest as publisher
from transcript_timing_correction_authority import CorrectionInput


class CorrectedManifestPublicationTests(unittest.TestCase):
    """Exercise actual correction/admission stores, new-only writes and rechecks."""

    def setUp(self) -> None:
        """Create a new isolated, explicitly simulated correction transaction."""
        self.fixture = CorrectedManifestFixture()
        self.addCleanup(self.fixture.close)
        self.fixture.commit()

    def test_only_pointer_changes_in_same_admitted_directory(self) -> None:
        """Keep all parent bytes and actual admission references unchanged."""
        fx = self.fixture
        before = fx.publish("status")
        self.assertEqual(before["state"], "not-published")
        self.assertFalse(fx.target.exists())
        result = fx.publish()
        self.assertEqual(result["state"], "published")
        self.assertFalse(result["replayed"])
        self.assertEqual(result["manifestSha256"], fx.sha(fx.target))
        self.assertEqual(fx.target.parent, fx.manifest.parent)
        expected = json.loads(fx.originals[fx.manifest])
        expected["sources"][0]["transcriptPath"] = str(Path(fx.committed["revision"]["path"])
                                                      .relative_to(fx.manifest.parent))
        self.assertEqual(fx.revised(), expected)
        entries = execution_media_authority_entries(json.loads(fx.plan.read_text()), fx.revised(), str(fx.target))
        self.assertEqual(entries[0]["snapshotPath"], str(fx.media))
        self.assertEqual(fx.originals, {path: path.read_bytes() for path in fx.originals})
        for flag in ("selected", "approvalsTransferred", "deliveryApproved", "newPlanWritten"):
            self.assertFalse(result[flag])
        self.assertTrue(result["freshCutRevisionRequired"])

    def test_exact_replay_is_read_only(self) -> None:
        """An identical command observes rather than rewrites its artifact."""
        fx = self.fixture
        fx.publish()
        before = fx.target.stat()
        self.assertTrue(fx.publish()["replayed"])
        self.assertEqual(before, fx.target.stat())
        self.assertEqual(fx.publish("status")["state"], "published")

    def test_expected_hashes_are_not_inferred(self) -> None:
        """Require each explicitly supplied correction binding independently."""
        fx = self.fixture
        for key in ("expectedRequestHash", "expectedRecordHash", "expectedCorrectedTranscriptSha256"):
            sent = {**fx.publication, key: "a" * 64}
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "bindings changed"):
                publisher.execute("publish", fx.inputs, fx.proposed, sent)
            self.assertFalse(fx.target.exists())

    def test_no_unknown_authority_or_boolean_schema(self) -> None:
        """Reject extra authority and coercible protocol identity fields."""
        fx = self.fixture
        for sent in ({**fx.publication, "selected": True}, {**fx.publication, "schemaVersion": True}):
            with self.assertRaises(RuntimeError):
                publisher.execute("publish", fx.inputs, fx.proposed, sent)
        self.assertFalse(fx.target.exists())

    def test_partial_conflict_symlink_and_hardlink_do_not_get_overwritten(self) -> None:
        """Never overwrite or follow conflicting/linked destination artifacts."""
        fx = self.fixture
        fx.target.write_text('{"partial":')
        with self.assertRaisesRegex(RuntimeError, "conflicts"):
            fx.publish()
        self.assertEqual(fx.target.read_text(), '{"partial":')
        fx.target.unlink()  # Exact TEST artifact, owned by this case.
        fx.target.symlink_to(fx.manifest)
        with self.assertRaises((OSError, RuntimeError)):
            fx.publish()
        fx.target.unlink()
        fx.target.hardlink_to(fx.manifest)
        with self.assertRaises((OSError, RuntimeError)):
            fx.publish()
        self.assertEqual(fx.manifest.read_bytes(), fx.originals[fx.manifest])

    def test_mutated_parent_and_corrected_bytes_block_before_publication(self) -> None:
        """Reconstruct current parent and corrected bytes before a new write."""
        fx = self.fixture
        path = Path(fx.committed["revision"]["path"])
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        with self.assertRaises(RuntimeError):
            fx.publish()
        self.assertFalse(fx.target.exists())
        path.write_bytes(original)
        fx.manifest.write_bytes(fx.originals[fx.manifest] + b" ")
        with self.assertRaises(RuntimeError):
            fx.publish()
        self.assertFalse(fx.target.exists())

    def test_changed_record_is_not_accepted_on_replay(self) -> None:
        """A previous manifest file cannot authorize a stale decision chain."""
        fx = self.fixture
        fx.publish()
        record = Path(fx.committed["revision"]["recordPath"])
        record.write_bytes(record.read_bytes() + b" ")
        with self.assertRaises(RuntimeError):
            fx.publish("status")
        self.assertTrue(fx.target.exists())

    def test_parent_expiry_blocks_without_read_or_write(self) -> None:
        """Decline expired work before invoking the expensive source reader."""
        fx = self.fixture
        with patch.object(publisher, "correction_status") as observe:
            with self.assertRaisesRegex(RuntimeError, "budget"):
                publisher.execute("publish", replace(fx.inputs, parent_deadline=time.monotonic() - 1),
                                  fx.proposed, fx.publication)
            observe.assert_not_called()
        self.assertFalse(fx.target.exists())

    def test_second_observation_shares_exact_original_deadline(self) -> None:
        """Both independent source observations share one caller expiry."""
        fx = self.fixture
        original = publisher.correction_status
        deadlines = []
        def tracked(command: str, inputs: CorrectionInput, proposed: dict) -> dict:
            """Observe unchanged production calls without replacing validation."""
            deadlines.append(inputs.parent_deadline)
            return original(command, inputs, proposed)
        with patch.object(publisher, "correction_status", side_effect=tracked):
            fx.publish()
        self.assertEqual(len(deadlines), 2)
        self.assertEqual(deadlines[0], deadlines[1])

    def test_post_write_authority_failure_does_not_report_success(self) -> None:
        """Retain an unselected artifact when its final authority check fails."""
        fx = self.fixture
        original = publisher.correction_status
        calls = 0
        def changed(command: str, inputs: CorrectionInput, proposed: dict) -> dict:
            """Inject an explicit post-write observation failure."""
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("TEST simulated changed correction after publication")
            return original(command, inputs, proposed)
        with patch.object(publisher, "correction_status", side_effect=changed):
            with self.assertRaisesRegex(RuntimeError, "changed correction"):
                fx.publish()
        self.assertTrue(fx.target.exists())  # New artifact remains unselected, never hidden/deleted.
        self.assertEqual(fx.originals, {path: path.read_bytes() for path in fx.originals})

    def test_readonly_status_never_creates_a_missing_manifest(self) -> None:
        """The observation command cannot publish a new manifest."""
        result = self.fixture.publish("status")
        self.assertFalse(self.fixture.target.exists())
        self.assertEqual(result["state"], "not-published")


if __name__ == "__main__":
    unittest.main()
