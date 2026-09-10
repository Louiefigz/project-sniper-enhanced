"""Initial opening read/capture wiring with real metadata and fake execution only."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from _guided_music_documents import admitted_values, publish
from headless import external_media_snapshot as snapshot_module
from headless.external_media_verification import SourceVerificationRuntime
from ingest_media_observation import SourceVerificationCapture
from guided_opening_inputs import observe_inputs, read_current_inputs


class GuidedOpeningSourceCaptureTests(unittest.TestCase):
    """Fourteen-document reads retain initial source identities without re-verification."""

    def setUp(self) -> None:
        """Create only sentinel assets and explicitly TEST-only approval-shaped documents."""
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-opening-source-capture-", dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path, self.sha = publish(self.root, admitted_values(self.root))
        self.runtime = SourceVerificationRuntime(Mock(return_value=30.0))

    def test_initial_capture_retains_same_pass_and_final_revalidation_is_unchanged(self) -> None:
        """Initial read hashes each source once; later whole-source verification remains real."""
        with patch.object(snapshot_module, "_hash_descriptor", wraps=snapshot_module._hash_descriptor) as hashes:
            inputs = read_current_inputs(self.path, self.sha, self.runtime)
            self.assertEqual(hashes.call_count, 2)
            captured = inputs.verified_media
            entries = captured.entries()
            self.assertEqual(len(captured.snapshots), 2)
            self.assertEqual(observe_inputs(inputs), entries)
            self.assertEqual(hashes.call_count, 4)
        self.assertIs(inputs.verified_media, captured)
        self.assertNotIn("verified_media", inputs.value)

    def test_legacy_read_has_no_capture_and_same_documents(self) -> None:
        """Historical/default callers do not acquire new persisted fields or policy tokens."""
        old = read_current_inputs(self.path, self.sha)
        self.assertIsNone(old.verified_media)
        new = read_current_inputs(self.path, self.sha, self.runtime)
        self.assertEqual((old.path, old.sha256, old.value, old.documents),
                         (new.path, new.sha256, new.value, new.documents))

    def test_late_requested_music_failure_aborts_initial_capture(self) -> None:
        """Hash completion cannot bypass later actual requested-media admission checks."""
        capture = SourceVerificationCapture(self.runtime)
        with patch("guided_opening_inputs.SourceVerificationCapture", return_value=capture):
            with patch("guided_opening_inputs.verify_music_admission", side_effect=RuntimeError("TEST requested music")):
                with self.assertRaisesRegex(RuntimeError, "requested music"):
                    read_current_inputs(self.path, self.sha, self.runtime)
        with self.assertRaisesRegex(RuntimeError, "twice"):
            capture.finish([])

    def test_expired_original_clock_refuses_before_invocation_bytes(self) -> None:
        """An already-expired caller cannot begin another metadata/source verification phase."""
        self.runtime.remaining.return_value = 0
        with patch("guided_opening_inputs._json") as reader, self.assertRaisesRegex(RuntimeError, "expired"):
            read_current_inputs(self.path, self.sha, self.runtime)
        reader.assert_not_called()

    def test_production_run_passes_its_same_original_clock_to_initial_read_once(self) -> None:
        """Stub execution only; the production entry borrows its existing phase clock."""
        import guided_opening_media as media

        clock = Mock()
        clock.remaining.return_value = 25.0
        clock.phase.side_effect = lambda _name, operation: operation()
        claim = SimpleNamespace(path=self.root / "TEST-claim", sha256="a" * 64)
        with patch.object(media, "opening_clock", return_value=clock), patch.object(media, "_directory"), \
                patch.object(media, "read_execution_claim", return_value=claim), patch.object(media, "write_new"), \
                patch.object(media, "read_current_inputs", return_value=Mock()) as reader, \
                patch.object(media, "_execute", return_value={"TEST": "no actual execution"}):
            result = media.run(self.path, self.root, (self.sha, 25.0, claim.path, claim.sha256))
        self.assertEqual(result, {"TEST": "no actual execution"})
        self.assertEqual(reader.call_count, 1)
        runtime = reader.call_args.args[2]
        self.assertIs(type(runtime), SourceVerificationRuntime)
        self.assertIs(runtime.remaining, clock.remaining)


if __name__ == "__main__":
    unittest.main()
