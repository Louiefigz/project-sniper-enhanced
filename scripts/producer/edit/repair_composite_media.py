"""Media execution and decoded oracles for a full P2 repair candidate."""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass

from edit.exact_timing import FrameRange, ProjectClock, SampleRange
from edit.repair_fragment_contracts import RepairMediaTools, RepairRenderError


@dataclass(frozen=True)
class RepairCompositeMediaJob:
    """Resolved paths and exact clocks for one full candidate composite."""

    parent_path: str
    fragment_path: str
    video_path: str
    audio_path: str
    staged_output_path: str
    total_frames: int
    dirty_frames: FrameRange
    picture_dirty: bool
    clock: ProjectClock
    tools: RepairMediaTools
    parent_audio_filter: str
    fragment_audio_filter: str


def _run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        tail = (result.stderr or "").strip().splitlines()[-12:]
        raise RepairRenderError("\n".join(tail) or f"{command[0]} failed")
    return result.stdout


def _stream_digest(command: list[str]) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.stdout is None:
        process.kill()
        raise RepairRenderError("media oracle did not expose decoded output")
    while True:
        chunk = process.stdout.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        count += len(chunk)
    process.stdout.close()
    stderr = process.stderr.read() if process.stderr is not None else b""
    if process.stderr is not None:
        process.stderr.close()
    return_code = process.wait()
    if return_code:
        tail = stderr.decode("utf-8", errors="replace").splitlines()[-12:]
        raise RepairRenderError("\n".join(tail) or f"{command[0]} failed")
    return digest.hexdigest(), count


def _video_piece(input_index: int, frames: FrameRange,
                 label: str) -> str:
    return (
        f"[{input_index}:v]trim=start_frame={frames.start_frame}:"
        f"end_frame={frames.end_frame_exclusive},"
        f"setpts=PTS-STARTPTS[{label}]"
    )


def _video_filter(job: RepairCompositeMediaJob) -> str:
    dirty = job.dirty_frames
    filters: list[str] = []
    labels: list[str] = []
    if dirty.start_frame:
        before = FrameRange(0, dirty.start_frame)
        filters.append(_video_piece(0, before, "beforev"))
        labels.append("beforev")
    fragment = FrameRange(0, dirty.length)
    filters.append(_video_piece(1, fragment, "fragmentv"))
    labels.append("fragmentv")
    if dirty.end_frame_exclusive < job.total_frames:
        after = FrameRange(dirty.end_frame_exclusive, job.total_frames)
        filters.append(_video_piece(0, after, "afterv"))
        labels.append("afterv")
    chain = "".join(f"[{label}]" for label in labels)
    filters.append(f"{chain}concat=n={len(labels)}:v=1:a=0[v]")
    return ";".join(filters)


def _audio_piece(
    input_index: int,
    samples: SampleRange,
    label: str,
    audio_filter: str,
) -> str:
    return (
        f"[{input_index}:a]{audio_filter},"
        f"atrim=start_sample={samples.start_sample}:"
        f"end_sample={samples.end_sample_exclusive},"
        f"asetpts=PTS-STARTPTS[{label}]"
    )


def _audio_filter(job: RepairCompositeMediaJob) -> str:
    dirty = job.clock.samples_for_frames(job.dirty_frames)
    terminal = job.clock.sample_at_frame(job.total_frames)
    filters: list[str] = []
    labels: list[str] = []
    if dirty.start_sample:
        before = SampleRange(0, dirty.start_sample)
        filters.append(_audio_piece(
            0, before, "beforea", job.parent_audio_filter))
        labels.append("beforea")
    fragment = SampleRange(0, dirty.length)
    filters.append(_audio_piece(
        1, fragment, "fragmenta", job.fragment_audio_filter))
    labels.append("fragmenta")
    if dirty.end_sample_exclusive < terminal:
        after = SampleRange(dirty.end_sample_exclusive, terminal)
        filters.append(_audio_piece(
            0, after, "aftera", job.parent_audio_filter))
        labels.append("aftera")
    chain = "".join(f"[{label}]" for label in labels)
    filters.append(
        f"{chain}concat=n={len(labels)}:v=0:a=1,"
        f"atrim=end_sample={terminal},asetpts=PTS-STARTPTS[a]")
    return ";".join(filters)


def render_composite(job: RepairCompositeMediaJob) -> None:
    """Render a full exact-clock candidate from parent + dirty fragment."""
    ffmpeg = job.tools.ffmpeg_path
    inputs = [
        ffmpeg, "-y", "-nostdin", "-v", "error",
        "-i", job.parent_path, "-i", job.fragment_path,
    ]
    fps = f"{job.clock.fps.numerator}/{job.clock.fps.denominator}"
    _run([
        *inputs, "-filter_complex", _video_filter(job), "-map", "[v]",
        "-an", "-c:v", "libx264", "-qp", "0", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-fps_mode", "cfr", "-r", fps,
        job.video_path,
    ])
    _run([
        *inputs, "-filter_complex", _audio_filter(job), "-map", "[a]",
        "-vn", "-ar", str(job.clock.sample_rate), "-ac", "2",
        "-c:a", "pcm_s32le", job.audio_path,
    ])
    _run([
        ffmpeg, "-y", "-nostdin", "-v", "error",
        "-i", job.video_path, "-i", job.audio_path,
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
        "-c:a", "pcm_s32le", "-ar", str(job.clock.sample_rate),
        "-ac", "2", job.staged_output_path,
    ])


def _video_probe(path: str, job: RepairCompositeMediaJob) -> dict:
    raw = _run([
        job.tools.ffprobe_path, "-v", "error", "-select_streams", "v:0",
        "-count_packets", "-show_entries",
        "stream=nb_read_packets,avg_frame_rate,width,height",
        "-of", "json", path,
    ])
    streams = json.loads(raw).get("streams") or []
    if len(streams) != 1:
        raise RepairRenderError("candidate has no unique video stream")
    return streams[0]


def _audio_decode(path: str, job: RepairCompositeMediaJob,
                  audio_filter: str | None = None) -> tuple[str, int]:
    command = [
        job.tools.ffmpeg_path, "-v", "error", "-xerror", "-i", path,
        "-map", "0:a:0",
    ]
    if audio_filter is not None:
        command.extend(["-af", audio_filter])
    command.extend([
        "-f", "s32le", "-ac", "2", "-ar",
        str(job.clock.sample_rate), "-",
    ])
    digest, size = _stream_digest(command)
    if size % 8:
        raise RepairRenderError("decoded candidate PCM is malformed")
    return digest, size // 8


def probe_full_media(path: str,
                     job: RepairCompositeMediaJob) -> dict[str, object]:
    """Fully decode a candidate and return exact terminal clock evidence."""
    video = _video_probe(path, job)
    pcm_hash, samples = _audio_decode(path, job)
    _run([
        job.tools.ffmpeg_path, "-v", "error", "-xerror",
        "-i", path, "-f", "null", "-",
    ])
    return {
        "videoFrames": int(video["nb_read_packets"]),
        "audioSamplesPerChannel": samples,
        "decodedPcmSha256": pcm_hash,
        "averageFrameRate": video["avg_frame_rate"],
        "width": int(video["width"]),
        "height": int(video["height"]),
        "decode": "ffmpeg-xerror-full-av-v1",
    }


def _outside_video_hash(path: str,
                        job: RepairCompositeMediaJob) -> str:
    command = [
        job.tools.ffmpeg_path, "-v", "error", "-xerror", "-i", path,
        "-map", "0:v:0",
    ]
    if job.picture_dirty:
        dirty = job.dirty_frames
        select = (
            f"select='lt(n\\,{dirty.start_frame})"
            f"+gte(n\\,{dirty.end_frame_exclusive})',"
            "setpts=N/FRAME_RATE/TB"
        )
        command.extend(["-vf", select])
    command.extend([
        "-an", "-pix_fmt", "yuv420p",
        "-fps_mode", "passthrough", "-f", "framehash",
        "-hash", "sha256", "-",
    ])
    output = _run(command)
    return hashlib.sha256(output.encode("utf-8")).hexdigest()


def _outside_audio_hash(path: str,
                        job: RepairCompositeMediaJob) -> str:
    dirty = job.clock.samples_for_frames(job.dirty_frames)
    terminal = job.clock.sample_at_frame(job.total_frames)
    filters: list[str] = []
    labels: list[str] = []
    has_before = bool(dirty.start_sample)
    has_after = dirty.end_sample_exclusive < terminal
    if has_before and has_after:
        filters.append("[0:a]asplit=2[sourcebefore][sourceafter]")
    before_input = "sourcebefore" if has_after else "0:a"
    after_input = "sourceafter" if has_before else "0:a"
    if has_before:
        filters.append(
            f"[{before_input}]atrim=start_sample=0:"
            f"end_sample={dirty.start_sample},"
            "asetpts=PTS-STARTPTS[before]")
        labels.append("before")
    if has_after:
        filters.append(
            f"[{after_input}]atrim=start_sample="
            f"{dirty.end_sample_exclusive}:"
            f"end_sample={terminal},asetpts=PTS-STARTPTS[after]")
        labels.append("after")
    if not labels:
        raise RepairRenderError("repair dirties the complete audio program")
    if len(labels) == 1:
        filters.append(f"[{labels[0]}]anull[out]")
    else:
        filters.append("[before][after]concat=n=2:v=0:a=1[out]")
    command = [
        job.tools.ffmpeg_path, "-v", "error", "-xerror", "-i", path,
        "-filter_complex", ";".join(filters), "-map", "[out]",
        "-f", "s32le", "-ac", "2", "-ar", str(job.clock.sample_rate), "-",
    ]
    return _stream_digest(command)[0]


def outside_dirty_oracle(parent: str, candidate: str,
                         job: RepairCompositeMediaJob) -> dict[str, object]:
    """Prove decoded picture and pre-AAC PCM are unchanged outside closure."""
    parent_video = _outside_video_hash(parent, job)
    output_video = _outside_video_hash(candidate, job)
    parent_audio = _outside_audio_hash(parent, job)
    output_audio = _outside_audio_hash(candidate, job)
    return {
        "pictureScope":
            "outside-dirty" if job.picture_dirty else "full-program",
        "parentPictureSha256": parent_video,
        "outputPictureSha256": output_video,
        "parentPcmSha256": parent_audio,
        "outputPcmSha256": output_audio,
        "pictureMatches": parent_video == output_video,
        "pcmMatches": parent_audio == output_audio,
    }
