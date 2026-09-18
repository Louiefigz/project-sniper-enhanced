"""Cold caption transport tests use TEST non-media held observations only."""
from __future__ import annotations

import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _guided_caption_fixture import fixture, guard
from cut_preview_io import bound_json, digest, write_new
from guided_caption_layers import caption_page_clips, caption_prefix_request
from guided_caption_projection import capture_caption_projection
from guided_caption_records import caption_projection_record, read_caption_record
from opening_prefix_contract import CompositorPrefixRequest, HeldPrefixInput, PrefixClock, PrefixRanges


class CaptionRecordTests(unittest.TestCase):
    """A serialized record can retain observations but cannot establish provenance."""

    def setUp(self) -> None:
        """Actual file guards run against synthetic local metadata/media placeholders."""
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-caption-record-test-")
        self.root = Path(self.temp.name).resolve()
        ctx, self.binding = fixture(self.root)
        self.held = capture_caption_projection(ctx, self.binding, guard)
        self.record = caption_projection_record(self.held)

    def tearDown(self) -> None:
        """Remove only this test's isolated files."""
        self.temp.cleanup()

    def read(self, record: dict | None = None):
        """Strong read uses independently retained original binding and root."""
        return read_caption_record(record or self.record, self.binding, Path(self.held.root), guard)

    def test_exact_roundtrip_never_renders_or_discovers_cache(self) -> None:
        """Cold reconstruction cannot call ordinary materialization entrypoints."""
        with patch("captions.caption_pages.materialize_caption_pages", side_effect=AssertionError("render")), \
                patch("captions.caption_pages._current", side_effect=AssertionError("cache")):
            actual = self.read()
        self.assertEqual(actual, self.held)
        self.assertNotIn("completion", self.record)
        self.assertNotIn("burned", self.record)

    def test_cross_runtime_disk_roundtrip_keeps_original_caption_number_lexemes(self) -> None:
        """Real caption proof floats must not become integers before domain hashing."""
        path = self.root / "TEST-transport.json"
        write_new(path, self.record)
        result = self.read(bound_json(path))
        self.assertEqual(result, self.held)
        self.assertNotIn("data", self.record)
        self.assertIs(type(result.data["shards"]["entries"][0]["proof"]["edgeAlphaMax"][0]), float)

    def test_changed_original_raw_document_is_not_resealed_from_embedded_data(self) -> None:
        """Even whitespace drift must reject against held raw SHA, never repair."""
        path = Path(self.held.root) / "caption_shards.json"
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        with self.assertRaises(RuntimeError):
            self.read()
        self.assertEqual(path.read_bytes(), original + b"\n")

    def test_self_consistent_wrong_binding_and_root_reject(self) -> None:
        """Recomputing a record hash cannot replace independently held inputs."""
        for field, value in (("root", str(self.root)), ("schemaVersion", True)):
            changed = copy.deepcopy(self.record)
            changed[field] = value
            changed["recordHash"] = digest({key: item for key, item in changed.items() if key != "recordHash"})
            with self.assertRaises(RuntimeError):
                self.read(changed)
        binding = replace(self.binding, execution_input_hash="e" * 64)
        with self.assertRaisesRegex(RuntimeError, "independently"):
            read_caption_record(self.record, binding, Path(self.held.root), guard)

    def test_unknown_live_fields_unsafe_sizes_and_omitted_assets_reject(self) -> None:
        """No executable callback, unbounded stat or incomplete inventory is accepted."""
        variants = [{**self.record, "burnCompleted": True}]
        for change in (lambda row: row["files"][0].update(size_bytes=2 * 1024 ** 3 + 1),
                       lambda row: row["files"].pop(),
                       lambda row: row["files"].append(copy.deepcopy(row["files"][0]))):
            modified = copy.deepcopy(self.record)
            change(modified)
            modified["recordHash"] = digest({key: item for key, item in modified.items() if key != "recordHash"})
            variants.append(modified)
        for modified in variants:
            with self.assertRaises(RuntimeError):
                self.read(modified)
        unsafe = copy.deepcopy(self.record)
        unsafe["files"][0]["size_bytes"] = 2 ** 53
        with self.assertRaises(ValueError):
            self.read(unsafe)

    def test_same_pages_extend_full_and_opening_without_page_restart(self) -> None:
        """Later-body pages remain in full graph, original first page crosses review."""
        base = HeldPrefixInput("/TEST-base.mp4", "f" * 64, 10)
        request = CompositorPrefixRequest(base, (), (), (), PrefixClock("30", 960, 1080, 1920),
                                          PrefixRanges((0, 15), (0, 25)))
        extended = caption_prefix_request(request, self.read())
        self.assertEqual(extended.caption_tail, (2, 1))
        self.assertEqual(extended.full_clips[0], extended.opening_clips[0])
        self.assertEqual(extended.opening_clips[0]["endFrameExclusive"], 900)
        self.assertEqual(extended.full_clips[1]["startFrame"], 900)
        self.assertEqual(extended.full_clips, caption_page_clips(self.held))
        with self.assertRaises(RuntimeError):
            caption_prefix_request(extended, self.held)


if __name__ == "__main__":
    unittest.main()
