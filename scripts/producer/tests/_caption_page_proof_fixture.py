"""TEST-only synthetic parser channels, never decoded media or approval proof."""
from __future__ import annotations

import json
import os
import subprocess
from fractions import Fraction


def expected(frames: int = 3, rate: str = "30/1") -> dict:
    """Return tiny explicit TEST metadata for page parser tests."""
    return {"codec_name": "png", "pix_fmt": "rgba", "width": 8, "height": 4,
            "r_frame_rate": rate, "nb_read_frames": str(frames)}


def md5_text(facts: dict) -> str:
    """Build recognizable TEST muxer text without hashing any actual pixels."""
    clock = 1 / Fraction(facts["r_frame_rate"])
    header = ("#format: frame checksums\n#version: 2\n#hash: MD5\n"
        "#software: TEST-only-not-FFmpeg-evidence\n"
        f"#tb 0: {clock.numerator}/{clock.denominator}\n"
        "#media_type 0: video\n#codec_id 0: rawvideo\n"
        f"#dimensions 0: {facts['width']}x{facts['height']}\n#sar 0: 0/1\n"
        "#stream#, dts,        pts, duration,     size, hash\n")
    size = facts["width"] * facts["height"] * 4
    return header + "".join(f"0, {index:10}, {index:10},        1, {size:8}, {'a' * 32}\n"
                            for index in range(int(facts["nb_read_frames"])))


def alpha_text(facts: dict) -> str:
    """Include fully transparent frames and one opaque frame in TEST metadata."""
    rate = Fraction(facts["r_frame_rate"])
    frames = int(facts["nb_read_frames"])
    return "".join(f"frame:{index} pts:{index * rate.denominator} "
                   f"pts_time:{float(index / rate):.6f}\n"
                   f"lavfi.signalstats.YMAX={255 if index == frames - 1 else 0}\n"
                   for index in range(frames))


def progress_text(frames: int, state: str = "end") -> str:
    """Emit the required TEST progress keys with one valid terminal block."""
    return (f"frame={frames}\nout_time_us={max(0, frames - 1) * 33333}\n"
            f"dup_frames=0\ndrop_frames=0\nprogress={state}\n")


class PageProcessStub:
    """Fake all tool calls; permit explicit failure injection after each return."""

    def __init__(self, facts: dict) -> None:
        """Hold TEST facts and calls without resolving or running any tool."""
        self.facts = facts
        self.requests = []
        self.after_decode = lambda _request: None
        self.frame_text = md5_text(facts)
        self.alpha_text = alpha_text(facts)

    def __call__(self, request: object) -> subprocess.CompletedProcess[str]:
        """Return metadata or write the exact inherited TEST progress FD."""
        self.requests.append(request)
        if request.command[0].endswith("ffprobe"):
            measured = {key: value for key, value in self.facts.items()
                        if key != "nb_read_frames"}
            return subprocess.CompletedProcess(request.command, 0, json.dumps({"streams": [measured]}), "")
        descriptor, = request.pass_fds
        os.write(descriptor, progress_text(int(self.facts["nb_read_frames"])).encode())
        self.after_decode(request)
        return subprocess.CompletedProcess(request.command, 0, self.frame_text, self.alpha_text)
