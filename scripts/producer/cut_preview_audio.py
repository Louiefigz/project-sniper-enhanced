"""Source-derived float cut audio; concatenate losslessly and encode AAC once."""
from __future__ import annotations

import math
import os
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from audio.channel_normalization import ChannelAuthority, ChannelRequest, ChannelTools, SourceIdentity
from audio.channel_normalization_receipt import verify_channel_receipt
from compile_timeline import compile_plan
from cut_preview_io import MAX_MEDIA, file_hash, write_new, run_bounded
from cut_preview_picture import picture_clock, origin_arguments, verify_picture_origin
from audio.render_audio_bus import fit_float_samples
from cut_speed import (PRESEEK_PAD_S, TailLead, _audio_chain, _tail_chain,
                       _tail_inputs, _tail_seek, has_audio, probe_video_frames)


@dataclass(frozen=True)
class AudioContext:
    """One already-admitted private execution's immutable media inputs."""
    plan: dict
    manifest: dict
    output: Path
    profile: dict
    tools: dict
    cut_proof: dict


def _channel_authorities(context: AudioContext) -> dict:
    """Reuse same-render bound channel decisions without a second full-source scan."""
    result = {}
    sources = {row["path"]: row["sourceSha256"] for row in context.manifest["sources"]}
    for item in context.cut_proof["channelNormalizationReceipts"]:
        receipt = verify_channel_receipt(item["receipt"])
        source, tools = receipt["source"], receipt["tools"]
        if source["path"] != item["sourcePath"] or sources.get(source["path"]) != source["sha256"] \
                or tools["ffmpegPath"] != context.tools["ffmpeg"] \
                or tools["ffprobePath"] != context.tools["ffprobe"]:
            raise RuntimeError("cut preview channel proof differs from admitted/executed media")
        info = os.stat(source["path"], follow_symlinks=False)
        request = ChannelRequest(source["path"], source["sha256"], source["selector"],
                                 ChannelTools(tools["ffmpegPath"], tools["ffmpegSha256"],
                                              tools["ffprobePath"], tools["ffprobeSha256"]))
        identity = SourceIdentity(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        result[source["path"]] = ChannelAuthority(request, identity, receipt)
    return result


def _segment_command(context: AudioContext, segment, next_segment, channels: dict) -> tuple[list[str], str]:
    """Reuse the canonical own/lead filters and input-seek compensation exactly."""
    sources = {row["id"]: row["path"] for row in context.manifest["sources"]}
    source = sources[segment.source_id]
    authority = channels.get(source)
    if authority is None and has_audio(source):
        raise RuntimeError("cut preview source audio is missing its channel proof")
    seek = max(0, segment.src_start - PRESEEK_PAD_S)
    length = (segment.src_end - segment.src_start) / segment.speed
    tail = TailLead(next_segment.audio_lead_s, sources[next_segment.source_id],
                    next_segment.src_start, next_segment.speed) \
        if next_segment is not None and next_segment.audio_lead_s > 0 else None
    own = length - (tail.lead_s if tail else 0)
    command = [context.tools["ffmpeg"], "-nostdin", "-v", "error", "-xerror", "-n"]
    command += (["-ss", f"{seek:.6f}"] if seek > 0 else []) + ["-i", source]
    if authority is None:
        command += ["-f", "lavfi", "-t", str(own + 1), "-i", "anullsrc=r=48000:cl=stereo"]
    filters = _audio_chain(segment, seek, own, authority)
    if segment.speed == 1:
        filters = filters.replace(f",atempo={segment.speed},", ",")
    if tail:
        lead_authority = channels.get(tail.src_path)
        if lead_authority is None and has_audio(tail.src_path):
            raise RuntimeError("cut preview lead audio is missing its channel proof")
        command += _tail_inputs(tail, lead_authority is not None)
        shifted = TailLead(tail.lead_s, tail.src_path, tail.src_start - _tail_seek(tail), tail.speed) \
            if lead_authority is not None else tail
        tail_filter = _tail_chain(shifted, 1 if authority else 2, lead_authority)
        if shifted.speed == 1:
            tail_filter = tail_filter.replace(f",atempo={shifted.speed},", ",")
        filters += ";" + tail_filter
        filters += ";[own][tail]concat=n=2:v=0:a=1[combined]"
    else:
        filters += ";[own]anull[combined]"
    return command, filters


def _run(command: list[str]) -> None:
    """Use a bounded command inside the controller-owned process group."""
    result = run_bounded(command, maximum=65536)
    if result.returncode or result.stderr.strip():
        raise RuntimeError("source-derived cut preview audio failed: " + result.stderr[-500:].decode("utf-8", errors="replace"))


def _float_parts(context: AudioContext, channels: dict) -> tuple[list[dict], Path]:
    """Accumulate exact video-frame/sample clocks; never accumulate rounded samples."""
    timeline = compile_plan(context.plan)
    rows, total_frames, previous_sample = [], 0, 0
    audio_dir = context.output / "audio-parts"
    audio_dir.mkdir(mode=0o700)
    for index, segment in enumerate(timeline.segments):
        part_frames = probe_video_frames(str(context.output / "parts" / f"part_{index:04d}.mp4"))
        total_frames += part_frames
        sample_end = round(Fraction(total_frames, 1) / Fraction(context.profile["fps"]) * 48000)
        count = sample_end - previous_sample
        next_segment = timeline.segments[index + 1] if index + 1 < len(timeline.segments) else None
        command, filters = _segment_command(context, segment, next_segment, channels)
        # The UNPADDED source-derived samples are rendered first, so the length check
        # proves the source actually carried this window (within one frame of picture
        # quantization); padding/trimming plus the exact-window declick come after.
        filters += ";[combined]asetpts=PTS-STARTPTS[a]"
        raw, target = audio_dir / f"raw_{index:04d}.f32", audio_dir / f"part_{index:04d}.f32"
        _run(command + ["-filter_complex", filters, "-map", "[a]", "-c:a", "pcm_f32le",
                        "-ar", "48000", "-ac", "2", "-f", "f32le", str(raw)])
        tolerance = math.ceil(48_000 / float(Fraction(context.profile["fps"]))) + 1
        fit = fit_float_samples(raw, target, count, tolerance)
        raw.unlink()
        if target.stat().st_size != count * 8:
            raise RuntimeError("cut preview float audio part violates its exact sample window")
        rows.append({"index": index, "videoFrames": part_frames,
                     "startSample": previous_sample, "endSample": sample_end, "quantizationFitSamples": fit,
                     "sourceId": segment.source_id, "srcStart": segment.src_start,
                     "srcEnd": segment.src_end, "speed": segment.speed,
                     "nextAudioLeadS": next_segment.audio_lead_s if next_segment else 0,
                     "floatSha256": file_hash(target)})
        previous_sample = sample_end
    return rows, audio_dir


def _concatenate(rows: list[dict], directory: Path, destination: Path) -> None:
    """Copy float samples byte-for-byte, avoiding per-part compressed priming."""
    with destination.open("xb") as output:
        for row in rows:
            source = directory / f"part_{row['index']:04d}.f32"
            if file_hash(source) != row["floatSha256"]:
                raise RuntimeError("cut preview float audio part changed")
            with source.open("rb") as handle:
                while data := handle.read(1024 * 1024):
                    output.write(data)
    if destination.stat().st_size != rows[-1]["endSample"] * 8:
        raise RuntimeError("cut preview float concat changed sample count")


def render_source_audio(context: AudioContext, maximum_media_bytes: int = MAX_MEDIA) -> str:
    """Mux copied video with one AAC encode from source-derived float samples."""
    channels = _channel_authorities(context)
    rows, directory = _float_parts(context, channels)
    audio_path = context.output / "cut-audio.f32"
    _concatenate(rows, directory, audio_path)
    picture = picture_clock(context.output / "cut-concat.mp4", context.tools["ffprobe"], maximum_media_bytes)
    _run([context.tools["ffmpeg"], "-nostdin", "-v", "error", "-xerror", "-n",
          *origin_arguments(picture), "-i", str(context.output / "cut-concat.mp4"), "-f", "f32le", "-ar", "48000", "-ac", "2",
          "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
          "-c:a", "aac", "-b:a", "192k",
          # The AAC priming edit list is written in the MOVIE timescale; at the MP4
          # default (1000) the presented sample count is millisecond-rounded and
          # equals the sealed float clock only when the total happens to be a whole
          # ms (90 NTSC frames do; the 82-part long-form's 14968554 samples did not,
          # measured 2026-09-06). The sample rate makes the presentation exact.
          "-movie_timescale", "48000",
          "-movflags", "+faststart", str(context.output / "cut-preview.mp4")])
    picture_proof = verify_picture_origin(picture, picture_clock(
        context.output / "cut-preview.mp4", context.tools["ffprobe"], maximum_media_bytes))
    for authority in channels.values():
        authority.assert_stable()
    clock = {"schemaVersion": 1, "kind": "cut-preview-source-audio-clock",
             "sampleRate": 48000, "channels": 2, "sampleFormat": "float32le",
             "frameRate": context.profile["fps"], "parts": rows,
             "pictureClock": picture_proof,
             "totalSamples": rows[-1]["endSample"], "floatSha256": file_hash(audio_path)}
    clock_path = context.output / "audio-clock.json"
    write_new(clock_path, clock)
    return file_hash(clock_path)
