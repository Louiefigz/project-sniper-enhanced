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
import os
import re
import subprocess
import sys
from functools import partial
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from producer_config import AUDIO, ENCODE
from audio.master_picture_options import (MasterSpec, _filter_quote, _subtitles_filter,
                                          _video_opts, inter_available)
from audio.mastering_filter import (MasterFilterInput, MasterFilterSelection,
                                    STATIC_MIN_I, STATIC_TRIM_TOL_LU,
                                    select_master_filter, with_prefix as _with_prefix)
from audio.mastering_profile import LEGACY_MASTERING_PROFILE
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
STATIC_MAX_TRIMS = LEGACY_MASTERING_PROFILE.maximum_static_dry_runs


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


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


def _measure_chain_lufs(src: str, chain: str) -> Optional[float]:
    """Integrated LUFS of the exact supplied source/filter (dry run, no encode)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-map", "0:a:0",
           "-af", f"{chain},ebur128=peak=true", "-f", "null", "-"]
    found = _LUFS_RE.findall(_run(cmd).stderr)
    return float(found[-1]) if found else None


def _audio_filter(src: str, prefix: Optional[str], measured: Optional[dict],
                  measure_chain: Optional[Callable[[str], Optional[float]]] = None,
                  ) -> tuple[str, Optional[str]]:
    """Keep the existing default mastering contract over the shared DSP builder."""
    selected = select_pass2_filter(src, prefix, measured, measure_chain)
    return selected.chain, selected.note


def select_pass2_filter(src: str, prefix: Optional[str], measured: Optional[dict],
                       measure_chain: Optional[Callable[[str], Optional[float]]] = None,
                       ) -> MasterFilterSelection:
    """Select the existing DSP and retain its exact processing observations."""
    callback = measure_chain if measure_chain is not None else partial(_measure_chain_lufs, src)
    return select_master_filter(MasterFilterInput(prefix, measured, callback))


def build_pass2_afilter(src: str, prefix: Optional[str], measured: Optional[dict],
                        measure_chain: Optional[Callable[[str], Optional[float]]] = None,
                        ) -> tuple[str, Optional[str]]:
    """Reuse default linear/static/dynamic mastering and an optional exact-mix measurement."""
    return _audio_filter(src, prefix, measured, measure_chain)


def _inter_available() -> bool:
    """Preserve the existing injectable command seam for the extracted font check."""
    return inter_available(_run)


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
    afilter, decision = None, None
    if audio:
        prefix, ch_warn = dead_channel_prefix(spec.src)
        if ch_warn:
            warnings.append(ch_warn)
        measured = measure_loudness(spec.src, prefix)
        selected = select_pass2_filter(spec.src, prefix, measured)
        afilter, decision = selected.chain, selected.evidence
        if selected.note:
            warnings.append(selected.note)
    result = _encode(spec, audio, afilter)
    if result.returncode != 0 or not os.path.exists(spec.out):
        return {"status": "error", "error": "encode failed",
                "ffmpeg": result.stderr[-1200:], "warnings": warnings,
                "mastering_decision": decision}
    return {**_finalize(spec, audio, warnings), "mastering_decision": decision}


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
