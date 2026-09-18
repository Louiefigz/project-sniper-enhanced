"""Real tiny observe→live-owner→prefix→encode tests, not production qualification.

The source admission references are explicitly TEST-only metadata. Actual local
FFmpeg/ffprobe process output is never stubbed. No Docker, catalog, provider,
human review, natural-face framing or audio/master approval is exercised here.
"""
from __future__ import annotations

import json
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from _guided_presenter_observation_media_fixture import PresenterObservationMediaFixture
from graphics.composite_core import CompositeOptions
from graphics.owned_execution import GraphicsComposition, OwnedGraphicsExecution, compose_owned
from graphics.presenter_layout_contract import PresenterCanvas, declaration_payload
from graphics.presenter_layout_geometry import compile_presenter_geometry
from guided_presenter_execution import OwnedPresenterExecution
from headless.process_runner import ProcessRequest
from opening_prefix_composition import PrefixCompositionJob, compose_verified_prefix
from opening_prefix_contract import CompositorPrefixRequest, HeldPrefixInput, PrefixClock, PrefixOracleRuntime, PrefixRanges
from opening_prefix_oracle import _frames
from test_opening_prefix_contract import held


class OwnedPresenterCompositionMediaTests(unittest.TestCase):
    """Two real input classes and a real wrong-future-graph counterexample."""

    @classmethod
    def setUpClass(cls) -> None:
        """Generate and observe selected assets once under the same cohort clock."""
        cls.fixture = PresenterObservationMediaFixture()
        cls.results = []
        cls.base = cls.fixture.root / "held-base.mp4"
        command = (cls.fixture.ffmpeg.path, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "lavfi", "-i", "color=c=lime:s=64x36:r=30000/1001:d=2", "-an", "-threads", "1",
            "-frames:v", "48", "-vf", "setsar=1,setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=limited",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", "bt709", "-color_range", "tv", "-video_track_timescale", "30000", str(cls.base))
        result = cls.run_actual("base-generate", command)
        if result.returncode or result.stderr:
            raise AssertionError(f"TEST actual base generation failed: {result.stderr}")

    @classmethod
    def run_actual(cls, label: str, command: tuple[str, ...]) -> object:
        """Retain exact bounded actual stdout/argv/timing with the original deadline."""
        request = ProcessRequest(command, "", str(cls.fixture.root), {"LANG": "C", "LC_ALL": "C"},
                                 cls.fixture.deadline.remaining(), max_output_bytes=1024 * 1024)
        return cls.fixture._run(label, request)

    @classmethod
    def tearDownClass(cls) -> None:
        """Retain observations even on assertion failure; test runner owns pass/fail."""
        report = {"scope": "actual64x36-presenter-owner-prefix-encode-with-TEST-only-admission-metadata",
            "elapsedSeconds": time.monotonic() - cls.fixture.deadline.started, "results": cls.results,
            "isolatedAdmissionVerified": False, "naturalFramingQualified": False, "audioCompared": False,
            "productionQualified": False, "deliveryApproved": False, "testOutcomeOwnedByRunner": True}
        (cls.fixture.root / "TEST-owned-composition.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"TEST-only actual owned presenter composition: {cls.fixture.root}", flush=True)

    def owner(self, label: str) -> OwnedPresenterExecution:
        """Reuse one actual decoded asset for two original full-program windows."""
        case = self.fixture.cases[label]
        canvas = PresenterCanvas(64, 36, 48, "yuv420p")
        payload = declaration_payload(case.selected.geometry)
        selected = tuple(replace(case.selected, operation_index=index,
            geometry=compile_presenter_geometry(payload, canvas, span))
            for index, span in ((7, (2, 18)), (1, (30, 46))))
        return OwnedPresenterExecution(selected, (case.observed,), "30000/1001", self.fixture.runtime)

    def compose(self, value: GraphicsComposition, change_future: bool = False) -> dict:
        """Execute the real oracle and one picture encode on the callback's actual graph."""
        root = Path(value.video_out).parent
        pair = value.presenter.prefix_graphs(12)
        if change_future:
            window = pair.full.windows[1]
            geometry = compile_presenter_geometry(declaration_payload(window.geometry), pair.full.canvas, (32, 48))
            full = replace(pair.full, windows=(pair.full.windows[0], replace(window, geometry=geometry)))
            pair = replace(pair, full=full)
        request = CompositorPrefixRequest(held(self.base), (), value.clips, (),
            PrefixClock(*value.frame_clock, *value.canvas), PrefixRanges((3, 9), (0, 12)), presenter=pair)
        runtime = PrefixOracleRuntime(held(Path(self.fixture.ffmpeg.path)), held(Path(self.fixture.runtime.ffprobe.path)),
            str(root), min(900, self.fixture.deadline.remaining()))
        proof = compose_verified_prefix(PrefixCompositionJob(request, runtime, value.video_out,
                                                               self.fixture.deadline.remaining))
        self.results.append({"output": value.video_out, "changedFuture": change_future, "proof": proof})
        return proof

    def value(self, label: str) -> GraphicsComposition:
        """Reserve a distinct private candidate directory; never replace an output."""
        root = self.fixture.root / label
        root.mkdir(mode=0o700)
        return GraphicsComposition(str(self.base), str(root / "picture.mp4"), (),
            CompositeOptions(eof_pass=True, frame_rate="30000/1001", video_only=True),
            (64, 36), ("30000/1001", 48))

    def assert_decoded(self, value: GraphicsComposition, label: str) -> None:
        """Decode every encoded output frame and observe that no asset audio leaked."""
        probe = self.run_actual(f"{label}-output-probe", (self.fixture.runtime.ffprobe.path,
            "-v", "error", "-count_frames", "-show_streams", "-of", "json", value.video_out))
        self.assertEqual((probe.returncode, probe.stderr), (0, ""))
        streams = json.loads(probe.stdout)["streams"]
        self.assertEqual([row["codec_type"] for row in streams], ["video"])
        self.assertEqual(streams[0]["nb_read_frames"], "48")
        self.assertEqual((streams[0]["width"], streams[0]["height"]), (64, 36))
        decoded = self.run_actual(f"{label}-output-full-decode", (self.fixture.ffmpeg.path,
            "-v", "error", "-nostdin", "-threads", "1", "-i", value.video_out, "-map", "0:v:0", "-an",
            "-c:v", "rawvideo", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough", "-f", "framehash", "-hash", "sha256", "-"))
        self.assertEqual((decoded.returncode, decoded.stderr), (0, ""))
        self.assertEqual(len(_frames(decoded.stdout, (48, "30000/1001", 64 * 36 * 3 // 2))), 48)

    def test_actual_still_owner_matches_prefix_and_decodes_complete_picture(self) -> None:
        """The explicit sRGB still is composed directly, without a lossy asset MP4."""
        self.run_owner_case("still")

    def test_actual_video_owner_matches_prefix_and_decodes_complete_picture(self) -> None:
        """One real24-frame video observation covers two distinct16-frame occurrences."""
        self.run_owner_case("video")

    def run_owner_case(self, label: str) -> None:
        """Use actual owned composition, with a sentinel against duplicate asset probing."""
        started = time.monotonic()
        owner, value = self.owner(label), self.value(label)
        execution = OwnedGraphicsExecution(Mock(), self.compose, self.fixture.deadline.remaining, presenter=owner)
        with patch("guided_presenter_observation.run_text", side_effect=AssertionError("repeated selected-asset decode")):
            proof = compose_owned(execution, value)
        oracle = proof["prefixOracle"]
        self.assertEqual(oracle["layerPolicy"]["fullPresenterWindows"], 2)
        self.assertEqual(oracle["layerPolicy"]["openingPresenterWindows"], 1)
        self.assertTrue(oracle["comparison"]["core"]["exactPreencodePixels"])
        self.assertTrue(oracle["comparison"]["review"]["exactPreencodePixels"])
        self.assertFalse(proof["deliveryApproved"])
        self.assert_decoded(value, label)
        self.results[-1]["ownerAndOutputQcSeconds"] = time.monotonic() - started

    def test_real_equal_opening_cannot_hide_changed_future_layout(self) -> None:
        """A genuine prefix proof for changed body geometry is rejected by the caller."""
        owner, value = self.owner("still"), self.value("wrong-future")
        execution = OwnedGraphicsExecution(Mock(), lambda actual: self.compose(actual, True),
                                            self.fixture.deadline.remaining, presenter=owner)
        with self.assertRaisesRegex(RuntimeError, "actual full graph"):
            compose_owned(execution, value)
        oracle = self.results[-1]["proof"]["prefixOracle"]
        self.assertTrue(oracle["comparison"]["core"]["exactPreencodePixels"])
        self.assertTrue(oracle["comparison"]["review"]["exactPreencodePixels"])
        self.assertFalse(self.results[-1]["proof"]["deliveryApproved"])


if __name__ == "__main__":
    unittest.main()
