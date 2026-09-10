"""Tiny actual compositor graph-prefix oracles; no encoded-output/creative approval."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _common import pl  # noqa: F401
import opening_prefix_oracle as oracle
from opening_prefix_contract import (CompositorPrefixRequest, PrefixClock, PrefixOracleError,
                                     PrefixOracleRuntime, PrefixRanges)
from test_opening_compositor_media import _clip, _ffmpeg
from test_opening_prefix_contract import held


def _fixture(root: Path, rate: str) -> CompositorPrefixRequest:
    """Moving pixels plus translucent, overlapping and future graphic occurrences."""
    base = root / "base.mp4"
    _ffmpeg(["-f", "lavfi", "-i", f"testsrc2=size=64x36:rate={rate}:duration=2", "-frames:v", "24",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(base)])
    paths = [root / f"graphic-{index}.mov" for index in range(3)]
    for index, path in enumerate(paths):
        _ffmpeg(["-f", "lavfi", "-i", f"testsrc=size=64x36:rate={rate}:duration=1,format=argb",
                 "-vf", f"hue=h={index * 100},format=argb,colorchannelmixer=aa=0.7", "-c:v", "qtrle", str(path)])
    clips = [_clip(paths[0], (2, 8), rate), _clip(paths[1], (5, 10), rate), _clip(paths[2], (15, 20), rate)]
    return CompositorPrefixRequest(held(base), tuple(held(path) for path in paths),
        (clips[2], clips[1], clips[0]), (clips[1], clips[0]), PrefixClock(rate, 24, 64, 36),
        PrefixRanges((3, 9), (0, 12)))


class OpeningPrefixOracleTests(unittest.TestCase):
    """Actual production verifier calls, with retained source/output timing evidence."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-prefix-oracle-", dir="/private/tmp"))
        print(f"Synthetic prefix oracle evidence: {cls.root}", flush=True)
        cls.tools = (held(Path(shutil.which("ffmpeg"))), held(Path(shutil.which("ffprobe"))))
        cls.requests = {}
        for rate in ("24", "30000/1001", "24000/1001"):
            path = cls.root / rate.replace("/", "-")
            path.mkdir()
            cls.requests[rate] = _fixture(path, rate)

    def _runtime(self) -> PrefixOracleRuntime:
        return PrefixOracleRuntime(*self.tools, str(self.root), 30)

    def _record(self, name: str, request: CompositorPrefixRequest) -> dict:
        result = oracle.verify_compositor_prefix(request, self._runtime())
        (self.root / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n")
        print(f"{name} timingMs={json.dumps(result['timingMs'])}", flush=True)
        return result

    def test_real_core_review_graphs_match_full_prefix_at_integer_and_fractional_rates(self) -> None:
        for rate, request in self.requests.items():
            with self.subTest(rate=rate):
                result = self._record("positive-" + rate.replace("/", "-"), request)
                self.assertTrue(result["comparison"]["core"]["exactPreencodePixels"])
                self.assertTrue(result["comparison"]["review"]["exactPreencodePixels"])
                self.assertEqual(result["comparison"]["core"]["frameCount"], 6)
                self.assertEqual(result["comparison"]["review"]["frameCount"], 12)
                self.assertFalse(result["encodedOutputObserved"])
                self.assertFalse(result["audioCompared"])
                self.assertFalse(result["approvalObserved"])

    def test_missing_graphic_and_shifted_half_open_boundary_fail_actual_pixels(self) -> None:
        request = self.requests["30000/1001"]
        shifted = [dict(row) for row in request.opening_clips]
        shifted[0]["endFrameExclusive"] = 11
        for name, clips in (("missing", request.opening_clips[:1]), ("shifted", tuple(shifted))):
            with self.subTest(name=name), self.assertRaisesRegex(PrefixOracleError, "absolute frame"):
                oracle.verify_compositor_prefix(replace(request, opening_clips=clips), self._runtime())

    def test_same_start_collision_order_is_not_normalized_away(self) -> None:
        request = self.requests["24"]
        first, second = (dict(row) for row in request.opening_clips)
        first.update(startFrame=2, outStart=2 / 24)
        graph = (first, second, request.full_clips[0])
        changed = replace(request, full_clips=graph, opening_clips=(second, first))
        with self.assertRaisesRegex(PrefixOracleError, "absolute frame"):
            oracle.verify_compositor_prefix(changed, self._runtime())

    def test_no_graphics_uses_same_shared_base_trim_without_new_encoder(self) -> None:
        request = self.requests["24"]
        changed = replace(request, assets=(), full_clips=(), opening_clips=(),
                          ranges=PrefixRanges((0, 6), (0, 6)))
        result = self._record("plain", changed)
        self.assertEqual(result["comparison"]["core"], result["comparison"]["review"])

    def test_wrong_full_count_canvas_offset_and_multiple_video_fail_before_graphs(self) -> None:
        request = self.requests["24"]
        shifted, multiple = self.root / "offset.mp4", self.root / "multiple.mp4"
        _ffmpeg(["-i", request.base.path, "-c", "copy", "-output_ts_offset", "0.5", str(shifted)])
        _ffmpeg(["-i", request.base.path, "-map", "0:v", "-map", "0:v", "-c", "copy", str(multiple)])
        cases = (replace(request, clock=replace(request.clock, total_frames=25)),
                 replace(request, clock=replace(request.clock, width=66)),
                 replace(request, base=held(shifted)), replace(request, base=held(multiple)))
        for changed in cases:
            with self.subTest(base=changed.base.path), patch.object(oracle, "_compare") as compare:
                with self.assertRaises(PrefixOracleError):
                    oracle.verify_compositor_prefix(changed, self._runtime())
                compare.assert_not_called()

    def test_rewrite_same_held_bytes_during_graph_work_rejects_inventory_identity(self) -> None:
        request = self.requests["24000/1001"]
        original = oracle._compare
        path = Path(request.assets[0].path)
        data = path.read_bytes()

        def mutate(*arguments):
            result = original(*arguments)
            path.write_bytes(data)
            return result

        with patch.object(oracle, "_compare", side_effect=mutate):
            with self.assertRaisesRegex(PrefixOracleError, "inventory changed"):
                oracle.verify_compositor_prefix(request, self._runtime())

    def test_actual_huge_native_graphic_and_wrong_rate_reject_without_graph_decode(self) -> None:
        request = self.requests["24"]
        huge = self.root / "wide-graphic.mov"
        _ffmpeg(["-f", "lavfi", "-i", "color=red:s=4098x2:r=24:d=1,format=argb",
                 "-frames:v", "1", "-c:v", "qtrle", str(huge)])
        wrong_rate = self.requests["30000/1001"].assets[0]
        for source in (held(huge), wrong_rate):
            clip = _clip(Path(source.path), (2, 8), "24")
            changed = replace(request, assets=(source,), full_clips=(clip,), opening_clips=(clip,))
            with self.subTest(source=source.path), patch.object(oracle, "_compare") as compare:
                with self.assertRaisesRegex(PrefixOracleError, "canvas|frame clock"):
                    oracle.verify_compositor_prefix(changed, self._runtime())
                compare.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
