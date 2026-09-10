"""Fault injection for opt-in audio publication, not a crash-atomicity claim."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio import assemble_publication as publication
from cut_preview_io import file_hash


class AssemblyPublicationTests(unittest.TestCase):
    """Exact support/final rollback and a closed interrupted-write read state."""

    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir="/private/tmp")))
        self.private = self.root / "private"
        self.private.mkdir()
        self.entries = {}
        self.before = {}
        self.originals = {}
        for name in ("support-a.json", "new-support.json", "final.mp4.assembled.json", "final.mp4"):
            if name != "new-support.json":
                raw = ("OLD TEST ONLY " + name).encode()
                (self.root / name).write_bytes(raw)
                self.originals[name] = raw
            (self.private / name).write_text("NEW TEST ONLY " + name)
            self.entries[name] = (self.private / name, file_hash(self.private / name))
            self.before[str(self.root / name)] = publication.optional_hash(self.root / name)

    def assert_restored(self) -> None:
        for name, raw in self.originals.items():
            self.assertEqual((self.root / name).read_bytes(), raw)
        self.assertFalse((self.root / "new-support.json").exists())
        self.assertFalse((self.root / publication.PENDING_PUBLICATION).exists())

    def test_failure_after_first_public_support_write_restores_every_original(self) -> None:
        original = os.replace
        written = []
        def fail(source, destination):
            if Path(source).parent.name == "new" and Path(destination).parent == self.root:
                written.append(Path(destination).name)
                if len(written) == 2:
                    raise OSError("TEST ONLY support publication failure")
            return original(source, destination)
        with patch.object(publication.os, "replace", side_effect=fail):
            with self.assertRaisesRegex(OSError, "TEST ONLY"):
                publication.publish_files(self.root, self.entries, self.before, lambda: None)
        self.assertEqual(written, ["support-a.json", "new-support.json"])
        self.assert_restored()

    def test_source_recheck_failure_before_final_restores_new_and_old_support(self) -> None:
        calls = []
        def changed() -> None:
            calls.append(True)
            if len(calls) == 2:
                raise RuntimeError("TEST ONLY source changed before final")
        with self.assertRaisesRegex(RuntimeError, "source changed"):
            publication.publish_files(self.root, self.entries, self.before, changed)
        self.assert_restored()

    def test_new_outputs_are_removed_on_post_final_recheck_failure(self) -> None:
        calls = []
        def changed() -> None:
            calls.append(True)
            if len(calls) == 3:
                raise RuntimeError("TEST ONLY source changed after final")
        with self.assertRaisesRegex(RuntimeError, "source changed"):
            publication.publish_files(self.root, self.entries, self.before, changed)
        self.assert_restored()

    def test_prior_output_race_rejects_before_any_public_mutation(self) -> None:
        (self.root / "support-a.json").write_text("OTHER WRITER")
        with self.assertRaisesRegex(RuntimeError, "public support changed"):
            publication.publish_files(self.root, self.entries, self.before, lambda: None)
        self.assertEqual((self.root / "support-a.json").read_text(), "OTHER WRITER")
        self.assertEqual((self.root / "final.mp4").read_bytes(), self.originals["final.mp4"])

    def test_interruption_retains_marker_and_closed_read_state(self) -> None:
        calls = []
        def interrupted() -> None:
            calls.append(True)
            if len(calls) == 2:
                raise SystemExit("TEST ONLY abrupt process interruption")
        with self.assertRaises(SystemExit):
            publication.publish_files(self.root, self.entries, self.before, interrupted)
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            publication.require_settled(self.root)
        self.assertEqual((self.root / "final.mp4").read_bytes(), self.originals["final.mp4"])
        self.assertTrue(list(self.root.glob(".source-audio-publication-*/old/final.mp4")))

    def test_success_promotes_all_prepared_files_and_clears_marker(self) -> None:
        publication.publish_files(self.root, self.entries, self.before, lambda: None)
        for name, (_, expected) in self.entries.items():
            self.assertEqual(file_hash(self.root / name), expected)
        publication.require_settled(self.root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
