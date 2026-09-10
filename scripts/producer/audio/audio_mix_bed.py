#!/usr/bin/env python3
"""audio_mix_bed — bed shaping for the music stage: pre-norm + length fit.

The lower half of the music stage (docs/producer/PRODUCER_PLAN.md §4.2 stage 4, §7). Split
out of ``audio_mix.py`` to keep each file under the 300-line logic budget and to
isolate the "shape the raw track into a video-length bed" concern from the
"duck + mix + master" concern. One-directional dependency: ``audio_mix`` imports
from here; this module imports only ``master`` (public helpers) + ``producer_config``.

Two edge cases live here:
- **M3** — ``prep_bed`` measures the library track's loudness and gains it to a
  consistent internal reference (a single measured gain, not dynamic loudnorm, so
  the music keeps its own dynamics), materializing a float-PCM base so a boost of
  a quiet track never clips.
- **M1 / M2** — ``fit_length`` trims a too-long track with an end fade (M2) or
  loops a too-short one with an equal-power crossfade at each seam (M1), built via
  a self-seamless loop period tiled with ``-stream_loop`` (robust for any target
  length; see ``_seamless_period``).
"""

from __future__ import annotations

import json
import math
import os
import subprocess
from fractions import Fraction
from typing import Optional

from audio.master import measure_integrated_lufs
from headless.process_runner import process_timeout

# Float intermediates: a pre-norm boost of a quiet track never clips (clipping is
# at full scale regardless of bit depth; float can exceed 1.0, the final loudnorm
# true-peak limiter brings it back under -1.5 dBTP).
FLOAT_WAV = ["-c:a", "pcm_f32le"]
AFMT = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"

XFADE_S = 1.0             # equal-power (qsin) crossfade at each loop seam (edge M1)
FADE_OUT_S = 2.0          # end fade-out for both loop and trim variants (edge M2, §7)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def probe_duration(path: str) -> Optional[float]:
    """Container duration in seconds via ffprobe, or None."""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=nokey=1:noprint_wrappers=1", path]
    try:
        return float(run(cmd).stdout.strip())
    except ValueError:
        return None


def probe_video_duration(path: str) -> Optional[float]:
    """Frame-derived picture duration, never stream/container duration.

    AAC priming/padding can make MP4 duration fields longer than the picture.
    The authoritative video timeline is therefore the exact packet count
    divided by the exact CFR rational rate (X8/X19/X20).
    """
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-count_packets", "-show_entries",
           "stream=avg_frame_rate,r_frame_rate,nb_frames,nb_read_packets",
           "-of", "json", path]
    try:
        proc = run(cmd)
        stream = json.loads(proc.stdout).get("streams", [])[0]
        frames = int(stream.get("nb_read_packets") or stream.get("nb_frames"))
        rates = [
            Fraction(str(stream[key]))
            for key in ("avg_frame_rate", "r_frame_rate")
            if stream.get(key) not in (None, "", "0/0")
        ]
    except (IndexError, KeyError, TypeError, ValueError, ZeroDivisionError,
            json.JSONDecodeError):
        return None
    if proc.returncode != 0 or frames <= 0 or not rates:
        return None
    if any(rate <= 0 or rate != rates[0] for rate in rates):
        return None
    value = float(Fraction(frames, 1) / rates[0])
    return value if math.isfinite(value) and value > 0 else None


def prep_bed(music: str, target_lufs: float, out_wav: str) -> dict:
    """Measure the track and gain it to ``target_lufs`` (edge M3 pre-normalize).

    A single measured gain (not dynamic loudnorm) preserves the music's own
    dynamics; float PCM output means a boost of a quiet track never clips.

    Returns a status dict with the measured/target LUFS and applied gain.
    """
    measured = measure_integrated_lufs(music)
    gain_db = (target_lufs - measured) if measured is not None else 0.0
    vf = f"volume={gain_db:.2f}dB,{AFMT}" if measured is not None else AFMT
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", music, "-map", "0:a:0",
           "-af", vf, *FLOAT_WAV, out_wav]
    res = run(cmd)
    ok = res.returncode == 0 and os.path.exists(out_wav)
    return {"ok": ok, "measured_lufs": measured, "target_lufs": round(target_lufs, 2),
            "gain_db": round(gain_db, 2) if measured is not None else None,
            "stderr": "" if ok else res.stderr[-600:]}


def _seamless_period(base_wav: str, dur: float, xfade: float, out_wav: str) -> bool:
    """Build a self-seamless loop period whose end flows into its start.

    The period is ``crossfade(track_tail -> track_head)`` followed by the middle
    body ``[xfade, dur-xfade]``. Because the wrap boundary is already an
    equal-power blend of the track's tail into its head, tiling copies of this
    period (via ``-stream_loop`` on the materialized file) is click-free — the
    robust alternative to an N-input acrossfade chain, which grows fragile as the
    video lengthens. Requires ``dur > 2*xfade`` (caller clamps xfade).
    """
    fc = (
        f"[0:a]asplit=3[a][b][c];"
        f"[a]atrim=start={xfade:.3f}:end={dur - xfade:.3f},asetpts=PTS-STARTPTS[body];"
        f"[b]atrim=start={dur - xfade:.3f}:end={dur:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=out:st=0:d={xfade:.3f}:curve=qsin[tail];"
        f"[c]atrim=start=0:end={xfade:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d={xfade:.3f}:curve=qsin[head];"
        f"[tail][head]amix=inputs=2:normalize=0[x];"
        f"[x][body]concat=n=2:v=0:a=1[out]"
    )
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", base_wav,
           "-filter_complex", fc, "-map", "[out]", *FLOAT_WAV, out_wav]
    return run(cmd).returncode == 0 and os.path.exists(out_wav)


def _end_fade(video_dur: float) -> tuple[float, str]:
    """(fade_out_s, afade-filter) ending exactly at the video's end (§7, M2)."""
    fade = min(FADE_OUT_S, video_dur * 0.5)
    end, length = round(video_dur * 48000), round(fade * 48000)
    return fade, f"afade=t=out:ss={max(0, end - length)}:ns={length}:curve=qsin"


def float_pcm_samples(path: str) -> int:
    """Observe a generated float stem's exact clock, rejecting missing metadata."""
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", path],
        capture_output=True, text=True, check=False, timeout=process_timeout())
    streams = json.loads(result.stdout).get("streams", [])
    if result.returncode or len(streams) != 1:
        raise ValueError("music float stem has no exact single-stream clock")
    audio = streams[0]
    samples = audio.get("duration_ts")
    if audio.get("codec_name") != "pcm_f32le" or audio.get("sample_fmt") != "flt" \
            or audio.get("sample_rate") != "48000" or audio.get("channels") not in {1, 2} \
            or audio.get("time_base") != "1/48000" or type(samples) is not int or samples <= 0:
        raise ValueError("music float stem sample clock or format is unproved")
    return samples


def _trim_to_video(base_wav: str, video_dur: float, out_wav: str) -> dict:
    """Too-long track: trim to the video length with an end fade-out (edge M2)."""
    fade, fade_af = _end_fade(video_dur)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", base_wav,
           "-af", f"{AFMT},atrim=end_sample={round(video_dur * 48000)},{fade_af}", *FLOAT_WAV, out_wav]
    ok = run(cmd).returncode == 0 and os.path.exists(out_wav)
    return {"ok": ok, "mode": "trim", "xfade_s": None, "fade_out_s": round(fade, 3)}


def _loop_to_video(base_wav: str, base_dur: float, video_dur: float, out_wav: str) -> dict:
    """Too-short track: loop with an equal-power crossfade at each seam (edge M1)."""
    fade, fade_af = _end_fade(video_dur)
    xfade = XFADE_S if base_dur > 2 * XFADE_S else round(base_dur * 0.4, 3)
    period = os.path.join(os.path.dirname(out_wav), "period.wav")
    if not _seamless_period(base_wav, base_dur, xfade, period):
        return {"ok": False, "mode": "loop", "error": "seamless period build failed"}
    period_dur = probe_duration(period) or (base_dur - xfade)
    loops = max(1, math.ceil(video_dur / period_dur))   # total plays
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-stream_loop", str(loops - 1),
           "-i", period, "-af", f"{AFMT},atrim=end_sample={round(video_dur * 48000)},{fade_af}",
           *FLOAT_WAV, out_wav]
    ok = run(cmd).returncode == 0 and os.path.exists(out_wav)
    return {"ok": ok, "mode": "loop", "xfade_s": xfade, "fade_out_s": round(fade, 3),
            "period_s": round(period_dur, 3), "loops": loops}


def fit_length(base_wav: str, video_dur: float, out_wav: str) -> dict:
    """Fit the bed to ``video_dur``: trim if long (M2), loop+crossfade if short (M1)."""
    base_dur = probe_duration(base_wav) or 0.0
    if base_dur >= video_dur:
        return _trim_to_video(base_wav, video_dur, out_wav)
    return _loop_to_video(base_wav, base_dur, video_dur, out_wav)
