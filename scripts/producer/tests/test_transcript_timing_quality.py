"""Objective transcript timing-quality acceptance and collapse rejection."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

from transcript_timing_quality import (
    require_timing_quality,
    timing_quality_report,
)


def _payload(words: list[dict]) -> dict:
    return {
        "transcript": [{
            "start": words[0]["start"], "end": words[-1]["end"],
            "text": " ".join(word["word"] for word in words),
            "words": words,
        }],
    }


class TranscriptTimingQualityTests(unittest.TestCase):
    def test_one_boundary_glitch_is_tolerated(self) -> None:
        words = [
            {"word": "one", "start": 0.0, "end": 0.3},
            {"word": "we're", "start": 0.3, "end": 0.31},
            {"word": "talking", "start": 0.3, "end": 0.8},
        ]
        report = timing_quality_report(_payload(words))
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["tinyWordCount"], 1)
        self.assertEqual(report["overlappingPairCount"], 1)

    def test_multiword_ten_millisecond_collapse_fails(self) -> None:
        words = [
            {"word": str(index), "start": 45.0, "end": 45.01}
            for index in range(9)
        ]
        report = timing_quality_report(_payload(words))
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["maxCollapsedRunWords"], 9)
        self.assertIn(
            "collapsed_run",
            {row["code"] for row in report["violations"]})
        with self.assertRaisesRegex(RuntimeError, "timing quality failed"):
            require_timing_quality(_payload(words))

    def test_malformed_nonfinite_and_empty_fail_closed(self) -> None:
        for payload in (
            {"transcript": []},
            {"transcript": [{"words": [
                {"word": "bad", "start": 0.0, "end": float("nan")},
            ]}]},
        ):
            self.assertEqual(timing_quality_report(payload)["status"], "fail")

    def test_retained_donor_and_repaired_project_pass_objective_metrics(self) -> None:
        root = Path(__file__).resolve().parents[3]
        donor = (
            root / "artifacts/p5-connected-qualification-20260730"
            / "short/source/raw-1.transcript.json"
        )
        fresh = Path(
            "/Users/maintainer/ProjectSniper/"
            "img-7134-20260731/source/raw-1.transcript.json")
        if not donor.is_file():
            self.skipTest("real acceptance donor transcript is not retained")
        donor_report = timing_quality_report(json.loads(donor.read_text()))
        self.assertEqual(donor_report["status"], "pass")
        self.assertEqual(donor_report["wordCount"], 964)
        self.assertEqual(donor_report["maxCollapsedRunWords"], 1)
        if fresh.is_file():
            repaired = json.loads(fresh.read_text())
            self.assertEqual(
                repaired["transcriptPromotionAuthority"]["policy"],
                "sniper-transcript-authority-promotion-v1")
            self.assertEqual(timing_quality_report(repaired)["status"], "pass")


if __name__ == "__main__":
    unittest.main(verbosity=2)
