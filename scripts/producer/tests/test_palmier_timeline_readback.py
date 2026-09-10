"""Adversarial tests for bounded Palmier caption-window readback."""
import copy
import unittest
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from palmier.mcp_client import PalmierError
import palmier.timeline_readback as timeline_readback
from palmier.timeline_readback import (_prove_partition,
                                       read_complete_timeline)


def _caption_rows(count=450):
    rows = [["caption-span", 100, 350, "spanning caption"]]
    rows.extend([
        [f"caption-{index}", index, index + 1, f"word {index}"]
        for index in range(count - 1)
    ])
    return rows


def _timeline(rows=None):
    rows = rows or _caption_rows()
    return {
        "id": "timeline-1", "name": "Candidate", "fps": 30,
        "width": 1080, "height": 1920, "totalFrames": 450,
        "tracks": [
            {"id": "video-track", "index": 0, "type": "video",
             "clips": [{"id": "source", "frames": [0, 450],
                        "mediaRef": "source-media"}]},
            {"id": "caption-track", "index": 1, "type": "video",
             "clips": [], "captionGroups": [{
                 "captionGroupId": "group-1", "clipCount": len(rows),
                 "frameRange": [0, 450], "textPreview": "word",
             }]},
        ],
    }


class WindowClient:
    def __init__(self, rows=None):
        self.rows = rows or _caption_rows()
        self.base = _timeline(self.rows)
        self.calls = []
        self.detail_calls = 0

    def _details(self, arguments):
        start, end = arguments["startFrame"], arguments["endFrame"]
        selected = [row for row in self.rows
                    if row[1] < end and row[2] > start][:200]
        return selected

    def _page(self, arguments):
        page = copy.deepcopy(self.base)
        details = self._details(arguments)
        page["tracks"][1]["captionGroups"][0]["clips"] = details
        return page

    def call_json(self, tool, arguments=None):
        if tool != "get_timeline":
            raise AssertionError(tool)
        arguments = arguments or {}
        self.calls.append(copy.deepcopy(arguments))
        if arguments.get("captionDetail") is True:
            self.detail_calls += 1
            return self._page(arguments)
        return copy.deepcopy(self.base)


class TimelineReadbackTests(unittest.TestCase):
    def test_pages_dense_group_and_proves_exact_coverage(self):
        client = WindowClient()
        found = read_complete_timeline(client)
        group = found.timeline["tracks"][1]["captionGroups"][0]
        self.assertEqual(len(group["clips"]), 450)
        self.assertEqual(group["clips"][0][0], "caption-0")
        self.assertTrue(found.coverage["complete"])
        self.assertGreater(found.coverage["windowCount"], 1)
        self.assertEqual(found.coverage["frameCoverage"][0][0], 0)
        self.assertEqual(found.coverage["frameCoverage"][-1][1], 450)
        self.assertEqual(found.coverage["captionGroups"][0]["readClipCount"],
                         450)
        self.assertEqual(
            found.coverage["cappedCaptionGroups"][0]["expectedClipCount"],
            450)
        self.assertTrue(found.coverage["closingCompactRead"])
        self.assertEqual(client.calls[-1], {},
                         "multi-window reads require a closing compact read")

    def test_overlap_row_must_be_identical_in_every_window(self):
        class Inconsistent(WindowClient):
            def _details(self, arguments):
                rows = copy.deepcopy(super()._details(arguments))
                for row in rows:
                    if row[0] == "caption-span" and arguments["startFrame"] > 0:
                        row[3] = "changed during paging"
                return rows

        with self.assertRaisesRegex(PalmierError, "overlap.*inconsistent"):
            read_complete_timeline(Inconsistent())

    def test_timeline_and_track_identity_drift_fail_closed(self):
        class Drift(WindowClient):
            def _page(self, arguments):
                page = super()._page(arguments)
                if self.detail_calls > 0:
                    page["tracks"][0]["id"] = "foreign-track"
                return page

        with self.assertRaisesRegex(PalmierError, "track identity drifted"):
            read_complete_timeline(Drift())

        class TimelineDrift(WindowClient):
            def _page(self, arguments):
                page = super()._page(arguments)
                page["id"] = "foreign-timeline"
                return page

        with self.assertRaisesRegex(PalmierError, "timeline id drifted"):
            read_complete_timeline(TimelineDrift())

    def test_missing_or_out_of_window_rows_cannot_claim_complete(self):
        class Missing(WindowClient):
            def _details(self, arguments):
                return [row for row in super()._details(arguments)
                        if row[0] != "caption-448"]

        with self.assertRaisesRegex(PalmierError, "expected 450, read 449"):
            read_complete_timeline(Missing())

        class ForeignRow(WindowClient):
            def _details(self, arguments):
                rows = super()._details(arguments)
                if arguments["startFrame"] > 225:
                    return [["foreign", 0, 1, "outside"], *rows]
                return rows

        with self.assertRaisesRegex(PalmierError, "outside its frame window"):
            read_complete_timeline(ForeignRow())

    def test_group_id_reuse_and_caption_id_movement_are_rejected(self):
        class ForeignGroup(WindowClient):
            def _page(self, arguments):
                page = super()._page(arguments)
                page["tracks"][1]["captionGroups"][0]["captionGroupId"] = "other"
                return page

        with self.assertRaisesRegex(PalmierError, "group identity drifted"):
            read_complete_timeline(ForeignGroup())

        class MovedCaption(WindowClient):
            def __init__(self):
                super().__init__()
                self.base["tracks"][1]["captionGroups"].append({
                    "captionGroupId": "group-2", "clipCount": 1,
                    "frameRange": [100, 350], "textPreview": "duplicate",
                })

            def _page(self, arguments):
                page = super()._page(arguments)
                page["tracks"][1]["captionGroups"][1]["clips"] = [
                    ["caption-span", 100, 350, "spanning caption"]]
                return page

        with self.assertRaisesRegex(PalmierError, "moved between groups"):
            read_complete_timeline(MovedCaption())

    def test_frame_partition_rejects_gaps_and_overlaps(self):
        self.assertEqual(_prove_partition([(5, 10), (0, 5)], 10),
                         [[0, 5], [5, 10]])
        for windows in ([(0, 4), (5, 10)], [(0, 6), (5, 10)]):
            with self.assertRaisesRegex(PalmierError, "gap or overlap"):
                _prove_partition(windows, 10)

    def test_closing_compact_read_is_inside_request_bound(self):
        rows = [
            *[[f"left-{index}", index, index + 1, "left"]
              for index in range(101)],
            *[[f"right-{index}", 300 + index, 301 + index, "right"]
              for index in range(100)],
        ]
        with patch.object(timeline_readback, "MAX_WINDOW_REQUESTS", 3):
            with self.assertRaisesRegex(PalmierError, "request bound"):
                read_complete_timeline(WindowClient(rows))

    def test_empty_caption_timeline_stays_single_call(self):
        timeline = _timeline([])
        timeline["tracks"][1]["captionGroups"] = []

        class Empty:
            calls = 0

            def call_json(self, tool, arguments=None):
                self.calls += 1
                return copy.deepcopy(timeline)

        client = Empty()
        found = read_complete_timeline(client)
        self.assertEqual(client.calls, 1)
        self.assertTrue(found.coverage["complete"])
        self.assertFalse(found.coverage["captionDetailRequested"])


if __name__ == "__main__":
    unittest.main()
