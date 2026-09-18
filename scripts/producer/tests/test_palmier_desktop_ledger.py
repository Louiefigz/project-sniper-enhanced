"""Contracts for refreshing stable Desktop elements after track insertions."""
import unittest

from _common import *  # noqa: F401,F403
from palmier.desktop_ledger import refresh_element_ledger
from palmier.mcp_client import PalmierError


def _state() -> dict:
    return {"elementLedger": {"schemaVersion": 1, "elements": {"card": {
        "status": "current", "clipId": "card-clip", "mediaRef": "card-media",
        "startFrame": 8, "endFrame": 146, "trackIndex": 0,
    }}}}


def _timeline(media: str = "card-media") -> dict:
    return {"tracks": [
        {"clips": [{"id": "caption", "mediaRef": "", "frames": [0, 20]}]},
        {"clips": []}, {"clips": []},
        {"clips": [{"id": "card-clip", "mediaRef": media,
                    "frames": [8, 146]}]},
    ]}


class DesktopLedgerRefreshTests(unittest.TestCase):
    def test_track_insertions_resolve_from_current_clip_location(self):
        state = _state()
        refresh_element_ledger(state, _timeline())
        row = state["elementLedger"]["elements"]["card"]
        self.assertEqual(row["trackIndex"], 3)

    def test_media_or_window_drift_fails_before_repair(self):
        with self.assertRaisesRegex(PalmierError, "drifted"):
            refresh_element_ledger(_state(), _timeline("wrong-media"))

    def test_unfinished_replacement_fails_before_repair(self):
        state = _state()
        state["elementLedger"]["elements"]["card"]["status"] = "cleanup-required"
        with self.assertRaisesRegex(PalmierError, "unfinished"):
            refresh_element_ledger(state, _timeline())


if __name__ == "__main__":
    unittest.main()
