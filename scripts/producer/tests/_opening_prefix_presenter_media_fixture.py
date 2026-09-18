"""Tiny actual graph/encode evidence, with explicitly TEST-only admission rows.

No isolated admission, external renderer, audio, caption authority or creative
approval is claimed. Every command uses the reusable fixture's original clock.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _guided_presenter_observation_media_fixture import PresenterObservationMediaFixture
from graphics.composite_core import CompositeOptions, composite
from graphics.presenter_layout_contract import PresenterCanvas, declaration_payload
from graphics.presenter_layout_geometry import compile_presenter_geometry
from graphics.presenter_layout_graph import PresenterGraphSpec, PresenterGraphWindow
from headless.process_runner import ProcessRequest
from opening_prefix_composition import PrefixCompositionJob, compose_verified_prefix
from opening_prefix_contract import CompositorPrefixRequest, PrefixClock, PrefixOracleRuntime, PrefixRanges
from opening_prefix_oracle import _frames
from opening_prefix_presenter import PrefixPresenterGraphs
from test_opening_prefix_contract import held


class PresenterPrefixMediaFixture:
    """Reuse actual returned observations without a second selected-asset decode."""

    def __init__(self) -> None:
        """Generate one alpha TEST page and copy a distinct already-observed base."""
        self.media = PresenterObservationMediaFixture()
        self.root = self.media.root
        self.base = self.root / "TEST-distinct-base.mp4"
        shutil.copyfile(self.media.cases["video"].source.path, self.base)
        self.page = self.root / "TEST-alpha-page.mov"
        command = [self.media.ffmpeg.path, "-v", "error", "-nostdin", "-f", "lavfi", "-i",
            "color=c=black@0:s=64x36:r=30000/1001:d=1,format=argb,"
            "drawbox=x=2:y=2:w=12:h=6:color=blue@1:t=fill:replace=1,setsar=1",
            "-an", "-frames:v", "24", "-threads", "1", "-c:v", "qtrle", "-pix_fmt", "argb",
            "-video_track_timescale", "30000", str(self.page)]
        self.run("TEST-alpha-generate", command)
        self.runtime = PrefixOracleRuntime(held(Path(self.media.ffmpeg.path)),
            held(Path(self.media.runtime.ffprobe.path)), str(self.root), 30)
        self.results: list[dict] = []
        self.failures: list[str] = []

    def run(self, label: str, command: list[str]) -> subprocess.CompletedProcess:
        """Bound every real process by the same original180s including setup."""
        request = ProcessRequest(tuple(command), "", str(self.root), {"LANG": "C", "LC_ALL": "C"},
            self.media.deadline.remaining(), max_output_bytes=1024 * 1024)
        result = self.media._run(label, request)
        if result.returncode:
            raise RuntimeError("TEST prefix command failed: " + result.stderr[-1200:])
        return result

    def request(self, name: str) -> CompositorPrefixRequest:
        """Keep crossing/future original windows and a full-native caption-role tail."""
        case = self.media.cases[name]
        canvas = PresenterCanvas(64, 36, 24, "yuv420p")
        declaration = declaration_payload(case.selected.geometry)
        first = compile_presenter_geometry(declaration, canvas, (2, 16))
        last = compile_presenter_geometry({**declaration, "enterFrames": 1, "exitFrames": 1}, canvas, (18, 24))
        windows = tuple(PresenterGraphWindow(index, geometry, case.observed.graph_asset)
                        for index, geometry in ((3, first), (8, last)))
        full = PresenterGraphSpec(canvas, "30000/1001", windows, "bt709-limited-video")
        presenter = PrefixPresenterGraphs(full, replace(full, windows=windows[:1]),
            (held(Path(case.source.path)),), (case.observed,), self.media.deadline.remaining)
        page = {"path": str(self.page), "outStart": 0, "outEnd": 24 * 1001 / 30000,
            "startFrame": 0, "endFrameExclusive": 24, "anchor": "own-screen", "x": 0, "y": 0,
            "compositionRole": "caption-page", "captionPageId": held(self.page).sha256}
        return CompositorPrefixRequest(held(self.base), (held(self.page),), (page,), (page,),
            PrefixClock("30000/1001", 24, 64, 36), PrefixRanges((3, 9), (0, 12)), (1, 1), presenter)

    def compose(self, name: str) -> tuple[dict, PrefixCompositionJob]:
        """Capture actual proof/encode commands and refuse any duplicate observer call."""
        directory = self.root / ("prefix-" + name)
        directory.mkdir(mode=0o700)
        job = PrefixCompositionJob(self.request(name), self.runtime, str(directory / "picture.mp4"),
                                   self.media.deadline.remaining)
        index = 0

        def capture(request: ProcessRequest) -> subprocess.CompletedProcess:
            """Record the unchanged owned runner, not synthesized tool output."""
            nonlocal index
            index += 1
            return self.media._run(f"{name}-prefix-{index}", request)

        with patch("opening_prefix_oracle.run_text", capture), \
                patch("opening_prefix_composition.run_text", capture), \
                patch("guided_presenter_observation.run_text", side_effect=AssertionError("duplicate observation")):
            result = compose_verified_prefix(job)
        (directory / "TEST-prefix-result.json").write_text(json.dumps(result, indent=2) + "\n")
        return result, job

    def reference(self, name: str, job: PrefixCompositionJob) -> Path:
        """Use the ordinary identical graph/encoder, differing only MP4 storage transport."""
        path = Path(job.output_path).with_name("ordinary-reference.mp4")
        commands = []
        composite(job.request.base.path, list(job.request.full_clips), str(path), CompositeOptions(
            eof_pass=True, ffmpeg=self.runtime.ffmpeg.path, ffprobe=self.runtime.ffprobe.path,
            command_runner=commands.append, frame_rate="30000/1001", video_only=True,
            caption_tail=1, presenter=job.request.presenter.full))
        if len(commands) != 1:
            raise AssertionError("TEST expected one ordinary picture encode")
        self.run(name + "-ordinary-encode", commands[0])
        return path

    def frames(self, label: str, path: Path) -> tuple[str, ...]:
        """Decode to strict EOF; compare all24 RGB frames, not just a container hash."""
        result = self.run(label, [self.runtime.ffmpeg.path, "-v", "error", "-xerror", "-err_detect", "explode",
            "-i", str(path), "-map", "0:v:0", "-an", "-c:v", "rawvideo", "-pix_fmt", "rgb24",
            "-fps_mode", "passthrough", "-f", "framehash", "-hash", "sha256", "-"])
        return _frames(result.stdout, (24, "30000/1001", 64 * 36 * 3))

    def record(self, status: str, error: str | None = None) -> None:
        """Retain successes and failures with limitations and original-clock timing."""
        if error is not None:
            self.failures.append(error)
        status = "failed" if self.failures else status
        report = {"scope": "TEST-actual-presenter-prefix-and-picture-transport-only", "status": status,
            "failures": self.failures, "results": self.results, "commands": self.media.commands,
            "elapsedSeconds": time.monotonic() - self.media.deadline.started,
            "isolatedAdmissionVerified": False, "captionAuthorityVerified": False,
            "audioCompared": False, "deliveryApproved": False, "framingApproved": False}
        (self.root / "TEST-prefix-media-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
