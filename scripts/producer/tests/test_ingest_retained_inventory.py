"""Additive rescan keeps old supporting inputs, lanes and stable IDs."""
from __future__ import annotations

import unittest
from pathlib import Path

from ingest_admission import AdmittedMedia, IngressCandidate
from ingest_retained_inventory import (
    RetainedIngest, include_retained_ingress, merge_retained_lane,
)


def admitted(original: str, lane: str = "broll") -> AdmittedMedia:
    """Return synthetic proof fields without decoding or admitting any media."""
    return AdmittedMedia(original, lane, f"/snapshot/{Path(original).name}",
                         "a" * 64, 100, "image", "receipt.json", "b" * 64)


def row(original: str, asset_id: str) -> dict:
    """Describe one prior verified media row for pure merge tests."""
    media = admitted(original)
    return {"id": asset_id, "originalPath": original, "path": media.snapshot_path,
            "sourceSha256": media.sha256, "sourceSizeBytes": 100,
            "description": "TEST prior inspected description"}


class RetainedInventoryTests(unittest.TestCase):
    """No lost reclassified files or collisions when new B-roll sorts first."""

    def test_reclassified_image_external_broll_and_music_remain_candidates(self) -> None:
        entries = [{"originalPath": name, "lane": lane} for name, lane in [
            ("/external/take.mp4", "source"), ("/external/title.png", "source"),
            ("/external/broll/cutaway.png", "broll"), ("/external/music/bed.wav", "music")]]
        current = [IngressCandidate(Path("/external/take.mp4"), "source"),
                   IngressCandidate(Path("/project/broll/new.png"), "broll")]
        result = include_retained_ingress(current, RetainedIngest({}, entries))
        self.assertEqual(len(result), 5)
        actual = {str(value.original_path): value.lane for value in result}
        self.assertEqual(actual["/external/title.png"], "source")
        self.assertEqual(actual["/external/music/bed.wav"], "music")

    def test_existing_ingress_cannot_change_lanes(self) -> None:
        previous = RetainedIngest({}, [{"originalPath": "/old.png", "lane": "source"}])
        with self.assertRaisesRegex(RuntimeError, "ingress lane"):
            include_retained_ingress([IngressCandidate(Path("/old.png"), "broll")], previous)

    def test_existing_rows_keep_ids_and_new_rows_avoid_collisions(self) -> None:
        old = [row("/z-old.png", "broll-1"), row("/external.png", "broll-3")]
        current = [row("/a-new.png", "broll-1"), row("/z-old.png", "broll-2")]
        mapping = {name: admitted(name) for name in ["/z-old.png", "/external.png", "/a-new.png"]}
        result = merge_retained_lane(current, old, mapping, "broll")
        self.assertEqual([value["id"] for value in result], ["broll-1", "broll-3", "broll-2"])
        self.assertEqual(result[0]["description"], old[0]["description"])
        self.assertEqual(len({value["originalPath"] for value in result}), 3)

    def test_changed_or_missing_old_asset_cannot_silently_disappear(self) -> None:
        old = [row("/old.png", "broll-1")]
        with self.assertRaisesRegex(RuntimeError, "changed or lost"):
            merge_retained_lane([], old, {}, "broll")
        changed = {**old[0], "sourceSha256": "c" * 64}
        with self.assertRaisesRegex(RuntimeError, "changed or lost"):
            merge_retained_lane([], [changed], {"/old.png": admitted("/old.png")}, "broll")

    def test_trusted_builtin_and_external_music_keep_previous_ids(self) -> None:
        builtin = {"id": "music-2", "path": "/trusted/builtin.wav", "source": "builtin"}
        old = [row("/outside/bed.wav", "music-1"), builtin]
        current = [{**builtin, "id": "music-1"}, row("/new.wav", "music-2")]
        result = merge_retained_lane(current, old, {"/outside/bed.wav": admitted("/outside/bed.wav", "music")}, "music")
        self.assertEqual([value["id"] for value in result], ["music-1", "music-2", "music-3"])
        self.assertEqual(result[1], builtin)


if __name__ == "__main__":
    unittest.main()
