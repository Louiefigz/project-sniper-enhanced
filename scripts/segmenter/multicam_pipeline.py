#!/usr/bin/env python3
"""Multicam sync + cut pipeline.

Takes A-cam (master, required) plus any combination of B-cam, C-cam, and up to
two audio-only lavalier inputs (lav1, lav2) that may have started rolling later.
Computes per-alt audio-sync offsets against A, cuts frame-accurate clips per
camera (and sample-accurate PCM WAV clips per lav) at A-cam-defined segment
timecodes, and self-validates the result.

  python3 scripts/segmenter/multicam_pipeline.py \\
    --acam Acam_full.mp4 --bcam Bcam_full.mp4 --ccam Ccam_full.mp4 \\
    --lav1 lav1.wav --lav2 lav2.wav \\
    --segments segments.json --outdir ./out/multicam

segments.json: [{"start": float, "end": float, "title"?: str}, ...] in A-cam timecode.

Sign convention: positive offset = source started LATER than A.
    alt_time_in_alt_file = a_time - alt_offset
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from fractions import Fraction
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import fftconvolve


MUXABLE_AUDIO = {"aac", "mp3", "ac3", "opus", "alac"}
MIN_FFMPEG_VERSION = (4, 4)

# Pre/post-roll padding added to every cut so boundaries don't clip the first or
# last word. Matches scripts/segmenter/export_mp4.py (single-cam). Applied identically
# across all cameras (after offset translation) so sync is preserved.
PAD_SECONDS = 5.0


def run_command(cmd):
    t = time.monotonic()
    if DEBUG:
        dbg("$ " + " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-15:]
        if DEBUG:
            dbg("FAILED", bin=os.path.basename(cmd[0]), code=result.returncode,
                secs=round(time.monotonic() - t, 2))
            for ln in tail:
                dbg("  ! " + ln)
        raise RuntimeError("\n".join(tail) or f"{cmd[0]} failed")
    if DEBUG:
        dbg("ok", bin=os.path.basename(cmd[0]), secs=round(time.monotonic() - t, 2))
    return result.stdout.strip()


_log_lock = threading.Lock()

# Verbose tracing for debugging a render. Goes to STDERR (not stdout, which the
# SSE route parses as JSON status events) — the export route mirrors stderr live
# to the `npm run dev` console. Enable with MULTICAM_DEBUG=1. Lines are prefixed
# with elapsed seconds and tagged with a thread/segment label where relevant.
# The project-wide SNIPER_DEBUG flag (ON by default, off only when set to "0")
# also enables this tracing, so the same env var lights up every script's logs.
DEBUG = os.environ.get("MULTICAM_DEBUG") == "1" or os.environ.get("SNIPER_DEBUG") != "0"
_t0 = time.monotonic()


def log_status(**fields):
    # Serialized: segments are cut concurrently and each status line is parsed
    # as one JSON object by the SSE route — interleaved writes would corrupt it.
    line = json.dumps(fields)
    with _log_lock:
        print(line, flush=True)


_ctx = threading.local()


class log_context:
    """Tag every dbg line emitted on this thread with `label` (e.g. 'seg0/b').
    Because segments are cut concurrently, the $command / ok lines from
    different workers interleave on stderr — the tag lets you tell them apart."""

    def __init__(self, label):
        self.label = label

    def __enter__(self):
        self.prev = getattr(_ctx, "label", "")
        _ctx.label = self.label

    def __exit__(self, *exc):
        _ctx.label = self.prev


def dbg(msg, **fields):
    if not DEBUG:
        return
    label = getattr(_ctx, "label", "")
    tag = f"[{label}] " if label else ""
    extra = "  ".join(f"{k}={v}" for k, v in fields.items())
    line = (f"[mc +{time.monotonic() - _t0:7.2f}s] {tag}{msg}"
            + (f"  |  {extra}" if extra else ""))
    with _log_lock:
        print(line, file=sys.stderr, flush=True)


def safe_name(s):
    cleaned = re.sub(r"[^\w\-. ]+", "_", s).strip().strip(".")
    return cleaned or "segment"


# ---------- ffprobe ----------

def ffprobe_duration(path):
    out = run_command([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", path,
    ])
    return float(json.loads(out)["format"]["duration"])


def ffprobe_frame_rate(path):
    """r_frame_rate as Fraction. avg_frame_rate is unreliable on VFR/MOV."""
    out = run_command([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ])
    val = out.strip().splitlines()[0] if out.strip() else ""
    if not val or "/" not in val:
        raise RuntimeError(f"Could not parse r_frame_rate for {path!r}: {val!r}")
    num, den = val.split("/")
    return Fraction(int(num), int(den))


def ffprobe_audio_info(path):
    out = run_command([
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,sample_rate,channels",
        "-of", "json", path,
    ])
    streams = json.loads(out).get("streams", [])
    if not streams:
        return {"codec_name": None, "sample_rate": None, "channels": None}
    s = streams[0]
    return {
        "codec_name": s.get("codec_name"),
        "sample_rate": int(s["sample_rate"]) if s.get("sample_rate") else None,
        "channels": int(s["channels"]) if s.get("channels") else None,
    }


def ffprobe_video_params(path):
    """Stream params needed to make re-encoded boundary GOPs seam-compatible
    with the stream-copied middle (pix_fmt, profile/level, SAR, color, timebase,
    fps). Missing/unknown fields are simply omitted by the arg builder."""
    out = run_command([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,pix_fmt,profile,level,sample_aspect_ratio,color_range,"
        "color_space,color_transfer,color_primaries,time_base,r_frame_rate",
        "-of", "json", path,
    ])
    streams = json.loads(out).get("streams", [])
    return streams[0] if streams else {}


def check_ffmpeg_version():
    out = run_command(["ffmpeg", "-version"])
    m = re.search(r"ffmpeg version (\d+)\.(\d+)", out)
    if not m:
        log_status(status="warn", reason="could_not_parse_ffmpeg_version")
        return
    ver = (int(m.group(1)), int(m.group(2)))
    if ver < MIN_FFMPEG_VERSION:
        log_status(
            status="warn", reason="ffmpeg_too_old",
            found=f"{ver[0]}.{ver[1]}",
            minimum=f"{MIN_FFMPEG_VERSION[0]}.{MIN_FFMPEG_VERSION[1]}",
            detail="Input-side -ss with re-encode requires ffmpeg >= 4.4 for frame-accurate cuts.",
        )


# ---------- audio extraction & xcorr ----------

def extract_audio_window(src, start, dur, out_wav, sr=8000):
    """Extract mono PCM WAV window from `src` starting at `start` (seconds).

    Uses fast input-side -ss to within ~5s of the target, then accurate
    output-side -ss for sample-precise trim. Pure input-side -ss can truncate
    the output by several seconds on some ffmpeg/codec combos (observed on
    ffmpeg 8.0.1 with stream-copied AAC); pure output-side -ss is accurate
    but decodes from the start of the file. This pattern is fast on long
    files and exact at the trim boundary.
    """
    start = max(0.0, start)
    pre_seek = max(0.0, start - 5.0)
    fine_seek = start - pre_seek
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if pre_seek > 0:
        cmd += ["-ss", f"{pre_seek:.3f}"]
    cmd += ["-i", src]
    if fine_seek > 0:
        cmd += ["-ss", f"{fine_seek:.3f}"]
    cmd += [
        "-t", f"{dur:.3f}",
        "-vn", "-ac", "1", "-ar", str(sr),
        "-c:a", "pcm_s16le", "-f", "wav",
        out_wav,
    ]
    run_command(cmd)


def load_wav_mono(path):
    sr, data = wavfile.read(path)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if data.dtype != np.float32:
        if np.issubdtype(data.dtype, np.integer):
            info = np.iinfo(data.dtype)
            denom = max(abs(int(info.min)), int(info.max))
            data = data.astype(np.float32) / float(denom)
        else:
            data = data.astype(np.float32)
    return data, sr


def xcorr_lag_seconds(ref, probe, sr):
    """Return the position (seconds) in `ref` where `probe` best aligns.

    fftconvolve(ref, probe[::-1], mode='valid') gives correlation values for
    each alignment of probe within ref; argmax = best start position in ref.
    """
    if len(ref) < len(probe):
        raise ValueError(
            f"xcorr_lag_seconds: ref ({len(ref)} samples) must be at least as long "
            f"as probe ({len(probe)} samples); otherwise mode='valid' returns an "
            f"empty array and argmax is undefined."
        )
    ref = ref - float(ref.mean())
    probe = probe - float(probe.mean())
    corr = fftconvolve(ref, probe[::-1], mode="valid")
    lag_samples = int(np.argmax(corr))
    return lag_samples / float(sr)


def estimate_offset(name, a_path, b_path, a_dur, b_dur,
                    coarse_sr, fine_sr, probe_dur, max_offset, tmp_dir):
    """Return offset (seconds) of camera `b_path` relative to A.

    Positive = camera started later than A. b_time_in_b_file = a_time - offset.
    """
    probe_dur = min(probe_dur, max(0.0, b_dur - 1.0))
    if probe_dur <= 1.0:
        raise RuntimeError(f"{name}: source too short to probe ({b_dur:.2f}s)")
    probe_start_in_b = max(0.0, (b_dur - probe_dur) / 2.0)

    # A's window must cover every plausible probe-match position. The probe
    # starts in A at (offset + probe_start_in_b) and is probe_dur long, so the
    # latest end is (max_offset + probe_start_in_b + probe_dur). Without the
    # probe_start_in_b term, fftconvolve's valid range clips off the true
    # match when the probe was pulled from deep inside B.
    a_search_dur = min(a_dur, max_offset + probe_start_in_b + probe_dur + 2.0)
    log_status(status="estimating_offset_coarse", cam=name,
               probe_dur=probe_dur, a_search_dur=a_search_dur, sr=coarse_sr)

    a_wav = os.path.join(tmp_dir, f"a_coarse_{name}.wav")
    b_wav = os.path.join(tmp_dir, f"b_coarse_{name}.wav")
    extract_audio_window(a_path, 0.0, a_search_dur, a_wav, sr=coarse_sr)
    extract_audio_window(b_path, probe_start_in_b, probe_dur, b_wav, sr=coarse_sr)
    a_sig, sr_a = load_wav_mono(a_wav)
    b_sig, sr_b = load_wav_mono(b_wav)
    if sr_a != sr_b:
        raise RuntimeError(f"{name}: coarse SR mismatch {sr_a} vs {sr_b}")

    coarse_lag_in_a = xcorr_lag_seconds(a_sig, b_sig, sr_a)
    coarse_offset = coarse_lag_in_a - probe_start_in_b
    log_status(status="estimating_offset_coarse_done", cam=name,
               coarse_offset=round(coarse_offset, 4))

    fine_probe_dur = min(probe_dur, 10.0)
    fine_probe_start_in_b = max(
        0.0,
        min(b_dur - fine_probe_dur,
            probe_start_in_b + (probe_dur - fine_probe_dur) / 2.0),
    )
    expected_lag_in_a = coarse_lag_in_a + (fine_probe_start_in_b - probe_start_in_b)
    fine_a_start = max(0.0, expected_lag_in_a - 2.0)
    fine_a_dur = min(a_dur - fine_a_start, fine_probe_dur + 4.0)
    if fine_a_dur <= fine_probe_dur:
        log_status(status="estimating_offset_fine_skipped", cam=name,
                   reason="not_enough_a_runway", offset=round(coarse_offset, 4))
        return coarse_offset

    log_status(status="estimating_offset_fine", cam=name,
               fine_probe_dur=fine_probe_dur, fine_a_dur=fine_a_dur, sr=fine_sr)
    a_fine_wav = os.path.join(tmp_dir, f"a_fine_{name}.wav")
    b_fine_wav = os.path.join(tmp_dir, f"b_fine_{name}.wav")
    extract_audio_window(a_path, fine_a_start, fine_a_dur, a_fine_wav, sr=fine_sr)
    extract_audio_window(b_path, fine_probe_start_in_b, fine_probe_dur, b_fine_wav, sr=fine_sr)
    a_fine, sr_fa = load_wav_mono(a_fine_wav)
    b_fine, _ = load_wav_mono(b_fine_wav)
    fine_lag_in_window = xcorr_lag_seconds(a_fine, b_fine, sr_fa)
    fine_lag_in_a = fine_a_start + fine_lag_in_window
    fine_offset = fine_lag_in_a - fine_probe_start_in_b
    log_status(status="estimating_offset_fine_done", cam=name,
               fine_offset=round(fine_offset, 4))
    return fine_offset


def round_offset_to_frame(offset_s, fps):
    frames = round(offset_s * float(fps))
    return frames / float(fps)


# ---------- segment cutting ----------

def full_reencode_segment(src, start, dur, out, audio_copy):
    """Re-encode a frame-accurate clip from `src` covering [start, start+dur].

    This is the legacy full-segment path (every frame re-encoded). It is now
    used (a) when --cut-method reencode is forced, and (b) as the per-clip
    fallback when smartcut's seam validation fails. Seam-free by definition.

    Uses the fast input-seek + accurate output-seek pattern (same reason as
    extract_audio_window). Pure input-side -ss on ffmpeg 8.0.1 produces
    incorrect durations here when combined with -t and a re-encoded video
    stream; the dual-seek form is reliable.
    """
    start = max(0.0, start)
    pre_seek = max(0.0, start - 5.0)
    fine_seek = start - pre_seek
    audio_args = ["-c:a", "copy"] if audio_copy else ["-c:a", "aac", "-b:a", "192k"]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if pre_seek > 0:
        cmd += ["-ss", f"{pre_seek:.3f}"]
    cmd += ["-i", src]
    if fine_seek > 0:
        cmd += ["-ss", f"{fine_seek:.3f}"]
    cmd += [
        "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        *audio_args,
        "-movflags", "+faststart",
        "-avoid_negative_ts", "make_zero",
        out,
    ]
    run_command(cmd)


# ---------- smartcut: re-encode only the boundary GOPs, copy the middle ----------

_PROFILE_MAP = {
    "constrained baseline": "baseline",
    "baseline": "baseline",
    "main": "main",
    "high": "high",
    "high 10": "high10",
    "high 4:2:2": "high422",
    "high 4:4:4 predictive": "high444",
}


def list_keyframes(src, start, end):
    """Sorted keyframe pts_times (seconds) within ~[start, end], read from
    packet flags (no decode). The window is widened slightly so a keyframe
    sitting exactly on a boundary isn't missed."""
    lo = max(0.0, start - 0.5)
    out = run_command([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-read_intervals", f"{lo:.3f}%{end + 0.5:.3f}",
        "-show_entries", "packet=pts_time,flags",
        "-of", "csv=p=0",
        src,
    ])
    kfs = []
    for line in out.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2 or "K" not in parts[1]:
            continue
        try:
            kfs.append(float(parts[0]))
        except ValueError:
            pass
    kfs.sort()
    return kfs


def _x264_match_args(vparams):
    """libx264 -crf 18 args that mirror the source's pixel/profile/color params
    so a re-encoded boundary piece concatenates cleanly with the copied middle.

    Preset is `veryfast`, NOT for quality reasons (CRF 18 fixes the quality
    target) but for speed: the boundary GOPs are tiny, transient pieces glued
    between lossless copy, so their encode *efficiency* is irrelevant — only
    wall-clock matters, and on heavy sources (4K 10-bit 4:2:2, long GOPs) a
    near-full-GOP boundary at `fast` can take ~40s. `veryfast` keeps CABAC and
    the high-profile feature set (unlike `ultrafast`), so the seam stays clean."""
    args = ["-c:v", "libx264", "-crf", "18", "-preset", "veryfast"]
    pix = vparams.get("pix_fmt")
    if pix and pix != "unknown":
        args += ["-pix_fmt", pix]
    profile = _PROFILE_MAP.get((vparams.get("profile") or "").lower())
    if profile:
        args += ["-profile:v", profile]
    # NOTE: deliberately do NOT force -level. The copied middle keeps its own
    # SPS, so the re-encoded pieces don't need a matching level to concat, and
    # forcing it risks an invalid value (e.g. ffprobe reports level 1b as 9 ->
    # "0.9", which libx264 rejects). libx264 picks a compatible level itself.
    for key, flag in (
        ("color_primaries", "-color_primaries"),
        ("color_transfer", "-color_trc"),
        ("color_space", "-colorspace"),
        ("color_range", "-color_range"),
    ):
        val = vparams.get(key)
        if val and val not in ("unknown", "unspecified", "reserved"):
            args += [flag, val]
    return args


def reencode_video_only(src, start, dur, out, vparams):
    """Re-encode a frame-accurate video-only piece (head or tail GOP)."""
    start = max(0.0, start)
    pre_seek = max(0.0, start - 5.0)
    fine_seek = start - pre_seek
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if pre_seek > 0:
        cmd += ["-ss", f"{pre_seek:.3f}"]
    cmd += ["-i", src]
    if fine_seek > 0:
        cmd += ["-ss", f"{fine_seek:.3f}"]
    cmd += ["-t", f"{dur:.3f}", "-an", *_x264_match_args(vparams)]
    sar = vparams.get("sample_aspect_ratio")
    if sar and re.fullmatch(r"\d+:\d+", sar) and sar != "0:1":
        cmd += ["-vf", f"setsar={sar.replace(':', '/')}"]
    rfr = vparams.get("r_frame_rate")
    if rfr and rfr not in ("0/0", "0/1"):
        cmd += ["-r", rfr, "-fps_mode", "cfr"]
    tb = vparams.get("time_base")
    if tb and "/" in tb:
        cmd += ["-video_track_timescale", tb.split("/")[1]]
    cmd += ["-avoid_negative_ts", "make_zero", out]
    run_command(cmd)


def copy_video_only(src, start, dur, out):
    """Stream-copy whole GOPs [start, start+dur). `start` must be a keyframe."""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-i", src,
        "-t", f"{dur:.3f}",
        "-an", "-c:v", "copy",
        "-avoid_negative_ts", "make_zero",
        out,
    ]
    run_command(cmd)


def extract_audio_clip(src, start, dur, out, audio_copy):
    """Single-pass audio cut for the whole window (never spliced), so there are
    no audio seams to worry about. Muxed back onto the spliced video."""
    start = max(0.0, start)
    pre_seek = max(0.0, start - 5.0)
    fine_seek = start - pre_seek
    audio_args = ["-c:a", "copy"] if audio_copy else ["-c:a", "aac", "-b:a", "192k"]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if pre_seek > 0:
        cmd += ["-ss", f"{pre_seek:.3f}"]
    cmd += ["-i", src]
    if fine_seek > 0:
        cmd += ["-ss", f"{fine_seek:.3f}"]
    cmd += ["-t", f"{dur:.3f}", "-vn", "-map", "0:a:0", *audio_args, out]
    run_command(cmd)


def concat_copy(parts, out, work_dir):
    """Lossless concat of H.264 pieces via the MPEG-TS protocol. Remuxing each
    piece to annex-B TS and joining with `concat:` regenerates clean, monotonic
    timestamps across the seam — the MP4 concat *demuxer* leaves non-monotonic
    DTS where a re-encoded piece meets a copied (B-frame) piece."""
    ts_parts = []
    for idx, p in enumerate(parts):
        ts = os.path.join(work_dir, f"part_{idx}.ts")
        run_command([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", p, "-c", "copy", "-bsf:v", "h264_mp4toannexb",
            "-f", "mpegts", ts,
        ])
        ts_parts.append(ts)
    run_command([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-fflags", "+genpts",
        "-i", "concat:" + "|".join(ts_parts),
        "-c", "copy", "-avoid_negative_ts", "make_zero",
        out,
    ])


def count_video_packets(path):
    out = run_command([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-count_packets", "-show_entries", "stream=nb_read_packets",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ])
    return int(out.strip().splitlines()[0])


def mux_av(video_only, audio, out):
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video_only]
    if audio:
        cmd += ["-i", audio]
    cmd += ["-c", "copy", "-map", "0:v:0"]
    if audio:
        cmd += ["-map", "1:a:0"]
    cmd += ["-movflags", "+faststart", out]
    run_command(cmd)


def smartcut_video(src, cut_start, cut_end, out, audio_copy, has_audio, vparams, fps):
    """Frame-accurate cut that re-encodes only the partial GOPs at each
    boundary and stream-copies the whole GOPs between. Returns a list of
    *seam positions* (seconds into the output clip, one per re-encode↔copy
    junction) on success — possibly empty (pure copy, no seams). Returns None
    if the window can't be smartcut (too few keyframes) — caller then falls
    back to a full re-encode. Raises on ffmpeg failure (also caught by the
    caller as a fallback trigger). The seam list lets validate_seam decode
    only around the junctions instead of the whole clip.

    `-c copy` is not frame-exact at its tail (it stops on a packet boundary and
    can spill a couple of frames into the next GOP), so we measure how many
    frames the copy actually produced and start the tail re-encode exactly
    where the copy ended. That makes head/copy/tail strictly contiguous — no
    overlap (which caused non-monotonic DTS) and no gap.
    """
    name = os.path.basename(src)
    dbg("smartcut start", src=name, window=f"[{cut_start:.3f},{cut_end:.3f}]",
        dur=round(cut_end - cut_start, 3))
    # Boundary GOPs are re-encoded with libx264 (H.264); concat with the copied
    # middle is only valid if the source is also H.264. Other codecs → fall back.
    if (vparams.get("codec_name") or "").lower() != "h264":
        dbg("smartcut skip: source not H.264", src=name, codec=vparams.get("codec_name"))
        return None
    fps_f = float(fps)
    half_frame = 0.5 / fps_f
    kfs = list_keyframes(src, cut_start, cut_end)
    # Tight epsilon (FP equality only). A keyframe more than ~1us before
    # cut_start is NOT treated as "on the boundary" — it's excluded so the head
    # re-encode fills [cut_start, next keyframe) and the start stays frame-exact.
    starts = [k for k in kfs if k >= cut_start - 1e-6]
    ends = [k for k in kfs if k <= cut_end + 1e-6]
    if not starts or not ends:
        dbg("smartcut skip: no keyframe in range", src=name, keyframes=len(kfs))
        return None
    middle_start = starts[0]
    middle_end = ends[-1]
    if middle_end - middle_start <= half_frame:
        dbg("smartcut skip: no copyable whole-GOP region", src=name,
            middle_start=round(middle_start, 3), middle_end=round(middle_end, 3))
        return None  # no copyable whole-GOP region
    dbg("smartcut keyframes", src=name, n=len(kfs),
        middle_start=round(middle_start, 3), middle_end=round(middle_end, 3))

    with tempfile.TemporaryDirectory(prefix="smartcut-") as work:
        parts = []
        # Junction positions in OUTPUT time, for targeted seam validation.
        seams = []
        head_dur = 0.0
        if middle_start - cut_start > half_frame:
            head = os.path.join(work, "head.mp4")
            dbg("smartcut head reencode", src=name,
                span=f"[{cut_start:.3f},{middle_start:.3f}]")
            reencode_video_only(src, cut_start, middle_start - cut_start, head, vparams)
            parts.append(head)
            head_dur = middle_start - cut_start
        else:
            dbg("smartcut no head (cut_start on keyframe)", src=name)

        mid = os.path.join(work, "mid.mp4")
        copy_video_only(src, middle_start, middle_end - middle_start, mid)
        parts.append(mid)

        # Where the copy actually ended in source time (it may overshoot
        # middle_end by a frame or two). Fill [copy_end, cut_end] by re-encode.
        n_copy = count_video_packets(mid)
        copy_dur = n_copy / fps_f
        copy_end = middle_start + copy_dur
        dbg("smartcut copy", src=name, copied_frames=n_copy,
            copy_end=round(copy_end, 3))
        if head_dur > 0:
            seams.append(head_dur)  # head → copy junction
        if cut_end - copy_end > half_frame:
            tail = os.path.join(work, "tail.mp4")
            dbg("smartcut tail reencode", src=name,
                span=f"[{copy_end:.3f},{cut_end:.3f}]")
            reencode_video_only(src, copy_end, cut_end - copy_end, tail, vparams)
            parts.append(tail)
            seams.append(head_dur + copy_dur)  # copy → tail junction
        else:
            dbg("smartcut no tail (copy reached end)", src=name)

        video_only = os.path.join(work, "video_only.mp4")
        if len(parts) == 1:
            shutil.copy(parts[0], video_only)
        else:
            dbg("smartcut concat", src=name, pieces=len(parts))
            concat_copy(parts, video_only, work)

        audio_path = None
        if has_audio:
            audio_path = os.path.join(work, "audio.m4a")
            extract_audio_clip(src, cut_start, cut_end - cut_start, audio_path, audio_copy)
        else:
            dbg("smartcut no audio stream", src=name)
        mux_av(video_only, audio_path, out)
    dbg("smartcut done", src=name, out=os.path.basename(out), seams=[round(s, 3) for s in seams])
    return seams


# Seconds decoded on each side of a splice junction during seam validation.
SEAM_PROBE_PAD = 2.0


def _decode_clean(clip, ss=None, t=None):
    """Decode (a window of) `clip` and report whether it's free of *decoder*
    errors. The `non monotonically increasing dts to muxer` line is a benign
    *muxer* bookkeeping warning at a concat seam (frames decode fine) and is
    ignored."""
    cmd = ["ffmpeg", "-v", "error"]
    if ss is not None:
        cmd += ["-ss", f"{ss:.3f}"]
    cmd += ["-i", clip]
    if t is not None:
        cmd += ["-t", f"{t:.3f}"]
    cmd += ["-f", "null", "-"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    for line in res.stderr.splitlines():
        if not line.strip():
            continue
        if "non monotonically increasing dts" in line.lower():
            continue
        dbg("seam REJECT: decoder error", clip=os.path.basename(clip), line=line)
        return False
    return True


def validate_seam(clip, expected_dur, fps, seams):
    """True if `clip` has ~the expected frame count AND each splice junction
    decodes without corruption.

    The copied middle is bit-identical to the source, so a glitch can only
    appear at a re-encode↔copy junction — we decode just a ±SEAM_PROBE_PAD
    window around each (input-side -ss seeks to the keyframe before it, so the
    junction is reconstructed with real references) instead of the whole clip.
    The frame-count check (packet count, no decode) still guarantees the whole
    clip is contiguous — no missing or extra frames."""
    try:
        n = count_video_packets(clip)
    except Exception:
        dbg("seam REJECT: could not count packets", clip=os.path.basename(clip))
        return False
    expected = round(expected_dur * float(fps))
    if abs(n - expected) > 2:
        dbg("seam REJECT: frame-count mismatch", clip=os.path.basename(clip),
            frames=n, expected=expected)
        return False
    for s in seams:
        if not _decode_clean(clip, ss=max(0.0, s - SEAM_PROBE_PAD), t=2 * SEAM_PROBE_PAD):
            return False
    return True


def cut_video_clip(src, cut_start, cut_end, out, audio_copy, has_audio,
                   vparams, cut_method, fps, label=""):
    """Produce a frame-accurate clip and return which method was used:
    'smartcut', 'reencode_fallback', or 'reencode' (forced)."""
    dur = cut_end - cut_start
    t = time.monotonic()
    with log_context(label):
        if cut_method == "smartcut":
            try:
                seams = smartcut_video(src, cut_start, cut_end, out, audio_copy,
                                       has_audio, vparams, fps)
                if seams is not None:  # [] is a valid (seamless pure-copy) result
                    if validate_seam(out, dur, fps, seams):
                        dbg("CUT smartcut OK", seams=len(seams),
                            secs=round(time.monotonic() - t, 2))
                        return "smartcut"
                    dbg("CUT smartcut REJECTED by seam validation -> reencode")
                else:
                    dbg("CUT smartcut not applicable -> reencode")
            except Exception as exc:
                dbg("CUT smartcut ERROR -> reencode",
                    error=f"{type(exc).__name__}: {exc}")
                log_status(status="smartcut_error", src=os.path.basename(src),
                           error=f"{type(exc).__name__}: {exc}")
            full_reencode_segment(src, cut_start, dur, out, audio_copy)
            dbg("CUT reencode_fallback done", secs=round(time.monotonic() - t, 2))
            return "reencode_fallback"
        full_reencode_segment(src, cut_start, dur, out, audio_copy)
        dbg("CUT reencode (forced) done", secs=round(time.monotonic() - t, 2))
        return "reencode"


def cut_audio_segment(src, start, dur, out):
    """Sample-accurate PCM WAV clip from an audio-only source.

    Always decodes to pcm_s16le so the output is uniform regardless of input
    container (.wav/.mp3/.m4a/.aac/.flac/.ogg/.opus). Source channel count is
    preserved (no -ac flag — don't downmix). Same dual-seek pattern as
    full_reencode_segment / extract_audio_window for sample-precise trim
    boundaries.
    """
    start = max(0.0, start)
    pre_seek = max(0.0, start - 5.0)
    fine_seek = start - pre_seek
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if pre_seek > 0:
        cmd += ["-ss", f"{pre_seek:.3f}"]
    cmd += ["-i", src]
    if fine_seek > 0:
        cmd += ["-ss", f"{fine_seek:.3f}"]
    cmd += [
        "-t", f"{dur:.3f}",
        "-vn",
        "-c:a", "pcm_s16le", "-f", "wav",
        out,
    ]
    run_command(cmd)


# Largest audio shortfall (seconds) we silence-pad rather than drop the track.
AUDIO_SILENCE_PAD_MAX = 0.5


def cut_audio_segment_window(src, lo, hi, src_dur, out):
    """Cut [lo, hi] from an audio source. If the window extends past the
    source's bounds [0, src_dur], pad the missing end(s) with silence so the
    real samples keep their correct position in the output window (prepend for
    a late start, append for an early end — never shift the existing audio).
    Returns (head_pad, tail_pad) seconds of silence added."""
    window = hi - lo
    head_pad = max(0.0, -lo)
    tail_pad = max(0.0, hi - src_dur)
    avail_lo = max(0.0, lo)
    avail_dur = min(src_dur, hi) - avail_lo
    if head_pad <= 1e-6 and tail_pad <= 1e-6:
        cut_audio_segment(src, avail_lo, avail_dur, out)
        return (0.0, 0.0)
    with tempfile.TemporaryDirectory(prefix="lavpad-") as work:
        raw = os.path.join(work, "raw.wav")
        cut_audio_segment(src, avail_lo, avail_dur, raw)  # sample-accurate
        af = []
        if head_pad > 1e-6:
            af.append(f"adelay={int(round(head_pad * 1000))}:all=1")  # prepend silence
        af.append(f"apad=whole_dur={window:.6f}")                     # fill to window len
        run_command([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", raw, "-af", ",".join(af),
            "-c:a", "pcm_s16le", "-f", "wav", out,
        ])
    return (head_pad, tail_pad)


# ---------- per-segment audio drift correction ----------

# Minimum normalized-correlation peak (0..1) for a per-segment offset to be
# trusted. A real A<->lav alignment produces a sharp, prominent peak; silence,
# non-matching audio, or a true match sitting outside the search window produce
# a weak/flat one. Below this we keep the reliable global offset rather than
# risk pushing a good track out of sync.
AUDIO_DRIFT_MIN_CONFIDENCE = 0.10


def _ncc_best_lag(ref, probe):
    """Best lag (in samples) of `probe` within `ref` and its normalized
    correlation peak (0..1). Uses 'valid' cross-correlation (probe fully inside
    ref), normalized per-lag by the windowed L2 norms so the peak is a true
    similarity score, not just a raw magnitude that scales with loudness."""
    ref = ref.astype(np.float64) - float(ref.mean())
    probe = probe.astype(np.float64) - float(probe.mean())
    corr = fftconvolve(ref, probe[::-1], mode="valid")
    P = len(probe)
    # Sliding L2 norm of ref over each length-P window, via a cumulative sum of
    # squares (cheap, no per-lag loop).
    csum = np.concatenate(([0.0], np.cumsum(ref * ref)))
    ks = np.arange(len(corr))
    win_norm = np.sqrt(np.maximum(csum[ks + P] - csum[ks], 1e-12))
    probe_norm = np.sqrt(max(float(np.dot(probe, probe)), 1e-12))
    ncc = corr / (win_norm * probe_norm)
    idx = int(np.argmax(ncc))
    return idx, float(ncc[idx])


def refine_audio_offset(name, a_path, lav_path, a_dur, lav_dur, global_offset,
                        a_center, probe_dur, search_pad, sr):
    """Re-measure the A->lav sync offset *locally* around a_center (a time on
    A's timeline), seeded by global_offset, to correct clock drift between the
    camera and a separate audio recorder.

    A single global offset is exact only where it was measured; a recorder whose
    clock runs slightly fast/slow slides out of sync across a long take. Here we
    pull a short probe from the lav around this segment and cross-correlate it
    against a slightly wider A window, so the returned offset reflects the drift
    *at this segment* instead of the whole-show average.

    Returns a refined offset (seconds), or None if the region can't be reliably
    probed — too short, the peak hard against a search-window edge (true match
    likely outside the window), or a weak correlation (silence / non-matching
    audio). In every None case the caller keeps the global offset. Self-contained
    — creates and cleans its own temp dir, so it is safe to call concurrently
    from the per-segment worker threads.
    """
    pd = min(probe_dur, max(0.0, lav_dur - 1.0), max(0.0, a_dur - 1.0))
    if pd <= 1.0:
        return None
    # Where this segment lives in the lav file, per the global offset.
    lav_center = a_center - global_offset
    lav_probe_start = max(0.0, min(lav_dur - pd, lav_center - pd / 2.0))
    # Search a wider A window centred on the expected match so residual drift
    # (a few hundred ms over a long take) lands comfortably inside it.
    expected_a_start = lav_probe_start + global_offset
    a_win_dur = min(a_dur, pd + 2.0 * search_pad)
    if a_win_dur <= pd:
        return None
    a_win_start = max(0.0, min(a_dur - a_win_dur, expected_a_start - search_pad))
    with tempfile.TemporaryDirectory(prefix="drift-") as tmp_dir:
        a_wav = os.path.join(tmp_dir, "a.wav")
        l_wav = os.path.join(tmp_dir, "l.wav")
        extract_audio_window(a_path, a_win_start, a_win_dur, a_wav, sr=sr)
        extract_audio_window(lav_path, lav_probe_start, pd, l_wav, sr=sr)
        a_sig, sr_a = load_wav_mono(a_wav)
        l_sig, _ = load_wav_mono(l_wav)
        if len(l_sig) == 0 or len(a_sig) < len(l_sig):
            return None
        lag_samples, confidence = _ncc_best_lag(a_sig, l_sig)
        lag_in_window = lag_samples / float(sr_a)
    # Weak correlation → distrust (silence / mismatched audio / no real match).
    if confidence < AUDIO_DRIFT_MIN_CONFIDENCE:
        dbg(f"{name} drift refine: weak match, keep global",
            confidence=round(confidence, 3))
        return None
    # A peak hard against either edge means the true match is probably outside
    # the search window — distrust it and keep the global offset.
    edge_margin = 0.1
    if lag_in_window < edge_margin or lag_in_window > (a_win_dur - pd) - edge_margin:
        dbg(f"{name} drift refine: peak at window edge, keep global",
            lag=round(lag_in_window, 3))
        return None
    return (a_win_start + lag_in_window) - lav_probe_start


# ---------- validation ----------

def measure_clip_lag(ref_clip, alt_clip, tmp_dir, probe_dur=10.0):
    """Signed lag (seconds) of alt_clip relative to ref_clip.

    Pull a probe from the middle of alt and a slightly wider window from the
    middle of ref. If clips are in sync, alt's t=0_in_window corresponds to
    the same ref time → returned lag ≈ 0.
    """
    ref_dur = ffprobe_duration(ref_clip)
    alt_dur = ffprobe_duration(alt_clip)
    pd = min(probe_dur, max(0.5, min(ref_dur, alt_dur) - 1.0))
    alt_start = max(0.0, (alt_dur - pd) / 2.0)
    ref_start = max(0.0, alt_start - 2.0)
    ref_dur_window = min(ref_dur - ref_start, pd + 4.0)
    if ref_dur_window <= pd:
        ref_start = 0.0
        ref_dur_window = min(ref_dur, pd + 4.0)
    ref_wav = os.path.join(tmp_dir, "val_ref.wav")
    alt_wav = os.path.join(tmp_dir, "val_alt.wav")
    extract_audio_window(ref_clip, ref_start, ref_dur_window, ref_wav, sr=16000)
    extract_audio_window(alt_clip, alt_start, pd, alt_wav, sr=16000)
    ref, sr = load_wav_mono(ref_wav)
    alt, _ = load_wav_mono(alt_wav)
    lag_in_window = xcorr_lag_seconds(ref, alt, sr)
    return (ref_start + lag_in_window) - alt_start


# ---------- input validation ----------

def validate_segments(segments, a_duration):
    """Attach validation_error per-segment; never raises for content issues."""
    out = []
    for i, seg in enumerate(segments):
        seg = dict(seg)
        err = None
        start = end = None
        try:
            start = float(seg.get("start"))
            end = float(seg.get("end"))
        except (TypeError, ValueError):
            err = "missing or non-numeric start/end"
        if err is None:
            if start < 0:
                err = f"start ({start}) is negative"
            elif end <= start:
                err = f"end ({end}) <= start ({start})"
            elif end > a_duration:
                err = f"end ({end:.3f}) exceeds A-cam duration ({a_duration:.3f})"
        if err:
            log_status(status="segment_invalid", index=i, reason=err)
            seg["validation_error"] = err
        out.append(seg)
    return out


# ---------- manifest I/O ----------

def write_manifest_atomic(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


# ---------- main ----------

def parse_args():
    p = argparse.ArgumentParser(description="Multicam sync + cut pipeline.")
    p.add_argument("--acam", required=True)
    p.add_argument("--bcam", default=None,
                   help="Optional. At least one of --bcam/--ccam/--lav1/--lav2 must be provided.")
    p.add_argument("--ccam", default=None,
                   help="Optional. At least one of --bcam/--ccam/--lav1/--lav2 must be provided.")
    p.add_argument("--lav1", default=None,
                   help="Optional audio-only source (lavalier mic). Sync'd to A-cam audio.")
    p.add_argument("--lav2", default=None,
                   help="Optional audio-only source (lavalier mic). Sync'd to A-cam audio.")
    p.add_argument("--segments", required=True,
                   help="JSON file: [{start, end, title?}, ...] in A-cam timecode")
    p.add_argument("--outdir", required=True)
    p.add_argument("--probe-dur", type=float, default=180.0,
                   help="Audio probe duration for sync correlation (seconds).")
    p.add_argument("--coarse-sr", type=int, default=8000)
    p.add_argument("--fine-sr", type=int, default=16000)
    p.add_argument("--max-offset", type=float, default=1200.0,
                   help="Max plausible offset (s) of any alt source after A.")
    p.add_argument("--tolerance-frames", type=float, default=1.5,
                   help="Allowed sync drift (A-cam frames). Re-encode can shift PTS ~10-40ms; 1.5 is safer than 1.")
    p.add_argument("--cut-method", choices=["smartcut", "reencode"], default="smartcut",
                   help="smartcut (default): re-encode only the boundary GOPs at "
                        "libx264 -crf 18 and stream-copy the whole GOPs between. "
                        "reencode: full libx264 -crf 18 re-encode of every segment "
                        "(legacy). Per-clip fallback to full re-encode happens "
                        "automatically when a smartcut seam fails validation.")
    p.add_argument("--workers", type=int, default=None,
                   help="Parallel segment workers. Default min(4, cpu_count).")
    p.add_argument("--audio-drift-correction", action=argparse.BooleanOptionalAction, default=True,
                   help="Re-measure each lav's sync offset per segment to correct "
                        "clock drift between the camera and a separate audio recorder "
                        "(default on). Use --no-audio-drift-correction to fall back to "
                        "one global offset for the whole recording.")
    p.add_argument("--audio-drift-window", type=float, default=2.0,
                   help="Plus/minus seconds of drift searched for around each segment "
                        "when refining a lav offset (default 2.0).")
    p.add_argument("--audio-drift-probe", type=float, default=15.0,
                   help="Audio probe length (s) used for per-segment lav offset "
                        "refinement (default 15.0).")
    p.add_argument("--skip-validation", action="store_true")
    p.add_argument("--zip-out", default=None,
                   help="If set, bundle the outdir into a ZIP at this path after success.")
    return p.parse_args()


def main():
    args = parse_args()

    if not any([args.bcam, args.ccam, args.lav1, args.lav2]):
        print(json.dumps({"error": "At least one of --bcam / --ccam / --lav1 / --lav2 is required"}),
              file=sys.stderr, flush=True)
        sys.exit(1)

    paths_to_check = [args.acam, args.segments]
    if args.bcam:
        paths_to_check.append(args.bcam)
    if args.ccam:
        paths_to_check.append(args.ccam)
    if args.lav1:
        paths_to_check.append(args.lav1)
    if args.lav2:
        paths_to_check.append(args.lav2)
    for p in paths_to_check:
        if not os.path.exists(p):
            print(json.dumps({"error": f"Not found: {p}"}), file=sys.stderr, flush=True)
            sys.exit(1)

    check_ffmpeg_version()

    outdir = Path(args.outdir)
    (outdir / "acam_clips").mkdir(parents=True, exist_ok=True)
    if args.bcam:
        (outdir / "bcam_clips").mkdir(parents=True, exist_ok=True)
    if args.ccam:
        (outdir / "ccam_clips").mkdir(parents=True, exist_ok=True)
    if args.lav1:
        (outdir / "lav1_clips").mkdir(parents=True, exist_ok=True)
    if args.lav2:
        (outdir / "lav2_clips").mkdir(parents=True, exist_ok=True)
    manifest_path = outdir / "clips_manifest.json"

    a_dur = ffprobe_duration(args.acam)
    b_dur = ffprobe_duration(args.bcam) if args.bcam else None
    c_dur = ffprobe_duration(args.ccam) if args.ccam else None
    l1_dur = ffprobe_duration(args.lav1) if args.lav1 else None
    l2_dur = ffprobe_duration(args.lav2) if args.lav2 else None
    fps = ffprobe_frame_rate(args.acam)
    log_status(status="probed_sources", a_duration=a_dur, b_duration=b_dur,
               c_duration=c_dur, lav1_duration=l1_dur, lav2_duration=l2_dur,
               a_fps=str(fps))

    cam_fps = {"a": fps}
    alt_cams = []
    if args.bcam:
        alt_cams.append(("B", "b", args.bcam))
    if args.ccam:
        alt_cams.append(("C", "c", args.ccam))
    for cam_name, cam_key, cam_path in alt_cams:
        try:
            other_fps = ffprobe_frame_rate(cam_path)
            cam_fps[cam_key] = other_fps
            if other_fps != fps:
                log_status(status="warn", reason="fps_mismatch",
                           cam=cam_name, a_fps=str(fps), cam_fps=str(other_fps))
        except Exception as e:
            cam_fps[cam_key] = fps
            log_status(status="warn", reason="fps_unreadable", cam=cam_name, detail=str(e))

    audio_copy = {}
    has_audio = {}
    vparams = {}
    cam_paths = [("a", args.acam)]
    if args.bcam:
        cam_paths.append(("b", args.bcam))
    if args.ccam:
        cam_paths.append(("c", args.ccam))
    for name, path in cam_paths:
        info = ffprobe_audio_info(path)
        has_audio[name] = info["codec_name"] is not None
        ok = (info["codec_name"] or "").lower() in MUXABLE_AUDIO
        audio_copy[name] = ok
        vparams[name] = ffprobe_video_params(path)
        if has_audio[name] and not ok:
            log_status(status="warn", reason="audio_codec_not_muxable",
                       cam=name, codec=info["codec_name"], fallback="aac@192k")

    b_offset = None
    c_offset = None
    l1_offset = None
    l2_offset = None
    _ctx.label = "offset"  # tag the xcorr-phase log lines (main thread)
    with tempfile.TemporaryDirectory(prefix="multicam-xcorr-") as tmp:
        if args.bcam:
            b_raw = estimate_offset("B", args.acam, args.bcam, a_dur, b_dur,
                                    args.coarse_sr, args.fine_sr,
                                    args.probe_dur, args.max_offset, tmp)
            b_offset = round_offset_to_frame(b_raw, fps)
        if args.ccam:
            c_raw = estimate_offset("C", args.acam, args.ccam, a_dur, c_dur,
                                    args.coarse_sr, args.fine_sr,
                                    args.probe_dur, args.max_offset, tmp)
            c_offset = round_offset_to_frame(c_raw, fps)
        if args.lav1:
            # Audio-only: keep the raw (sub-frame) offset. cut_audio_segment is
            # sample-accurate, so rounding to the video frame grid would only
            # throw away up to half a frame of genuine sync precision.
            l1_offset = estimate_offset("L1", args.acam, args.lav1, a_dur, l1_dur,
                                        args.coarse_sr, args.fine_sr,
                                        args.probe_dur, args.max_offset, tmp)
        if args.lav2:
            l2_offset = estimate_offset("L2", args.acam, args.lav2, a_dur, l2_dur,
                                        args.coarse_sr, args.fine_sr,
                                        args.probe_dur, args.max_offset, tmp)
    log_status(status="offsets_rounded",
               b_offset=round(b_offset, 4) if b_offset is not None else None,
               c_offset=round(c_offset, 4) if c_offset is not None else None,
               lav1_offset=round(l1_offset, 4) if l1_offset is not None else None,
               lav2_offset=round(l2_offset, 4) if l2_offset is not None else None)

    raw_segments = json.loads(Path(args.segments).read_text())
    if not isinstance(raw_segments, list) or not raw_segments:
        print(json.dumps({"error": "segments JSON must be a non-empty list"}),
              file=sys.stderr, flush=True)
        sys.exit(1)
    validated = validate_segments(raw_segments, a_dur)

    manifest = {
        "sources": {
            "acam": {"path": str(Path(args.acam).resolve()),
                     "duration": a_dur,
                     "fps": f"{fps.numerator}/{fps.denominator}"},
            "bcam": (None if not args.bcam else
                     {"path": str(Path(args.bcam).resolve()),
                      "duration": b_dur, "offset_seconds": b_offset}),
            "ccam": (None if not args.ccam else
                     {"path": str(Path(args.ccam).resolve()),
                      "duration": c_dur, "offset_seconds": c_offset}),
            "lav1": (None if not args.lav1 else
                     {"path": str(Path(args.lav1).resolve()),
                      "duration": l1_dur, "offset_seconds": l1_offset}),
            "lav2": (None if not args.lav2 else
                     {"path": str(Path(args.lav2).resolve()),
                      "duration": l2_dur, "offset_seconds": l2_offset}),
        },
        "convention": "alt_time = a_time - alt_offset (positive offset = alt started later)",
        "segments": [],
        "validation": None,
    }
    write_manifest_atomic(manifest_path, manifest)

    pad = max(3, len(str(len(validated))))

    def process_segment(i, seg):
        """Cut every camera/lav for one segment and return its manifest entry.
        Pure w.r.t. shared state — safe to run concurrently across segments."""
        # Tag every dbg line from this worker with the segment (cut_video_clip
        # refines it to seg{i}/{cam}); makes the interleaved parallel log
        # readable. Each worker only runs process_segment, so a plain set is
        # fine — the next segment on this thread overwrites it.
        _ctx.label = f"seg{i}"
        base = f"segment_{i:0{pad}d}.mp4"
        wav_base = f"segment_{i:0{pad}d}.wav"
        entry = {
            "index": i, "title": safe_name(str(seg.get("title") or f"segment_{i:0{pad}d}")),
            "a_start": seg.get("start"), "a_end": seg.get("end"),
            "acam_clip": None, "bcam_clip": None, "ccam_clip": None,
            "lav1_clip": None, "lav2_clip": None,
            "bcam_available": False, "ccam_available": False,
            "lav1_available": False, "lav2_available": False,
            "acam_method": None, "bcam_method": None, "ccam_method": None,
            "error": None,
        }

        if "validation_error" in seg:
            entry["error"] = seg["validation_error"]
            log_status(status="segment_skipped", index=i, reason=seg["validation_error"])
            dbg("segment SKIP (invalid)", seg=i, reason=seg["validation_error"])
            return entry

        seg_t = time.monotonic()
        try:
            a_start = float(seg["start"])
            a_end = float(seg["end"])

            # All candidate sources for this segment (A is the reference, offset 0).
            candidates = [
                ("a", "video", args.acam, 0.0, a_dur, outdir / "acam_clips" / base,
                 "acam_clip", "acam_method"),
            ]
            if args.bcam:
                candidates.append(("b", "video", args.bcam, b_offset, b_dur,
                                   outdir / "bcam_clips" / base, "bcam_clip", "bcam_method"))
            if args.ccam:
                candidates.append(("c", "video", args.ccam, c_offset, c_dur,
                                   outdir / "ccam_clips" / base, "ccam_clip", "ccam_method"))
            if args.lav1:
                candidates.append(("l1", "audio", args.lav1, l1_offset, l1_dur,
                                   outdir / "lav1_clips" / wav_base, "lav1_clip", None))
            if args.lav2:
                candidates.append(("l2", "audio", args.lav2, l2_offset, l2_dur,
                                   outdir / "lav2_clips" / wav_base, "lav2_clip", None))

            # VIDEO sources define the window: include only those that fully
            # cover the core (video can't be fabricated), and a dropped video
            # source doesn't constrain padding. They alone determine the common
            # pre/post-roll so every video clip shares one real-world window and
            # stays frame-aligned (clamping per-camera would shift a clip's t=0).
            video = [c for c in candidates if c[1] == "video"]
            audio = [c for c in candidates if c[1] == "audio"]
            video_included = []
            for c in video:
                name, offset, src_dur = c[0], c[3], c[4]
                if (a_start - offset) < -1e-6 or (a_end - offset) > src_dur + 1e-6:
                    log_status(status="source_dropped", index=i, source=name,
                               reason="video does not cover the segment (cannot pad video)")
                    dbg(f"{name} DROP: video core out of range",
                        core_in_src=f"[{a_start - offset:.3f},{a_end - offset:.3f}]", src_dur=src_dur)
                    continue
                video_included.append(c)

            pre = min([PAD_SECONDS] + [a_start - c[3] for c in video_included])
            post = min([PAD_SECONDS] + [c[4] - (a_end - c[3]) for c in video_included])
            pre = max(0.0, pre)
            post = max(0.0, post)
            a_lo = a_start - pre
            a_hi = a_end + post

            # AUDIO sources adapt to that window: a small shortfall is filled
            # with silence (real samples stay put); only a large gap drops it.
            # Each lav's offset is first re-measured *for this segment* so clock
            # drift is corrected before we decide the window. audio_included
            # holds (candidate, segment_offset) — the offset actually cut with.
            a_center = (a_start + a_end) / 2.0
            audio_included = []
            for c in audio:
                name, src, offset, src_dur = c[0], c[2], c[3], c[4]
                seg_offset = offset
                if args.audio_drift_correction:
                    try:
                        refined = refine_audio_offset(
                            name, args.acam, src, a_dur, src_dur, offset, a_center,
                            args.audio_drift_probe, args.audio_drift_window, args.fine_sr)
                    except Exception as exc:
                        refined = None
                        dbg(f"{name} drift refine error -> keep global offset",
                            error=f"{type(exc).__name__}: {exc}")
                    if refined is not None:
                        drift = refined - offset
                        if abs(drift) > 1e-4:
                            log_status(status="audio_drift_corrected", index=i, source=name,
                                       global_offset=round(offset, 4),
                                       segment_offset=round(refined, 4), drift=round(drift, 4))
                            dbg(f"{name} drift corrected", global_off=round(offset, 4),
                                seg_off=round(refined, 4), drift=round(drift, 4))
                        seg_offset = refined
                short = max(0.0, seg_offset - a_lo) + max(0.0, (a_hi - seg_offset) - src_dur)
                if short > AUDIO_SILENCE_PAD_MAX:
                    log_status(status="source_dropped", index=i, source=name,
                               reason=f"audio short by {short:.3f}s (> {AUDIO_SILENCE_PAD_MAX}s)")
                    dbg(f"{name} DROP: audio short by {short:.3f}s")
                    continue
                audio_included.append((c, seg_offset))

            dbg("segment start", title=entry["title"],
                core=f"[{a_start:.3f},{a_end:.3f}]", padded=f"[{a_lo:.3f},{a_hi:.3f}]",
                pre=round(pre, 3), post=round(post, 3),
                included=[c[0] for c in video_included] + [c[0] for c, _ in audio_included])
            if pre < PAD_SECONDS - 1e-3 or post < PAD_SECONDS - 1e-3:
                log_status(status="padding_reduced", index=i,
                           pre=round(pre, 3), post=round(post, 3),
                           reason="a source lacks runway; padding shared to keep sync")

            avail = []
            for name, kind, src, offset, src_dur, out_path, clip_key, method_key in video_included:
                lo = max(0.0, a_lo - offset)
                hi = min(src_dur, a_hi - offset)
                # video source names ('a','b','c') match the per-cam dict keys
                entry[method_key] = cut_video_clip(
                    src, lo, hi, str(out_path),
                    audio_copy[name], has_audio[name], vparams[name],
                    args.cut_method, cam_fps[name], label=f"seg{i}/{name}")
                entry[clip_key] = str(out_path.relative_to(outdir))
                entry[clip_key.replace("_clip", "_available")] = True
                avail.append(name)

            for c, seg_offset in audio_included:
                name, kind, src, _global_offset, src_dur, out_path, clip_key, method_key = c
                lo = a_lo - seg_offset
                hi = a_hi - seg_offset
                with log_context(f"seg{i}/{name}"):
                    head_pad, tail_pad = cut_audio_segment_window(src, lo, hi, src_dur, str(out_path))
                    if head_pad > 1e-6 or tail_pad > 1e-6:
                        log_status(status="audio_padded", index=i, source=name,
                                   head_pad=round(head_pad, 3), tail_pad=round(tail_pad, 3))
                        dbg(f"padded silence head={head_pad:.3f}s tail={tail_pad:.3f}s "
                            f"so {name} is kept")
                entry[clip_key] = str(out_path.relative_to(outdir))
                entry[clip_key.replace("_clip", "_available")] = True
                avail.append(name)

            log_status(status="segment_cut", index=i, available=avail)
            dbg("segment done", seg=i, available=avail,
                methods={k: entry[k] for k in ("acam_method", "bcam_method", "ccam_method") if entry[k]},
                secs=round(time.monotonic() - seg_t, 2))
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
            log_status(status="segment_failed", index=i, error=entry["error"])
            dbg("segment FAILED", seg=i, error=entry["error"])
        return entry

    workers = args.workers if args.workers and args.workers > 0 else min(4, os.cpu_count() or 2)
    log_status(status="cutting", cut_method=args.cut_method, workers=workers,
               segments=len(validated), pad_seconds=PAD_SECONDS)
    entries_by_index = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_to_index = {ex.submit(process_segment, i, seg): i
                           for i, seg in enumerate(validated)}
        for fut in as_completed(future_to_index):
            i = future_to_index[fut]
            try:
                entry = fut.result()
            except Exception as exc:
                # process_segment handles its own errors and returns an entry;
                # this only fires for an unexpected raise. Record it as a failed
                # segment rather than aborting the whole export (losing every
                # already-completed clip).
                entry = {"index": i, "error": f"{type(exc).__name__}: {exc}"}
                log_status(status="segment_failed", index=i, error=entry["error"])
            entries_by_index[entry["index"]] = entry
    manifest["segments"] = [entries_by_index[i] for i in sorted(entries_by_index)]
    write_manifest_atomic(manifest_path, manifest)

    if args.skip_validation:
        log_status(status="validation_skipped")
    else:
        _ctx.label = "validate"  # tag the validation-phase log lines (main thread)
        tolerance_s = args.tolerance_frames / float(fps)
        validation = {"tolerance_seconds": round(tolerance_s, 4)}
        try:
            with tempfile.TemporaryDirectory(prefix="multicam-validate-") as tmp:
                has_b = args.bcam is not None
                has_c = args.ccam is not None
                has_l1 = args.lav1 is not None
                has_l2 = args.lav2 is not None

                # One representative cut segment per alt source (A present too).
                b_seg = next((s for s in manifest["segments"]
                              if s["acam_clip"] and s["bcam_clip"]), None) if has_b else None
                c_seg = next((s for s in manifest["segments"]
                              if s["acam_clip"] and s["ccam_clip"]), None) if has_c else None
                l1_seg = next((s for s in manifest["segments"]
                               if s["acam_clip"] and s["lav1_clip"]), None) if has_l1 else None
                l2_seg = next((s for s in manifest["segments"]
                               if s["acam_clip"] and s["lav2_clip"]), None) if has_l2 else None
                all_three = next(
                    (s for s in manifest["segments"]
                     if s["acam_clip"] and s["bcam_clip"] and s["ccam_clip"]),
                    None,
                ) if has_b and has_c else None

                def check(label, seg, clip_key):
                    """Measure one alt source's lag vs A on its representative
                    segment; record it and fail validation if out of tolerance."""
                    lag = measure_clip_lag(str(outdir / seg["acam_clip"]),
                                           str(outdir / seg[clip_key]), tmp)
                    validation[f"{label}_segment_index"] = seg["index"]
                    validation[f"{label}_lag_seconds"] = round(lag, 4)
                    if abs(lag) > tolerance_s:
                        validation["passed"] = False

                if not any([b_seg, c_seg, l1_seg, l2_seg]):
                    validation.update(method="skipped_no_overlap", passed=True)
                else:
                    # Prefer reporting B/C against a shared A+B+C segment when one
                    # exists; lavs are ALWAYS validated regardless of that branch.
                    validation["passed"] = True
                    if all_three:
                        validation["method"] = "all_three"
                        validation["segment_index"] = all_three["index"]
                        a_clip = str(outdir / all_three["acam_clip"])
                        b_lag = measure_clip_lag(a_clip, str(outdir / all_three["bcam_clip"]), tmp)
                        c_lag = measure_clip_lag(a_clip, str(outdir / all_three["ccam_clip"]), tmp)
                        validation["b_lag_seconds"] = round(b_lag, 4)
                        validation["c_lag_seconds"] = round(c_lag, 4)
                        if abs(b_lag) > tolerance_s or abs(c_lag) > tolerance_s:
                            validation["passed"] = False
                    else:
                        validation["method"] = "per_cam"
                        if b_seg:
                            check("b", b_seg, "bcam_clip")
                        if c_seg:
                            check("c", c_seg, "ccam_clip")
                    if l1_seg:
                        check("lav1", l1_seg, "lav1_clip")
                    if l2_seg:
                        check("lav2", l2_seg, "lav2_clip")
        except Exception as exc:
            validation["error"] = f"{type(exc).__name__}: {exc}"
            log_status(status="validation_error", error=validation["error"])

        manifest["validation"] = validation
        write_manifest_atomic(manifest_path, manifest)

        if validation.get("passed") is False:
            log_status(status="validation_failed", validation=validation)
            print(json.dumps({"error": "sync validation exceeded tolerance",
                              "validation": validation}),
                  file=sys.stderr, flush=True)
            sys.exit(2)
        log_status(status="validation_passed", validation=validation)

    if args.zip_out:
        import zipfile
        zip_path = Path(args.zip_out)
        log_status(status="zipping", path=str(zip_path))
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            for f in sorted(outdir.rglob("*")):
                if f.is_file():
                    zf.write(f, arcname=str(f.relative_to(outdir)))
        log_status(status="zipped", path=str(zip_path))

    log_status(status="done", manifest=str(manifest_path))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr, flush=True)
        sys.exit(1)
