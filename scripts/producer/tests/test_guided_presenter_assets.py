"""Pure selected-admission TEST metadata, not actual source or media qualification."""
from __future__ import annotations

import copy
import unittest
from dataclasses import FrozenInstanceError
from itertools import product
from unittest.mock import patch

from graphics.presenter_layout_contract import PresenterCanvas
from guided_presenter_assets import PRESENTER_ASSET_SCOPE, select_presenter_assets
from test_presenter_layout_geometry import _payload

_SOURCE_SHA = "a" * 64
_RECEIPT_SHA = "b" * 64


def _window(index: int = 7, start: int = 0, end: int = 60, asset_id: str = "slide-1") -> dict:
    """Build a TEST window preserving its distinct original operation index."""
    layout = _payload()
    layout["assetId"] = asset_id
    return {"operationIndex": index, "startFrame": start, "endFrameExclusive": end, "layout": layout}


def _metadata() -> tuple[dict, dict]:
    """Mirror real admission field names and paths using invented, unopened bytes."""
    row = {"id": "slide-1", "kind": "image", "duration": None, "resolution": [1920, 1080],
        "originalPath": "/TEST/ingress/slide.png", "sourceSha256": _SOURCE_SHA,
        "path": f"/TEST/producer/.sniper-external-media/{_SOURCE_SHA}.media", "sourceSizeBytes": 1234,
        "admissionReceiptPath": f".sniper-external-media/receipts/{_RECEIPT_SHA}.json",
        "admissionReceiptSha256": _RECEIPT_SHA}
    entry = {"lane": "broll", "mediaKind": "still-image", "originalPath": row["originalPath"],
        "snapshotPath": row["path"], "sha256": _SOURCE_SHA, "sizeBytes": row["sourceSizeBytes"],
        "admissionReceiptPath": row["admissionReceiptPath"], "admissionReceiptSha256": _RECEIPT_SHA}
    return row, entry


class GuidedPresenterAssetTests(unittest.TestCase):
    """Closed metadata joins; no media, paths or receipts in this fixture are real."""

    def setUp(self) -> None:
        """Start each fault with one independent untouched TEST admission."""
        self.row, self.entry = _metadata()
        self.plan = {"presenterLayouts": [_window()]}
        self.manifest = {"broll": [self.row]}
        self.entries = [self.entry]
        self.canvas = PresenterCanvas(1920, 1080, 120, "yuv420p")

    def select(self) -> tuple:
        """Invoke only the pure metadata bridge against this test's state."""
        return select_presenter_assets(self.plan, self.manifest, self.entries, self.canvas)

    def test_exact_still_admission_returns_immutable_unqualified_metadata(self) -> None:
        """The exact join retains hashes/size/lane but cannot grant media eligibility."""
        selected = self.select()[0]
        self.assertEqual(selected.operation_index, 7)
        self.assertEqual(selected.admission.source_size_bytes, 1234)
        self.assertEqual(selected.admission.source_sha256, _SOURCE_SHA)
        self.assertEqual(selected.admission.receipt_path, self.row["admissionReceiptPath"])
        self.assertEqual(selected.admission.media_kind, "still-image")
        self.assertEqual(selected.scope, PRESENTER_ASSET_SCOPE)
        self.assertFalse(selected.executable or selected.media_eligibility_verified or selected.rights_verified)
        self.assertFalse(selected.geometry.framing_observed)
        with self.assertRaises(FrozenInstanceError):
            selected.admission.source_size_bytes = 4
        self.row["sourceSizeBytes"] = self.entry["sizeBytes"] = 5
        self.plan["presenterLayouts"][0]["layout"]["sourceIds"].append("later-mutation")
        self.assertEqual(selected.admission.source_size_bytes, 1234)
        self.assertEqual(selected.geometry.declaration.source_ids, ("raw-2", "raw-1"))

    def test_source_and_broll_lanes_accept_both_actual_media_kind_mappings(self) -> None:
        """A source-lane supplemental asset is valid; image/video never cross types."""
        for lane, kind, media in (("source", "image", "still-image"), ("broll", "video", "timed-media")):
            self.entry.update(lane=lane, mediaKind=media)
            self.row.update(kind=kind, duration=None if kind == "image" else 5.0)
            self.assertEqual(self.select()[0].admission.lane, lane)
            self.assertEqual(self.select()[0].admission.media_kind, media)

    def test_chronological_windows_preserve_nonmonotonic_operation_indices(self) -> None:
        """Touching half-open windows may repeat an asset and keep indices 7 then 2."""
        self.plan["presenterLayouts"].append(_window(2, 60, 120))
        selected = self.select()
        self.assertEqual(tuple(row.operation_index for row in selected), (7, 2))
        self.assertEqual(tuple(row.geometry.timing.start_frame for row in selected), (0, 60))
        self.assertEqual(tuple(row.admission.asset_id for row in selected), ("slide-1", "slide-1"))

    def test_multiple_assets_remain_in_window_order_not_catalog_order(self) -> None:
        """Selection preserves the authored timeline instead of manifest ordering."""
        other, admitted = copy.deepcopy(self.row), copy.deepcopy(self.entry)
        other.update(id="video-2", originalPath="/TEST/ingress/video.mp4", kind="video", duration=4,
            sourceSha256="c" * 64, path=f"/TEST/producer/.sniper-external-media/{'c' * 64}.media",
            admissionReceiptSha256="d" * 64,
            admissionReceiptPath=f".sniper-external-media/receipts/{'d' * 64}.json")
        admitted.update(originalPath=other["originalPath"], mediaKind="timed-media", sha256=other["sourceSha256"],
            snapshotPath=other["path"], admissionReceiptSha256=other["admissionReceiptSha256"],
            admissionReceiptPath=other["admissionReceiptPath"])
        self.manifest["broll"].insert(0, other)
        self.entries.insert(0, admitted)
        self.plan["presenterLayouts"].append(_window(2, 60, 120, "video-2"))
        self.assertEqual(tuple(row.admission.asset_id for row in self.select()), ("slide-1", "video-2"))

    def test_source_catalog_id_cannot_shadow_or_supply_broll_selection(self) -> None:
        """A source-lane receipt is allowed only through an explicit broll manifest row."""
        self.manifest["sources"] = [{**self.row, "path": "/TEST/not-selected-source"}]
        self.assertEqual(self.select()[0].admission.snapshot_path, self.row["path"])
        self.manifest["broll"] = []
        with self.assertRaises(ValueError):
            self.select()

    def test_join_does_not_modify_input_metadata_or_declared_authority(self) -> None:
        """No normalization, approval or provenance facts are written into inputs."""
        before = copy.deepcopy((self.plan, self.manifest, self.entries))
        self.select()
        self.assertEqual((self.plan, self.manifest, self.entries), before)

    def test_absent_field_is_a_no_op_without_new_input_requirements(self) -> None:
        """A legacy plan does not inspect unrelated manifests, entries or canvas."""
        self.assertEqual(select_presenter_assets({}, None, None, None), ())
        for value in (None, [], False):
            with self.assertRaises(ValueError):
                select_presenter_assets(value, self.manifest, self.entries, self.canvas)

    def test_present_empty_null_or_oversize_track_is_not_a_no_op(self) -> None:
        """Fresh projection emits only nonempty tracks bounded to 32 occurrences."""
        for value in ([], None, {}, False, [_window()] * 33):
            self.plan["presenterLayouts"] = value
            with self.assertRaises(ValueError):
                self.select()

    def test_all_broll_ids_are_checked_even_when_unselected(self) -> None:
        """An unselected duplicate or malformed ID cannot make the catalog ambiguous."""
        for row in ({"id": "slide-1"}, {"id": " "}, {"id": True}, {"id": "x" * 129}, []):
            self.manifest["broll"] = [self.row, row]
            with self.assertRaises(ValueError):
                self.select()

    def test_unselected_metadata_is_not_read_as_new_asset_eligibility(self) -> None:
        """Only ID uniqueness belongs to this bridge for unselected catalog rows."""
        self.manifest["broll"].append({"id": "unused", "path": None, "kind": "unknown"})
        self.entries.extend({"originalPath": f"/TEST/unselected/{n}", "sizeBytes": None} for n in range(129))
        self.assertEqual(len(self.select()), 1)

    def test_broll_catalog_shape_limit_and_missing_selection_reject(self) -> None:
        """A selected ID must exist in a bounded actual broll array."""
        for value in (None, {}, [], [{"id": f"unused-{n}"} for n in range(129)]):
            self.manifest["broll"] = value
            with self.assertRaises(ValueError):
                self.select()

    def test_wrong_lane_unknown_kind_and_cross_kind_are_rejected(self) -> None:
        """Music, bools and swapped still/timed identities cannot pass a join."""
        for key, value in (("lane", "music"), ("lane", True), ("mediaKind", "timed-media"), ("mediaKind", "image")):
            self.entries = [{**self.entry, key: value}]
            with self.assertRaises(ValueError):
                self.select()
        self.entries = [self.entry]
        for kind in ("audio", "still-image", None, True):
            self.row["kind"] = kind
            with self.assertRaises(ValueError):
                self.select()

    def test_missing_duplicate_and_nonclosed_selected_entries_reject(self) -> None:
        """Exactly one closed original-path admission is required for a selection."""
        for entries in (None, [], [self.entry, copy.deepcopy(self.entry)], [{**self.entry, "approved": True}],
                        [{key: value for key, value in self.entry.items() if key != "sizeBytes"}]):
            self.entries = entries
            with self.assertRaises(ValueError):
                self.select()

    def test_each_selected_reference_and_byte_count_is_exact(self) -> None:
        """Every expected receipt/source field resists isolated substitution."""
        changes = {"originalPath": "/TEST/other.png", "snapshotPath": "/TEST/other.media",
            "sha256": "c" * 64, "sizeBytes": 1235,
            "admissionReceiptPath": ".sniper-external-media/receipts/other.json",
            "admissionReceiptSha256": "d" * 64}
        for key, value in changes.items():
            self.entries = [{**self.entry, key: value}]
            with self.assertRaises(ValueError):
                self.select()

    def test_size_types_and_boolean_integer_aliases_cannot_match(self) -> None:
        """Canonical positive safe-integer bytes are stricter than Python equality."""
        for size in (True, False, 0, -1, 1234.0, float("inf"), float("nan"), 2**53, "1234"):
            self.row["sourceSizeBytes"] = size
            with self.assertRaises(ValueError):
                self.select()
        self.row["sourceSizeBytes"] = 1
        self.entry["sizeBytes"] = True
        with self.assertRaises(ValueError):
            self.select()

    def test_source_and_receipt_hashes_require_lowercase_full_sha(self) -> None:
        """Malformed hashes are rejected even before consulting matching authority."""
        fields = ("sourceSha256", "admissionReceiptSha256")
        for key, value in product(fields, ("A" * 64, "a" * 63, None, True)):
            changed = copy.deepcopy(self.row)
            changed[key] = value
            self.manifest["broll"] = [changed]
            with self.assertRaises(ValueError):
                self.select()

    def test_canonical_path_aliases_are_not_silently_normalized(self) -> None:
        """Even coherent supplied entries cannot normalize original-path spelling."""
        for value in ("relative.png", "//TEST/a.png", "/TEST/./a.png", "/TEST/x/../a.png",
                      "/TEST//a.png", "/TEST/a.png/", "/", "/TEST/a\x00.png", "/TEST/a\n.png"):
            self.row["originalPath"] = self.entry["originalPath"] = value
            with self.assertRaises(ValueError):
                self.select()

    def test_snapshot_suffix_and_relative_receipt_binding_are_required(self) -> None:
        """Canonical source-store/hash and receipt namespace are not interchangeable."""
        for value in ("/TEST/producer/not-the-store/" + _SOURCE_SHA + ".media",
                      "/TEST/producer/.sniper-external-media/" + "c" * 64 + ".media"):
            self.row["path"] = self.entry["snapshotPath"] = value
            with self.assertRaises(ValueError):
                self.select()
        self.row, self.entry = _metadata()
        self.manifest, self.entries = {"broll": [self.row]}, [self.entry]
        relative = self.row["admissionReceiptPath"]
        for value in ("/TEST/producer/" + relative, "./" + relative, relative.replace("/receipts/", "/receipts//")):
            self.row["admissionReceiptPath"] = self.entry["admissionReceiptPath"] = value
            with self.assertRaises(ValueError):
                self.select()

    def test_original_indices_are_unique_bounded_and_not_coerced(self) -> None:
        """Indices bind actual proposal slots without imposing chronological numbering."""
        for value in (-1, 128, True, "7", 1.5, -0.0):
            self.plan["presenterLayouts"] = [{**_window(), "operationIndex": value}]
            with self.assertRaises(ValueError):
                self.select()
        self.plan["presenterLayouts"] = [_window(), _window(7, 60, 120)]
        with self.assertRaises(ValueError):
            self.select()

    def test_overlap_unsorted_frames_and_incomplete_ramps_reject(self) -> None:
        """No sorting, clamping, truncated exits or fractional-frame invention occurs."""
        tracks = [[_window(), _window(2, 59, 120)], [_window(7, 60, 120), _window(2, 0, 60)],
            [_window(7, 0, 33)], [_window(7, 0, 121)], [_window(7, -1, 60)], [_window(7, .5, 60)]]
        for track in tracks:
            self.plan["presenterLayouts"] = track
            with self.assertRaises(ValueError):
                self.select()

    def test_extra_window_fields_and_invalid_geometry_cannot_bypass_compiler(self) -> None:
        """The adapter reuses the closed geometry contract instead of trusting shape."""
        self.plan["presenterLayouts"][0]["approved"] = True
        with self.assertRaises(ValueError):
            self.select()
        self.plan["presenterLayouts"] = [_window()]
        self.plan["presenterLayouts"][0]["layout"]["assetAudio"] = "keep"
        with self.assertRaises(ValueError):
            self.select()

    def test_supplied_canvas_is_revalidated_and_io_is_never_invoked(self) -> None:
        """Metadata selection neither reads bytes nor trusts a tampered frozen canvas."""
        with patch("builtins.open", side_effect=AssertionError("unexpected read")), \
                patch("os.stat", side_effect=AssertionError("unexpected stat")), \
                patch("subprocess.Popen", side_effect=AssertionError("unexpected process")):
            self.assertEqual(len(self.select()), 1)
        object.__setattr__(self.canvas, "pixel_format", "yuv420p10le")
        with self.assertRaises(ValueError):
            self.select()


if __name__ == "__main__":
    unittest.main()
