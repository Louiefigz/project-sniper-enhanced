"""Deterministic FFmpeg compositing for already-rendered graphic assets.

This module deliberately knows nothing about graphic rendering, caches, GUI
state, or publication.  Callers provide every overlay path and placement.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable

from producer_config import CANVAS, ENCODE
from graphics.composite_layers import (caption_layer_policy, frame_window as _frame_window,
                                      ordered_clips, validate_caption_tails)
from graphics.presenter_layout_graph import (PresenterGraphSpec, build_presenter_graph,
                                            presenter_input_arguments, validate_presenter_graph)

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
    frame_rate: str | None = None
    frame_range: tuple[int, int] | None = None
    video_only: bool = False
    caption_tail: int | None = None  # Explicit held caption pages AFTER sorted graphics.
    presenter: PresenterGraphSpec | None = None  # Low-level opt-in; no released Producer owner.


@dataclass
class _Graph:
    """Filter graph accumulator plus the overlay EOF policy."""

    parts: list[str]
    eof_pass: bool = False
    frame_rate: str | None = None


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


def _gate(clip: dict, graph: _Graph) -> str:
    """Keep legacy gates unchanged; the private opt-in uses exact frame indices."""
    if graph.frame_rate is not None:
        start, end = _frame_window(clip)
        return f"enable='gte(n,{start})*lt(n,{end})'"
    start, end = float(clip["outStart"]), float(clip["outEnd"])
    return f"enable='between(t,{start:.4f},{end:.4f})'"


def _overlay_origin(clip: dict, graph: _Graph) -> str:
    """Maintain the original absolute animation origin without decimal truncation."""
    if graph.frame_rate is None:
        return f"{float(clip['outStart']):.4f}/TB"
    start, _end = _frame_window(clip)
    rate = Fraction(graph.frame_rate)
    return f"{start}*{rate.denominator}/({rate.numerator}*TB)"


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
    gate = _gate(clip, graph)
    graph.parts.append(f"[ph{idx}a][ph{idx}s]overlay=x={hx}:y={hy}:{gate}{based}")
    return based


def _base_effects(prev: str, clip: dict, idx: int, graph: _Graph) -> str:
    gate = _gate(clip, graph)
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
    gate = _gate(clip, graph)
    prev = _pip_hole(prev, clip, idx, graph)
    prev = _base_effects(prev, clip, idx, graph)
    x, y = int(clip.get("x", 0)), int(clip.get("y", 0))
    xy = f"x={x}:y={y}:" if (x or y) else ""
    eof = ":eof_action=pass" if graph.eof_pass else ""
    out = f"[gc{idx}]"
    graph.parts.append(f"{prev}[ov{idx}]overlay={xy}{gate}:format=auto{eof}{out}")
    return out


def build_graph(clips: list[dict], eof_pass: bool = False, frame_rate: str | None = None,
                presenter: PresenterGraphSpec | None = None) -> tuple[str, str]:
    """Build the proven input-0 base plus ordered overlay filter graph."""
    graph = _Graph(parts=[], eof_pass=eof_pass, frame_rate=frame_rate)
    previous = "[0:v]"
    if presenter is not None:
        if frame_rate != presenter.frame_rate:
            raise ValueError("presenter graph differs from the held compositor clock")
        graph.parts, previous = build_presenter_graph(presenter, len(clips) + 1)
    for idx, clip in enumerate(clips):
        prefix = ""
        if clip.get("scaleDims"):
            width, height = clip["scaleDims"]
            prefix = f"scale={width}:{height}:flags=lanczos,"
        graph.parts.append(
            f"[{idx + 1}:v]{prefix}setpts=PTS-STARTPTS+{_overlay_origin(clip, graph)}[ov{idx}]"
        )
    for idx, clip in enumerate(clips):
        previous = _overlay_clip(previous, clip, idx, graph)
    return ";".join(graph.parts), previous


def _range_graph(graph: str, final: str, options: CompositeOptions) -> tuple[str, str]:
    """Trim only AFTER global composition; never restart an intersecting animation."""
    if options.frame_range is None:
        return graph, final
    start, end = options.frame_range
    tail = f"{final}trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS[range]"
    return (graph + ";" if graph else "") + tail, "[range]"


def _options_valid(options: CompositeOptions) -> None:
    """The development range lane must be explicit and cannot silently copy audio."""
    if options.presenter is not None:
        validate_presenter_graph(options.presenter)
        if options.frame_rate != options.presenter.frame_rate or not options.video_only:
            raise ValueError("presenter composition requires its exact picture-only clock")
    if options.frame_rate is None:
        if options.frame_range is not None or options.video_only:
            raise ValueError("private range compositor needs an exact frame rate")
        return
    if type(options.frame_rate) is not str or Fraction(options.frame_rate) <= 0 or not options.video_only:
        raise ValueError("private exact-frame compositor is picture-only")
    if options.frame_range is not None:
        if type(options.frame_range) is not tuple or len(options.frame_range) != 2:
            raise ValueError("private compositor frame range is malformed")
        start, end = options.frame_range
        _frame_window({"startFrame": start, "endFrameExclusive": end})
        if options.presenter is not None and end > options.presenter.canvas.total_frames:
            raise ValueError("presenter compositor range exceeds its held base")


def _composite_pass(
    video_in: str, clips: list[dict], video_out: str, options: CompositeOptions
) -> None:
    """Build one ordinary encode with optional explicit picture-only layers."""
    strict = options.frame_rate is not None
    cmd = [options.ffmpeg, "-n" if strict else "-y", "-hide_banner", "-loglevel", "error"]
    if strict:
        cmd += ["-nostdin", "-xerror", "-err_detect", "explode"]
    cmd += ["-i", video_in]
    for clip in clips:
        cmd.extend(("-i", clip["path"]))
    if options.presenter is not None:
        cmd += presenter_input_arguments(options.presenter)
    graph, final = build_graph(clips, options.eof_pass, options.frame_rate, options.presenter)
    graph, final = _range_graph(graph, final, options)
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
            *(() if options.video_only else ("-map", "0:a?")),
            "-c:v",
            ENCODE["vcodec"],
            "-crf",
            str(ENCODE["mezzanine_crf"]),
            "-preset",
            ENCODE["composite_preset"],
            "-pix_fmt",
            CANVAS["pix_fmt"],
            *(("-an",) if options.video_only else ("-c:a", "copy")),
            *(("-frames:v", str(options.frame_range[1] - options.frame_range[0])) if options.frame_range else ()),
            "-movflags",
            "+faststart",
            video_out,
            *extra,
        )
    )
    (options.command_runner or run_command)(cmd)


def composite(
    video_in: str,
    clips: list[dict],
    video_out: str,
    options: CompositeOptions | None = None,
) -> int:
    """Composite every ordered clip in one graph and one picture encode."""
    options = options or CompositeOptions()
    _options_valid(options)
    if options.caption_tail is not None and (options.frame_rate is None or not options.video_only):
        raise ValueError("caption-tail composition requires exact-frame picture-only execution")
    ordered = ordered_clips(clips, options.caption_tail)
    if not ordered and options.frame_range is None and options.presenter is None:
        raise RuntimeError("prebound composite requires at least one overlay")
    _composite_pass(video_in, ordered, video_out, options)
    return 1
