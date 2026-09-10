#!/usr/bin/env python3
"""master — stage 5: final encode, two-pass loudnorm, cover frame.

The last PRODUCER stage (see docs/producer/PRODUCER_PLAN.md §4.2 stage 5). Takes the
reframed + overlaid video and produces the delivery master in a single ffmpeg
encode pass that (optionally) burns the ASS caption track, then measures the
result and reports it. Encoding follows ``producer_config.ENCODE`` (H.264 High,
CFR, closed GOP, CABAC, faststart) and ``producer_config.AUDIO`` (AAC 256k /
48k stereo, EBU R128 to -14 LUFS / -1.5 dBTP).

Loudness is TWO-PASS: pass 1 measures with ``loudnorm=...:print_format=json``
(parsed from stderr), pass 2 applies the measured values with ``linear=true``
inside the final encode — linear normalization needs the measured stats to hit
the target without dynamic pumping. A cheap third ``ebur128`` pass verifies the
integrated LUFS landed within ``AUDIO.lufs_tolerance`` (+/-1 LU) and reports it.

Two source pathologies are handled up front (C16, quiet Sony-mic footage):
a DEAD stereo channel (mic recorded to one channel; the other at noise floor)
is dual-mono'd via ``pan`` before measurement and encode, and sources where
ffmpeg's loudnorm would SILENTLY degrade linear→dynamic (the one-shot gain
projects the true peak past the TP param, or measured LRA exceeds the LRA
param) are mastered with a measured STATIC gain + true-peak limiter instead —
dynamic loudnorm undershoots I and crushes LRA; a fixed gain preserves both.

CLI: master.py <in.mp4> <out.mp4> [--ass captions.ass] [--fps 30] [--cover cover.png]
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from guided_source_color_consumption import SourceColorPictureConsumption

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from producer_config import AUDIO, ENCODE
from producer_config import MASTERING_POLICY_VERSION as MASTERING_POLICY_VERSION

_JSON_RE = re.compile(r"\{[^{}]*\}", re.S)
_LUFS_RE = re.compile(r"\bI:\s*(-?\d+(?:\.\d+)?)\s*LUFS")
_PEAK_RE = re.compile(r"Peak level dB:\s*(-?(?:\d+(?:\.\d+)?|inf))")
CAP_FONT = "Inter"   # documented caption default; captions.py owns the real style

# --- C16 quiet-master constants (local by design; producer_config.AUDIO is
# shared and unchanged). A camera that records its mic to one stereo channel
# leaves the other at noise floor: ebur128 then reads ~3 LU low AND the
# delivery plays in one ear — detect and dual-mono instead.
DEAD_CH_FLOOR_DB = -50.0    # channel peak below this = dead (noise floor)
DEAD_CH_DELTA_DB = 25.0     # live channel must beat the dead one by this much
STATIC_MIN_I = -50.0        # below this the "speech" is room tone → dynamic
STATIC_TRIM_TOL_LU = 0.10   # stop trimming the static gain within this of target
STATIC_MAX_TRIMS = 2        # measured trim iterations (each ≈ one audio scan)


@dataclass
class MasterSpec:
    """One master render (kept to <=4 constructor args via a dataclass)."""

    src: str
    out: str
    ass: Optional[str] = None
    fps: int = 30
    # Exact rational frame rate (e.g. "24000/1001"). When set it is passed to
    # -r verbatim so an NTSC-fractional source is NOT retimed to the integer
    # rate — rounding 23.976 -> 24 duplicated ~1 frame/42s and slid every
    # downstream frame-indexed event off its seam (v2 intro, 2026-07-06).
    # ``fps`` (int) stays for GOP size / bitrate-table lookups only.
    fps_exact: Optional[str] = None
    cover: Optional[str] = None
    # Picture-derived duration clamp (+half frame in _encode). Callers should
    # derive this from frame_count / exact rational FPS, never from an MP4
    # stream/container duration that may include AAC tail padding (X9/X19).
    duration: Optional[float] = None
    # Pre-master picture packet count. When present, the final encode is
    # explicitly capped to this many video frames so CFR can never manufacture
    # frames from an AAC-padded or timestamp-inflated tail.
    frame_count: Optional[int] = None
    picture_consumption: SourceColorPictureConsumption | None = None  # Never a CLI/JSON field.


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _finite(value: object) -> Optional[float]:
    """Parse a loudnorm stat to a finite float, or None (silent/degenerate)."""
    try:
        num = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def has_audio(path: str) -> bool:
    """True if the file has at least one audio stream."""
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a",
           "-show_entries", "stream=index", "-of", "csv=p=0", path]
    return bool(_run(cmd).stdout.strip())


def measure_loudness(src: str, prefix: Optional[str] = None) -> Optional[dict]:
    """Pass 1: scan input loudness, return the parsed loudnorm JSON block.

    ``prefix`` (e.g. the dead-channel dual-mono ``pan``) is applied before the
    measurement so pass-2 stats describe the audio the encoder will actually see.
    """
    af = (f"loudnorm=I={AUDIO['lufs_target']}:TP={AUDIO['loudnorm_tp_param']}"
          f":LRA={AUDIO['lra']}:print_format=json")
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-map", "0:a:0",
           "-af", _with_prefix(prefix, af), "-f", "null", "-"]
    blocks = _JSON_RE.findall(_run(cmd).stderr)
    for block in reversed(blocks):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if "input_i" in data:
            return data
    return None


def _with_prefix(prefix: Optional[str], afilter: str) -> str:
    """Prepend an optional filter (dual-mono pan) to a filtergraph chain."""
    return f"{prefix},{afilter}" if prefix else afilter


def _channel_peaks(src: str) -> list[float]:
    """Per-channel sample peak (dBFS) via astats; the trailing Overall value
    is dropped. Empty list when unparseable (no audio / odd layout)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-map", "0:a:0",
           "-af", "astats=metadata=0", "-f", "null", "-"]
    vals = [float(v) for v in _PEAK_RE.findall(_run(cmd).stderr)]
    return vals[:-1] if len(vals) > 1 else []


def dead_channel_prefix(src: str) -> tuple[Optional[str], Optional[str]]:
    """Detect a dead stereo channel; return (dual-mono pan filter, warning).

    C16 root-cause part 1: the Sony camera records its mic to ONE channel; the
    other sits at noise floor. That halves the ebur128 program energy (~-3 LU)
    and ships speech in one ear. Dual-mono the live channel for measurement AND
    encode. (None, None) when the layout is not exactly one-dead-one-live."""
    peaks = _channel_peaks(src)
    if len(peaks) != 2:
        return None, None
    for dead, live in ((0, 1), (1, 0)):
        if (peaks[dead] < DEAD_CH_FLOOR_DB <= peaks[live]
                and peaks[live] - peaks[dead] >= DEAD_CH_DELTA_DB):
            return (f"pan=stereo|c0=c{live}|c1=c{live}",
                    f"dead audio channel {dead} (peak {peaks[dead]:.1f} dBFS) — "
                    f"dual-mono from channel {live}")
    return None, None


def _parse_stats(measured: Optional[dict]) -> Optional[dict]:
    """Pass-1 JSON → loudnorm ``measured_*`` kwargs, or None if any is
    non-finite (silent/degenerate input)."""
    if measured is None:
        return None
    stats = {
        "measured_I": _finite(measured.get("input_i")),
        "measured_TP": _finite(measured.get("input_tp")),
        "measured_LRA": _finite(measured.get("input_lra")),
        "measured_thresh": _finite(measured.get("input_thresh")),
        "offset": _finite(measured.get("target_offset")),
    }
    return None if any(v is None for v in stats.values()) else stats


def _linear_eligible(stats: dict) -> bool:
    """Mirror ffmpeg af_loudnorm's SILENT linear→dynamic fallback conditions.

    loudnorm only honors ``linear=true`` when (a) no measured stat is a sentinel
    (TP 99 / thresh -70 / LRA 0 / I 0) AND (b) the one-shot gain would keep the
    true peak under the TP param AND (c) measured LRA fits the LRA param.
    Otherwise it degrades to dynamic mode without saying so — C16: a quiet mic
    needs +18 dB, projected TP lands above -2.0, dynamic mode then undershoots
    I (-15.6) and crushes LRA (2.7). Pre-checking here routes those sources to
    the static-gain path instead of letting loudnorm degrade silently."""
    if not _loudnorm_stats_in_range(stats):
        return False
    projected_tp = stats["measured_TP"] + (AUDIO["lufs_target"] - stats["measured_I"])
    sentinel = (stats["measured_thresh"] <= -70.0 or stats["measured_TP"] >= 99.0
                or stats["measured_LRA"] == 0.0 or stats["measured_I"] == 0.0)
    return (not sentinel and projected_tp <= AUDIO["loudnorm_tp_param"]
            and stats["measured_LRA"] <= AUDIO["lra"])


def _loudnorm_stats_in_range(stats: dict) -> bool:
    """Finite float headroom may exceed loudnorm's measured-option domains."""
    bounds = {
        "measured_I": (-99, 0), "measured_TP": (-99, 99),
        "measured_LRA": (0, 99), "measured_thresh": (-99, 0),
        "offset": (-99, 99),
    }
    return all(low <= stats[key] <= high for key, (low, high) in bounds.items())


def _tp_limiter() -> str:
    """True-peak-style limiter at the loudnorm TP param.

    ``alimiter`` is sample-peak; oversampling to 192k first (exactly what
    loudnorm does internally) makes sample peak ≈ true peak. The output
    ``-ar 48000`` downsamples afterwards. ``level=false`` is required —
    alimiter's default auto-level would re-normalize to full scale."""
    limit = 10.0 ** (AUDIO["loudnorm_tp_param"] / 20.0)
    return (f"aresample=192000,alimiter=limit={limit:.6f}"
            f":attack=5:release=100:level=false:latency=true")


def _static_chain(prefix: Optional[str], gain_db: float) -> str:
    """volume + true-peak limiter chain (LRA-preserving master path)."""
    return _with_prefix(prefix, f"volume={gain_db:.2f}dB,{_tp_limiter()}")


def _measure_chain_lufs(src: str, chain: str) -> Optional[float]:
    """Integrated LUFS of ``src`` played through ``chain`` (dry run, no encode)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-map", "0:a:0",
           "-af", f"{chain},ebur128=peak=true", "-f", "null", "-"]
    found = _LUFS_RE.findall(_run(cmd).stderr)
    return float(found[-1]) if found else None


def _static_gain_filter(src: str, prefix: Optional[str],
                        measured_i: float,
                        measure_chain: Optional[Callable[[str], Optional[float]]] = None,
                        ) -> tuple[str, float]:
    """Static gain to target + TP limiter, trimmed against a measured dry run.

    Gain starts at ``target - measured_I``; because the limiter shaves the
    loudest transients, the result can land slightly under target, so up to
    ``STATIC_MAX_TRIMS`` dry-run measurements adjust the gain by the residual.
    A single fixed gain never pumps, so LRA passes through intact."""
    gain = AUDIO["lufs_target"] - measured_i
    chain = _static_chain(prefix, gain)
    for _ in range(STATIC_MAX_TRIMS):
        got = (measure_chain(chain) if measure_chain is not None
               else _measure_chain_lufs(src, chain))
        if got is None or abs(AUDIO["lufs_target"] - got) <= STATIC_TRIM_TOL_LU:
            break
        gain += AUDIO["lufs_target"] - got
        chain = _static_chain(prefix, gain)
    return chain, round(gain, 2)


def _audio_filter(src: str, prefix: Optional[str],
                  measured: Optional[dict],
                  measure_chain: Optional[Callable[[str], Optional[float]]] = None,
                  ) -> tuple[str, Optional[str]]:
    """Build the pass-2 audio filter. Returns (filter, note); note is None on
    the default linear path, otherwise a warning line for the report.

    linear  — loudnorm linear=true with measured stats (preserves dynamics)
    static  — volume + TP limiter when loudnorm would silently go dynamic
              (quiet/high-crest source, or LRA beyond the param — C16)
    dynamic — single-pass loudnorm for degenerate audio (non-finite stats or
              room-tone-only programs quieter than ``STATIC_MIN_I``)"""
    base = (f"loudnorm=I={AUDIO['lufs_target']}:TP={AUDIO['loudnorm_tp_param']}"
            f":LRA={AUDIO['lra']}")
    stats = _parse_stats(measured)
    if stats is None or stats["measured_I"] < STATIC_MIN_I:
        return (_with_prefix(prefix, f"{base}:print_format=summary"),
                "loudnorm fell back to dynamic (input stats non-finite or "
                "near-silent; e.g. synthetic audio)")
    if _linear_eligible(stats):
        part = ":".join(f"{k}={v}" for k, v in stats.items())
        return (_with_prefix(prefix, f"{base}:{part}:linear=true"
                             ":print_format=summary"), None)
    chain, gain = _static_gain_filter(src, prefix, stats["measured_I"], measure_chain)
    projected_tp = stats["measured_TP"] + (AUDIO["lufs_target"] - stats["measured_I"])
    return chain, (f"loudnorm linear ineligible (stats/range or projected TP "
                   f"{projected_tp:+.1f}; ceiling {AUDIO['loudnorm_tp_param']}) — static "
                   f"gain {gain:+.1f} dB + true-peak limiter (LRA preserved)")


def build_pass2_afilter(src: str, prefix: Optional[str],
                        measured: Optional[dict],
                        measure_chain: Optional[Callable[[str], Optional[float]]] = None,
                        ) -> tuple[str, Optional[str]]:
    """PUBLIC seam over the pass-2 audio-filter builder (linear / static /
    dynamic dispatch — see ``_audio_filter``). Exists so an audio-only
    re-master (audio/base_audio.py) reuses the exact mastering intelligence
    instead of duplicating it. A mix caller supplies ``measure_chain`` to measure
    that exact in-memory sum on static-gain dry runs, not just its dialogue leg.
    Returns (filter, warning|None).
    """
    return _audio_filter(src, prefix, measured, measure_chain)


def _video_opts(fps: int, fps_exact: Optional[str] = None) -> list[str]:
    """H.264 High, CFR, closed GOP (2*fps), CABAC, target bitrate, faststart."""
    gop = 2 * fps
    rate = ENCODE["bitrate_by_fps"].get(fps, ENCODE["bitrate_by_fps"][30])
    bufsize = f"{int(str(rate).rstrip('M')) * 2}M"
    return [
        "-c:v", ENCODE["vcodec"], "-profile:v", ENCODE["profile"],
        "-pix_fmt", ENCODE["pix_fmt"],
        "-b:v", rate, "-maxrate", rate, "-bufsize", bufsize,
        "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
        "-flags", "+cgop", "-bf", str(ENCODE["bframes"]),
        "-coder", "1" if ENCODE["coder"] == "cabac" else "0",
        "-r", fps_exact or str(fps), "-fps_mode", "cfr",
        "-movflags", ENCODE["movflags"],
    ]


def _filter_quote(path: str) -> str:
    """Escape a path for a single-quoted ffmpeg filtergraph token.

    Inside single quotes ffmpeg honors NO backslash escapes, so a literal
    quote uses the close-reopen idiom ('…'\\''…') — the previous
    backslash-escaping produced a premature quote-close (review finding).
    """
    return path.replace("'", "'\\''")


def _subtitles_filter(ass_path: str) -> str:
    """`subtitles` (libass) filter with fontsdir fallback, path-escaped for the
    filtergraph. libass resolves the Inter font via fontconfig; if Inter is
    absent it substitutes a system sans (the caller warns)."""
    esc = _filter_quote(ass_path)
    fonts = os.environ.get("PRODUCER_FONTS_DIR")
    if fonts and os.path.isdir(fonts):
        return f"subtitles=filename='{esc}':fontsdir='{_filter_quote(fonts)}'"
    return f"subtitles=filename='{esc}'"


def _inter_available() -> bool:
    """True if Inter is reachable — repo fontsdir first, then system fonts.

    A vendored ``PRODUCER_FONTS_DIR`` containing Inter*.ttf satisfies libass
    via the subtitles filter's fontsdir, so it must count (the fc-list check
    alone false-positives the warning). Word-boundary match on fc-list so
    'Painter'/'Winter' don't read as hits."""
    fonts_dir = os.environ.get("PRODUCER_FONTS_DIR")
    if fonts_dir and os.path.isdir(fonts_dir):
        try:
            if any(f.lower().startswith("inter") and f.lower().endswith(".ttf")
                   for f in os.listdir(fonts_dir)):
                return True
        except OSError:
            pass
    try:
        listing = _run(["fc-list"])
    except (OSError, ValueError):
        return True   # cannot check → do not cry wolf
    if listing.returncode != 0:
        return True
    return re.search(r"(?i)\binter\b", listing.stdout) is not None


def measure_integrated_lufs(path: str) -> Optional[float]:
    """Verify pass: ebur128 integrated loudness of the finished master."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:a:0",
           "-af", "ebur128=peak=true", "-f", "null", "-"]
    found = _LUFS_RE.findall(_run(cmd).stderr)
    return float(found[-1]) if found else None


def extract_cover(src: str, cover: str) -> Optional[list[int]]:
    """Write frame 0 as a PNG (the de-facto thumbnail + loop start); return its
    [w, h] or None on failure."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-i", src,
           "-frames:v", "1", "-f", "image2", cover]
    if _run(cmd).returncode != 0 or not os.path.exists(cover):
        return None
    probe = ["ffprobe", "-v", "error", "-select_streams", "v",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", cover]
    dims = _run(probe).stdout.strip().split(",")
    return [int(dims[0]), int(dims[1])] if len(dims) == 2 else None


def _encode(spec: MasterSpec, audio: bool, afilter: Optional[str],
            picture_guard: Callable[[], None] | None = None) -> subprocess.CompletedProcess:
    """The single final encode pass (video + optional burn + optional loudnorm)."""
    from guided_source_color_consumption_hooks import capture_master, run_picture_command
    consumption = capture_master(spec, picture_guard)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", spec.src, "-map", "0:v:0"]
    if spec.duration:
        cmd += ["-t", f"{spec.duration + 0.5 / spec.fps:.4f}"]
    if spec.ass:
        cmd += ["-vf", _subtitles_filter(spec.ass)]
    cmd += _video_opts(spec.fps, spec.fps_exact)
    if spec.frame_count is not None:
        cmd += ["-frames:v", str(spec.frame_count)]
    if audio:
        cmd += ["-map", "0:a:0", "-c:a", ENCODE["acodec"],
                "-b:a", ENCODE["audio_bitrate"], "-ar", str(ENCODE["audio_rate"]),
                "-ac", str(ENCODE["audio_channels"])]
        if afilter:
            cmd += ["-af", afilter]
        # Multi-segment mining at low fps quantizes each video segment DOWN a
        # sub-frame while audio keeps exact spans - the accumulated audio tail
        # past the last video frame trips the AV-timing gate (measured +126ms
        # on a 4-segment 23.976fps cut; gate limit 120ms). The tail is room
        # tone after the final frame; end both streams together.
        cmd += ["-shortest"]
    else:
        cmd += ["-an"]
    cmd.append(spec.out)
    if consumption is not None:
        if audio or afilter is not None:
            raise RuntimeError("source-color consumption requires the existing picture-only encode")
        return run_picture_command(consumption, cmd, (picture_guard, _run))
    if picture_guard is not None:
        picture_guard()
    result = _run(cmd)
    if picture_guard is not None:
        picture_guard()
    return result


def master(spec: MasterSpec) -> dict:
    """Run the full master: measure → encode → verify. Returns a status dict."""
    warnings: list[str] = []
    audio = has_audio(spec.src)
    if not audio:
        warnings.append("source has no audio track — loudnorm skipped")
    if spec.ass and not _inter_available():
        warnings.append(f"font '{CAP_FONT}' not installed — libass substituting "
                        "a system sans via fontconfig")
    afilter = None
    if audio:
        prefix, ch_warn = dead_channel_prefix(spec.src)
        if ch_warn:
            warnings.append(ch_warn)
        measured = measure_loudness(spec.src, prefix)
        afilter, note = _audio_filter(spec.src, prefix, measured)
        if note:
            warnings.append(note)
    result = _encode(spec, audio, afilter)
    if result.returncode != 0 or not os.path.exists(spec.out):
        return {"status": "error", "error": "encode failed",
                "ffmpeg": result.stderr[-1200:], "warnings": warnings}
    return _finalize(spec, audio, warnings)


def encode_picture_only(spec: MasterSpec, picture_guard: Callable[[], None] | None = None) -> dict:
    """Run the existing final picture encode without processing any audio bus."""
    if picture_guard is not None:
        picture_guard()
    result = _encode(spec, False, None) if picture_guard is None else _encode(spec, False, None, picture_guard)
    observed = {"ok": result.returncode == 0 and os.path.isfile(spec.out),
                "stderr": result.stderr[-1200:] if result.returncode else ""}
    if picture_guard is not None:
        picture_guard()
    return observed


def finalize_master(spec: MasterSpec, warnings: list[str]) -> dict:
    """Retain ordinary cover/report behavior after independently qualified audio."""
    return _finalize(spec, True, warnings)


def _finalize(spec: MasterSpec, audio: bool, warnings: list[str]) -> dict:
    """Post-encode measurements: LUFS tolerance, cover, file-size budget."""
    lufs = measure_integrated_lufs(spec.out) if audio else None
    within = (lufs is not None
              and abs(lufs - AUDIO["lufs_target"]) <= AUDIO["lufs_tolerance"])
    if audio and not within:
        warnings.append(f"integrated LUFS {lufs} outside "
                        f"{AUDIO['lufs_target']}+/-{AUDIO['lufs_tolerance']}")
    cover_dims = extract_cover(spec.out, spec.cover) if spec.cover else None
    # MiB, not 10^6 — TikTok's 287 in-app cap is binary (review finding).
    size_mb = round(os.path.getsize(spec.out) / (1024 * 1024), 2)
    if size_mb > ENCODE["max_file_mb"]:
        warnings.append(f"output {size_mb}MB exceeds cap {ENCODE['max_file_mb']}MB")
    return {
        "status": "done",
        "mastering_policy_version": MASTERING_POLICY_VERSION,
        "out": spec.out,
        "fps": spec.fps,
        "burned_captions": bool(spec.ass),
        "lufs_target": AUDIO["lufs_target"],
        "lufs_measured": lufs,
        "lufs_within_tolerance": within if audio else None,
        "cover": spec.cover if cover_dims else None,
        "cover_dims": cover_dims,
        "size_mb": size_mb,
        "warnings": warnings,
    }


def main() -> None:
    args = sys.argv[1:]
    opts = {"--ass": None, "--fps": "30", "--cover": None}
    for key in list(opts):
        if key in args:
            idx = args.index(key)
            opts[key] = args[idx + 1] if idx + 1 < len(args) else None
            del args[idx:idx + 2]
    if len(args) != 2:
        print(json.dumps({"status": "error", "error": "Usage: master.py <in.mp4> "
                          "<out.mp4> [--ass captions.ass] [--fps 30] [--cover cover.png]"}))
        sys.exit(1)
    spec = MasterSpec(src=args[0], out=args[1], ass=opts["--ass"],
                      fps=int(opts["--fps"]), cover=opts["--cover"])
    status = master(spec)
    print(json.dumps(status, indent=2))
    sys.exit(0 if status.get("status") == "done" else 1)


if __name__ == "__main__":
    main()
