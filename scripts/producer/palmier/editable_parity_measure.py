"""Full-stream measurements for editable Palmier export parity."""
from __future__ import annotations

import json
import math
import re
import subprocess
from fractions import Fraction

from palmier.mcp_client import PalmierError
from palmier.process_deadline import process_timeout

_SSIM = re.compile(r"\bAll:([0-9.]+)")
_RMS = re.compile(r"\bRMS level dB:\s*(-?inf|-?[0-9.]+)", re.IGNORECASE)
_PEAK = re.compile(r"\bPeak level dB:\s*(-?inf|-?[0-9.]+)", re.IGNORECASE)
_SAMPLES = re.compile(r"\bNumber of samples:\s*([0-9]+)", re.IGNORECASE)


def _run(command: list[str], label: str) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command, capture_output=True, text=True,
        timeout=process_timeout())
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-12:]
        raise PalmierError(
            f"Palmier editable parity {label} failed: "
            f"{' | '.join(tail) or 'no diagnostic'}")
    return result


def _first_stream(value: dict, kind: str) -> dict:
    streams = value.get("streams")
    found = next((row for row in streams or []
                  if isinstance(row, dict) and row.get("codec_type") == kind),
                 None)
    if found is None:
        raise PalmierError(f"Palmier editable parity input has no {kind} stream")
    return found


def _positive_int(value: object, label: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise PalmierError(
            f"Palmier editable parity cannot measure {label}") from exc
    if parsed <= 0:
        raise PalmierError(f"Palmier editable parity {label} is not positive")
    return parsed


def _positive_float(value: object, label: str) -> float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError) as exc:
        raise PalmierError(
            f"Palmier editable parity cannot measure {label}") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise PalmierError(f"Palmier editable parity {label} is not positive")
    return parsed


def _decoded_sample_count(path: str) -> int:
    result = _run([
        "ffmpeg", "-nostdin", "-hide_banner", "-v", "info",
        "-i", path, "-map", "0:a:0",
        "-af", "astats=metadata=0:reset=0:measure_perchannel=none:"
        "measure_overall=Number_of_samples",
        "-f", "null", "-",
    ], "audio sample decode")
    matches = _SAMPLES.findall(result.stderr)
    if not matches:
        raise PalmierError(
            "Palmier editable parity cannot count decoded audio samples")
    return _positive_int(matches[-1], "decoded audio sample count")


def probe(path: str) -> dict:
    """Decode-count the first video stream and return exact timing facts."""
    result = _run([
        "ffprobe", "-v", "error", "-count_frames", "-show_streams",
        "-show_format", "-of", "json", path,
    ], "probe")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PalmierError(
            "Palmier editable parity probe returned invalid JSON") from exc
    video, audio = _first_stream(value, "video"), _first_stream(value, "audio")
    frame_rate = video.get("avg_frame_rate") or video.get("r_frame_rate")
    try:
        canonical_rate = str(Fraction(str(frame_rate)))
    except (ValueError, ZeroDivisionError) as exc:
        raise PalmierError(
            "Palmier editable parity frame rate is invalid") from exc
    frames = video.get("nb_read_frames") or video.get("nb_frames")
    return {
        "width": _positive_int(video.get("width"), "width"),
        "height": _positive_int(video.get("height"), "height"),
        "frameRate": canonical_rate,
        "frameCount": _positive_int(frames, "decoded frame count"),
        "durationSeconds": _positive_float(
            video.get("duration") or value.get("format", {}).get("duration"),
            "video duration"),
        "audioSampleRate": _positive_int(
            audio.get("sample_rate"), "audio sample rate"),
        "audioChannels": _positive_int(audio.get("channels"), "audio channels"),
        "audioSampleCount": _decoded_sample_count(path),
    }


def _db(value: str) -> float:
    return -300.0 if value.lower() == "-inf" else float(value)


def compare_streams(master: str, candidate: str) -> dict:
    """Decode all picture/audio and measure SSIM plus PCM-difference energy."""
    graph = (
        "[0:v:0][1:v:0]ssim=shortest=1[v];"
        "[0:a:0]aformat=sample_fmts=fltp:sample_rates=48000:"
        "channel_layouts=stereo[a];"
        "[1:a:0]aformat=sample_fmts=fltp:sample_rates=48000:"
        "channel_layouts=stereo[b];"
        "[a][b]amerge=inputs=2[m];"
        "[m]pan=stereo|c0=c0-c2|c1=c1-c3,"
        "astats=metadata=0:reset=0[d]"
    )
    result = _run([
        "ffmpeg", "-nostdin", "-hide_banner", "-v", "info",
        "-i", master, "-i", candidate, "-filter_complex", graph,
        "-map", "[v]", "-map", "[d]", "-f", "null", "-",
    ], "full picture/audio comparison")
    ssim, rms, peak = (_SSIM.findall(result.stderr),
                       _RMS.findall(result.stderr),
                       _PEAK.findall(result.stderr))
    if not ssim or not rms or not peak:
        raise PalmierError(
            "Palmier editable parity comparison returned incomplete metrics")
    return {"meanSsim": float(ssim[-1]),
            "audioDifferenceRmsDb": _db(rms[-1]),
            "audioDifferencePeakDb": _db(peak[-1])}
