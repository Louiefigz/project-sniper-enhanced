"""Prior J-cut ownership filters analysis candidates before promotion."""
from __future__ import annotations

import unittest

from edit.cut_repair_existing_lead_filter import (
    ExistingLeadFilterError,
    filter_existing_lead_candidates,
)
from edit.picture_lock_common import content_hash


def _candidate(start: int, end: int, extension: int = 2) -> dict:
    operation = {
        "method": "audio-lj-overlap",
        "extensionFrames": extension,
        "pictureDirtyWindows": [],
        "audioDirtyWindows": [{
            "startFrame": start // 1_600,
            "endFrameExclusive": max(start // 1_600 + 1, end // 1_600),
        }],
        "replacedAudioSampleRanges": [{
            "startSample": start,
            "endSampleExclusive": end,
        }],
    }
    return {
        "operation": operation,
        "operationHash": content_hash(operation),
    }


def _existing(start: int, end: int) -> list[dict]:
    return [{
        "segmentId": "seg-prior",
        "outputSampleRange": {
            "startSample": start,
            "endSampleExclusive": end,
        },
    }]


class ExistingLeadFilterTests(unittest.TestCase):
    def test_overlap_is_removed_and_disjoint_candidate_is_reselected(
        self,
    ) -> None:
        blocked = _candidate(100, 200)
        disjoint = _candidate(300, 400, 3)
        result = filter_existing_lead_candidates({
            "status": "eligible",
            "candidates": [blocked, disjoint],
            "recommendedCandidate": blocked,
        }, _existing(150, 250))
        self.assertEqual(result["candidates"], [disjoint])
        self.assertEqual(
            result["recommendedCandidate"]["operationHash"],
            disjoint["operationHash"])

    def test_all_candidates_blocked_returns_exact_non_ripple_reason(
        self,
    ) -> None:
        result = filter_existing_lead_candidates({
            "status": "eligible",
            "candidates": [_candidate(100, 200)],
            "recommendedCandidate": None,
        }, _existing(150, 250))
        self.assertEqual(result["status"], "impossible-without-ripple")
        self.assertEqual(result["candidates"], [])
        self.assertIsNone(result["recommendedCandidate"])
        self.assertEqual(result["rippleImpact"], {
            "reason": "existing-audio-lead-overlap",
            "preservedExistingAudioLeadSegmentIds": ["seg-prior"],
        })

    def test_malformed_existing_range_fails_closed(self) -> None:
        malformed = _existing(100, 200)
        malformed[0]["outputSampleRange"]["endSampleExclusive"] = 100
        with self.assertRaisesRegex(
                ExistingLeadFilterError, "malformed"):
            filter_existing_lead_candidates({
                "status": "eligible",
                "candidates": [_candidate(300, 400)],
            }, malformed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
