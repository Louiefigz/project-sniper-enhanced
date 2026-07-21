"""Deterministic FFmpeg compositing for already-rendered graphic assets.

This module deliberately knows nothing about graphic rendering, caches, GUI
state, or publication.  Callers provide every overlay path and placement.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Callable

from producer_config import CANVAS, ENCODE

_CHUNK = 8
_FOCUS_BLUR = 20
_TAKEOVER_SIGMA = 24


@dataclass(frozen=True)
class CompositeOptions:
    """One closed invocation's compositor settings and tool identities."""

    eof_pass: bool = False
    ydif_file: str | None = None
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    command_runner: Callable[[list[str]], None] | None = None


@dataclass
class _Graph:
    """Filter graph accumulator plus the overlay EOF policy."""

    parts: list[str]
    eof_pass: bool = False


def run_command(cmd: list[str]) -> None:
    """Run one media command and retain a useful error tail."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        return
    tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-8:])
    raise RuntimeError(f"{cmd[0]} failed ({proc.returncode}):\n{tail}")


def probe_frames(path: str, ffprobe: str = "ffprobe") -> int:
    """Count video packets for the producer's one-frame-per-packet MP4s."""
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-count_packets",
        "-show_entries",
        "stream=nb_read_packets",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {proc.stderr.strip()[-200:]}")
    try:
        return int(proc.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"ffprobe returned no packet count for {path}") from exc


def _pip_hole(prev: str, clip: dict, idx: int, graph: _Graph) -> str:
    if not clip.get("pipHole"):
        return prev
    cw, ch, cx, cy = clip["pipHole"]["crop"]
    hx, hy, hw, hh = clip["pipHole"]["rect"]
    graph.parts.append(f"{prev}split[ph{idx}a][ph{idx}b]")
    graph.parts.append(
        f"[ph{idx}b]crop={cw}:{ch}:{cx}:{cy},"
        f"scale={hw}:{hh}:flags=lanczos[ph{idx}s]"
    )
    based = f"[phb{idx}]"
    start, end = float(clip["outStart"]), float(clip["outEnd"])
    gate = f"enable='between(t,{start:.4f},{end:.4f})'"
    graph.parts.append(f"[ph{idx}a][ph{idx}s]overlay=x={hx}:y={hy}:{gate}{based}")
    return based


def _base_effects(prev: str, clip: dict, idx: int, graph: _Graph) -> str:
    start, end = float(clip["outStart"]), float(clip["outEnd"])
    gate = f"enable='between(t,{start:.4f},{end:.4f})'"
    if clip.get("takeoverBase") == "blur-desat":
        graph.parts.append(f"{prev}split[tb{idx}a][tb{idx}b]")
        graph.parts.append(
            f"[tb{idx}b]gblur=sigma={_TAKEOVER_SIGMA},hue=s=0[tb{idx}bd]"
        )
        prev = f"[tbb{idx}]"
        graph.parts.append(f"[tb{idx}a][tb{idx}bd]overlay={gate}{prev}")
    if clip.get("anchor") != "focus-shift":
        return prev
    graph.parts.append(f"{prev}split[fb{idx}a][fb{idx}b]")
    graph.parts.append(f"[fb{idx}b]boxblur={_FOCUS_BLUR}[fb{idx}bl]")
    blurred = f"[fbl{idx}]"
    graph.parts.append(f"[fb{idx}a][fb{idx}bl]overlay={gate}{blurred}")
    return blurred


def _overlay_clip(prev: str, clip: dict, idx: int, graph: _Graph) -> str:
    """Composite one time-gated overlay and return its output label."""
    start, end = float(clip["outStart"]), float(clip["outEnd"])
    gate = f"enable='between(t,{start:.4f},{end:.4f})'"
    prev = _pip_hole(prev, clip, idx, graph)
    prev = _base_effects(prev, clip, idx, graph)
    x, y = int(clip.get("x", 0)), int(clip.get("y", 0))
    xy = f"x={x}:y={y}:" if (x or y) else ""
    eof = ":eof_action=pass" if graph.eof_pass else ""
    out = f"[gc{idx}]"
    graph.parts.append(f"{prev}[ov{idx}]overlay={xy}{gate}:format=auto{eof}{out}")
    return out


def build_graph(clips: list[dict], eof_pass: bool = False) -> tuple[str, str]:
    """Build the proven input-0 base plus ordered overlay filter graph."""
    graph = _Graph(parts=[], eof_pass=eof_pass)
    for idx, clip in enumerate(clips):
        start = float(clip["outStart"])
        prefix = ""
        if clip.get("scaleDims"):
            width, height = clip["scaleDims"]
            prefix = f"scale={width}:{height}:flags=lanczos,"
        graph.parts.append(
            f"[{idx + 1}:v]{prefix}setpts=PTS-STARTPTS+{start:.4f}/TB[ov{idx}]"
        )
    previous = "[0:v]"
    for idx, clip in enumerate(clips):
        previous = _overlay_clip(previous, clip, idx, graph)
    return ";".join(graph.parts), previous


def _composite_pass(
    video_in: str, clips: list[dict], video_out: str, options: CompositeOptions
) -> None:
    cmd = [options.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", video_in]
    for clip in clips:
        cmd.extend(("-i", clip["path"]))
    graph, final = build_graph(clips, options.eof_pass)
    map_label, extra = final, []
    if options.ydif_file:
        escaped = options.ydif_file.replace("'", r"'\''")
        graph += (
            f";{final}split[venc][vchk];"
            f"[vchk]signalstats,metadata=print:key=lavfi.signalstats.YDIF"
            f":file='{escaped}'[vydif]"
        )
        map_label = "[venc]"
        extra = ["-map", "[vydif]", "-f", "null", "-"]
    cmd.extend(
        (
            "-filter_complex",
            graph,
            "-map",
            map_label,
            "-map",
            "0:a?",
            "-c:v",
            ENCODE["vcodec"],
            "-crf",
            str(ENCODE["mezzanine_crf"]),
            "-preset",
            ENCODE["composite_preset"],
            "-pix_fmt",
            CANVAS["pix_fmt"],
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            video_out,
            *extra,
        )
    )
    (options.command_runner or run_command)(cmd)


def _clean_temp(path: str) -> None:
    for name in os.listdir(path):
        os.remove(os.path.join(path, name))
    os.rmdir(path)


def composite(
    video_in: str,
    clips: list[dict],
    video_out: str,
    options: CompositeOptions | None = None,
) -> int:
    """Composite pre-rendered clips, with at most eight inputs per FFmpeg pass."""
    options = options or CompositeOptions()
    ordered = sorted(clips, key=lambda clip: float(clip["outStart"]))
    chunks = [ordered[idx : idx + _CHUNK] for idx in range(0, len(ordered), _CHUNK)]
    if not chunks:
        raise RuntimeError("prebound composite requires at least one overlay")
    if len(chunks) == 1:
        _composite_pass(video_in, chunks[0], video_out, options)
        return 1
    middle = CompositeOptions(
        eof_pass=options.eof_pass,
        ffmpeg=options.ffmpeg,
        ffprobe=options.ffprobe,
        command_runner=options.command_runner,
    )
    temp = tempfile.mkdtemp(
        prefix="graphics-passes-", dir=os.path.dirname(os.path.abspath(video_out))
    )
    try:
        source = video_in
        for idx, chunk in enumerate(chunks):
            final = idx == len(chunks) - 1
            target = video_out if final else os.path.join(temp, f"pass_{idx:02d}.mp4")
            _composite_pass(source, chunk, target, options if final else middle)
            source = target
        return len(chunks)
    finally:
        _clean_temp(temp)
