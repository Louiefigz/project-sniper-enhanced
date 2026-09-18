"""Source-derived float cut bus for a fresh ordinary-render execution."""
from __future__ import annotations

import math
import os
import json
import stat
from array import array
from contextlib import contextmanager
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import BinaryIO, Iterator

from audio.cut_audio_filters import CutAudioFilter, source_filter
from producer_config import AUDIO
from audio.channel_normalization import ChannelAuthority
from audio.render_audio_authority import (
    AudioAdmission, SOURCE_FLOAT_POLICY_V2, assert_admission, channel_authorities,
    run_audio, seal_audio_record,
)
from compile_timeline import Segment, compile_plan
from cut_manifestation_authority import verify_manifestation
from cut_speed import PRESEEK_PAD_S, TailLead, _tail_inputs, _tail_seek
from fingerprints import file_sha256
from media_probe import probe_video_frames


@dataclass(frozen=True)
class SourceAudioBus:
    """Retained unmastered WAV and same-run source/clock evidence."""

    path: str
    sha256: str
    samples: int
    frame_rate: str
    frames: int
    directory: str
    receipt: dict
    admission: AudioAdmission
    manifestation_root: str | None = None


@dataclass(frozen=True)
class BusRender:
    """Fresh ordinary cut outputs, not a private-preview or reconstructed cache."""

    plan: dict
    admission: AudioAdmission
    output_directory: str
    parts: tuple[str, ...]
    cut_proof: dict


def _authority(path: str, channels: dict, sources: dict) -> ChannelAuthority | None:
    """Absence is authorized only when the observed source has no audio stream."""
    value = channels.get(path)
    if value is None and sources[path]["audioStreamIndex"] is not None:
        raise RuntimeError("source-float source audio is missing its current channel receipt")
    return value


def _segment_command(job: BusRender, pair: tuple[Segment, Segment | None],
                     channels: dict) -> tuple[list[str], str]:
    """Use the same source windows/J-cut seek math with explicit unity policy."""
    segment, following = pair
    paths = {row["id"]: row["path"] for row in job.admission.sources}
    sources = {row["path"]: row for row in job.admission.sources}
    path = paths[segment.source_id]
    authority = _authority(path, channels, sources)
    seek = max(0, segment.src_start - PRESEEK_PAD_S)
    length = (segment.src_end - segment.src_start) / segment.speed
    tail = (TailLead(following.audio_lead_s, paths[following.source_id],
                     following.src_start, following.speed)
            if following is not None and following.audio_lead_s > 0 else None)
    own = length - (tail.lead_s if tail else 0)
    command = [job.admission.tools["ffmpeg"]["path"], "-nostdin", "-v", "error",
               "-xerror", "-err_detect", "explode", "-n"]
    command += (["-ss", f"{seek:.6f}"] if seek > 0 else []) + ["-i", path]
    if authority is None:
        command += ["-f", "lavfi", "-t", str(own + 1), "-i", "anullsrc=r=48000:cl=stereo"]
    filters = source_filter(CutAudioFilter(segment.src_start - seek, own, segment.speed,
        authority, preserve_unity=True, source_end=segment.src_start + own * segment.speed - seek), "own")
    if tail is None:
        return command, filters + ";[own]anull[combined]"
    lead = _authority(tail.src_path, channels, sources)
    command += _tail_inputs(tail, lead is not None)
    end = tail.src_start - _tail_seek(tail) if lead is not None else tail.src_start
    index = 1 if authority is not None else 2
    filters += ";" + source_filter(CutAudioFilter(
        end - tail.lead_s * tail.speed, tail.lead_s, tail.speed, lead,
        index, index, True, end), "tail")
    return command, filters + ";[own][tail]concat=n=2:v=0:a=1[combined]"


def _declick_tail(target: Path, samples: int) -> None:
    """Re-apply the qsin edge fade on the exact fitted window (stereo float32).

    Fitting can truncate up to one frame past the nominal fade, which left a
    full-amplitude step at the seam (adversarial review 2026-09-06)."""
    fade = min(int(48_000 * AUDIO["join_crossfade_ms"] / 1000), samples // 2)
    if fade <= 0:
        return
    with target.open("r+b") as handle:
        handle.seek((samples - fade) * 8)
        tail = array("f")
        tail.frombytes(handle.read(fade * 8))
        for index in range(fade):
            gain = math.cos(math.pi / 2 * (index + 1) / fade)
            tail[2 * index] *= gain
            tail[2 * index + 1] *= gain
        handle.seek((samples - fade) * 8)
        handle.write(tail.tobytes())


def fit_float_samples(source: Path, target: Path, samples: int, tolerance: int) -> int:
    """Public seam for the private preview: same fit, same tolerance, same declick."""
    return _fit_samples(source, target, samples, tolerance)


def _float_identity(info: os.stat_result) -> tuple:
    """Bind the measured input to one unchanged regular, unaliased file."""
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_nlink)


@contextmanager
def _float_source(path: Path) -> Iterator[tuple[BinaryIO, int]]:
    """Hold a nonblocking descriptor from byte-count measurement through copy."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise RuntimeError("source-float input must be one regular unaliased file")
        identity = _float_identity(before)
        if _float_identity(path.lstat()) != identity:
            raise RuntimeError("source-float input changed before measurement")
        yield handle, before.st_size
        if _float_identity(os.fstat(handle.fileno())) != identity \
                or _float_identity(path.lstat()) != identity:
            raise RuntimeError("source-float input changed during fitting")


def _copy_float_prefix(source: BinaryIO, target: BinaryIO, size: int) -> None:
    """Copy measured bytes exactly; unexpected EOF is never rounding silence."""
    while size:
        data = source.read(min(size, 1024 * 1024))
        if not data:
            raise RuntimeError("source-float input ended before its measured byte count")
        target.write(data)
        size -= len(data)


def _fit_samples(source: Path, target: Path, samples: int, tolerance: int) -> int:
    """Fit only proved sub-frame quantization; don't hide missing source audio."""
    if type(samples) is not int or type(tolerance) is not int or samples <= 0 or tolerance < 0:
        raise RuntimeError("source-float sample count and tolerance must be valid integers")
    with _float_source(source) as (input_file, size):
        if size == 0:
            raise RuntimeError("source-float decoded audio is empty, not quantization silence")
        if size % 8 or abs(size // 8 - samples) > tolerance:
            raise RuntimeError("source-float audio differs from executed picture by more than one frame")
        with target.open("xb") as output:
            _copy_float_prefix(input_file, output, min(size, samples * 8))
            output.write(bytes(max(0, samples * 8 - size)))
    _declick_tail(target, samples)
    return samples - size // 8


def _float_parts(job: BusRender, channels: dict, directory: Path) -> list[dict]:
    """Compute every window on the accumulated executed frame/sample grid."""
    segments = compile_plan(job.plan).segments
    manifestation = verify_manifestation(job.output_directory, job.plan)
    rate = Fraction(manifestation["frameRate"])
    rows, frames, previous = [], 0, 0
    if len(segments) != len(job.parts):
        raise RuntimeError("source-float cut-part coverage is incomplete")
    for index, segment in enumerate(segments):
        part_frames = probe_video_frames(job.parts[index])
        sealed = manifestation["parts"][index]
        if part_frames != sealed["partFrames"] or file_sha256(job.parts[index]) != sealed["partSha256"]:
            raise RuntimeError("source-float executed part differs from cut manifestation")
        frames += part_frames
        end = round(Fraction(frames, 1) / rate * 48_000)
        following = segments[index + 1] if index + 1 < len(segments) else None
        command, filters = _segment_command(job, (segment, following), channels)
        raw, fitted = directory / f"raw-{index:04d}.f32", directory / f"part-{index:04d}.f32"
        run_audio(command + ["-filter_complex", filters, "-map", "[combined]",
                            "-ar", "48000", "-ac", "2", "-c:a", "pcm_f32le", "-f", "f32le", str(raw)])
        adjustment = _fit_samples(raw, fitted, end - previous, math.ceil(48_000 / rate) + 1)
        rows.append({"index": index, "sourceId": segment.source_id,
            "srcStart": segment.src_start, "srcEnd": segment.src_end, "speed": segment.speed,
            "nextAudioLeadS": following.audio_lead_s if following else 0,
            "videoFrames": part_frames, "startSample": previous, "endSample": end,
            "quantizationFitSamples": adjustment, "path": str(fitted),
            "sha256": file_sha256(str(fitted))})
        previous = end
    return rows


def _concat(rows: list[dict], directory: Path, ffmpeg: str) -> Path:
    """Concatenate exact float bytes and wrap once in a lossless WAV bus."""
    joined = directory / "dialogue.f32"
    with joined.open("xb") as output:
        for row in rows:
            if file_sha256(row["path"]) != row["sha256"]:
                raise RuntimeError("source-float part bytes changed before concat")
            with open(row["path"], "rb") as source:
                while data := source.read(1024 * 1024):
                    output.write(data)
    if joined.stat().st_size != rows[-1]["endSample"] * 8:
        raise RuntimeError("source-float concat has the wrong sample count")
    wav = directory / "dialogue.wav"
    run_audio([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-n", "-f", "f32le",
               "-ar", "48000", "-ac", "2", "-i", str(joined), "-c:a", "pcm_f32le", str(wav)])
    return wav


def render_source_bus(job: BusRender) -> SourceAudioBus:
    """Render and retain an unmastered exact bus; never read the concat AAC."""
    assert_admission(job.admission, job.plan)
    channels = channel_authorities(job.admission, job.cut_proof["channelNormalizationReceipts"])
    directory = Path(tempfile.mkdtemp(prefix=f".{job.admission.policy}-", dir=job.output_directory))
    rows = _float_parts(job, channels, directory)
    path = _concat(rows, directory, job.admission.tools["ffmpeg"]["path"])
    assert_admission(job.admission, job.plan)
    manifestation = verify_manifestation(job.output_directory, job.plan)
    body = {"schemaVersion": 2 if job.admission.policy == SOURCE_FLOAT_POLICY_V2 else 1,
        "kind": "ordinary-source-float-bus",
        "audioClockPolicy": job.admission.policy, "planHash": job.admission.plan_hash,
        "manifestHash": job.admission.manifest_hash, "sourceSetDigest": job.admission.source_set_digest,
        "cutManifestationHash": manifestation["receiptHash"], "sampleRate": 48000,
        "channels": 2, "codec": "pcm_f32le", "sampleFormat": "flt", "masteringApplied": False,
        "frameRate": manifestation["frameRate"], "totalSamples": rows[-1]["endSample"],
        "videoFrames": sum(row["videoFrames"] for row in rows), "parts": rows,
        "sourceFacts": list(job.admission.sources), "channelReceipts": job.cut_proof["channelNormalizationReceipts"],
        "path": str(path), "sha256": file_sha256(str(path)), "tools": job.admission.tools,
        "code": list(job.admission.code)}
    if job.admission.policy == SOURCE_FLOAT_POLICY_V2:
        body.update(audioInputHash=job.admission.audio_input_hash,
                    manifestSourceHash=job.admission.manifest_source_hash)
    receipt = seal_audio_record(str(directory / "bus-receipt.json"), body)
    return SourceAudioBus(str(path), body["sha256"], body["totalSamples"], body["frameRate"],
                          body["videoFrames"], str(directory), receipt, job.admission, job.output_directory)


def verify_source_bus(bus: SourceAudioBus, plan: dict) -> None:
    """Refuse stale current-run state or changed retained bus bytes."""
    assert_admission(bus.admission, plan)
    if file_sha256(bus.path) != bus.sha256:
        raise RuntimeError("source-float retained dialogue bus changed before mastering")
    receipt_path = Path(bus.directory) / "bus-receipt.json"
    if json.loads(receipt_path.read_text(encoding="utf-8")) != bus.receipt:
        raise RuntimeError("source-float retained bus receipt changed")
    manifestation = verify_manifestation(bus.manifestation_root or str(Path(bus.directory).parent), plan)
    if manifestation["receiptHash"] != bus.receipt["cutManifestationHash"]:
        raise RuntimeError("source-float cut manifestation changed")
    document = json.loads(run_audio([bus.admission.tools["ffprobe"]["path"], "-v", "error",
        "-show_streams", "-of", "json", bus.path]))
    rows = document.get("streams", [])
    if len(rows) != 1:
        raise RuntimeError("source-float bus must contain exactly one PCM audio stream")
    audio = rows[0]
    samples = Fraction(audio["duration_ts"]) * Fraction(audio["time_base"]) * 48000
    if audio.get("codec_name") != "pcm_f32le" or audio.get("sample_fmt") != "flt" \
            or audio.get("channels") != 2 or audio.get("sample_rate") != "48000" \
            or samples != bus.samples:
        raise RuntimeError("source-float bus format or exact sample clock changed")
