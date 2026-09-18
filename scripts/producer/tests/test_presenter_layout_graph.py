"""TEST-only graph/command contracts; no admitted asset, render or approval."""
from __future__ import annotations

import copy
import unittest
from dataclasses import replace
from unittest.mock import Mock

from graphics.composite_core import CompositeOptions, build_graph, composite
from graphics.owned_execution import GraphicsComposition, OwnedGraphicsExecution, compose_owned
from graphics.presenter_layout_contract import PresenterCanvas
from graphics.presenter_layout_geometry import compile_presenter_geometry
from graphics.presenter_layout_graph import (PresenterGraphAsset, PresenterGraphSpec,
    PresenterGraphWindow, build_presenter_graph, presenter_input_arguments, validate_presenter_graph)


def declaration(kind: str = "inset") -> dict:
    """Explicit synthetic manual envelope, not a face observation."""
    row = {"schemaVersion": 1, "sourceIds": ["TEST-source"], "layout": kind,
        "cropSpace": "held-base-display", "presenterCrop": {"x": 0, "y": 0, "width": 1, "height": 1},
        "protectedPresenterRect": {"x": .4, "y": .3, "width": .2, "height": .4},
        "presenterRect": {"x": .5, "y": .5, "width": .5, "height": .5},
        "presentationRect": {"x": 0, "y": 0, "width": 1, "height": 1},
        "mask": {"kind": "rounded-rect", "radiusPx": 2}, "assetId": "TEST-presentation",
        "assetStart": {"numerator": 0, "denominator": 1}, "presentationFit": "contain",
        "assetAudio": "discard", "enterFrames": 3, "exitFrames": 3, "easing": "smoothstep-v1", "track": False}
    if kind == "split":
        row.update(mask={"kind": "rect"},
            presenterCrop={"x": 0, "y": 0, "width": .5, "height": 1},
            protectedPresenterRect={"x": .1, "y": .3, "width": .2, "height": .4},
            presenterRect={"x": 0, "y": 0, "width": .5, "height": 1},
            presentationRect={"x": .5, "y": 0, "width": .5, "height": 1})
    if kind == "bubble":
        row.update(mask={"kind": "circle"},
            presenterCrop={"x": .21875, "y": 0, "width": .5625, "height": 1},
            presenterRect={"x": .75, "y": .5, "width": .25, "height": 4 / 9})
    return row


def graph_spec(kind: str = "inset", image: bool = True) -> PresenterGraphSpec:
    """Use fake absolute paths and metadata only; no files are created."""
    canvas = PresenterCanvas(64, 36, 24, "yuv420p")
    geometry = compile_presenter_geometry(declaration(kind), canvas, (2, 18))
    asset = PresenterGraphAsset("TEST-presentation", "/TEST/presentation.png" if image else "/TEST/presentation.mp4",
        "still-image" if image else "video", 64, 36, "rgb24" if image else "yuv420p",
        None if image else "30000/1001", 1 if image else 48, True, "1:1",
        "srgb-display-to-bt709-bt1886-v1" if image else "bt709-limited-video")
    return PresenterGraphSpec(canvas, "30000/1001", (PresenterGraphWindow(3, geometry, asset),), "bt709-limited-video")


def changed_asset(value: PresenterGraphSpec, **changes: object) -> PresenterGraphSpec:
    """Replace only TEST-observed metadata for bounded refusal cases."""
    window = value.windows[0]
    return replace(value, windows=(replace(window, asset=replace(window.asset, **changes)),))


class PresenterLayoutGraphTests(unittest.TestCase):
    """Keep code-construction proof separate from pixel-quality qualification."""

    def test_all_layouts_branch_clean_input_and_keep_absolute_trim_counters(self) -> None:
        """Check independent graph labels and counters for every actual form."""
        for kind in ("inset", "bubble", "split"):
            with self.subTest(kind=kind):
                parts, label = build_presenter_graph(graph_spec(kind), 4)
                graph = ";".join(parts)
                self.assertTrue(graph.startswith("[0:v]setparams=colorspace=bt709:"))
                self.assertIn("settb=expr=1/30000,setpts=N*1001,split=2[plbase][pl0source]", graph)
                self.assertIn("[pl0source]trim=start_frame=2:end_frame=18,split", graph)
                self.assertIn("in-1+2", graph)
                self.assertIn("N+2", graph)
                self.assertIn("enable='gt(n,2)*lt(n,17)'", graph)
                self.assertIn("[4:v]trim=start_frame=0:end_frame=1", graph)
                self.assertIn("loop=loop=15:size=1:start=0", graph)
                self.assertNotIn(":a", graph)
                self.assertEqual(label, "[pl0out]")

    def test_still_input_repeats_inside_bounded_graph_without_an_intermediate_video(self) -> None:
        """No temporary video or resampling flags can substitute for a still."""
        args = presenter_input_arguments(graph_spec())
        self.assertEqual(args, ["-f", "image2", "-pattern_type", "none", "-framerate",
            "30000/1001", "-i", "/TEST/presentation.png"])
        self.assertEqual(presenter_input_arguments(graph_spec(image=False)), ["-i", "/TEST/presentation.mp4"])

    def test_video_uses_exact_frame_aligned_nonzero_asset_start(self) -> None:
        """Resolve the rational offset against actual declared video cadence."""
        spec, payload = graph_spec(image=False), declaration()
        payload["assetStart"] = {"numerator": 1001, "denominator": 10000}
        geometry = compile_presenter_geometry(payload, spec.canvas, (2, 18))
        spec = replace(spec, windows=(replace(spec.windows[0], geometry=geometry),))
        graph = ";".join(build_presenter_graph(spec, 1)[0])
        self.assertIn("trim=start_frame=3:end_frame=19", graph)
        self.assertIn("settb=expr=1/30000,setpts=(N+2)*1001", graph)

    def test_wrong_cadence_depth_alpha_color_or_short_video_never_spawns(self) -> None:
        """All observed-metadata refusals happen before command execution."""
        image, video = graph_spec(), graph_spec(image=False)
        cases = [(image, {"pixel_format": "rgba"}), (image, {"frame_rate": "30"}),
            (image, {"total_frames": 2}), (image, {"color_policy": "unknown"}),
            (video, {"frame_rate": "30"}), (video, {"pixel_format": "yuv420p10le"}),
            (video, {"zero_origin": False}), (video, {"sample_aspect_ratio": "4:3"}),
            (video, {"total_frames": 15}), (video, {"color_policy": "bt2020-pq"}),
            (image, {"path": "/TEST/../private.png"}), (image, {"width": 99999}), (video, {"total_frames": 432001})]
        for original, change in cases:
            command = Mock()
            with self.subTest(change=change), self.assertRaises(ValueError):
                composite("/TEST/base.mp4", [], "/TEST/out.mp4", CompositeOptions(
                    frame_rate=original.frame_rate, video_only=True, command_runner=command,
                    presenter=changed_asset(original, **change)))
            command.assert_not_called()

    def test_invalid_geometry_overlap_and_wrong_clock_are_rejected(self) -> None:
        """Frozen dataclasses and a matching numeric rate are not sufficient."""
        spec = graph_spec()
        duplicate = replace(spec.windows[0], operation_index=4)
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_presenter_graph(replace(spec, windows=(*spec.windows, duplicate)))
        bad = replace(spec.windows[0].geometry, shape=replace(spec.windows[0].geometry.shape, scale=.1))
        with self.assertRaisesRegex(ValueError, "derived scale"):
            validate_presenter_graph(replace(spec, windows=(replace(spec.windows[0], geometry=bad),)))
        with self.assertRaisesRegex(ValueError, "clock"):
            build_graph([], frame_rate="30", presenter=spec)
        for rate in ("1_0", " 30 ", "24/1", "60000/2002", "１", "1/10000000000000000"):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                validate_presenter_graph(replace(spec, frame_rate=rate))
        with self.assertRaises(ValueError):
            validate_presenter_graph(replace(spec, base_color_policy="unknown"))

    def test_shared_compositor_keeps_one_picture_encode_then_captions_and_global_trim(self) -> None:
        """Capture the same production command builder; do not claim an encode."""
        spec, commands = graph_spec(), []
        graphic = {"path": "/TEST/graphic.mov", "outStart": 0, "outEnd": .8,
            "startFrame": 0, "endFrameExclusive": 24}
        caption = {"path": "/TEST/caption.mov", "outStart": 0, "outEnd": .8,
            "startFrame": 0, "endFrameExclusive": 24, "x": 0, "y": 0, "anchor": "own-screen",
            "compositionRole": "caption-page", "captionPageId": "c" * 64}
        original = copy.deepcopy((graphic, caption))
        composite("/TEST/base.mp4", [graphic, caption], "/TEST/out.mp4", CompositeOptions(
            command_runner=commands.append, frame_rate=spec.frame_rate, frame_range=(5, 11),
            video_only=True, caption_tail=1, presenter=spec))
        self.assertEqual((graphic, caption), original)
        self.assertEqual(len(commands), 1)
        command = commands[0]
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("[3:v]trim=", graph)
        self.assertIn("[pl0out][ov0]overlay=", graph)
        self.assertIn("[gc0][ov1]overlay=", graph)
        self.assertTrue(graph.endswith("[gc1]trim=start_frame=5:end_frame=11,setpts=PTS-STARTPTS[range]"))
        self.assertIn("-an", command)
        self.assertNotIn("-c:a", command)
        self.assertEqual(command.count("-c:v"), 1)
        self.assertEqual(command.count("-i"), 4)

    def test_unintegrated_presenter_never_acquires_legacy_owned_prefix_proof(self) -> None:
        """The existing owned path cannot issue evidence for an unbound layer."""
        compose, guard = Mock(), Mock()
        execution = OwnedGraphicsExecution(Mock(), compose, guard)
        value = GraphicsComposition("/TEST/base", "/TEST/out", (),
            CompositeOptions(frame_rate="30000/1001", video_only=True, presenter=graph_spec()),
            (64, 36), ("30000/1001", 24))
        with self.assertRaisesRegex(RuntimeError, "no released held execution/proof owner"):
            compose_owned(execution, value)
        compose.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
