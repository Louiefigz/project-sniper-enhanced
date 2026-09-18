"""Palmier P2 disposition and bounded readback tests."""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from edit.exact_timing import PositiveRational
from edit.picture_lock_common import content_hash
from palmier.cut_repair_projection import (
    PalmierRepairProjectionInput,
    project_cut_repair,
    verify_cut_repair_readback,
)
from palmier.mcp_client import PalmierError


def _operation(
    method: str,
    speed: PositiveRational,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "operation": "cut.restoreSpeech",
        "method": method,
        "speed": speed.to_dict(),
        "sourceExtension": {
            "startSample": 48_000, "endSampleExclusive": 52_800},
        "sourceSampleRate": 48_000,
        "extensionOutputSamples":
            4_800 * speed.denominator // speed.numerator,
    }


@dataclass(frozen=True)
class _InputOptions:
    selected: bool = True
    fps: PositiveRational | None = None
    multi_source: bool = False
    speed: PositiveRational | None = None


def _input(
    method: str,
    options: _InputOptions = _InputOptions(),
) -> PalmierRepairProjectionInput:
    requested = options.speed or PositiveRational(1, 1)
    operation = _operation(method, requested)
    second_source = "source-b" if options.multi_source else "source-a"
    cuts = (
        {"sourceId": "source-a", "start": 0.0, "end": 2.0, "speed": 1.0},
        {"sourceId": second_source, "start": 3.0, "end": 5.0, "speed": 1.0},
    )
    output = operation["extensionOutputSamples"]
    retime = {
        "requestedSpeed": requested.to_dict(),
        "sourceSampleRange": operation["sourceExtension"],
        "sourceSampleRate": 48_000,
        "normalizedSourceSampleRange":
            operation["sourceExtension"],
        "outputSamples": output,
        "effectiveRatio": requested.to_dict(),
    }
    return PalmierRepairProjectionInput(
        operation, content_hash(operation), cuts,
        options.fps or PositiveRational(30, 1),
        options.selected, retime)


def _timeline(changed_overlay: bool = False) -> dict:
    return {
        "totalFrames": 120,
        "tracks": [
            {"clips": [
                {"id": "base-a", "frames": [0, 60],
                 "source": [0.0, 2.0], "speed": 1.0},
                {"id": "base-b", "frames": [60, 120],
                 "source": [3.0, 5.0], "speed": 1.0},
            ]},
            {"clips": [
                {"id": "overlay-a", "frames": [30, 50],
                 "textContent": "changed" if changed_overlay else "same"},
            ]},
        ],
    }


class PalmierRepairProjectionTests(unittest.TestCase):
    def test_unselected_authorizes_zero_palmier_work(self) -> None:
        result = project_cut_repair(_input(
            "extend-and-reclaim-silence",
            _InputOptions(selected=False)))
        self.assertEqual(result["nativeStatus"], "skipped")
        self.assertNotIn("expectedCuts", result)

    def test_audio_lj_is_baked_not_falsely_called_native(self) -> None:
        result = project_cut_repair(_input(
            "audio-lj-overlap",
            _InputOptions(speed=PositiveRational(5, 4))))
        self.assertEqual(result["nativeStatus"], "unsupported")
        self.assertEqual(result["deliveryDisposition"], "baked-exact-master")
        self.assertFalse(result["sampleExact"])
        self.assertEqual(
            result["repairSpeed"], {"numerator": "5", "denominator": "4"})
        self.assertEqual(
            result["repairRetime"]["effectiveRatio"],
            {"numerator": "5", "denominator": "4"})

    def test_fractional_and_multi_source_repairs_fail_native_closed(self) -> None:
        inputs = (
            _input("extend-and-reclaim-silence", _InputOptions(
                fps=PositiveRational(30000, 1001))),
            _input("extend-and-reclaim-silence", _InputOptions(
                multi_source=True)),
        )
        for item in inputs:
            with self.subTest(item=item):
                result = project_cut_repair(item)
                self.assertEqual(result["nativeStatus"], "unsupported")
                self.assertNotIn("expectedCuts", result)
                self.assertNotIn("expectedTotalFrames", result)

    def test_integer_single_source_frame_projection_gets_full_readback(self) -> None:
        result = project_cut_repair(_input(
            "extend-and-reclaim-silence"))
        self.assertEqual(result["nativeStatus"], "frame-exact-unqualified")
        self.assertEqual(result["expectedTotalFrames"], 120)
        proof = verify_cut_repair_readback(
            result, _timeline(), _timeline())
        self.assertTrue(proof["unrelatedInventoryPreserved"])
        self.assertFalse(proof["sampleExact"])
        self.assertRegex(proof["readbackHash"], r"^[0-9a-f]{64}$")

    def test_unrelated_palmier_change_blocks_readback(self) -> None:
        result = project_cut_repair(_input(
            "extend-and-reclaim-silence"))
        with self.assertRaisesRegex(PalmierError, "unrelated"):
            verify_cut_repair_readback(
                result, _timeline(), _timeline(changed_overlay=True))

    def test_renderer_retime_substitution_fails_closed(self) -> None:
        item = _input("audio-lj-overlap")
        item.retime["effectiveRatio"] = {
            "numerator": "2", "denominator": "1"}
        with self.assertRaisesRegex(PalmierError, "retime disagrees"):
            project_cut_repair(item)


if __name__ == "__main__":
    unittest.main(verbosity=2)
