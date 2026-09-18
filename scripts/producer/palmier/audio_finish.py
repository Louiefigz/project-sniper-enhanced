#!/usr/bin/env python3
"""Remux Palmier's picture with authoritative in-house master audio.
The new staging MP4 is rejected unless timing and audio QC pass. Inputs and
pre-existing outputs are never replaced.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import re
import struct
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from fractions import Fraction
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from palmier.mcp_client import PalmierError
_LUFS_RE = re.compile(r"\bI:\s*(-?\d+(?:\.\d+)?)\s*LUFS")
_PEAK_RE = re.compile(r"Peak:\s*(-?\d+(?:\.\d+)?)\s+dBFS")
_RMS_RE = re.compile(r"RMS level dB:\s*(-?(?:inf|\d+(?:\.\d+)?))", re.I)


class AudioFinishError(PalmierError):
    """An authoritative-audio handoff or QC failure."""

@dataclass(frozen=True)
class FinishLimits:
    """Safety and delivery bounds for one finish."""
    source_duration_delta_s: float = 0.100
    output_av_skew_s: float = 0.050
    lufs_target: float = -14.0
    lufs_tolerance: float = 1.0
    true_peak_ceiling_dbtp: float = -1.0
    stereo_imbalance_db: float = 3.0
    end_fade_s: float = 0.020

@dataclass(frozen=True)
class FinishSpec:
    """The two authorities and the disposable staging destination."""
    visual_path: str
    audio_master_path: str
    staging_output_path: str
    limits: FinishLimits = field(default_factory=FinishLimits)

@dataclass(frozen=True)
class VideoTiming:
    """Frame-derived CFR timing; container/AAC duration is not authoritative."""
    frames: int
    frame_rate: Fraction

    @property
    def duration_s(self) -> float:
        """Exact frame count divided by the stream's average frame rate."""
        return float(Fraction(self.frames, 1) / self.frame_rate)

@dataclass(frozen=True)
class FinishReport:
    """Measurements from a verified staging output."""
    output_path: str
    video_duration_s: float
    audio_duration_s: float
    av_skew_s: float
    integrated_lufs: float
    true_peak_dbtp: float
    stereo_imbalance_db: float

def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a media command without a shell and retain diagnostics."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise AudioFinishError(f"could not run {cmd[0]}: {exc}") from exc

def _probe_media(path: str) -> dict:
    """Read stream facts plus decoded packet counts from one media file."""
    entries = ("stream=codec_type,codec_name,sample_rate,channels,channel_layout,"
               "duration,duration_ts,time_base,avg_frame_rate,r_frame_rate,"
               "nb_frames,nb_read_packets")
    proc = _run(["ffprobe", "-v", "error", "-count_packets", "-show_entries",
                 entries, "-of", "json", path])
    if proc.returncode != 0:
        raise AudioFinishError(
            f"ffprobe failed for {path}: {proc.stderr.strip()[-400:]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AudioFinishError(f"ffprobe returned invalid JSON for {path}") from exc

def _first_stream(probe: dict, kind: str) -> dict | None:
    """Return the first stream of ``kind``."""
    return next((s for s in probe.get("streams", [])
                 if s.get("codec_type") == kind), None)

def _positive_fraction(*values: object) -> Fraction | None:
    """Return the first finite positive rational value."""
    for value in values:
        try:
            found = Fraction(str(value))
        except (ValueError, ZeroDivisionError):
            continue
        if found > 0:
            return found
    return None

def _video_timing(probe: dict, label: str) -> VideoTiming:
    """Require a countable CFR video stream and derive its duration."""
    stream = _first_stream(probe, "video")
    if stream is None:
        raise AudioFinishError(f"{label} has no video stream")
    rate = _positive_fraction(stream.get("avg_frame_rate"),
                              stream.get("r_frame_rate"))
    try:
        frames = int(stream.get("nb_read_packets") or stream.get("nb_frames"))
    except (TypeError, ValueError):
        frames = 0
    if rate is None or frames <= 0:
        raise AudioFinishError(f"{label} has no usable frame count/rate")
    return VideoTiming(frames, rate)

def _stream_duration(stream: dict | None, label: str) -> float:
    """Read a positive stream duration, with time-base fallback."""
    if stream is None:
        raise AudioFinishError(f"{label} has no audio stream")
    raw = _positive_fraction(stream.get("duration"))
    if raw is None:
        ticks = _positive_fraction(stream.get("duration_ts"))
        base = _positive_fraction(stream.get("time_base"))
        raw = ticks * base if ticks is not None and base is not None else None
    if raw is None:
        raise AudioFinishError(f"{label} has no positive audio duration")
    return float(raw)

def _validate_paths(spec: FinishSpec) -> None:
    """Keep every write distinct and reject overwrite-style destinations."""
    inputs = (spec.visual_path, spec.audio_master_path)
    for path in inputs:
        if not os.path.isfile(path):
            raise AudioFinishError(f"required input does not exist: {path}")
    output = os.path.realpath(os.path.abspath(spec.staging_output_path))
    if output in {os.path.realpath(os.path.abspath(path)) for path in inputs}:
        raise AudioFinishError("staging output must be separate from both inputs")
    if os.path.lexists(spec.staging_output_path):
        raise AudioFinishError(
            f"refusing to replace existing staging output: {spec.staging_output_path}")

def _audio_filter(duration_s: float, fade_s: float) -> str:
    """Pad/trim to picture length and de-click only the final 20ms by default."""
    fade = min(max(0.0, fade_s), duration_s)
    start = max(0.0, duration_s - fade)
    return ("aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:"
            "channel_layouts=stereo,asetpts=PTS-STARTPTS,apad,"
            f"atrim=start=0:end={duration_s:.9f},"
            f"afade=t=out:st={start:.9f}:d={fade:.9f}")

def _encode(spec: FinishSpec, timing: VideoTiming) -> None:
    """Copy picture, encode only authoritative audio, and never overwrite."""
    os.makedirs(os.path.dirname(os.path.abspath(spec.staging_output_path)),
                exist_ok=True)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-n",
           "-i", spec.visual_path, "-i", spec.audio_master_path,
           "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
           "-af", _audio_filter(timing.duration_s, spec.limits.end_fade_s),
           "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "256k",
           "-movflags", "+faststart", "-map_metadata", "0", "-sn", "-dn",
           spec.staging_output_path]
    proc = _run(cmd)
    if proc.returncode != 0:
        raise AudioFinishError(f"ffmpeg audio finish failed: "
                               f"{proc.stderr.strip()[-500:]}")
    if not os.path.isfile(spec.staging_output_path) \
            or os.path.getsize(spec.staging_output_path) <= 0:
        raise AudioFinishError("ffmpeg reported success but wrote no staging MP4")

def _measure_loudness(path: str) -> tuple[float | None, float | None]:
    """Return integrated LUFS and EBU R128 true peak."""
    proc = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
                 "-map", "0:a:0", "-af", "ebur128=peak=true",
                 "-f", "null", "-"])
    lufs = _LUFS_RE.findall(proc.stderr)
    peaks = _PEAK_RE.findall(proc.stderr)
    return (float(lufs[-1]) if lufs else None,
            float(peaks[-1]) if peaks else None)

def _stereo_rms(path: str) -> tuple[float, float] | None:
    """Measure whole-program RMS for left/right, excluding Overall."""
    proc = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
                 "-map", "0:a:0", "-af", "astats=metadata=0:reset=0",
                 "-f", "null", "-"])
    values = [float(value) for value in _RMS_RE.findall(proc.stderr)]
    return (values[0], values[1]) if len(values) >= 3 else None

def _is_faststart(path: str) -> bool:
    """Return whether the top-level moov atom occurs before mdat."""
    seen_mdat = False
    try:
        with open(path, "rb") as handle:
            while header := handle.read(8):
                if len(header) < 8:
                    break
                size, atom = struct.unpack(">I4s", header)
                if size == 1:
                    size = struct.unpack(">Q", handle.read(8))[0]
                if atom == b"moov":
                    return not seen_mdat
                seen_mdat = seen_mdat or atom == b"mdat"
                if size < 8:
                    break
                handle.seek(size - (16 if header[:4] == b"\x00\x00\x00\x01" else 8), 1)
    except (OSError, struct.error):
        return False
    return False

def verify_finished(path: str, expected: VideoTiming,
                    limits: FinishLimits) -> FinishReport:
    """Verify picture identity, encode shape, sync, loudness, peak, and balance."""
    probe = _probe_media(path)
    timing = _video_timing(probe, "finished staging output")
    audio = _first_stream(probe, "audio")
    audio_duration = _stream_duration(audio, "finished staging output")
    problems: list[str] = []
    if timing != expected:
        problems.append("video frame count/rate changed instead of stream-copying")
    if audio is None or audio.get("codec_name") != "aac":
        problems.append("audio codec is not AAC")
    if audio is None or str(audio.get("sample_rate")) != "48000":
        problems.append("audio sample rate is not 48000 Hz")
    if audio is None or str(audio.get("channels")) != "2":
        problems.append("audio is not stereo")
    skew = abs(audio_duration - timing.duration_s)
    if skew > limits.output_av_skew_s:
        problems.append(f"A/V skew {skew:.4f}s exceeds {limits.output_av_skew_s:.4f}s")
    if not _is_faststart(path):
        problems.append("MP4 is not faststart (moov does not precede mdat)")
    lufs, peak = _measure_loudness(path)
    levels = _stereo_rms(path)
    imbalance = (abs(levels[0] - levels[1]) if levels is not None
                 and all(math.isfinite(level) for level in levels) else math.inf)
    if lufs is None or abs(lufs - limits.lufs_target) > limits.lufs_tolerance:
        problems.append(f"integrated loudness {lufs} is outside "
                        f"{limits.lufs_target:.1f}±{limits.lufs_tolerance:.1f} LUFS")
    if peak is None or peak >= limits.true_peak_ceiling_dbtp:
        problems.append(f"true peak {peak} is not below "
                        f"{limits.true_peak_ceiling_dbtp:.1f} dBTP")
    if imbalance > limits.stereo_imbalance_db:
        problems.append(f"stereo RMS imbalance {imbalance:.2f} dB exceeds "
                        f"{limits.stereo_imbalance_db:.2f} dB")
    if problems:
        raise AudioFinishError("finished audio QC failed: " + "; ".join(problems))
    return FinishReport(path, timing.duration_s, audio_duration, skew,
                        float(lufs), float(peak), imbalance)

def finish_authoritative_audio(spec: FinishSpec) -> FinishReport:
    """Create and verify a staging MP4 without replacing any existing file."""
    _validate_paths(spec)
    visual_probe = _probe_media(spec.visual_path)
    audio_probe = _probe_media(spec.audio_master_path)
    timing = _video_timing(visual_probe, "Palmier visual authority")
    audio_duration = _stream_duration(_first_stream(audio_probe, "audio"),
                                      "in-house audio authority")
    delta = abs(timing.duration_s - audio_duration)
    if delta > spec.limits.source_duration_delta_s:
        raise AudioFinishError(
            f"authority duration mismatch: picture {timing.duration_s:.6f}s vs "
            f"audio {audio_duration:.6f}s (delta {delta:.4f}s exceeds "
            f"{spec.limits.source_duration_delta_s:.4f}s)")
    _encode(spec, timing)
    try:
        return verify_finished(spec.staging_output_path, timing, spec.limits)
    except AudioFinishError:
        try:
            os.unlink(spec.staging_output_path)
        except OSError:
            pass
        raise

def main(argv: list[str] | None = None) -> int:
    """CLI entry point for an explicit three-path staging handoff."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("palmier_mp4")
    parser.add_argument("in_house_final_mp4")
    parser.add_argument("staging_output_mp4")
    parser.add_argument("--duration-tolerance", type=float, default=0.100)
    parser.add_argument("--av-skew", type=float, default=0.050)
    args = parser.parse_args(argv)
    limits = FinishLimits(source_duration_delta_s=args.duration_tolerance,
                          output_av_skew_s=args.av_skew)
    try:
        report = finish_authoritative_audio(FinishSpec(
            args.palmier_mp4, args.in_house_final_mp4,
            args.staging_output_mp4, limits))
    except AudioFinishError as exc:
        print(f"audio finish failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(report), sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
