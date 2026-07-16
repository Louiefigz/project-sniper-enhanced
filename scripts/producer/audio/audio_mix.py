#!/usr/bin/env python3
"""audio_mix — stage 4: music bed pre-norm + ducking + dual with/without masters.

The music stage of the PRODUCER renderer (docs/producer/PRODUCER_PLAN.md §4.2 stage 4 and
§7 "Music"). It runs on the FINAL master (dialogue already two-pass loudnormed to
-14 LUFS by master.py) and lays a music bed under it:

1. **Bed pre-normalization (edge M3)** — measure the library track's integrated
   loudness and gain it to a consistent internal reference so wild-loudness tracks
   mix predictably. The reference is dialogue-relative: ``dialogue_LUFS - gap_dB``
   (``AUDIO.music_gap_db`` midpoint), so the bed sits ~gap_dB under speech AT REST
   before any ducking. Falls back to a fixed ``lufs_target - gap_dB`` if the
   dialogue is silent/unmeasurable.
2. **Length fit** — track shorter than the video is LOOPED with an equal-power
   (qsin) crossfade at the seam (edge M1); longer is TRIMMED with a fade-out
   ending at the video end (edge M2). Both variants get an end fade-out (§7).
3. **Ducking** — ``sidechaincompress`` keyed off the dialogue reduces the bed
   further while speech is present, so it lands ~``AUDIO.music_duck_db`` under
   voice and recovers toward ``AUDIO.music_gap_db`` in gaps. The compressor knobs
   are documented STARTING POINTS for operator tuning; the ACHIEVED duck depth is
   MEASURED off the bed stem and reported (never assumed).
4. **Mix + master** — dialogue + ducked bed summed to one stereo bus, then a
   two-pass loudnorm to ``AUDIO.lufs_target`` at ``AUDIO.loudnorm_tp_param``
   (mirrors master.py: loudnorm's linear limiter overshoots its TP param by
   ~0.1-0.2 dB, so it targets -2.0 to land under the -1.5 dBTP
   ``AUDIO.true_peak_dbtp`` delivery ceiling — edge C13). The VIDEO STREAM IS
   COPIED (``-c:v copy``) — the video was encoded
   once by master.py; this stage only re-encodes audio. ``--also-without`` remuxes
   the input untouched (video + original dialogue) so both variants exist at
   mux-only cost (§7 "video encodes once, muxes twice").

Because both variants copy the same input video stream, their video is
bit-identical to the input and to each other.

Bed shaping (pre-norm M3, length fit M1/M2) lives in ``audio_mix_bed.py``; this
module owns ducking, mixing, mastering, measurement, and the CLI. The stage
materializes its bed intermediates (bed_base / period / bed_fit / bed_ducked
WAVs, float PCM to avoid pre-norm clipping) in a work dir — resumable and
independently verifiable per the staged-render doctrine (§4.2). Pass
``--work-dir DIR`` to keep them for inspection; otherwise a temp dir is used and
cleaned.

CLI: audio_mix.py <video_in> <music_track> <out_with_music.mp4>
                  [--also-without out_no_music.mp4] [--work-dir DIR]

Reuses master.py's public ``measure_integrated_lufs`` / ``has_audio`` and
``producer_config`` (AUDIO, ENCODE). It does not edit or depend on master's
private helpers; the two-pass loudnorm builder here mirrors master's approach
(they cannot share code without editing master, which this stage must not do).
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from producer_config import AUDIO, ENCODE
from audio.master import has_audio, measure_integrated_lufs
from audio.audio_mix_bed import (AFMT, FLOAT_WAV, fit_length, prep_bed,
                                 probe_video_duration, run as _run)

_JSON_RE = re.compile(r"\{[^{}]*\}", re.S)

# --- Ducking knobs -----------------------------------------------------------
# STARTING POINTS for operator tuning. These are graph-level compressor knobs,
# deliberately NOT in producer_config (which holds editorial targets). The
# editorial targets are AUDIO.music_duck_db / music_gap_db, realized by two
# levers: (a) pre-normalizing the bed to (dialogue_LUFS - gap_dB) so it sits ~gap_dB
# under speech at rest, and (b) this compressor adding the ~(duck_dB - gap_dB) ≈
# 6-10 dB extra reduction while speech is present. Depth is MEASURED off the bed
# stem and reported; these values were tuned on real -14 LUFS speech (Samantha TTS)
# to land ~8-9 dB additional duck → bed ~18-20 dB under dialogue during speech and
# ~11 dB under in gaps, matching AUDIO.music_duck_db / music_gap_db. Re-tune per
# voice/material — depth is program-dependent (that is why we measure, not assume).
DUCK = {
    "threshold": 0.06,    # ~ -24 dBFS linear: speech RMS clears it; room tone/gaps sit below
    "ratio": 2.5,         # gentle: additional reduction lands ~8-9 dB, not a hard gate
    "attack": 8.0,        # ms: duck by the first syllable without an audible pre-swell/click
    "release": 300.0,     # ms: recover in gaps >= ~0.8s; hold through inter-word gaps (no pumping)
    "makeup": 1.0,        # 1 = no makeup gain — do NOT re-inflate the ducked bed
    "knee": 2.82843,      # ffmpeg default soft knee
    "detection": "rms",   # track speech energy, not transient peaks (less jittery ducking)
    "link": "average",
}
SILENCE_NOISE_DB = -30    # silencedetect floor for the duck-depth gap finder (tunable)
SILENCE_MIN_S = 0.6       # shortest silence that counts as a measurable gap
MEASURE_WIN_S = 0.6       # duck-depth measurement window length

_MIX = (f"[0:a]{AFMT}[d];[1:a]{AFMT}[b];"
        "[d][b]amix=inputs=2:duration=first:normalize=0[mix]")


@dataclass
class MixSpec:
    """One music-mix job (kept to <=4 CLI-facing knobs via a dataclass).

    ``duck`` / ``gap_db`` are the plan.music knobs (assemble-time contract):
    ``duck=False`` is legal only when the video has no existing audio. Dialogue
    programs always sidechain: a rest-level gap alone cannot guarantee that a
    quiet phrase stays above music. ``gap_db`` overrides the configured
    bed-below-dialogue rest level.
    """

    video_in: str
    music: str
    out_with: str
    out_without: Optional[str] = None
    work_dir: Optional[str] = None
    duck: bool = True
    gap_db: Optional[float] = None


@dataclass
class _Ctx:
    """Runtime context threaded through the pipeline (keeps arg counts <=4)."""

    spec: MixSpec
    video_dur: float
    dialogue: bool
    work: str
    warnings: list = field(default_factory=list)


def emit(event: str, **fields) -> None:
    """Emit one NDJSON status line to stdout (worker convention)."""
    print(json.dumps({"event": event, **fields}, default=str), flush=True)


def _finite(value: object) -> Optional[float]:
    """Parse a loudnorm stat to a finite float, or None (silent/degenerate)."""
    try:
        num = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def _parse_loudnorm_json(stderr: str) -> Optional[dict]:
    """Last valid loudnorm JSON block in ffmpeg stderr (mirrors master.py)."""
    for block in reversed(_JSON_RE.findall(stderr)):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if "input_i" in data:
            return data
    return None


def duck_bed(video_in: str, bed_fit_wav: str, out_wav: str) -> dict:
    """Sidechain-duck the bed under the dialogue (input 0) → bed stem (out_wav)."""
    fc = (f"[1:a]{AFMT}[bed];[0:a]{AFMT}[key];"
          f"[bed][key]sidechaincompress="
          f"threshold={DUCK['threshold']}:ratio={DUCK['ratio']}:attack={DUCK['attack']}"
          f":release={DUCK['release']}:makeup={DUCK['makeup']}:knee={DUCK['knee']}"
          f":detection={DUCK['detection']}:link={DUCK['link']}[ducked]")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", video_in, "-i", bed_fit_wav,
           "-filter_complex", fc, "-map", "[ducked]", *FLOAT_WAV, out_wav]
    res = _run(cmd)
    ok = res.returncode == 0 and os.path.exists(out_wav)
    return {"ok": ok, "stderr": "" if ok else res.stderr[-600:]}


def _silence_gaps(video_in: str) -> list[tuple[float, float]]:
    """Dialogue silence intervals (start, end) via ffmpeg silencedetect."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", video_in, "-map", "0:a:0",
           "-af", f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_S}",
           "-f", "null", "-"]
    err = _run(cmd).stderr
    starts = [float(m) for m in re.findall(r"silence_start:\s*(-?\d+(?:\.\d+)?)", err)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*(-?\d+(?:\.\d+)?)", err)]
    return [(s, e) for s, e in zip(starts, ends) if e > s]


def _window_mean_db(path: str, start: float, dur: float) -> Optional[float]:
    """Mean volume (dBFS, an RMS proxy) of ``path`` over [start, start+dur)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
           "-i", path, "-af", "volumedetect", "-f", "null", "-"]
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", _run(cmd).stderr)
    return float(m.group(1)) if m else None


def measure_duck_depth(video_in: str, bed_ducked_wav: str) -> dict:
    """Achieved duck depth = bed level in a speech gap minus during speech.

    Measured on the BED STEM (dialogue-free) so the delta reflects the bed alone,
    not the mix. Best-effort: needs at least one detectable silence gap in the
    dialogue; reports ``measured: False`` with a reason otherwise. The window
    levels are ``volumedetect`` mean volume (an RMS proxy), so read the depth as
    a solid estimate, not a lab-grade figure.
    """
    gaps = _silence_gaps(video_in)
    if not gaps:
        return {"measured": False, "reason": "no silence gap detected in dialogue"}
    gs, ge = max(gaps, key=lambda g: g[1] - g[0])
    gap_win = max(0.0, (gs + ge) / 2 - MEASURE_WIN_S / 2)
    speech_win = max(0.0, min(g[0] for g in gaps) - MEASURE_WIN_S - 0.1)
    gap_db = _window_mean_db(bed_ducked_wav, gap_win, MEASURE_WIN_S)
    speech_db = _window_mean_db(bed_ducked_wav, speech_win, MEASURE_WIN_S)
    if gap_db is None or speech_db is None:
        return {"measured": False, "reason": "window volume measurement failed"}
    return {"measured": True, "gap_win_s": round(gap_win, 3),
            "speech_win_s": round(speech_win, 3), "bed_gap_db": round(gap_db, 2),
            "bed_speech_db": round(speech_db, 2), "duck_depth_db": round(gap_db - speech_db, 2)}


def _final_loudnorm(measured: Optional[dict]) -> tuple[str, bool]:
    """Build the pass-2 loudnorm filter (linear if stats finite). Mirrors master.py."""
    base = (f"loudnorm=I={AUDIO['lufs_target']}:TP={AUDIO['loudnorm_tp_param']}"
            f":LRA={AUDIO['lra']}")
    stats = None if measured is None else {
        "measured_I": _finite(measured.get("input_i")),
        "measured_TP": _finite(measured.get("input_tp")),
        "measured_LRA": _finite(measured.get("input_lra")),
        "measured_thresh": _finite(measured.get("input_thresh")),
        "offset": _finite(measured.get("target_offset")),
    }
    if not stats or any(v is None for v in stats.values()):
        return base, False
    part = ":".join(f"{k}={v}" for k, v in stats.items())
    return f"{base}:{part}:linear=true", True


def _measure_mix(video_in: str, bed_ducked_wav: str,
                 video_dur: float) -> Optional[dict]:
    """Pass 1: measure the summed (dialogue + bed) mix loudness for linear pass 2."""
    fc = (f"{_MIX};[mix]atrim=0:{video_dur:.6f},asetpts=PTS-STARTPTS,"
          f"loudnorm=I={AUDIO['lufs_target']}:TP={AUDIO['loudnorm_tp_param']}"
          f":LRA={AUDIO['lra']}:print_format=json[out]")
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", video_in, "-i", bed_ducked_wav,
           "-filter_complex", fc, "-map", "[out]", "-f", "null", "-"]
    return _parse_loudnorm_json(_run(cmd).stderr)


def mix_master(video_in: str, bed_ducked_wav: str, out_path: str,
               video_dur: float) -> dict:
    """Sum dialogue + ducked bed → two-pass loudnorm → AAC; copy the video stream."""
    measured = _measure_mix(video_in, bed_ducked_wav, video_dur)
    afilter, linear = _final_loudnorm(measured)
    fc = (f"{_MIX};[mix]atrim=0:{video_dur:.6f},asetpts=PTS-STARTPTS,"
          f"{afilter}[aout]")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", video_in, "-i", bed_ducked_wav,
           "-filter_complex", fc, "-map", "0:v:0", "-c:v", "copy", "-map", "[aout]",
           "-c:a", ENCODE["acodec"], "-b:a", ENCODE["audio_bitrate"],
           "-ar", str(ENCODE["audio_rate"]), "-ac", str(ENCODE["audio_channels"]),
           "-t", f"{video_dur:.6f}", "-movflags", ENCODE["movflags"], out_path]
    res = _run(cmd)
    ok = res.returncode == 0 and os.path.exists(out_path)
    return {"ok": ok, "linear": linear, "stderr": "" if ok else res.stderr[-800:]}


def remux_without(video_in: str, out_path: str) -> dict:
    """Copy-remux the input untouched (video + original dialogue) — mux-only cost."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", video_in,
           "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
           "-movflags", ENCODE["movflags"], out_path]
    res = _run(cmd)
    ok = res.returncode == 0 and os.path.exists(out_path)
    return {"ok": ok, "stderr": "" if ok else res.stderr[-500:]}


def _bed_target_lufs(ctx: _Ctx) -> tuple[float, Optional[float]]:
    """Bed reference = dialogue_LUFS - gap_dB (fixed target-relative if silent).

    ``spec.gap_db`` (plan.music.gapDb) overrides the config midpoint."""
    d_lufs = measure_integrated_lufs(ctx.spec.video_in) if ctx.dialogue else None
    gap_db = (ctx.spec.gap_db if ctx.spec.gap_db is not None
              else sum(AUDIO["music_gap_db"]) / 2.0)
    ref = (d_lufs - gap_db) if d_lufs is not None else (AUDIO["lufs_target"] - gap_db)
    return ref, d_lufs


def _pipeline(ctx: _Ctx) -> dict:
    """Prep → fit → duck → mix/master, emitting a status line per stage."""
    target, d_lufs = _bed_target_lufs(ctx)
    base = os.path.join(ctx.work, "bed_base.wav")
    prep = prep_bed(ctx.spec.music, target, base)
    emit("bed_prep", ok=prep["ok"], measured_lufs=prep["measured_lufs"],
         target_lufs=prep["target_lufs"], gain_db=prep["gain_db"])
    if not prep["ok"]:
        return {"status": "error", "error": "bed prep failed", "detail": prep["stderr"]}
    fit = os.path.join(ctx.work, "bed_fit.wav")
    fitr = fit_length(base, ctx.video_dur, fit)
    emit("bed_fit", **fitr)
    if not fitr["ok"]:
        return {"status": "error", "error": "length fit failed", "detail": fitr}
    ducked, depth = _make_bed_stem(ctx, fit)
    if ducked is None:
        return {"status": "error", "error": "ducking failed", "detail": depth}
    mm = mix_master(ctx.spec.video_in, ducked, ctx.spec.out_with, ctx.video_dur)
    emit("mix_master", ok=mm["ok"], linear=mm["linear"])
    if not mm["ok"]:
        return {"status": "error", "error": "mix/master failed", "detail": mm["stderr"]}
    if not mm["linear"]:
        ctx.warnings.append("final loudnorm fell back to dynamic (mix stats non-finite)")
    return _finalize(ctx, prep, fitr, depth)


def _make_bed_stem(ctx: _Ctx, fit: str) -> tuple[Optional[str], dict]:
    """Produce the ducked bed stem + its measured duck depth (bypass if no dialogue)."""
    ducked = os.path.join(ctx.work, "bed_ducked.wav")
    if not ctx.dialogue:
        shutil.copyfile(fit, ducked)
        return ducked, {"measured": False, "reason": "input has no dialogue to key ducking"}
    if not ctx.spec.duck:
        shutil.copyfile(fit, ducked)
        return ducked, {"measured": False, "reason": "ducking disabled (music.duck=false)"}
    dr = duck_bed(ctx.spec.video_in, fit, ducked)
    emit("duck", ok=dr["ok"])
    if not dr["ok"]:
        return None, dr["stderr"]
    depth = measure_duck_depth(ctx.spec.video_in, ducked)
    emit("duck_depth", **depth)
    return ducked, depth


def _finalize(ctx: _Ctx, prep: dict, fitr: dict, depth: dict) -> dict:
    """Verify the with-music LUFS, optionally remux the without variant, summarize."""
    spec = ctx.spec
    final_lufs = measure_integrated_lufs(spec.out_with)
    within = (final_lufs is not None
              and abs(final_lufs - AUDIO["lufs_target"]) <= AUDIO["lufs_tolerance"])
    if not within:
        ctx.warnings.append(f"with-music LUFS {final_lufs} outside "
                            f"{AUDIO['lufs_target']}+/-{AUDIO['lufs_tolerance']}")
    without = None
    if spec.out_without:
        rw = remux_without(spec.video_in, spec.out_without)
        emit("remux_without", ok=rw["ok"])
        without = spec.out_without if rw["ok"] else None
        if not rw["ok"]:
            ctx.warnings.append("without-music remux failed")
    return {
        "status": "done",
        "with_music": spec.out_with,
        "without_music": without,
        "video_dur_s": round(ctx.video_dur, 3),
        "bed_measured_lufs": prep["measured_lufs"],
        "bed_target_lufs": prep["target_lufs"],
        "bed_gain_db": prep["gain_db"],
        "length_fit": fitr,
        "duck_depth": depth,
        "final_lufs": final_lufs,
        "lufs_within_tolerance": within,
        "work_dir": ctx.work,
        "warnings": ctx.warnings,
    }


def _work_dir(requested: Optional[str]) -> tuple[str, bool]:
    """(path, cleanup): a given dir persists for inspection; a temp dir is cleaned."""
    if requested:
        os.makedirs(requested, exist_ok=True)
        return requested, False
    return tempfile.mkdtemp(prefix="producer-audiomix-"), True


def run_audio_mix(spec: MixSpec) -> dict:
    """Validate inputs, run the pipeline in a work dir, return the status dict."""
    if not has_audio(spec.music):
        return {"status": "error", "error": "music track has no audio stream"}
    video_dur = probe_video_duration(spec.video_in)
    if not video_dur:
        return {"status": "error", "error": "could not probe video duration"}
    dialogue = has_audio(spec.video_in)
    if dialogue and not spec.duck:
        return {"status": "error", "error":
                "music ducking cannot be disabled when dialogue is present"}
    warnings: list = []
    if not dialogue:
        warnings.append("input has no audio track — bed becomes the sole audio; ducking skipped")
    work, cleanup = _work_dir(spec.work_dir)
    ctx = _Ctx(spec=spec, video_dur=video_dur, dialogue=dialogue, work=work, warnings=warnings)
    try:
        return _pipeline(ctx)
    finally:
        if cleanup:
            shutil.rmtree(work, ignore_errors=True)


def _pop_opt(args: list[str], flag: str) -> Optional[str]:
    """Pull ``--flag VALUE`` out of ``args`` in place, returning VALUE (or None)."""
    if flag not in args:
        return None
    idx = args.index(flag)
    value = args[idx + 1] if idx + 1 < len(args) else None
    del args[idx:idx + 2]
    return value


def main() -> None:
    args = sys.argv[1:]
    out_without = _pop_opt(args, "--also-without")
    work_dir = _pop_opt(args, "--work-dir")
    gap_db = _pop_opt(args, "--gap-db")
    duck = "--no-duck" not in args
    if not duck:
        args.remove("--no-duck")
    if len(args) != 3:
        emit("error", error="Usage: audio_mix.py <video_in> <music_track> "
             "<out_with_music.mp4> [--also-without out.mp4] [--work-dir DIR] "
             "[--no-duck] [--gap-db N]")
        sys.exit(1)
    spec = MixSpec(video_in=args[0], music=args[1], out_with=args[2],
                   out_without=out_without, work_dir=work_dir,
                   duck=duck, gap_db=float(gap_db) if gap_db else None)
    status = run_audio_mix(spec)
    emit("result", **status)
    sys.exit(0 if status.get("status") == "done" else 1)


if __name__ == "__main__":
    main()
