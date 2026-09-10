"""Tiny local raw-pixel geometry probes; NOT production/media-owner qualification."""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
import unittest
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from graphics.composite_core import CompositeOptions, composite
from graphics.presenter_layout_geometry import compile_presenter_geometry
from graphics.presenter_layout_graph import PresenterGraphSpec, PresenterGraphWindow
from graphics import composite_core, presenter_layout_graph
from test_opening_compositor_media import _ffmpeg
from test_presenter_layout_graph import declaration, graph_spec

_FRAME_BYTES = 64 * 36 * 3 // 2


class PresenterLayoutGraphMediaTests(unittest.TestCase):
    """Observe64×36 synthetic pixels; no Docker/catalog/creator footage/provider."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create bounded original-clock/color synthetic fixtures and retain them."""
        cls.started = time.monotonic()
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-presenter-pixels-", dir="/private/tmp"))
        cls.base, cls.image, cls.video = (cls.root / name for name in ("base.mkv", "slide.png", "slide.mkv"))
        cls.results = []
        _ffmpeg(["-f", "lavfi", "-i", "color=c=lime:s=64x36:r=30000/1001:d=1",
            "-frames:v", "24", "-c:v", "ffv1", "-pix_fmt", "yuv420p", "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709", str(cls.base)])
        _ffmpeg(["-f", "lavfi", "-i", "color=c=red:s=64x36", "-frames:v", "1",
            "-pix_fmt", "rgb24", "-update", "1", str(cls.image)])
        _ffmpeg(["-f", "lavfi", "-i", "color=c=gray:s=64x36:r=30000/1001:d=2",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
            "-vf", "geq=lum='16+4*N':cb=128:cr=128,"
            "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=limited", "-frames:v", "48",
            "-c:v", "ffv1", "-c:a", "pcm_s16le", "-pix_fmt", "yuv420p", "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709", str(cls.video)])
        cls.base_raw = _ffmpeg(["-i", str(cls.base), "-map", "0:v:0", "-pix_fmt", "yuv420p", "-f", "rawvideo", "-"])
        cls.video_raw = _ffmpeg(["-i", str(cls.video), "-map", "0:v:0", "-pix_fmt", "yuv420p", "-f", "rawvideo", "-"])
        if [cls.video_raw[n * _FRAME_BYTES] for n in range(48)] != [16 + 4 * n for n in range(48)]:
            raise AssertionError("TEST source generator changed its explicitly declared BT709 luma")
        print(f"TEST-only presenter pixel evidence: {cls.root}", flush=True)

    @classmethod
    def tearDownClass(cls) -> None:
        """Keep observations even on assertion failure; runner output owns status."""
        report = {"scope": "TEST-only64x36-raw-geometry-not-owner-quality-or-approval",
            "elapsedSeconds": time.monotonic() - cls.started, "observations": cls.results,
            "productionQualified": False, "audioCompared": False, "deliveryApproved": False,
            "assertionOutcomeNotRecorded": True}
        (cls.root / "observations.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"Presenter pixel cohort elapsedSeconds={report['elapsedSeconds']:.3f}", flush=True)

    def _spec(self, kind: str, image: bool = True) -> PresenterGraphSpec:
        """Attach only the fixture paths to exact TEST metadata."""
        spec = graph_spec(kind, image)
        asset = replace(spec.windows[0].asset, path=str(self.image if image else self.video))
        return replace(spec, windows=(replace(spec.windows[0], asset=asset),))

    def _raw(self, label: str, spec: PresenterGraphSpec, frame_range: tuple[int, int] = (0, 24)) -> bytes:
        """Run the actual shared graph before encoding, with15s per-command bound."""
        started, commands = time.monotonic(), []
        composite(str(self.base), [], str(self.root / f"{label}-unused.mp4"), CompositeOptions(
            frame_rate=spec.frame_rate, frame_range=frame_range, video_only=True,
            presenter=spec, command_runner=commands.append))
        command = commands[0]
        graph_end = command.index("-map") + 2
        arguments = command[1:graph_end]
        raw = _ffmpeg([*arguments, "-pix_fmt", "yuv420p", "-frames:v", str(frame_range[1] - frame_range[0]),
            "-f", "rawvideo", "-"])
        (self.root / f"{label}.yuv").write_bytes(raw)
        self.results.append({"label": label, "range": frame_range, "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "elapsedSeconds": time.monotonic() - started,
            "sharedGraphSha256": hashlib.sha256(command[command.index("-filter_complex") + 1].encode()).hexdigest()})
        self.assertEqual(len(raw), (frame_range[1] - frame_range[0]) * _FRAME_BYTES)
        return raw

    def _luma(self, raw: bytes, frame: int, point: tuple[int, int]) -> int:
        """Read the full-resolution8-bit luma plane, not subsampled edge chroma."""
        return raw[frame * _FRAME_BYTES + point[1] * 64 + point[0]]

    def test_actual_masks_and_untouched_enter_exit_pixels_for_all_three_forms(self) -> None:
        """Observe exact outside-window pixels and distinct settled mask shapes."""
        for kind in ("inset", "bubble", "split"):
            with self.subTest(kind=kind):
                self._assert_form(kind)

    def _assert_form(self, kind: str) -> None:
        """Use source pixel equality and independent final mask probe points."""
        raw = self._raw(kind, self._spec(kind))
        for frame in (0, 1, 2, 17, 18, 23):
            interval = slice(frame * _FRAME_BYTES, (frame + 1) * _FRAME_BYTES)
            self.assertEqual(raw[interval], self.base_raw[interval], (kind, frame))
        centre = {"inset": (48, 27), "bubble": (56, 26), "split": (16, 18)}[kind]
        backing = (48, 18) if kind == "split" else (0, 0)
        self.assertGreater(self._luma(raw, 5, centre), 130)  # Actual lime presenter.
        self.assertLess(self._luma(raw, 5, backing), 100)  # Actual red presentation.
        if kind == "bubble":
            self.assertLess(self._luma(raw, 5, (48, 18)), 100)  # Real circle excludes corner.
        if kind == "inset":
            self.assertLess(self._luma(raw, 3, (0, 0)), 100)  # Entry really started at global3.
            self.assertGreater(self._luma(raw, 3, (32, 18)), 130)

    def test_opening_trim_inside_entry_hold_exit_matches_actual_full_graph(self) -> None:
        """Prefix parity compares raw pixels from the actual global graph."""
        spec = self._spec("bubble")
        full = self._raw("trim-reference", spec)
        for start, end in ((3, 8), (6, 12), (13, 20)):
            raw = self._raw(f"trim-{start}-{end}", spec, (start, end))
            self.assertEqual(raw, full[start * _FRAME_BYTES:end * _FRAME_BYTES])

    def test_video_asset_first_frame_selection_is_not_reset_by_global_origin(self) -> None:
        """Compare against observed source frames, not unobserved fixture labels."""
        spec, payload = self._spec("inset", False), declaration()
        payload["assetStart"] = {"numerator": 1001, "denominator": 10000}  # Exactly source frame3.
        geometry = compile_presenter_geometry(payload, spec.canvas, (2, 18))
        spec = replace(spec, windows=(replace(spec.windows[0], geometry=geometry),))
        raw = self._raw("video-start", spec)
        for frame in range(5, 15):
            source_frame = 3 + frame - 2
            self.assertEqual(self._luma(raw, frame, (0, 0)), self._luma(self.video_raw, source_frame, (0, 0)))

    def test_srgb_midgray_uses_declared_display_transfer_not_camera_oetf(self) -> None:
        """Check n8's explicit display mapping; do not misname it camera BT709."""
        image = self.root / "srgb-midgray.png"
        _ffmpeg(["-f", "lavfi", "-i", "nullsrc=s=64x36,format=gbrp,geq=r=128:g=128:b=128",
            "-frames:v", "1", "-pix_fmt", "rgb24", "-update", "1", str(image)])
        source = _ffmpeg(["-i", str(image), "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
        self.assertEqual(source, bytes([128]) * (64 * 36 * 3))
        spec = self._spec("inset")
        spec = replace(spec, windows=(replace(spec.windows[0], asset=replace(spec.windows[0].asset, path=str(image))),))
        raw = self._raw("srgb-midgray", spec)
        linear = ((128 / 255 + .055) / 1.055) ** 2.4
        # Equal SDR white/black endpoints: source sRGB EOTF, destination inverse
        # BT1886 (n8 libswscale/cms.c and libavutil/csp.c), then limited range.
        # Nominal BT709 camera OETF is a different, deliberately unclaimed path.
        expected = 16 + 219 * linear ** (1 / 2.4)
        self.assertLessEqual(abs(self._luma(raw, 5, (0, 0)) - expected), 1)

    def test_actual_single_picture_encode_discards_real_presentation_asset_audio(self) -> None:
        """Observe a real MP4; this is not the final held-master audio workflow."""
        def streams(file: Path) -> list[dict]:
            """Observe actual output streams with a short local-tool deadline."""
            result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(file)],
                capture_output=True, check=True, timeout=15)
            return json.loads(result.stdout)["streams"]

        def run(command: list[str]) -> None:
            """Execute only this tiny captured production command, bounded15s."""
            subprocess.run(command, capture_output=True, check=True, timeout=15)

        self.assertEqual([s["codec_type"] for s in streams(self.video)], ["video", "audio"])
        spec, output = self._spec("inset", False), self.root / "actual-picture-only.mp4"
        started = time.monotonic()
        composite(str(self.base), [], str(output), CompositeOptions(
            frame_rate=spec.frame_rate, video_only=True, presenter=spec, command_runner=run))
        observed = streams(output)
        self.assertEqual([s["codec_type"] for s in observed], ["video"])
        self.assertEqual((int(observed[0]["nb_frames"]), observed[0]["avg_frame_rate"]), (24, spec.frame_rate))
        decoded = _ffmpeg(["-xerror", "-err_detect", "explode", "-i", str(output), "-map", "0:v:0",
            "-pix_fmt", "yuv420p", "-f", "rawvideo", "-"])
        self.assertEqual(len(decoded), 24 * _FRAME_BYTES)
        self.results.append({"label": "actual-picture-only-encode", "elapsedSeconds": time.monotonic() - started,
            "path": str(output), "videoFrames": 24, "audioStreams": 0, "fullDecode": True})

    def test_cached_still_is_pixel_identical_to_repeated_decode_and_color_work(self) -> None:
        """Retain the slower TEST reference; no quality tolerance or encode hides differences."""
        spec = self._spec("bubble")
        cached = self._raw("cached-still", spec)
        original_filter = presenter_layout_graph._presentation_filter
        original_inputs = composite_core.presenter_input_arguments

        def repeated_filter(window: PresenterGraphWindow, rate: Fraction) -> str:
            """Restore the prior per-frame still work for this16-frame TEST case."""
            value = original_filter(window, rate)
            self.assertIn("end_frame=1,", value)
            self.assertIn(",loop=loop=15:size=1:start=0", value)
            return value.replace("end_frame=1,", "end_frame=16,").replace(",loop=loop=15:size=1:start=0", "")

        def repeated_input(value: PresenterGraphSpec) -> list[str]:
            """Repeat decoding the exact same source, not a re-encoded surrogate."""
            return ["-loop", "1", *original_inputs(value)]

        with patch.object(presenter_layout_graph, "_presentation_filter", side_effect=repeated_filter), \
                patch.object(composite_core, "presenter_input_arguments", side_effect=repeated_input):
            uncached = self._raw("uncached-still-reference", spec)
        self.assertEqual(cached, uncached)

    def test_local_mask_registers_preserve_every_raw_frame_in_all_layout_forms(self) -> None:
        """Compare every output byte against original expanded arithmetic, no tolerance."""
        from test_presenter_alpha_optimization import legacy_alpha
        for kind, still in ((kind, still) for kind in ("inset", "bubble", "split") for still in (True, False)):
            spec = self._spec(kind, still)
            label = f"alpha-{kind}-{'still' if still else 'video'}"
            optimized = self._raw(label + "-local", spec)
            with patch("graphics.presenter_layout_geometry._alpha", side_effect=legacy_alpha):
                reference = self._raw(label + "-expanded-reference", spec)
            self.assertEqual(optimized, reference, label)


if __name__ == "__main__":
    unittest.main(verbosity=2)
