"""Tests for exact-frame current baseline plan preparation."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import prepare_current_baseline as baseline
from baseline_fixture_authority import load_fixture
from baseline_source_ranges import parse_source_frame_ranges

REQUESTED = "1680:17580,17660:21899"


def _project(root: Path, declared_frames: int = 21_905) -> dict:
    receipt = {"decoded": {"facts": {"declaredFrames": declared_frames}}}
    payload = json.dumps(receipt, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    relative = Path(".admission") / f"{digest}.json"
    (root / relative).parent.mkdir(parents=True)
    (root / relative).write_bytes(payload)
    source_sha = "b" * 64
    manifest = {
        "sources": [{
            "id": "raw-1",
            "duration": 913.621,
            "fps": 23.976,
            "frameRate": "24000/1001",
            "vfr": False,
            "sourceSha256": source_sha,
        }],
        "sourceSetAdmission": {"sourceSetDigest": "c" * 64},
    }
    (root / "asset_manifest.json").write_text(json.dumps(manifest))
    return {
        "lane": "source",
        "sha256": source_sha,
        "admissionReceiptPath": str(relative),
        "admissionReceiptSha256": digest,
    }


def _spec(ranges: str | None = REQUESTED) -> baseline.BaselineSpec:
    return baseline.BaselineSpec(
        mode="longform",
        frames=20_139,
        rate=("24000", "1001"),
        source_frame_ranges=parse_source_frame_ranges(ranges),
    )


class PrepareCurrentBaselineTests(unittest.TestCase):
    """Require canonical half-open frame selection and closed authority."""

    def test_requested_ranges_are_exact_half_open_total(self) -> None:
        ranges = parse_source_frame_ranges(REQUESTED)
        self.assertIsNotNone(ranges)
        assert ranges is not None
        self.assertEqual([
            (item.start_frame, item.end_frame_exclusive)
            for item in ranges
        ], [(1680, 17580), (17660, 21899)])
        self.assertEqual(sum(item.length for item in ranges), 20_139)
        self.assertEqual(
            Fraction(20_139 * 1001, 24_000),
            Fraction(6_719_713, 8_000),
        )

    def test_parser_rejects_noncanonical_empty_and_overlap_ranges(self) -> None:
        invalid = (
            "", " ", "01680:17580", "1680-17580", "1680:17580,",
            "-1:10", "10:10", "11:10", "0:10,9:20", "10:20,0:5",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                parse_source_frame_ranges(value)

    def test_prepare_writes_requested_segments_and_closed_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            entry = _project(project)
            with patch.object(
                    baseline, "verify_source_set_binding",
                    return_value=[entry]):
                plan_path, fixture_path = baseline.prepare(project, _spec())
            plan = json.loads(plan_path.read_text())
            fixture = load_fixture(fixture_path)

            self.assertEqual(plan["target"]["durationTargetS"], 839.964125)
            self.assertEqual(plan["cutTrack"], [
                {
                    "sourceId": "raw-1", "start": 70.07,
                    "end": 733.2325, "speed": 1.0,
                },
                {
                    "sourceId": "raw-1", "start": 736.5691666666667,
                    "end": 913.3707916666667, "speed": 1.0,
                },
            ])
            duration = sum(
                Fraction(str(row["end"])) - Fraction(str(row["start"]))
                for row in plan["cutTrack"])
            self.assertEqual(duration, Fraction(6_719_713, 8_000))
            self.assertEqual(fixture["durationFrames"], 20_139)
            self.assertEqual(
                fixture["inputAuthority"]["planSha256"],
                hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            )

    def test_prepare_rejects_out_of_bounds_and_wrong_total(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            entry = _project(project)
            out_of_bounds = baseline.BaselineSpec(
                **{**_spec().__dict__, "source_frame_ranges":
                   parse_source_frame_ranges("1680:17580,17660:21906")})
            wrong_total = baseline.BaselineSpec(
                **{**_spec().__dict__, "source_frame_ranges":
                   parse_source_frame_ranges("1680:17580,17660:21898")})
            with patch.object(
                    baseline, "verify_source_set_binding",
                    return_value=[entry]):
                with self.assertRaisesRegex(RuntimeError, "source bounds"):
                    baseline.prepare(project, out_of_bounds)
                with self.assertRaisesRegex(RuntimeError, "must total"):
                    baseline.prepare(project, wrong_total)

    def test_prepare_rejects_wrong_clock_and_non_lf14_duration(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            entry = _project(project)
            wrong_clock = baseline.BaselineSpec(
                **{**_spec().__dict__, "rate": ("24001", "1001")})
            overlong = baseline.BaselineSpec(
                **{**_spec().__dict__, "frames": 21_905,
                   "source_frame_ranges": None})
            with patch.object(
                    baseline, "verify_source_set_binding",
                    return_value=[entry]):
                with self.assertRaisesRegex(RuntimeError, "does not match"):
                    baseline.prepare(project, wrong_clock)
                with self.assertRaisesRegex(RuntimeError, "between 12 and 14"):
                    baseline.prepare(project, overlong)

    def test_exact_rate_allows_harmless_container_average_drift(self) -> None:
        source = {
            "fps": 29.998,
            "frameRate": "30/1",
            "vfr": False,
        }
        baseline.validate_source_rate(source, (30, 1))
        source["frameRate"] = "30000/1001"
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            baseline.validate_source_rate(source, (30, 1))


if __name__ == "__main__":
    unittest.main()
