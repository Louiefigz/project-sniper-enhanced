"""Real tiny opening range pictures; no public profile, admission or creative QC."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch

from _guided_presenter_observation_media_fixture import PresenterObservationMediaFixture
from cut_preview_io import digest
from graphics.composite_core import CompositeOptions, composite
from graphics.presenter_layout_contract import PresenterCanvas, declaration_payload
from graphics.presenter_layout_geometry import compile_presenter_geometry
from guided_opening_picture import compose_ranges
from guided_opening_presenter import OpeningPictureContext, OpeningPresenterContext
from guided_presenter_execution import OwnedPresenterExecution
from headless.process_runner import ProcessRequest
from opening_prefix_oracle import _frames
from palmier.process_deadline import use_process_deadline
from test_opening_prefix_contract import held


class OpeningPresenterMediaTests(unittest.TestCase):
    """Compare every encoded opening frame with the unchanged full original graph."""

    @classmethod
    def setUpClass(cls) -> None:
        """One original180s clock starts before every generated input and observation."""
        cls.media = PresenterObservationMediaFixture()
        cls.base = cls.media.root / "TEST-distinct-opening-base.mp4"
        shutil.copyfile(cls.media.cases["video"].source.path, cls.base)
        cls.results, cls.commands, cls.failures = [], [], []

    def context(self, name: str) -> OpeningPictureContext:
        """Join returned actual observations to explicit TEST-only low-level ownership."""
        case = self.media.cases[name]
        payload = declaration_payload(case.selected.geometry)
        canvas = PresenterCanvas(64, 36, 24, "yuv420p")
        spans = ((3, (2, 16), payload), (8, (18, 24), {**payload, "enterFrames": 1, "exitFrames": 1}))
        selected = tuple(replace(case.selected, operation_index=index,
            geometry=compile_presenter_geometry(declaration, canvas, span)) for index, span, declaration in spans)
        owner = OwnedPresenterExecution(selected, (case.observed,), "30000/1001", self.media.runtime)
        plan = {"presenterLayouts": [{"operationIndex": row.operation_index,
            "startFrame": row.geometry.timing.start_frame, "endFrameExclusive": row.geometry.timing.end_frame_exclusive,
            "layout": declaration_payload(row.geometry)} for row in selected]}
        authority = {"candidatePlanHash": digest(plan), "frameRate": "30000/1001", "totalFrames": 24,
            "target": {"width": 64, "height": 36}, "core": {"startFrame": 0, "endFrameExclusive": 6},
            "review": {"startFrame": 0, "endFrameExclusive": 12}}
        output = self.media.root / ("opening-" + name)
        output.mkdir(mode=0o700)
        tools = {"ffmpeg": {"path": self.media.ffmpeg.path}, "ffprobe": {"path": self.media.runtime.ffprobe.path}}
        return OpeningPictureContext(output, authority, tools, OpeningPresenterContext(owner, plan, held(self.base)))

    def frames(self, path: Path, count: int) -> tuple:
        """Decode strict EOF to actual RGB frame hashes using the same original clock."""
        command = (self.media.ffmpeg.path, "-v", "error", "-xerror", "-err_detect", "explode",
            "-i", str(path), "-map", "0:v:0", "-an", "-c:v", "rawvideo", "-pix_fmt", "rgb24",
            "-fps_mode", "passthrough", "-f", "framehash", "-hash", "sha256", "-")
        request = ProcessRequest(command, "", str(self.media.root), {"LANG": "C", "LC_ALL": "C"},
            min(60, self.media.deadline.remaining()), max_output_bytes=1024 * 1024)
        result = self.media._run("opening-frames-" + path.parent.name + "-" + path.stem, request)
        if result.returncode:
            raise RuntimeError(result.stderr[-1200:])
        return _frames(result.stdout, (count, "30000/1001", 64 * 36 * 3))

    def _record(self) -> None:
        """Retain failed attempts too; synthetic admission never becomes profile approval."""
        report = {"scope": "TEST-tiny-actual-opening-presenter-range-pictures-only",
            "results": self.results, "commands": self.commands, "setupAndOwnedCommands": self.media.commands,
            "failures": self.failures, "status": "failed" if self.failures else "passed",
            "elapsedSeconds": time.monotonic() - self.media.deadline.started,
            "sourceAdmissionVerified": False, "captionClearanceVerified": False,
            "audioCompared": False, "native1080Qualified": False, "deliveryApproved": False}
        (self.media.root / "TEST-opening-presenter-evidence.json").write_text(json.dumps(report, indent=2) + "\n")

    def _check(self, name: str) -> None:
        """Instrument unchanged real subprocess returns; never synthesize media facts."""
        context, original = self.context(name), subprocess.run

        def run(command: list, *args: object, **kwargs: object) -> subprocess.CompletedProcess:
            """Retain timing with each child capped by60s and the original remainder."""
            kwargs["timeout"] = min(60, self.media.deadline.remaining(), kwargs.get("timeout", 60))
            started = time.monotonic()
            row = {"argv": list(command), "timeoutSeconds": kwargs["timeout"]}
            self.commands.append(row)
            try:
                result = original(command, *args, **kwargs)
                row["returncode"] = result.returncode
                return result
            finally:
                row["elapsedSeconds"] = time.monotonic() - started

        try:
            with use_process_deadline(self.media.deadline), patch("subprocess.run", side_effect=run), \
                    patch("guided_presenter_observation.run_text", side_effect=AssertionError("duplicate selected decode")):
                result = compose_ranges(self.base, [], context)
                self._references(context, result)
            self.results.append({"case": name, "ranges": result["ranges"], "all18EncodedRgbFramesEqual": True,
                "crossingWindowNotRetimed": True, "futureWindowNotPrematurelyOverlaid": True})
            (context.root / "TEST-picture-result.json").write_text(json.dumps(result, indent=2) + "\n")
        except BaseException as error:
            self.failures.append(f"{name}: {type(error).__name__}: {error}")
            raise
        finally:
            self._record()

    def _references(self, context: OpeningPictureContext, result: dict) -> None:
        """Use full original windows, same graph/compiler/encoder and exact range origin."""
        for label in ("core", "review"):
            row = result["ranges"][label]
            reference = context.root / (label + "-full-graph-reference.mp4")
            composite(str(self.base), [], str(reference), CompositeOptions(eof_pass=True,
                ffmpeg=self.media.ffmpeg.path, ffprobe=self.media.runtime.ffprobe.path,
                frame_rate="30000/1001", frame_range=(0, row["frames"]), video_only=True,
                presenter=context.presenter.owner.full_graph()))
            self.assertTrue(row["videoDecodeSucceeded"])
            self.assertEqual(self.frames(Path(row["path"]), row["frames"]), self.frames(reference, row["frames"]))
        self.assertEqual(result["presenterLayers"]["pictureRangesHash"], digest(result["ranges"]))

    def test_actual_still_ranges_match_original_full_graph(self) -> None:
        """Actual opaque sRGB PNG is observed once, then used by both real ranges."""
        self._check("still")

    def test_actual_video_ranges_match_original_full_graph(self) -> None:
        """Actual NTSC video retains its selected source frames and motion timing."""
        self._check("video")


if __name__ == "__main__":
    unittest.main()
