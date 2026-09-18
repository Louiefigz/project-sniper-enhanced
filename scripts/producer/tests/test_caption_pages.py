"""Bounded CaptionTrackV1 alpha-page planning tests."""
from __future__ import annotations

import copy
import os
import unittest

from captions.caption_contract import CaptionContractError
from captions.caption_page_contract import _determinism
from captions.caption_page_media import (
    CaptionPageMediaContext,
    caption_page_command,
)
from captions.caption_pages import (
    caption_page_compositor_identity,
    caption_page_key,
    plan_caption_pages,
)


def _manifest() -> dict:
    def row(cue: str, start: int, end: int) -> dict:
        return {
            "cueId": cue, "startFrame": start,
            "endFrameExclusive": end,
            "media": {"name": f"{cue}.mov", "sha256": "a" * 64},
        }

    return {"entries": [
        row("cue-a", 0, 119),
        row("cue-b", 118, 238),
        row("cue-c", 237, 346),
        row("cue-d", 600, 660),
    ]}


class CaptionPagePlanningTests(unittest.TestCase):
    def test_pages_preserve_overlap_and_split_crossing_cues(self) -> None:
        pages = plan_caption_pages(_manifest(), 700, 200)
        self.assertEqual(
            [(row["startFrame"], row["endFrameExclusive"]) for row in pages],
            [(0, 200), (200, 400), (600, 700)])
        first = pages[0]["inputs"]
        self.assertEqual([row["cueId"] for row in first], ["cue-a", "cue-b"])
        self.assertEqual(first[1]["sourceEndFrameExclusive"], 82)
        second = pages[1]["inputs"]
        self.assertEqual([row["cueId"] for row in second], ["cue-b", "cue-c"])
        self.assertEqual(second[0]["sourceStartFrame"], 82)
        self.assertEqual(second[0]["pageStartFrame"], 0)

    def test_blank_pages_are_omitted_but_timeline_frames_stay_absolute(self) -> None:
        pages = plan_caption_pages(_manifest(), 700, 200)
        self.assertEqual(pages[-1]["startFrame"], 600)
        self.assertEqual(pages[-1]["inputs"][0]["pageStartFrame"], 0)

    def test_stale_tail_beyond_sealed_picture_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "sealed picture"):
            plan_caption_pages(_manifest(), 659, 200)

    def test_unordered_entries_fail_instead_of_changing_z_order(self) -> None:
        manifest = _manifest()
        manifest["entries"][0], manifest["entries"][1] = (
            manifest["entries"][1], manifest["entries"][0])
        with self.assertRaisesRegex(ValueError, "not ordered"):
            plan_caption_pages(manifest, 700, 200)

    def test_invalid_frame_authorities_fail(self) -> None:
        for total, page in ((True, 30), (0, 30), (700, False), (700, 0)):
            with self.subTest(total=total, page=page):
                with self.assertRaises(ValueError):
                    plan_caption_pages(copy.deepcopy(_manifest()), total, page)

    def test_contract_rejects_complete_cue_shifted_to_wrong_page_time(
            self) -> None:
        page = plan_caption_pages(_manifest(), 700, 200)[0]
        tools, compositor = caption_page_compositor_identity()
        manifest = {
            "fps": {"numerator": "30", "denominator": "1"},
            "destination": {"width": 1080, "height": 1920},
            "shardManifestHash": "b" * 64,
        }
        page_id = caption_page_key(manifest, compositor, page)
        path = os.path.join("/tmp", f"caption-page-{page_id}.mov")
        command = caption_page_command(
            page, CaptionPageMediaContext(manifest, "/tmp", tools), path)
        receipt = {
            "startFrame": page["startFrame"],
            "endFrameExclusive": page["endFrameExclusive"],
            "inputs": copy.deepcopy(page["inputs"]),
            "pageId": page_id, "command": command,
        }
        _determinism([receipt], [page], manifest, "/tmp")
        receipt["inputs"][0]["pageStartFrame"] += 1
        with self.assertRaisesRegex(
                CaptionContractError, "deterministic projection"):
            _determinism([receipt], [page], manifest, "/tmp")

    def test_page_identity_is_local_to_affected_media_window(self) -> None:
        manifest = _manifest()
        pages = plan_caption_pages(manifest, 700, 200)
        context = {
            "fps": {"numerator": "30", "denominator": "1"},
            "destination": {"width": 1080, "height": 1920},
        }
        compositor = "c" * 64
        before = [caption_page_key(context, compositor, page)
                  for page in pages]
        changed = copy.deepcopy(manifest)
        changed["entries"][0]["media"]["sha256"] = "d" * 64
        changed_pages = plan_caption_pages(changed, 700, 200)
        after = [caption_page_key(context, compositor, page)
                 for page in changed_pages]
        self.assertNotEqual(before[0], after[0])
        self.assertEqual(before[1:], after[1:])


if __name__ == "__main__":
    unittest.main()
