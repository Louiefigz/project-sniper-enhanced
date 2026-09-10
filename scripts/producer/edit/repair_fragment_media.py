"""FFmpeg execution and decoded-oracle helpers for P2 repair fragments."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from edit.exact_timing import FrameRange, ProjectClock, SampleRange
from edit.repair_fragment_contracts import (
    RepairMediaTools,
    RepairRenderError,
    ValidatedRepair,
)


@dataclass(frozen=True)
class RepairMediaJob:
    """Resolved paths and timing for one staged fragment."""

    parent_path: str
    source_path: str
    video_path: str
    audio_path: str
    staged_output_path: str
    clock: ProjectClock
    tools: RepairMediaTools
    parent_audio_filter: str
    source_audio_filter: str


@dataclass(frozen=True)
class RepairAudioFilters:
    """The two exact channel filters bound by input receipts."""

    parent: str
    source: str


def _run(command: list[str], binary: bool = False) -> bytes | str:
    result = subprocess.run(command, capture_output=True, text=not binary)
    if result.returncode:
        stderr = result.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        tail = str(stderr or "").strip().splitlines()[-12:]
        raise RepairRenderError("\n".join(tail) or f"{command[0]} failed")
    return result.stdout


def _speed(repair: ValidatedRepair) -> tuple[str, str]:
    value = repair.operation.get("speed")
    if not isinstance(value, dict):
        raise RepairRenderError("repair speed is malformed")
    try:
        numerator = int(value["numerator"])
        denominator = int(value["denominator"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RepairRenderError("repair speed is malformed") from exc
    if numerator <= 0 or denominator <= 0:
        raise RepairRenderError("repair speed is not positive")
    tempo = format(numerator / denominator, ".17g")
    return tempo, f"{denominator}/{numerator}"


def _video_source_filter(repair: ValidatedRepair,
                         clock: ProjectClock) -> str:
    source = repair.source_video_frames
    if source is None:
        raise RepairRenderError("picture repair lacks exact source frames")
    _tempo, setpts = _speed(repair)
    fps = f"{clock.fps.numerator}/{clock.fps.denominator}"
    return (
        f"[1:v]trim=start_frame={source.start_frame}:"
        f"end_frame={source.end_frame_exclusive},"
        f"setpts=(PTS-STARTPTS)*{setpts},fps=fps={fps}:round=near,"
        f"trim=end_frame={repair.extension_frames},"
        "setpts=PTS-STARTPTS[srcv]"
    )


def _parent_video(label: str, frames: FrameRange) -> str:
    return (
        f"[0:v]trim=start_frame={frames.start_frame}:"
        f"end_frame={frames.end_frame_exclusive},"
        f"setpts=PTS-STARTPTS[{label}]"
    )


def _picture_video_filter(repair: ValidatedRepair,
                          clock: ProjectClock) -> str:
    silence = repair.reclaimed_frames
    if silence is None:
        raise RepairRenderError("picture repair lacks silence frames")
    dirty = repair.dirty_frames
    filters = [_video_source_filter(repair, clock)]
    if repair.edge == "end":
        start, end = (silence.end_frame_exclusive,
                      dirty.end_frame_exclusive)
        order = "[parentv][srcv]"
    else:
        start, end = dirty.start_frame, silence.start_frame
        order = "[srcv][parentv]"
    if start < end:
        parent = FrameRange(start, end)
        filters.append(_parent_video("parentv", parent))
        filters.append(f"{order}concat=n=2:v=1:a=0[v]")
    else:
        filters.append("[srcv]null[v]")
    return ";".join(filters)


def video_filter(repair: ValidatedRepair, clock: ProjectClock) -> str:
    """Build a frame-exact video fragment filter."""
    if repair.method == "audio-lj-overlap":
        dirty = repair.dirty_frames
        return (
            f"[0:v]trim=start_frame={dirty.start_frame}:"
            f"end_frame={dirty.end_frame_exclusive},"
            "setpts=PTS-STARTPTS[v]"
        )
    return _picture_video_filter(repair, clock)


def _parent_audio(
    label: str,
    samples: SampleRange,
    audio_filter: str,
) -> str:
    return (
        f"[0:a]{audio_filter},"
        f"atrim=start_sample={samples.start_sample}:"
        f"end_sample={samples.end_sample_exclusive},"
        f"asetpts=PTS-STARTPTS[{label}]"
    )


def _source_audio(
    repair: ValidatedRepair,
    sample_rate: int,
    audio_filter: str,
) -> str:
    source = repair.source_extension
    tempo, _setpts = _speed(repair)
    return (
        f"[1:a]{audio_filter},"
        f"atrim=start_sample={source.start_sample}:"
        f"end_sample={source.end_sample_exclusive},"
        f"asetpts=PTS-STARTPTS,atempo={tempo},"
        f"aresample={sample_rate}:async=0,apad,"
        f"atrim=end_sample={repair.extension_output_samples},"
        "asetpts=PTS-STARTPTS[srca]"
    )


def _concat_audio(filters: list[str], labels: list[str],
                  output_samples: int) -> str:
    if len(labels) == 1:
        filters.append(
            f"[{labels[0]}]atrim=end_sample={output_samples},"
            "asetpts=PTS-STARTPTS[a]")
        return ";".join(filters)
    filters.append(
        "".join(f"[{label}]" for label in labels)
        + f"concat=n={len(labels)}:v=0:a=1,"
        + f"atrim=end_sample={output_samples},asetpts=PTS-STARTPTS[a]")
    return ";".join(filters)


def _audio_only_filter(repair: ValidatedRepair,
                       clock: ProjectClock,
                       channels: RepairAudioFilters) -> str:
    envelope = clock.samples_for_frames(repair.dirty_frames)
    replacement = repair.dirty_samples
    filters = [_source_audio(
        repair, clock.sample_rate, channels.source)]
    labels: list[str] = []
    if envelope.start_sample < replacement.start_sample:
        before = SampleRange(
            envelope.start_sample, replacement.start_sample)
        filters.append(_parent_audio(
            "beforea", before, channels.parent))
        labels.append("beforea")
    labels.append("srca")
    if replacement.end_sample_exclusive < envelope.end_sample_exclusive:
        after = SampleRange(
            replacement.end_sample_exclusive,
            envelope.end_sample_exclusive)
        filters.append(_parent_audio(
            "aftera", after, channels.parent))
        labels.append("aftera")
    return _concat_audio(filters, labels, envelope.length)


def _picture_audio_filter(repair: ValidatedRepair,
                          clock: ProjectClock,
                          channels: RepairAudioFilters) -> str:
    silence = repair.reclaimed_frames
    if silence is None:
        raise RepairRenderError("picture repair lacks reclaimed silence")
    dirty = clock.samples_for_frames(repair.dirty_frames)
    removed = clock.samples_for_frames(silence)
    residual = repair.quantization_residual_samples
    filters = [_source_audio(
        repair, clock.sample_rate, channels.source)]
    labels = ["srca"]
    if residual:
        room = SampleRange(
            removed.start_sample, removed.start_sample + residual)
        filters.append(_parent_audio(
            "rooma", room, channels.parent))
        labels = (["srca", "rooma"] if repair.edge == "end"
                  else ["rooma", "srca"])
    if repair.edge == "end":
        start, end = (removed.end_sample_exclusive,
                      dirty.end_sample_exclusive)
        if start < end:
            filters.append(_parent_audio(
                "parenta", SampleRange(start, end), channels.parent))
            labels = ["parenta", *labels]
    else:
        start, end = dirty.start_sample, removed.start_sample
        if start < end:
            filters.append(_parent_audio(
                "parenta", SampleRange(start, end), channels.parent))
            labels.append("parenta")
    return _concat_audio(filters, labels, dirty.length)


def audio_filter(
    repair: ValidatedRepair,
    clock: ProjectClock,
    channels: RepairAudioFilters,
) -> str:
    """Build an exact-project-sample audio fragment filter."""
    if repair.method == "audio-lj-overlap":
        return _audio_only_filter(repair, clock, channels)
    return _picture_audio_filter(repair, clock, channels)


def render_staged_media(repair: ValidatedRepair,
                        job: RepairMediaJob) -> None:
    """Render separate frame/sample streams, then mux one local fragment."""
    ffmpeg = job.tools.ffmpeg_path
    common = [ffmpeg, "-y", "-nostdin", "-v", "error",
              "-i", job.parent_path, "-i", job.source_path]
    fps = f"{job.clock.fps.numerator}/{job.clock.fps.denominator}"
    _run([*common, "-filter_complex", video_filter(repair, job.clock),
          "-map", "[v]", "-an", "-c:v", "libx264", "-qp", "0",
          "-preset", "fast", "-pix_fmt", "yuv420p", "-fps_mode", "cfr",
          "-r", fps, job.video_path])
    channels = RepairAudioFilters(
        job.parent_audio_filter, job.source_audio_filter)
    _run([*common, "-filter_complex",
          audio_filter(repair, job.clock, channels),
          "-map", "[a]", "-vn", "-ar", str(job.clock.sample_rate),
          "-ac", "2", "-c:a", "pcm_s32le", job.audio_path])
    _run([ffmpeg, "-y", "-nostdin", "-v", "error",
          "-i", job.video_path, "-i", job.audio_path,
          "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
          "-c:a", "pcm_s32le", "-ar", str(job.clock.sample_rate),
          "-ac", "2", job.staged_output_path])


def probe_fragment(path: str, job: RepairMediaJob) -> dict[str, object]:
    """Decode the staged artifact and return exact frame/sample evidence."""
    ffprobe, ffmpeg = job.tools.ffprobe_path, job.tools.ffmpeg_path
    raw = _run([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-count_packets", "-show_entries",
        "stream=nb_read_packets,avg_frame_rate,width,height",
        "-of", "json", path])
    streams = json.loads(str(raw)).get("streams") or []
    if len(streams) != 1:
        raise RepairRenderError("repair fragment has no unique video stream")
    pcm = _run([
        ffmpeg, "-v", "error", "-xerror", "-i", path,
        "-map", "0:a:0", "-f", "s32le", "-ac", "2",
        "-ar", str(job.clock.sample_rate), "-"], binary=True)
    if not isinstance(pcm, bytes) or len(pcm) % 8:
        raise RepairRenderError("repair fragment decoded PCM is malformed")
    _run([ffmpeg, "-v", "error", "-xerror", "-i", path,
          "-f", "null", "-"])
    stream = streams[0]
    return {
        "videoFrames": int(stream["nb_read_packets"]),
        "audioSamplesPerChannel": len(pcm) // 8,
        "averageFrameRate": stream["avg_frame_rate"],
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "decode": "ffmpeg-xerror-full-av-v1",
    }
