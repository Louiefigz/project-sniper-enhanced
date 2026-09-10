"""Half-open motion windows: pure tests plus explicit opt-in tiny native evidence only."""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import unittest
from pathlib import Path

from color.deadline import require_time, wall_budget
from motion import punch_in
from _punch_endpoint_fixture import CASES, endpoint_case, source_hashes


def enables(windows: list[dict]) -> list[str]:
    """Extract complete actual overlay predicates without substituting a test renderer."""
    parsed = punch_in.parse_windows(windows)
    return re.findall(r"overlay=enable='([^']+)'", punch_in.build_filter(320, 180, parsed))


def evaluate(expression: str, point: float) -> float:
    """Evaluate only the actual closed arithmetic predicate for pure boundary assertions."""
    scope = {"t": point, "gte": lambda x, y: x >= y, "lt": lambda x, y: x < y,
             "between": lambda t, s, e: s <= t <= e}
    return eval(expression, {"__builtins__": {}}, scope)


class PunchEndpointTests(unittest.TestCase):
    """Existing projections/branches use start-inclusive, end-exclusive windows."""

    def test_static_exact_frame_aligned_boundaries(self) -> None:
        """Exercise both integer rates and the exactly six-decimal NTSC endpoints."""
        for rate, _, start, end in CASES:
            n, d = map(int, rate.split("/"))
            window = {"outStart": start * d / n, "outEnd": end * d / n, "zoom": 1.25}
            actual = enables([window])[0]
            points = [frame * d / n for frame in (start - 1, start, end - 1, end, end + 1)]
            self.assertEqual([evaluate(actual, t) for t in points], [0, 1, 1, 0, 0], rate)

    def test_animated_paths_are_half_open(self) -> None:
        """Both push and ramp share the corrected animated overlay predicate."""
        for move in ({"zoom": 1.25, "attackS": 0.2}, {"ramp": {"direction": "in", "ratePctPerS": 1}}):
            actual = enables([{"outStart": 1, "outEnd": 2, **move}])[0]
            self.assertEqual([evaluate(actual, t) for t in (0.99, 1, 1.99, 2, 2.01)], [0, 1, 1, 0, 0])

    def test_adjacent_same_setting_group_is_not_double_enabled(self) -> None:
        """One grouped branch contributes exactly once at a touching window edge."""
        rows = enables([{"outStart": 1, "outEnd": 2, "zoom": 1.25},
                        {"outStart": 2, "outEnd": 3, "zoom": 1.25}])
        self.assertEqual(len(rows), 1)
        self.assertEqual([evaluate(rows[0], t) for t in (1, 2, 3)], [1, 1, 0])

    def test_distinct_adjacent_groups_never_overlap_at_boundary(self) -> None:
        """A later setting owns the touching edge, not both overlays."""
        rows = enables([{"outStart": 1, "outEnd": 2, "zoom": 1.2},
                        {"outStart": 2, "outEnd": 3, "zoom": 1.25}])
        self.assertEqual(len(rows), 2)
        self.assertEqual([evaluate(row, 2) for row in rows], [0, 1])

    def test_bracket_release_and_original_six_decimal_projection(self) -> None:
        """Do not silently introduce a new fractional-frame quantization policy."""
        actual = enables([{"outStart": 1.001, "outEnd": 3.003, "zoom": 1.25,
                           "bracket": True, "holdS": 1.001}])[0]
        self.assertEqual(actual, "gte(t,1.001000)*lt(t,2.002000)")
        self.assertEqual([evaluate(actual, t) for t in (1.001, 2.002)], [1, 0])

    def test_no_window_control_keeps_original_format_and_no_overlay(self) -> None:
        """The existing empty-list primitive control remains unmodified."""
        actual = punch_in.build_filter(320, 180, [])
        self.assertNotIn("overlay", actual)
        self.assertEqual(actual, "[0:v]setsar=1,split=1[base];[base]format=yuv420p[vout]")


def assert_metadata(test: unittest.TestCase, case: dict, record: dict) -> None:
    """Require exact counts, video PTS and every copied audio packet record."""
    actual, original = record["metadata"], case["sourceMetadata"]
    video = next(row for row in actual["streams"] if row["codec_type"] == "video")
    source = next(row for row in original["streams"] if row["codec_type"] == "video")
    test.assertEqual(int(video["nb_read_frames"]), case["count"])
    test.assertEqual(int(video["nb_read_packets"]), case["count"])
    test.assertEqual(int(source["nb_read_frames"]), case["count"])
    test.assertEqual(int(source["nb_read_packets"]), case["count"])
    test.assertEqual(video["r_frame_rate"], case["rate"])
    test.assertEqual(actual["frames"], original["frames"])
    test.assertGreater(len(original["audioPackets"]), 0)
    test.assertEqual(actual["audioPackets"], original["audioPackets"])
    test.assertEqual(record["result"]["driftFrames"], 0)


def assert_positions(test: unittest.TestCase, case: dict, kind: str) -> None:
    """Assert explicit base/zoom geometry at every requested frame, not merely any image difference."""
    for frame in case["samples"]:
        wide = case["variants"]["control"]["markers"][frame]
        actual = case["variants"][kind]["markers"][frame]
        zoomed = kind != "control" and case["start"] <= frame < case["end"] and not (kind == "animated" and frame == case["start"])
        test.assertAlmostEqual(wide["centerX"], 69.5, delta=1)
        test.assertAlmostEqual(actual["centerX"], 47.0 if zoomed else wide["centerX"], delta=1.5)
        test.assertAlmostEqual(actual["bbox"][2] - actual["bbox"][0] + 1, 25 if zoomed else 20, delta=2)


@unittest.skipUnless(os.environ.get("SNIPER_PUNCH_ENDPOINT_NATIVE") == "1", "explicit tiny native endpoint opt-in required")
class PunchEndpointNativeTests(unittest.TestCase):
    """One 120-second batch; actual unchanged-quality static/animated outputs, not guided qualification."""

    def test_all_original_frame_aligned_endpoints(self) -> None:
        """Retain every source/output/PNG and exact metadata even if an assertion fails."""
        began = time.monotonic()
        root = Path(tempfile.mkdtemp(prefix="sniper-punch-endpoints-native-", dir="/private/tmp"))
        report = {"scope": "TEST synthetic ordinary primitive only; no guided/media/human approval",
                  "originalCapSeconds": 120, "pid": os.getpid(), "cases": []}
        print(f"PUNCH_ENDPOINT_NATIVE_ROOT={root}", flush=True)
        try:
            with wall_budget(began + 120):
                self.run_original_batch(root, report)
        finally:
            report["elapsedSeconds"] = time.monotonic() - began
            (root / "result.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        require_time(began + 120)

    def run_original_batch(self, root: Path, report: dict) -> None:
        """One original source-hash/clock lifetime for every serial case; never retry."""
        report["beforeHashes"] = source_hashes()
        for spec in CASES:
            report["cases"].append(endpoint_case(root, spec))
        report["afterHashes"] = source_hashes()
        self.assertEqual(report["beforeHashes"], report["afterHashes"])
        for case in report["cases"]:
            self.assert_case(case)

    def assert_case(self, case: dict) -> None:
        """Keep every rate/variant assertion without stopping the remaining planned comparisons."""
        self.assertEqual(case["encode"], {"mezzanine_crf": 12, "mezzanine_preset": "fast", "pix_fmt": "yuv420p"})
        for kind, record in case["variants"].items():
            with self.subTest(rate=case["rate"], kind=kind):
                assert_metadata(self, case, record)
                assert_positions(self, case, kind)


if __name__ == "__main__":
    unittest.main()
