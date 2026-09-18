"""Pure held-caption protocol faults; TEST bytes are not decoded-media proof."""
from __future__ import annotations

import copy
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _guided_caption_fixture import fixture, guard
from captions.caption_fingerprints import caption_compiler_hash
from captions.caption_pages import caption_page_compositor_identity
from captions.caption_plan_pipeline import PROJECTION_TOOLCHAIN
from guided_caption_dependencies import hold_caption_file, read_caption_json, stage_caption_files
from guided_caption_identity import projection_identities
from guided_caption_projection import (HeldCaptionProjection, capture_caption_projection, read_caption_projection,
                                       stage_caption_dependencies)


def unsafe_file(target: Path, kind: str, source: Path) -> None:
    """Create one deliberately unsafe TEST target, never external user files."""
    if kind == "symlink":
        target.symlink_to(source)
        return
    if kind == "fifo":
        os.mkfifo(target)
        return
    os.link(source, target)


class HeldCaptionProjectionTests(unittest.TestCase):
    """Exercise real immutable files without claiming any renderer invocation."""

    def setUp(self) -> None:
        """Build only explicitly synthetic metadata and non-media files."""
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-caption-held-test-")
        self.root = Path(self.temp.name).resolve()
        self.ctx, self.binding = fixture(self.root)

    def tearDown(self) -> None:
        """Remove this test's temporary fixtures only."""
        self.temp.cleanup()

    def capture(self) -> HeldCaptionProjection:
        """Capture typed TEST return, with no provenance or media claims."""
        return capture_caption_projection(self.ctx, self.binding, guard)

    def test_capture_read_never_materialize_and_preserve_full_later_page(self) -> None:
        """Later cues/pages remain present while every original file stays unchanged."""
        before = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with patch("captions.caption_pages.materialize_caption_pages", side_effect=AssertionError("render")), \
                patch("captions.caption_pages._current", side_effect=AssertionError("cache")), \
                patch("captions.caption_shards.materialize_caption_shards", side_effect=AssertionError("render")):
            held = self.capture()
            self.assertIs(read_caption_projection(held, self.binding, guard), held)
        self.assertEqual([row["startFrame"] for row in held.data["pages"]["entries"]], [0, 900])
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_staging_copies_only_real_audit_dependencies_newly(self) -> None:
        """Copies use new inodes; input manifests/fonts/pages never move or rewrite."""
        held = self.capture()
        destination = self.root / "new-audit-dependencies"
        rows = stage_caption_dependencies(held, self.binding, destination, guard)
        names = {Path(row.path).name for row in rows}
        self.assertIn("caption_authority.json", names)
        self.assertNotIn("asset_manifest.json", names)
        self.assertNotIn("caption_pages.json", names)
        self.assertFalse(any(name.startswith("caption-page-") for name in names))
        for row in rows:
            original = Path(held.root) / Path(row.path).name
            self.assertEqual(original.read_bytes(), Path(row.path).read_bytes())
            self.assertNotEqual(original.stat().st_ino, Path(row.path).stat().st_ino)
        with self.assertRaises(FileExistsError):
            stage_caption_dependencies(held, self.binding, destination, guard)

    def test_plan_manifest_transcript_and_timeline_mutation_reject(self) -> None:
        """All independently held original input bytes remain live dependencies."""
        held = self.capture()
        for row in (self.binding.plan, self.binding.manifest, self.binding.timeline, *self.binding.dependencies):
            path, original = Path(row.path), Path(row.path).read_bytes()
            path.write_bytes(original + b" ")
            with self.assertRaises(RuntimeError):
                read_caption_projection(held, self.binding, guard)
            path.write_bytes(original)

    def test_font_page_shard_and_sidecar_mutation_reject(self) -> None:
        """No late media/receipt/font substitution is concealed by a self-hash."""
        held = self.capture()
        targets = [row for row in held.files if ".mov" in row.path]
        targets.append(next(row for row in held.external if row.path.endswith(".ttf")))
        for row in targets:
            path, original = Path(row.path), Path(row.path).read_bytes()
            path.write_bytes(original[:-1] + b"!")
            with self.assertRaises(RuntimeError):
                read_caption_projection(held, self.binding, guard)
            path.write_bytes(original)

    def test_missing_transcript_or_media_inventory_reject(self) -> None:
        """Omitting body-only assets or transcript dependencies is not a valid read."""
        with self.assertRaisesRegex(RuntimeError, "execution/pipeline"):
            capture_caption_projection(self.ctx, replace(self.binding, dependencies=()), guard)
        held = self.capture()
        with self.assertRaisesRegex(RuntimeError, "inventory"):
            read_caption_projection(replace(held, files=held.files[:-1]), self.binding, guard)

    def test_returned_projection_context_and_frame_binding_reject(self) -> None:
        """Wrong context, clock or actual returned data cannot become captured proof."""
        with self.assertRaisesRegex(RuntimeError, "destination/full"):
            capture_caption_projection(self.ctx, replace(self.binding, frame_clock=("30", 961, 1080, 1920)), guard)
        held = self.capture()
        modified = copy.deepcopy(held)
        modified.data["pages"]["entries"][-1]["startFrame"] += 1
        with self.assertRaisesRegex(RuntimeError, "returned projection"):
            read_caption_projection(modified, self.binding, guard)
        self.ctx.plan = {**self.ctx.plan, "unexpected": True}
        with self.assertRaisesRegex(RuntimeError, "context"):
            self.capture()

    def test_link_fifo_and_staging_under_original_tree_reject(self) -> None:
        """Refuse blocking reads and writing anywhere beneath the held generation."""
        held = self.capture()
        source = Path(held.files[0].path)
        for kind in ("symlink", "fifo", "hardlink"):
            target = self.root / kind
            unsafe_file(target, kind, source)
            with self.assertRaises((OSError, RuntimeError)):
                hold_caption_file(target, guard)
            target.unlink()
        with self.assertRaisesRegex(RuntimeError, "retained source tree"):
            stage_caption_dependencies(held, self.binding, Path(held.root) / "nested", guard)

    def test_guard_exhaustion_stops_read_and_retains_partial_stage(self) -> None:
        """A late original deadline never produces a successful stage/read return."""
        held = self.capture()
        with self.assertRaisesRegex(RuntimeError, "expired"):
            read_caption_projection(held, self.binding, lambda: (_ for _ in ()).throw(RuntimeError("expired")))
        destination = self.root / "partial"
        def expire_after_write() -> None:
            """Inject expiry after actual new file creation, not before work starts."""
            if destination.exists() and list(destination.iterdir()):
                raise RuntimeError("expired")
        with self.assertRaisesRegex(RuntimeError, "expired"):
            stage_caption_files((held.files[0],), destination, expire_after_write)
        self.assertTrue(destination.exists())
        self.assertTrue(list(destination.iterdir()))

    def test_strict_json_rejects_duplicate_fields_and_nonfinite_overflow(self) -> None:
        """Exact byte bindings do not excuse malformed or ambiguous JSON."""
        path = self.root / "bad.json"
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'[]'):
            path.write_bytes(raw)
            with self.assertRaises(RuntimeError):
                read_caption_json(hold_caption_file(path, guard), guard)

    def test_guarded_identity_matches_existing_compiler_and_page_domains(self) -> None:
        """The safe reader changes I/O ownership, never the renderer's cache keys."""
        identities = projection_identities(self.capture().external)
        tools, compositor = caption_page_compositor_identity()
        self.assertEqual(identities, {"compiler": caption_compiler_hash(PROJECTION_TOOLCHAIN),
                                     "tools": tools, "compositor": compositor})

    def test_external_omission_and_wrong_returned_path_reject(self) -> None:
        """An omitted font/code/tool reference cannot qualify an otherwise exact read."""
        held = self.capture()
        with self.assertRaisesRegex(RuntimeError, "external inventory"):
            read_caption_projection(replace(held, external=held.external[:-1]), self.binding, guard)
        changed = replace(self.ctx.caption_projection.artifacts, ass=str(self.root / "wrong.ass"))
        self.ctx.caption_projection = replace(self.ctx.caption_projection, artifacts=changed)
        with self.assertRaisesRegex(RuntimeError, "artifact path"):
            self.capture()

    def test_staging_parent_swap_cannot_redirect_any_file(self) -> None:
        """A real rename+symlink at mkdir stays confined to the held parent FD."""
        held = self.capture()
        parent, moved, other = (self.root / name for name in ("parent", "moved", "other"))
        parent.mkdir()
        other.mkdir()
        original = os.mkdir
        def swap(path: str | Path, mode: int = 0o777, *, dir_fd: int | None = None) -> None:
            """Swap only this test's parent at the exact child creation boundary."""
            if path == "new" and dir_fd is not None:
                parent.rename(moved)
                parent.symlink_to(other, target_is_directory=True)
            return original(path, mode, dir_fd=dir_fd)
        with patch("guided_caption_dependencies.os.mkdir", side_effect=swap):
            with self.assertRaises((OSError, RuntimeError)):
                stage_caption_files((held.files[0],), parent / "new", guard)
        self.assertEqual(list(other.iterdir()), [])
        self.assertTrue((moved / "new").is_dir())

    def test_deadline_mid_file_does_not_read_the_rest(self) -> None:
        """Bounded per-chunk guards interrupt large metadata/media reads promptly."""
        path = self.root / "chunked.bin"
        path.write_bytes(b"x" * (3 * 1024 * 1024))
        original, counts = os.read, []
        def read(fd: int, count: int) -> bytes:
            """Count actual read bytes without changing their content."""
            result = original(fd, count)
            counts.append(len(result))
            return result
        def expire() -> None:
            """Expire once the first bounded chunk was actually read."""
            if counts:
                raise RuntimeError("expired")
        with patch("guided_caption_dependencies.os.read", side_effect=read):
            with self.assertRaisesRegex(RuntimeError, "expired"):
                hold_caption_file(path, expire)
        self.assertEqual(counts, [1024 * 1024])

    def test_preflight_growth_rejects_before_reading_expanded_bytes(self) -> None:
        """The opened FD must retain the caller's exact aggregate-admitted size."""
        path = self.root / "growing.bin"
        path.write_bytes(b"held")
        original = os.open
        def expand(value: str | Path, flags: int, *args, **kwargs) -> int:
            """Grow this TEST file only at the descriptor-open boundary."""
            if Path(value) == path:
                path.write_bytes(b"not the four admitted bytes")
            return original(value, flags, *args, **kwargs)
        with patch("guided_caption_dependencies.os.open", side_effect=expand), \
                patch("guided_caption_dependencies.os.read", side_effect=AssertionError("must not read")):
            with self.assertRaisesRegex(RuntimeError, "preflight size changed"):
                hold_caption_file(path, guard, expected_size=4)


if __name__ == "__main__":
    unittest.main()
