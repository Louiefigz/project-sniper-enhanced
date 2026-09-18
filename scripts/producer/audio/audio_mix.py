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

Reuses master.py's public mastering dispatch and supplies a measurement callback
for the exact float sum, so static-gain dry runs include both program and bed.
The optional without-music variant is a delivery copy, not a raw stem export:
an over-range program must be mastered before that copy can be requested.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field, replace
from functools import partial
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from producer_config import AUDIO, ENCODE, AUDIO_MIX_POLICY_VERSION
from audio.master import (
    MASTERING_POLICY_VERSION, build_pass2_afilter, has_audio, measure_integrated_lufs,
)
from audio.channel_normalization import (
    ChannelNormalizationError,
    observe_channel_authority,
    system_program_request,
)
from audio.channel_normalization_media import materialize_normalized_program
from audio.audio_mix_delivery import render_qualified_mix
from audio.audio_mix_picture import (
    PictureSource, assert_picture_stable, observe_picture_source, verify_picture_copy,
)
from audio.audio_mix_without import (
    WithoutDeliveryPlan, prepare_without_delivery, render_without_delivery,
)
from audio.audio_mix_bed import (AFMT, FLOAT_WAV, fit_length, prep_bed, float_pcm_samples,
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
    delivery: dict = field(default_factory=dict)
    without_plan: Optional[WithoutDeliveryPlan] = None
    picture: Optional[PictureSource] = None


@dataclass(frozen=True)
class MixMasterJob:
    """Separate float audio inputs from the original coded-picture authority."""

    video_in: str
    bed_path: str
    out_path: str
    duration: float
    picture: PictureSource


def emit(event: str, **fields) -> None:
    """Emit one NDJSON status line to stdout (worker convention)."""
    print(json.dumps({"event": event, **fields}, default=str), flush=True)


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


def duck_bed(video_in: str, bed_fit_wav: str, out_wav: str,
             samples: int | None = None) -> dict:
    """Sidechain-duck the bed under the dialogue (input 0) → bed stem (out_wav)."""
    bed_samples = float_pcm_samples(bed_fit_wav)
    samples = bed_samples if samples is None else samples
    if type(samples) is not int or samples <= 0:
        raise ValueError("exact ducking requires positive integer samples")
    if bed_samples != samples:
        raise ValueError("exact ducking bed does not cover its requested sample clock")
    framing = f",atrim=end_sample={samples},asetpts=N/SR/TB,asetnsamples=n=1024:p=1"
    # The key is an inaudible detector. Zero-fill after its genuine EOF so the
    # compressor can release over a longer bed; never pad the ducked output.
    fc = (f"[1:a]{AFMT}{framing}[bed];"
          f"[0:a]{AFMT},apad=whole_len={samples}{framing}[key];"
          f"[bed][key]sidechaincompress="
          f"threshold={DUCK['threshold']}:ratio={DUCK['ratio']}:attack={DUCK['attack']}"
          f":release={DUCK['release']}:makeup={DUCK['makeup']}:knee={DUCK['knee']}"
          f":detection={DUCK['detection']}:link={DUCK['link']}[ducked-full]"
          f";[ducked-full]atrim=end_sample={samples},asetpts=PTS-STARTPTS[ducked]")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-xerror", "-err_detect", "explode", "-i", video_in, "-i", bed_fit_wav,
           "-filter_complex", fc, "-map", "[ducked]", *FLOAT_WAV, out_wav]
    res = _run(cmd)
    ok = res.returncode == 0 and os.path.exists(out_wav)
    if ok and float_pcm_samples(out_wav) != samples:
        return {"ok": False, "stderr": "ducked bed did not preserve every fitted input sample"}
    return {"ok": ok, "stderr": "" if ok else res.stderr[-600:],
            "samples": samples, "audioMixPolicyVersion": AUDIO_MIX_POLICY_VERSION}


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


def _measure_mix_chain_lufs(video_in: str, bed_path: str,
                            video_dur: float, chain: str) -> Optional[float]:
    """Measure master's gain/limiter dry run on the same unquantized full sum."""
    graph = (f"{_MIX};[mix]atrim=0:{video_dur:.6f},asetpts=PTS-STARTPTS,"
             f"{chain},ebur128=peak=true[out]")
    command = ["ffmpeg", "-hide_banner", "-nostats", "-i", video_in,
               "-i", bed_path, "-filter_complex", graph, "-map", "[out]",
               "-f", "null", "-"]
    result = _run(command)
    values = re.findall(r"\bI:\s*(-?\d+(?:\.\d+)?)\s*LUFS", result.stderr)
    return float(values[-1]) if result.returncode == 0 and values else None


def _measure_mix(video_in: str, bed_ducked_wav: str,
                 video_dur: float) -> Optional[dict]:
    """Pass 1: measure the summed (dialogue + bed) mix loudness for linear pass 2."""
    fc = (f"{_MIX};[mix]atrim=0:{video_dur:.6f},asetpts=PTS-STARTPTS,"
          f"loudnorm=I={AUDIO['lufs_target']}:TP={AUDIO['loudnorm_tp_param']}"
          f":LRA={AUDIO['lra']}:print_format=json[out]")
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", video_in, "-i", bed_ducked_wav,
           "-filter_complex", fc, "-map", "[out]", "-f", "null", "-"]
    return _parse_loudnorm_json(_run(cmd).stderr)


def _render_mix_master(job: MixMasterJob, out_path: str) -> dict:
    """Sum dialogue + ducked bed → two-pass loudnorm → AAC; copy the video stream."""
    video_in, bed_ducked_wav, video_dur = job.video_in, job.bed_path, job.duration
    try:
        assert_picture_stable(job.picture)
    except ChannelNormalizationError as exc:
        return _mix_failure(str(exc))
    measured = _measure_mix(video_in, bed_ducked_wav, video_dur)
    afilter, note = build_pass2_afilter(
        video_in, None, measured,
        partial(_measure_mix_chain_lufs, video_in, bed_ducked_wav, video_dur))
    fc = (f"{_MIX};[mix]atrim=0:{video_dur:.6f},asetpts=PTS-STARTPTS,"
          f"{afilter}[aout]")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", video_in, "-i", bed_ducked_wav]
    picture_index = 0
    if job.picture.path != video_in:
        cmd += ["-i", job.picture.path]
        picture_index = 2
    cmd += ["-filter_complex", fc, "-map", f"{picture_index}:v:0", "-c:v", "copy", "-map", "[aout]",
           "-c:a", ENCODE["acodec"], "-b:a", ENCODE["audio_bitrate"],
           "-ar", str(ENCODE["audio_rate"]), "-ac", str(ENCODE["audio_channels"]),
           "-t", f"{video_dur:.6f}", "-video_track_timescale", str(job.picture.time_base.denominator),
           "-movflags", ENCODE["movflags"], out_path]
    res = _run(cmd)
    ok = res.returncode == 0 and os.path.exists(out_path)
    try:
        picture_proof = verify_picture_copy(job.picture, out_path) if ok else None
    except ChannelNormalizationError as exc:
        return _mix_failure(str(exc))
    return {"ok": ok, "linear": note is None, "mastering_note": note,
            "mastering_policy_version": MASTERING_POLICY_VERSION,
            "picture": picture_proof,
            "stderr": "" if ok else res.stderr[-800:]}


def _mix_failure(detail: str) -> dict:
    """Return failed picture authority through the retained-candidate contract."""
    return {"ok": False, "linear": False, "mastering_note": None,
            "mastering_policy_version": MASTERING_POLICY_VERSION, "stderr": detail}


def mix_master(video_in: str, bed_ducked_wav: str, out_path: str,
               video_dur: float) -> dict:
    """Render privately; only replace delivery after whole-output LUFS/TP pass."""
    picture = observe_picture_source(video_in, video_dur)
    return _publish_mix(MixMasterJob(video_in, bed_ducked_wav, out_path, video_dur, picture))


def _publish_mix(job: MixMasterJob) -> dict:
    """Bind original picture verification to the isolated AAC candidate render."""
    return render_qualified_mix(job.out_path, lambda candidate: _render_mix_master(job, candidate))


def remux_without(video_in: str, out_path: str) -> dict:
    """Deliver compatible AAC; retain original AAC only when verified safe."""
    try:
        authority = observe_channel_authority(system_program_request(video_in))
        duration = probe_video_duration(video_in)
        if not duration:
            return {"ok": False, "stderr": "without-music picture duration is unproved"}
        with tempfile.TemporaryDirectory(prefix="without-normalized-") as directory:
            normalized = os.path.join(directory, "program.mkv")
            materialize_normalized_program(authority, normalized)
            plan = prepare_without_delivery(authority, normalized, duration)
            return render_without_delivery(plan, out_path)
    except ChannelNormalizationError as exc:
        return {"ok": False, "stderr": str(exc)}


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
    if ctx.picture is None:
        return {"status": "error", "error": "original picture authority is missing"}
    mm = _publish_mix(MixMasterJob(
        ctx.spec.video_in, ducked, ctx.spec.out_with, ctx.video_dur, ctx.picture))
    emit("mix_master", ok=mm["ok"], linear=mm["linear"])
    if not mm["ok"]:
        return {"status": "error", "error": "mix/master failed", "detail": mm["stderr"],
                "unapproved_candidate": mm.get("unapprovedCandidate"),
                "delivery": mm.get("delivery")}
    if mm["mastering_note"]:
        ctx.warnings.append(mm["mastering_note"])
    ctx.delivery = mm["delivery"]
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
    final_lufs = ctx.delivery["integratedLufs"]
    within = ctx.delivery["lufsWithinTolerance"]
    without = None
    without_result = None
    if spec.out_without:
        if ctx.without_plan is None:
            return {"status": "error", "error": "without-music preflight plan is missing",
                    "with_music": spec.out_with, "without_music": None}
        rw = render_without_delivery(ctx.without_plan, spec.out_without)
        without_result = rw
        emit("remux_without", ok=rw["ok"])
        without = spec.out_without if rw["ok"] else None
        if not rw["ok"]:
            return {"status": "error", "error": "requested without-music variant failed",
                    "detail": rw["stderr"], "with_music": spec.out_with,
                    "without_music": None, "without_delivery": rw}
    return {
        "status": "done",
        "with_music": spec.out_with,
        "without_music": without,
        "without_delivery": without_result,
        "video_dur_s": round(ctx.video_dur, 3),
        "bed_measured_lufs": prep["measured_lufs"],
        "bed_target_lufs": prep["target_lufs"],
        "bed_gain_db": prep["gain_db"],
        "length_fit": fitr,
        "duck_depth": depth,
        "final_lufs": final_lufs,
        "lufs_within_tolerance": within,
        "mastering_policy_version": MASTERING_POLICY_VERSION,
        "audio_mix_policy_version": AUDIO_MIX_POLICY_VERSION,
        "final_true_peak_dbtp": ctx.delivery["truePeakDbtp"],
        "delivery": ctx.delivery,
        "work_dir": ctx.work,
        "warnings": ctx.warnings,
    }


def _work_dir(requested: Optional[str]) -> tuple[str, bool]:
    """(path, cleanup): a given dir persists for inspection; a temp dir is cleaned."""
    if requested:
        os.makedirs(requested, exist_ok=True)
        return requested, False
    return tempfile.mkdtemp(prefix="producer-audiomix-"), True


def _normalize_context(ctx: _Ctx) -> Optional[dict]:
    """Keep picture authority original while replacing only the program audio leg."""
    if not ctx.dialogue:
        ctx.picture = observe_picture_source(ctx.spec.video_in, ctx.video_dur)
        return None
    authority = observe_channel_authority(system_program_request(ctx.spec.video_in))
    ctx.picture = observe_picture_source(
        ctx.spec.video_in, ctx.video_dur, authority.request.source_sha256)
    normalized_dir = tempfile.mkdtemp(prefix="channel-normalization-", dir=ctx.work)
    normalized = os.path.join(normalized_dir, "program.mkv")
    materialized = materialize_normalized_program(authority, normalized)
    if ctx.spec.out_without:
        ctx.without_plan = prepare_without_delivery(authority, normalized, ctx.video_dur)
    ctx.spec = replace(ctx.spec, video_in=normalized)
    return {"receipt": authority.receipt, "materialization": materialized}


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
    try:
        ctx = _Ctx(
            spec=spec, video_dur=video_dur, dialogue=dialogue,
            work=work, warnings=warnings)
        normalization = _normalize_context(ctx)
        if spec.out_without and ctx.without_plan is None:
            return {"status": "error", "error": "without-music program audio is absent"}
        result = _pipeline(ctx)
        if normalization is not None:
            result["channel_normalization"] = normalization
        return result
    except ChannelNormalizationError as exc:
        return {"status": "error", "error":
                f"program channel normalization or delivery preflight failed: {exc}",
                "detail": str(exc), "with_music": None, "without_music": None}
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
