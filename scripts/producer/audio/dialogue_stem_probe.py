"""Pinned-tool media probes for exact dialogue-stem rendering."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, replace

from audio.channel_normalization import (
    ChannelNormalizationError,
    ChannelTools,
    observe_channel_authority,
    selected_stream_request,
)
from audio.dialogue_stem_contracts import (
    DialogueSourceSnapshot,
    DialogueStemRenderError,
    DialogueStemTools,
)
from fingerprints import file_sha256


@dataclass(frozen=True)
class FileIdentity:
    """Fields that must remain stable for one held source pathname."""

    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int
    links: int


@dataclass(frozen=True)
class DecodedSource:
    """One proved native-rate, contiguous PCM staging snapshot."""

    source: DialogueSourceSnapshot
    identity: FileIdentity
    native_pcm_path: str
    proof: dict[str, object]
    project_pcm_path: str = ""


def run_media(command: list[str], label: str) -> str:
    """Run one argument-vector-only media command and bound its failure."""
    result = subprocess.run(
        command, text=True, capture_output=True, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout)[-2000:].strip()
        raise DialogueStemRenderError(f"{label} failed: {detail}")
    return result.stdout


def file_identity(path: str) -> FileIdentity:
    """Observe the closed identity fields used for source drift checks."""
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise DialogueStemRenderError(
            f"dialogue source identity is unreadable: {exc}") from exc
    return FileIdentity(
        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
        info.st_ctime_ns, info.st_nlink)


def assert_source_stable(decoded: DecodedSource) -> None:
    """Reprove source path identity and bytes after all media work."""
    source = decoded.source
    if file_identity(source.path) != decoded.identity \
            or file_sha256(source.path) != source.sha256:
        raise DialogueStemRenderError(
            f"dialogue source changed during render: {source.source_id}")


def require_rubberband(tools: DialogueStemTools) -> None:
    """Require the pinned pitch-preserving retimer; never silently fall back."""
    output = run_media(
        [tools.ffmpeg_path, "-hide_banner", "-filters"],
        "FFmpeg filter capability probe")
    rows = [row.split() for row in output.splitlines()]
    if not any("rubberband" in row for row in rows):
        raise DialogueStemRenderError(
            "pinned FFmpeg lacks the required rubberband retime filter")


def _probe_streams(path: str, tools: DialogueStemTools) -> list[dict]:
    raw = run_media([
        tools.ffprobe_path, "-v", "error", "-show_streams",
        "-of", "json", path,
    ], "FFprobe stream inspection")
    try:
        streams = json.loads(raw).get("streams")
    except (AttributeError, json.JSONDecodeError) as exc:
        raise DialogueStemRenderError("FFprobe returned malformed JSON") from exc
    if not isinstance(streams, list) \
            or not all(isinstance(row, dict) for row in streams):
        raise DialogueStemRenderError("FFprobe returned malformed streams")
    return streams


def _source_stream(
    source: DialogueSourceSnapshot,
    expected_rate: int,
    tools: DialogueStemTools,
) -> dict[str, object]:
    matches = [
        row for row in _probe_streams(source.path, tools)
        if row.get("index") == source.audio_stream_index
    ]
    if len(matches) != 1 or matches[0].get("codec_type") != "audio":
        raise DialogueStemRenderError(
            f"{source.source_id} audio stream selector is not unique")
    row = matches[0]
    try:
        sample_rate = int(row.get("sample_rate", 0))
        channels = int(row.get("channels", 0))
    except (TypeError, ValueError) as exc:
        raise DialogueStemRenderError(
            f"{source.source_id} audio stream clock is malformed") from exc
    if sample_rate != expected_rate or channels <= 0:
        raise DialogueStemRenderError(
            f"{source.source_id} audio stream does not match map clock")
    codec = row.get("codec_name")
    if not isinstance(codec, str) or not codec:
        raise DialogueStemRenderError(
            f"{source.source_id} audio codec is unproved")
    layout = row.get("channel_layout")
    if not isinstance(layout, str) or not layout:
        layout = f"{channels}ch-unspecified"
    return {
        "sourceSampleRate": sample_rate,
        "sourceChannels": channels,
        "sourceChannelLayout": layout,
        "sourceCodec": codec,
    }


def probe_pcm(
    path: str,
    tools: DialogueStemTools,
    expected_rate: int,
    expected_samples: int | None = None,
) -> dict[str, object]:
    """Prove one mono signed-32 PCM WAV and its decoded sample count."""
    streams = _probe_streams(path, tools)
    audio = [row for row in streams if row.get("codec_type") == "audio"]
    if len(streams) != 1 or len(audio) != 1:
        raise DialogueStemRenderError("staged dialogue PCM is not audio-only")
    row = audio[0]
    try:
        rate = int(row.get("sample_rate", 0))
        channels = int(row.get("channels", 0))
        samples = int(row.get("duration_ts", -1))
    except (TypeError, ValueError) as exc:
        raise DialogueStemRenderError(
            "staged dialogue PCM clock is malformed") from exc
    valid = row.get("codec_name") == "pcm_s32le"
    valid = valid and row.get("sample_fmt") == "s32"
    valid = valid and rate == expected_rate and channels == 1
    valid = valid and row.get("time_base") == f"1/{expected_rate}"
    valid = valid and samples >= 0
    if expected_samples is not None:
        valid = valid and samples == expected_samples
    if not valid:
        raise DialogueStemRenderError(
            "staged dialogue PCM violates the exact output contract")
    return {
        "codec": "pcm_s32le",
        "sampleFormat": "s32",
        "sampleRate": rate,
        "channels": 1,
        "channelLayout": "mono",
        "decodedSamples": samples,
    }


def decode_source(
    source: DialogueSourceSnapshot,
    expected_rate: int,
    destination: str,
    tools: DialogueStemTools,
) -> DecodedSource:
    """Decode one selected stream once into native-rate contiguous PCM."""
    identity = file_identity(source.path)
    stream = _source_stream(source, expected_rate, tools)
    try:
        channel_authority = observe_channel_authority(
            selected_stream_request(
                source.path, source.sha256, source.audio_stream_index,
                ChannelTools(
                    tools.ffmpeg_path, tools.ffmpeg_sha256,
                    tools.ffprobe_path, tools.ffprobe_sha256)))
    except ChannelNormalizationError as exc:
        raise DialogueStemRenderError(
            f"dialogue channel normalization failed: {exc}") from exc
    command = [
        tools.ffmpeg_path, "-nostdin", "-v", "error", "-y",
        "-i", source.path, "-map", f"0:{source.audio_stream_index}", "-vn",
        "-af", f"asetpts=N/SR/TB,{channel_authority.filter_for('mono')},"
        "aformat=sample_fmts=s32:channel_layouts=mono",
        "-ar", str(expected_rate), "-c:a", "pcm_s32le",
        "-map_metadata", "-1", "-fflags", "+bitexact",
        "-flags:a", "+bitexact", destination,
    ]
    run_media(command, f"native decode for {source.source_id}")
    channel_authority.assert_stable()
    pcm = probe_pcm(destination, tools, expected_rate)
    proof = {
        "sourceId": source.source_id,
        "path": source.path,
        "sha256": source.sha256,
        "audioStreamIndex": source.audio_stream_index,
        **stream,
        "channelNormalization": channel_authority.receipt,
        "decodedSamples": pcm["decodedSamples"],
        "decodedPcmSha256": file_sha256(destination),
    }
    decoded = DecodedSource(source, identity, destination, proof)
    assert_source_stable(decoded)
    return decoded


def normalize_source(
    decoded: DecodedSource,
    project_rate: int,
    destination: str,
    tools: DialogueStemTools,
) -> DecodedSource:
    """Normalize a full native snapshot once on the absolute project clock."""
    command = [
        tools.ffmpeg_path, "-nostdin", "-v", "error", "-y",
        "-i", decoded.native_pcm_path,
        "-af", f"asetpts=N/SR/TB,aresample={project_rate}:"
        "exact_rational=1:first_pts=0,"
        "aformat=sample_fmts=s32:channel_layouts=mono",
        "-ar", str(project_rate), "-c:a", "pcm_s32le",
        "-map_metadata", "-1", "-fflags", "+bitexact",
        "-flags:a", "+bitexact", destination,
    ]
    run_media(command, f"project normalization for "
              f"{decoded.source.source_id}")
    pcm = probe_pcm(destination, tools, project_rate)
    proof = {
        **decoded.proof,
        "normalizedDecodedSamples": pcm["decodedSamples"],
        "normalizedPcmSha256": file_sha256(destination),
    }
    result = replace(
        decoded, proof=proof, project_pcm_path=destination)
    assert_source_stable(result)
    return result
