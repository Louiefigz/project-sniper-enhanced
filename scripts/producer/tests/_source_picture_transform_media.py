"""Tiny installed-tool math diagnostic, explicitly not source/grade authority.

The NUT/raw-video fixture has no ingest/creator receipt. Each actual child uses
the unchanged owned runner and one decreasing 30-second aggregate deadline.
Outputs stay in a new retained private test root, with no network/provider use.
"""
from __future__ import annotations

import json
import shutil
import struct
import time
from dataclasses import replace
from pathlib import Path

from _source_picture_transform_fixture import held_test_file, transform_fixture
from color.source_picture_transform import PictureTransformPlan, compile_source_picture_transform
from headless.process_runner import ProcessRequest, run_text


class RampRun:
    """Small native files and closed TEST commands under one existing deadline."""

    def __init__(self, root: Path) -> None:
        """Capture explicit installed tools once; never download or infer images."""
        self.root, self.expires = root, time.monotonic() + 30
        self.calls = []
        self.ffmpeg = str(Path(shutil.which("ffmpeg")).resolve(strict=True))
        self.ffprobe = str(Path(shutil.which("ffprobe")).resolve(strict=True))
        prefix = Path(self.ffmpeg).parent.parent
        zimg = Path("/opt/homebrew/Cellar/zimg/3.0.6/lib/libzimg.2.dylib")
        self.tools = {"ffmpeg": held_test_file(Path(self.ffmpeg)),
            "libavfilter": held_test_file(prefix / "lib/libavfilter.11.dylib"),
            "libzimg": held_test_file(zimg), "ffmpegVersion": "8.0", "zimgVersion": "3.0.6"}
        version = self.run((self.ffmpeg, "-version"), "installed-version")
        if not version.startswith("ffmpeg version 8.0 "):
            raise RuntimeError("TEST FFmpeg changed version outside compiler class")

    def guard(self) -> None:
        """No phase, retry, probe or assertion renews the original test clock."""
        if time.monotonic() >= self.expires:
            raise TimeoutError("TEST original aggregate deadline expired")

    def run(self, command: tuple[str, ...], label: str) -> str:
        """Keep stderr and exact command; owned runner proves its group gone."""
        self.guard()
        started = time.monotonic()
        result = run_text(ProcessRequest(command, "", str(self.root),
            {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, self.expires - time.monotonic(),
            max_output_bytes=256 * 1024))
        self.calls.append({"label": label, "command": list(command), "returnCode": result.returncode,
            "elapsedMs": (time.monotonic() - started) * 1000, "stderr": result.stderr})
        self.guard()
        if result.returncode or result.stderr:
            raise RuntimeError(f"TEST ramp command failed/warned: {result.stderr}")
        return result.stdout

    def ff(self, args: tuple[str, ...], label: str) -> None:
        """Test-only absolute tool invocation; no shell or inherited model env."""
        self.run((self.ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-n",
            "-threads", "1", "-filter_threads", "1", *args), label)

    def source(self, name: str, values: list[tuple[int, int, int]], rate: str) -> Path:
        """Create uniform chroma patches and a nonzero native rational PTS clock."""
        raw, output = self.root / f"{name}.yuv", self.root / f"{name}.nut"
        raw.write_bytes(b"".join(bytes([y]) * 32 + bytes([cb]) * 8 + bytes([cr]) * 8
                                 for y, cb, cr in values))
        self.ff(("-f", "rawvideo", "-pixel_format", "yuv420p", "-video_size", "8x4",
            "-framerate", rate, "-i", str(raw), "-vf", "setpts=PTS+2/TB", "-fps_mode", "passthrough",
            "-c:v", "rawvideo", "-f", "nut", str(output)), name + "-source")
        return output

    def compile(self, rate: str, count: int) -> PictureTransformPlan:
        """Only filter syntax comes from synthetic compiled context, never authority."""
        context, intent = transform_fixture(rate, count)
        return compile_source_picture_transform(replace(context, tools=self.tools), intent, self.guard)

    def convert(self, source: Path, fragment: str, name: str) -> Path:
        """Run exactly the fixed filter fragment without FPS/geometry changes."""
        output = self.root / f"{name}.nut"
        self.ff(("-copyts", "-i", str(source), "-map", "0:v:0", "-an", "-vf", fragment,
            "-fps_mode", "passthrough", "-c:v", "rawvideo", "-f", "nut", str(output)), name)
        return output

    def float_pixels(self, source: Path, name: str) -> tuple[float, ...]:
        """Read a small complete planar float output; no large raw buffering."""
        data = self.raw_pixels(source, name)
        if len(data) % 4:
            raise RuntimeError("TEST raw float size is not exact")
        return struct.unpack("<" + "f" * (len(data) // 4), data)

    def raw_pixels(self, source: Path, name: str) -> bytes:
        """Extract complete raw bytes under the same tiny file/deadline bounds."""
        path = self.root / f"{name}.f32"
        self.ff(("-i", str(source), "-map", "0:v:0", "-an", "-c:v", "copy",
            "-f", "rawvideo", str(path)), name + "-raw")
        size = path.stat().st_size
        if not 0 < size <= 64 * 1024:
            raise RuntimeError("TEST raw output size is not bounded")
        return path.read_bytes()

    def metadata(self, path: Path) -> dict:
        """Observe every native frame and packet timestamp from actual NUT bytes."""
        raw = self.run((self.ffprobe, "-v", "error", "-show_streams", "-show_frames",
            "-of", "json", str(path)), path.stem + "-probe")
        return json.loads(raw)

    def finish(self) -> None:
        """Retain all timing and unchanged tool identities, without any approval."""
        for key in ("ffmpeg", "libavfilter", "libzimg"):
            if held_test_file(Path(self.tools[key]["path"])) != self.tools[key]:
                raise RuntimeError("TEST tool changed during diagnostic")
        self.guard()
        (self.root / "TEST-ramp-calls.json").write_text(json.dumps({"tools": self.tools,
            "calls": self.calls, "sourceAuthority": False, "gradeApproved": False,
            "deliveryApproved": False}, indent=2) + "\n")
