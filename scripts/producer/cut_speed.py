#!/usr/bin/env python3
"""cut_speed — stage 1 of the PRODUCER renderer: cut + speed + normalize.

Consumes a compiled ``edit_plan`` (via :func:`compile_timeline.compile_plan`)
plus an ``asset_manifest`` (sourceId -> file path) and produces one mezzanine
MP4: every kept range is extracted frame-accurately from its source, re-timed by
its per-range ``speed`` (video ``setpts``, audio ``atempo`` — the SAME factor, so
A/V never drift), normalized to ONE common profile (resolution, CFR fps, 48 kHz
stereo) and concatenated. Near-lossless x264 (CRF 12) so later stages (reframe,
captions, master) re-encode from a clean intermediate.

Frame-accuracy: a fast input-side ``-ss`` lands a keyframe ahead of the range,
then an in-filter ``trim`` selects the exact window on the (input-seek-rebased)
timeline before ``setpts`` applies the speed — re-encoded throughout, so the
stream-copy truncation caveat that bites ``export_mp4.py`` does not apply here.

J-CUT LEADS (LIAM-4-MOVES move 2, additive): a cutTrack range may carry
``audioLeadMs`` — the incoming segment's audio PRE-ROLL (source audio from
before its in-point) starts that early, so sound leads picture at the seam.
Architecture: the lead is baked into the OUTGOING part's audio TAIL (own
audio gives up its last ``lead_s`` output-seconds; the next segment's
``[src_start − lead·speed, src_start]`` source audio fills them, atempo'd
and 15 ms edge-declicked) — every part keeps audio == video length EXACTLY,
so the concat demuxer contract and the stage-1 duration assertion are
untouched, and the incoming segment's own audio starts at its in-point in
perfect A/V sync (measured: the concat demuxer offsets whole FILES, so
unequal part lengths would desync — never do it that way). Bounds validated
by ``compile_timeline.parse_audio_lead`` (``AUDIO["jcut"]``).

The output duration is asserted against the compiler's prediction within a tight
frame tolerance — the stage-1 backstop against speed-math / drift bugs
(PRODUCER_PLAN §4.2, §8 "Render").

CLI:
    cut_speed.py <edit_plan.json> <asset_manifest.json> <out_mezzanine.mp4> [--workdir DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from compile_timeline import Segment, compile_plan  # noqa: E402
# Probe primitives live in media_probe (this file's 300-line budget); the
# re-import keeps every historical `cut_speed.<probe>` import path working.
from media_probe import (display_dims, has_audio, probe_duration,  # noqa: E402,F401
                         probe_video, probe_video_frames, run_ff, _fps_fraction)
from producer_config import AUDIO, ENCODE  # noqa: E402

# Fast input-seek lands a keyframe at-or-before (src_start - this); the decoder
# then rolls forward and the in-filter trim discards up to the exact boundary.
PRESEEK_PAD_S = 10.0
AUDIO_RATE = ENCODE["audio_rate"]        # 48000
AUDIO_CH = ENCODE["audio_channels"]      # 2
# Stage-1 duration assertion (frames). We assert on the VIDEO timeline
# (frame_count / fps), not the container duration — MP4 format duration is
# inflated by AAC encoder padding (~1 frame), which is a muxing artifact, not a
# timeline error. Each CFR segment can legitimately round by up to ~half a frame
# when it is quantized to the profile grid, so the tolerance grows with segment
# count. A genuine speed-math bug (a wrong atempo/setpts factor) drifts by whole
# percent of the runtime — orders of magnitude past this — so the gross-error
# backstop stays sharp. See PRODUCER_PLAN §4.2 / §8.
DURATION_TOL_BASE_FRAMES = 1.0
DURATION_TOL_PER_SEGMENT_FRAMES = 0.5


def emit(**fields) -> None:
    """One JSON status object per line on stdout (NDJSON, like the sibling stages)."""
    print(json.dumps(fields), flush=True)


@dataclass(frozen=True)
class Profile:
    """Common target every segment is normalized to (from the first source)."""

    width: int
    height: int
    fps: Fraction
    pix_fmt: str

    @property
    def fps_arg(self) -> str:
        """ffmpeg rational fps string, e.g. ``30000/1001``."""
        return f"{self.fps.numerator}/{self.fps.denominator}"

    @property
    def frame_s(self) -> float:
        """Duration of one frame in seconds."""
        return 1.0 / float(self.fps)


def decide_profile(first_source_path: str) -> Profile:
    """Phase-1 rule: the FIRST source defines the common profile; every other
    source is scaled + letterbox-padded to fit it (PRODUCER_PLAN §6)."""
    v = probe_video(first_source_path)
    width, height = display_dims(v)
    return Profile(width=width, height=height,
                   fps=_fps_fraction(v["r_frame_rate"]),
                   pix_fmt=v.get("pix_fmt") or ENCODE["pix_fmt"])


def proxy_profile(profile: Profile, scale: float) -> Profile:
    """The DOWNSCALED proxy variant of a profile (geometry contract v3 A1).

    Only the canvas shrinks (even-snapped); fps and pix_fmt are untouched, so
    every downstream trim/setpts/atempo/fps term — the segment math — runs
    bit-identically to the full render, just onto smaller frames.

    Args:
        profile: The full-resolution common profile.
        scale: Downscale factor in (0, 1].

    Returns:
        The proxy Profile.

    Raises:
        ValueError: On a scale outside (0, 1].
    """
    if not 0.0 < scale <= 1.0:
        raise ValueError(f"proxy scale {scale} outside (0, 1]")
    width = max(2, int(round(profile.width * scale / 2.0)) * 2)
    height = max(2, int(round(profile.height * scale / 2.0)) * 2)
    return Profile(width=width, height=height, fps=profile.fps,
                   pix_fmt=profile.pix_fmt)


def _video_chain(seg: Segment, pre_seek: float, profile: Profile) -> str:
    """Trim the exact source window, apply speed, scale + letterbox to profile,
    then force CFR at the profile fps."""
    fs, fe = seg.src_start - pre_seek, seg.src_end - pre_seek
    pw, ph = profile.width, profile.height
    return (
        f"[0:v]trim=start={fs:.6f}:end={fe:.6f},"
        f"setpts=(PTS-STARTPTS)/{seg.speed},"
        f"scale={pw}:{ph}:force_original_aspect_ratio=decrease:eval=init,"
        f"pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
        f"fps=fps={profile.fps_arg}[v]"
    )


def _fade_suffix(out_len: float, fade_s: float) -> str:
    """15 ms equal-power (qsin) fade in+out at each part's edges — declicks the
    concat joins without acrossfade's N-part duration drift (PRODUCER_PLAN §4.2;
    the lead-specified Phase-1 join treatment). Clamped for very short parts."""
    d = min(fade_s, out_len / 2.0)
    if d <= 0:
        return ""
    return (f",afade=t=in:st=0:d={d:.4f}:curve=qsin"
            f",afade=t=out:st={out_len - d:.6f}:d={d:.4f}:curve=qsin")


def _audio_chain(seg: Segment, pre_seek: float, out_len: float,
                 has_src_audio: bool) -> str:
    """Trim + atempo the source audio (or synthesize silence), normalize to
    48 kHz stereo, and taper both edges to declick the join.

    ``out_len`` is the OWN audio length this part contributes — the full
    video length, minus a J-cut tail when the next segment's lead audio is
    appended after it (``encode_segment``'s [tail] chain). Labeled [own];
    the caller maps it (or concats the tail) to the final [a].
    """
    if has_src_audio:
        fs = seg.src_start - pre_seek
        fe = seg.src_start + out_len * seg.speed - pre_seek
        head = (f"[0:a]atrim=start={fs:.6f}:end={fe:.6f},asetpts=PTS-STARTPTS,"
                f"atempo={seg.speed},aresample={AUDIO_RATE}")
    else:  # no audio track on this source → keep the timeline uniform with silence
        head = f"[1:a]atrim=0:{out_len:.6f},asetpts=PTS-STARTPTS"
    fade = _fade_suffix(out_len, AUDIO["join_crossfade_ms"] / 1000.0)
    return (f"{head},aformat=sample_fmts=fltp:sample_rates={AUDIO_RATE}:"
            f"channel_layouts=stereo{fade}[own]")


@dataclass(frozen=True)
class TailLead:
    """The J-cut tail of one part: the NEXT segment's audio pre-roll.

    ``lead_s`` OUTPUT seconds of the next segment's source audio, ending at
    its in-point (``src_start``), retimed by its ``speed``. ``src_path`` may
    differ from the part's own source (multi-source cuts).
    """

    lead_s: float
    src_path: str
    src_start: float
    speed: float


@dataclass(frozen=True)
class EncodeJob:
    """Everything one part's encode needs beyond its Segment."""

    src_path: str
    profile: Profile
    tail: TailLead | None = None


def _tail_chain(tail: TailLead, idx: int, tail_has_audio: bool) -> str:
    """The J-cut lead piece: pre-in-point source audio → ``lead_s`` output
    seconds, normalized + 15 ms edge-declicked (the seam's audio switch gets
    the SAME join treatment every part boundary gets), labeled [tail]."""
    if tail_has_audio:
        s0 = tail.src_start - tail.lead_s * tail.speed
        head = (f"[{idx}:a]atrim=start={s0:.6f}:end={tail.src_start:.6f},"
                f"asetpts=PTS-STARTPTS,atempo={tail.speed},"
                f"aresample={AUDIO_RATE}")
    else:  # incoming segment's source has no audio → its pre-roll is silence
        head = f"[{idx}:a]atrim=0:{tail.lead_s:.6f},asetpts=PTS-STARTPTS"
    fade = _fade_suffix(tail.lead_s, AUDIO["join_crossfade_ms"] / 1000.0)
    return (f"{head},aformat=sample_fmts=fltp:sample_rates={AUDIO_RATE}:"
            f"channel_layouts=stereo{fade}[tail]")


def _tail_inputs(tail: TailLead) -> tuple[list[str], bool]:
    """The extra ffmpeg input for a part's J-cut tail → (args, has_audio)."""
    if not has_audio(tail.src_path):
        return (["-f", "lavfi", "-t", f"{tail.lead_s + 0.5:.3f}",
                 "-i", f"anullsrc=r={AUDIO_RATE}:cl=stereo"], False)
    seek = _tail_seek(tail)
    args = (["-ss", f"{seek:.6f}"] if seek > 0 else []) + ["-i", tail.src_path]
    return args, True


def _tail_seek(tail: TailLead) -> float:
    """The input-side seek applied by :func:`_tail_inputs` (0 when none)."""
    return max(0.0, tail.src_start - tail.lead_s * tail.speed - 1.0)


def encode_segment(seg: Segment, job: EncodeJob, out_path: str) -> None:
    """Extract [src_start, src_end], re-time by speed, normalize to profile.

    With a ``job.tail`` (J-cut): the part's own audio stops ``lead_s`` early
    and the next segment's pre-roll fills the tail — audio stays EXACTLY the
    video length, so the concat join contract is unchanged.
    """
    pre_seek = max(0.0, seg.src_start - PRESEEK_PAD_S)
    out_len = (seg.src_end - seg.src_start) / seg.speed
    own_len = out_len - (job.tail.lead_s if job.tail else 0.0)
    src_has_audio = has_audio(job.src_path)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if pre_seek > 0:
        cmd += ["-ss", f"{pre_seek:.6f}"]
    cmd += ["-i", job.src_path]
    next_idx = 1
    if not src_has_audio:
        cmd += ["-f", "lavfi", "-t", f"{own_len + 1.0:.3f}",
                "-i", f"anullsrc=r={AUDIO_RATE}:cl=stereo"]
        next_idx = 2
    fc = (_video_chain(seg, pre_seek, job.profile) + ";"
          + _audio_chain(seg, pre_seek, own_len, src_has_audio))
    amap = "[own]"
    if job.tail is not None:
        targs, tail_has_audio = _tail_inputs(job.tail)
        cmd += targs
        shifted = (TailLead(job.tail.lead_s, job.tail.src_path,
                            job.tail.src_start - _tail_seek(job.tail),
                            job.tail.speed) if tail_has_audio else job.tail)
        fc += (";" + _tail_chain(shifted, next_idx, tail_has_audio)
               + ";[own][tail]concat=n=2:v=0:a=1[a]")
        amap = "[a]"
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", amap,
            "-c:v", "libx264", "-crf", str(ENCODE["mezzanine_crf"]),
            "-preset", ENCODE["mezzanine_preset"],
            "-pix_fmt", job.profile.pix_fmt,
            "-fps_mode", "cfr", "-r", job.profile.fps_arg,
            "-c:a", "aac", "-b:a", ENCODE["audio_bitrate"],
            "-ar", str(AUDIO_RATE), "-ac", str(AUDIO_CH),
            "-movflags", "+faststart", out_path]
    run_ff(cmd)


def concat_parts(parts: list[str], out_path: str, work_dir: str) -> None:
    """Concat identical-profile mezzanine parts via the concat demuxer — all
    parts share codec / resolution / fps / audio format, so stream-copy joins
    cleanly (unlike the mixed re-encoded/copied pieces smartcut has to TS-splice)."""
    listfile = os.path.join(work_dir, "concat.txt")
    with open(listfile, "w") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
    run_ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", listfile,
            "-c", "copy", "-movflags", "+faststart", out_path])


def _warn_off_profile(segments: list[Segment], id_to_path: dict[str, str],
                      profile: Profile) -> None:
    """Emit a warn line for each source whose aspect ratio differs from the
    profile (it will be letterbox-padded, not cropped)."""
    seen: set[str] = set()
    target_ar = profile.width / profile.height
    for seg in segments:
        if seg.source_id in seen:
            continue
        seen.add(seg.source_id)
        v = probe_video(id_to_path[seg.source_id])
        w, h = int(v["width"]), int(v["height"])
        if abs(w / h - target_ar) > 0.01:
            emit(stage="cut_speed", status="warn", reason="letterbox",
                 sourceId=seg.source_id, source_res=[w, h],
                 profile_res=[profile.width, profile.height])


def assert_duration(out_path: str, expected_s: float, profile: Profile,
                    n_segments: int) -> dict:
    """Hard-error if the rendered VIDEO timeline drifts from the compiler
    prediction (container duration is reported too, for transparency)."""
    frames = probe_video_frames(out_path)
    video_s = frames / float(profile.fps)
    drift_frames = abs(frames - expected_s * float(profile.fps))
    tol = DURATION_TOL_BASE_FRAMES + DURATION_TOL_PER_SEGMENT_FRAMES * n_segments
    result = {"videoDuration": round(video_s, 4),
              "containerDuration": round(probe_duration(out_path), 4),
              "expectedDuration": round(expected_s, 4),
              "videoFrames": frames,
              "driftFrames": round(drift_frames, 3),
              "toleranceFrames": round(tol, 3),
              "segments": n_segments}
    if drift_frames > tol:
        raise RuntimeError(
            f"stage-1 video timeline {video_s:.4f}s ({frames} frames) off expected "
            f"{expected_s:.4f}s by {drift_frames:.2f} frames (> {tol:.2f})")
    return result


@dataclass(frozen=True)
class CutSpeedOptions:
    """Optional knobs for one cut+speed render (keeps entry points ≤4 params).

    Attributes:
        work_dir: Where the per-segment parts land.
        proxy_scale: When set, render a DOWNSCALED proxy mezzanine through the
            SAME segment math (see :func:`proxy_profile`); ``None`` = full res.
    """

    work_dir: str
    proxy_scale: float | None = None


def render_cut_speed(plan: dict, manifest: dict, out_path: str,
                     work_dir: str) -> dict:
    """Compile the plan and render its cut+speed mezzanine into ``out_path``."""
    return render_cut_speed_opts(plan, manifest, out_path,
                                 CutSpeedOptions(work_dir))


def render_cut_speed_opts(plan: dict, manifest: dict, out_path: str,
                          opts: CutSpeedOptions) -> dict:
    """Cut+speed render with options (the proxy-capable entry point)."""
    work_dir = opts.work_dir
    tmap = compile_plan(plan)
    if not tmap.segments:
        raise RuntimeError("plan compiles to zero segments — nothing to render")
    id_to_path = {s["id"]: s["path"] for s in manifest.get("sources", [])}
    missing = {seg.source_id for seg in tmap.segments} - set(id_to_path)
    if missing:
        raise RuntimeError(f"sources missing from manifest: {sorted(missing)}")
    profile = decide_profile(id_to_path[tmap.segments[0].source_id])
    if opts.proxy_scale is not None:
        profile = proxy_profile(profile, opts.proxy_scale)
        emit(stage="cut_speed", status="proxy", scale=opts.proxy_scale,
             width=profile.width, height=profile.height)
    emit(stage="cut_speed", status="profile", width=profile.width,
         height=profile.height, fps=profile.fps_arg, pix_fmt=profile.pix_fmt)
    _warn_off_profile(tmap.segments, id_to_path, profile)
    parts: list[str] = []
    segs = tmap.segments
    for i, seg in enumerate(segs):
        part = os.path.join(work_dir, f"part_{seg.index:04d}.mp4")
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        tail = None
        if nxt is not None and nxt.audio_lead_s > 0.0:   # J-cut seam ahead
            tail = TailLead(nxt.audio_lead_s, id_to_path[nxt.source_id],
                            nxt.src_start, nxt.speed)
        encode_segment(seg, EncodeJob(id_to_path[seg.source_id], profile,
                                      tail), part)
        parts.append(part)
        emit(stage="cut_speed", status="segment", index=seg.index,
             sourceId=seg.source_id,
             out_len=round((seg.src_end - seg.src_start) / seg.speed, 4),
             **({"jcutTailS": round(tail.lead_s, 4)} if tail else {}))
    concat_parts(parts, out_path, work_dir)
    emit(stage="cut_speed", status="concat", parts=len(parts))
    result = assert_duration(out_path, tmap.output_duration, profile, len(parts))
    emit(stage="cut_speed", status="done", **result)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="PRODUCER stage 1: cut + speed + normalize to a mezzanine")
    ap.add_argument("edit_plan")
    ap.add_argument("manifest")
    ap.add_argument("out")
    ap.add_argument("--workdir", help="reuse (and keep) this work dir instead of a temp one")
    args = ap.parse_args()
    own_workdir = args.workdir is None
    work_dir = args.workdir or tempfile.mkdtemp(prefix="producer-cutspeed-")
    try:
        os.makedirs(work_dir, exist_ok=True)
        with open(args.edit_plan) as f:
            plan = json.load(f)
        with open(args.manifest) as f:
            manifest = json.load(f)
        render_cut_speed(plan, manifest, args.out, work_dir)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        emit(error=str(exc))
        return 1
    finally:
        if own_workdir:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
