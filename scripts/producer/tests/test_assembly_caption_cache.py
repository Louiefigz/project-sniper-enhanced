"""Ordinary isolated caption-cache seeding; inert bytes are not media approval."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audio import assemble_publication as publication
from audio import assemble_source_audio as assembly
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2
from cut_preview_io import file_hash
from tests._caption_legacy_fixture import plan as caption_plan


class AssemblyCaptionCacheTests(unittest.TestCase):
    """Exercise the real staging boundary, not a cache directory abstraction."""

    def setUp(self) -> None:
        """Create a valid ordinary plan with opaque, paired cache candidates."""
        temporary = tempfile.TemporaryDirectory(prefix="sniper-caption-seed-", dir="/private/tmp")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.media = self.root / ("caption-shard-" + "a" * 64 + ".mov")
        self.receipt = Path(str(self.media) + ".json")
        self.media.write_bytes(b"TEST ONLY opaque media candidate")
        self.receipt.write_text('{"untrusted":"must still validate"}')
        (self.root / "caption_shards.json").write_text(json.dumps({
            "entries": [{"media": {"name": self.media.name}}]}))
        self.job = SimpleNamespace(plan=caption_plan(), out=str(self.root / "final.mp4"),
            audio_clock_policy=SOURCE_FLOAT_POLICY_V2, plan_path=str(self.root / "edit_plan.json"),
            owned_graphics=None)
        self._save_plan()

    def _save_plan(self) -> None:
        """Keep initial plan bytes consistent before actual stage admission."""
        Path(self.job.plan_path).write_text(json.dumps(self.job.plan))

    def test_complete_pairs_seed_private_bytes_and_keep_original_holds(self) -> None:
        """A cache candidate is copied, never linked, or accepted as a receipt."""
        candidate = assembly._stage(self.job)
        for original in (self.media, self.receipt):
            copied = candidate.directory / original.name
            self.assertEqual(copied.read_bytes(), original.read_bytes())
            self.assertNotEqual(copied.stat().st_ino, original.stat().st_ino)
            self.assertEqual(candidate.before[str(original)], file_hash(original))
        assembly._assert_held(candidate)
        (candidate.directory / self.media.name).write_bytes(b"private overwrite")
        self.assertEqual(self.media.read_bytes(), b"TEST ONLY opaque media candidate")

    def test_incomplete_pairs_are_not_seeded(self) -> None:
        """Never scan new files to fill a missing originally observed partner."""
        self.receipt.unlink()
        candidate = assembly._stage(self.job)
        self.assertFalse((candidate.directory / self.media.name).exists())

    def test_source_change_after_seeding_still_refuses_original_hold(self) -> None:
        """The copy is not permission to release or replace original public holds."""
        candidate = assembly._stage(self.job)
        self.media.write_bytes(b"concurrent source mutation")
        with self.assertRaisesRegex(RuntimeError, "held inputs or public outputs changed"):
            assembly._assert_held(candidate)

    def test_noncaption_and_owned_graph_do_not_import_ordinary_cache(self) -> None:
        """Guided held captions must use their owned execution, not caller hints."""
        with patch.object(publication, "copy_verified", side_effect=AssertionError("cache copied")):
            self.job.owned_graphics = object()
            assembly._stage(self.job)
            self.job.owned_graphics = None
            self.job.plan.pop("captionsTrack")
            self._save_plan()
            assembly._stage(self.job)

    def test_held_preparation_does_not_import_ordinary_cache(self) -> None:
        """No caller cache crosses the separately held preparation boundary."""
        held = SimpleNamespace(root=self.root, support={})
        with patch.object(publication, "copy_verified", side_effect=AssertionError("cache copied")):
            candidate = assembly._stage(self.job, held)
        self.assertFalse((candidate.directory / self.media.name).exists())

    def test_no_arbitrary_support_or_unbound_composite_seed(self) -> None:
        """Graphics placement evidence is not silently inferred from picture bytes."""
        for name in ("unrelated.mov", "caption-shard-not-a-hash.mov", "graphics_placements.json",
                     ".caption-free-composite.mp4", ".caption-free-composite.json"):
            (self.root / name).write_bytes(b"unrelated retained support")
        candidate = assembly._stage(self.job)
        self.assertEqual({path.name for path in candidate.directory.iterdir()},
                         {"edit_plan.json", self.media.name, self.receipt.name})

    def test_changed_partner_during_copy_refuses_without_public_write(self) -> None:
        """A later read cannot bless a receipt replaced after the original hold."""
        original = publication.copy_verified

        def mutate(source: Path, destination: Path, expected: str) -> None:
            """Replace only the test receipt after the original media copy."""
            original(source, destination, expected)
            if source == self.media:
                self.receipt.write_text('{"concurrent":"replacement"}')

        with patch.object(publication, "copy_verified", side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, "support changed before publication"):
                assembly._stage(self.job)
        self.assertFalse((self.root / "final.mp4").exists())
        self.assertEqual(self.media.read_bytes(), b"TEST ONLY opaque media candidate")

    def test_cache_symlink_is_not_followed(self) -> None:
        """Reuse cannot bypass the original no-follow public snapshot."""
        target = self.root / "unrelated.txt"
        target.write_bytes(self.media.read_bytes())
        self.media.unlink()
        self.media.symlink_to(target)
        with self.assertRaises((OSError, RuntimeError)):
            assembly._stage(self.job)

    def test_obsolete_pairs_not_in_prior_active_manifest_are_not_copied(self) -> None:
        """Revision history must not grow each private seed by every old shard."""
        old = self.root / ("caption-shard-" + "b" * 64 + ".mov")
        old.write_bytes(b"obsolete page")
        Path(str(old) + ".json").write_text("{}")
        candidate = assembly._stage(self.job)
        self.assertFalse((candidate.directory / old.name).exists())
        self.assertTrue((candidate.directory / self.media.name).exists())

    def test_malformed_or_missing_cache_manifest_is_only_a_cache_miss(self) -> None:
        """A bad hint does not become authority or prevent a fresh caption build."""
        manifest = self.root / "caption_shards.json"
        for raw in ("broken JSON", "[]", '{"entries":3}', '{"entries":[{"media":{"name":"../escape.mov"}}]}'):
            manifest.write_text(raw)
            candidate = assembly._stage(self.job)
            self.assertFalse((candidate.directory / self.media.name).exists())
        manifest.unlink()
        candidate = assembly._stage(self.job)
        self.assertFalse((candidate.directory / self.media.name).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
