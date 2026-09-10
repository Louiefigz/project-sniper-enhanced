"""Exact program mix of dialogue plus separately preserved auxiliary stems."""
from __future__ import annotations

import os
from dataclasses import dataclass

from audio.dialogue_program_contracts import (
    AuxiliaryStemSnapshot,
    ValidatedDialogueProgram,
)
from audio.dialogue_stem_contracts import DialogueStemRenderError
from audio.dialogue_stem_media import _write_new
from audio.dialogue_stem_probe import (
    FileIdentity,
    _probe_streams,
    file_identity,
    probe_pcm,
    run_media,
)
from fingerprints import file_sha256

PROGRAM_NAME = "dialogue-program.wav"
PROGRAM_CODEC = "pcm_f32le"
PROGRAM_SAMPLE_FORMAT = "flt"
PROGRAM_MIX_POLICY_VERSION = 2


def program_mix_policy() -> dict[str, object]:
    """Identify the headroom-preserving premix, distinct from delivery mastering."""
    return {"version": PROGRAM_MIX_POLICY_VERSION,
            "mix": "linear-sum-no-normalize", "channels": "stereo",
            "codec": PROGRAM_CODEC, "sampleFormat": PROGRAM_SAMPLE_FORMAT,
            "masteringApplied": False}


@dataclass(frozen=True)
class AuxiliaryProof:
    """One reobserved, program-aligned auxiliary PCM stream."""

    stem: AuxiliaryStemSnapshot
    identity: FileIdentity
    proof: dict[str, object]


def _selected_stream(
    stem: AuxiliaryStemSnapshot,
    request: ValidatedDialogueProgram,
) -> dict:
    matches = [
        row for row in _probe_streams(stem.path, request.tools)
        if row.get("index") == stem.audio_stream_index
    ]
    if len(matches) != 1 or matches[0].get("codec_type") != "audio":
        raise DialogueStemRenderError(
            f"auxiliary stream selector is invalid for {stem.stem_id}")
    return matches[0]


def _auxiliary_proof(
    stem: AuxiliaryStemSnapshot,
    request: ValidatedDialogueProgram,
) -> AuxiliaryProof:
    row = _selected_stream(stem, request)
    expected_rate = request.dialogue_map["projectSampleRate"]
    expected_samples = request.dialogue_map["totalOutputSamples"]
    try:
        rate = int(row.get("sample_rate", 0))
        channels = int(row.get("channels", 0))
        samples = int(row.get("duration_ts", -1))
    except (TypeError, ValueError) as exc:
        raise DialogueStemRenderError(
            f"auxiliary clock is malformed for {stem.stem_id}") from exc
    layout = row.get("channel_layout")
    valid = row.get("codec_name") == "pcm_s32le"
    valid = valid and row.get("sample_fmt") == "s32"
    valid = valid and rate == expected_rate and channels in {1, 2}
    valid = valid and layout in {"mono", "stereo"}
    valid = valid and row.get("time_base") == f"1/{expected_rate}"
    valid = valid and samples == expected_samples
    if not valid:
        raise DialogueStemRenderError(
            f"auxiliary stem {stem.stem_id} is not exact program PCM")
    proof = {
        **stem.authority_row(),
        "path": stem.path,
        "sampleRate": rate,
        "channels": channels,
        "channelLayout": layout,
        "decodedSamples": samples,
    }
    return AuxiliaryProof(stem, file_identity(stem.path), proof)


def prove_auxiliary_stems(
    request: ValidatedDialogueProgram,
) -> tuple[AuxiliaryProof, ...]:
    """Reobserve every declared room-tone, music, and SFX authority."""
    return tuple(
        _auxiliary_proof(stem, request)
        for stem in request.auxiliary_stems)


def assert_auxiliary_stable(proof: AuxiliaryProof) -> None:
    """Fail if an auxiliary pathname or any source byte changed."""
    if file_identity(proof.stem.path) != proof.identity \
            or file_sha256(proof.stem.path) != proof.stem.sha256:
        raise DialogueStemRenderError(
            f"auxiliary stem changed during render: {proof.stem.stem_id}")


def _mix_graph(count: int, total_samples: int) -> str:
    lines = []
    for index in range(count):
        lines.append(
            f"[{index}:a]atrim=end_sample={total_samples},"
            "asetpts=N/SR/TB,aformat=sample_fmts=fltp:"
            f"channel_layouts=stereo[input{index:04}]")
    inputs = "".join(f"[input{index:04}]" for index in range(count))
    lines.append(
        f"{inputs}amix=inputs={count}:duration=first:"
        f"dropout_transition=0:normalize=0,"
        f"atrim=end_sample={total_samples},asetpts=N/SR/TB,"
        f"aformat=sample_fmts={PROGRAM_SAMPLE_FORMAT}:channel_layouts=stereo[out]")
    return ";\n".join(lines) + "\n"


def _program_layout_evidence(row: dict) -> str:
    """Recognize declared stereo or the producer's two-channel IEEE-float header."""
    if row.get("channel_layout") == "stereo":
        return "declared-stereo"
    if row.get("channels") == 2 and row.get("channel_layout") is None \
            and row.get("codec_tag") == "0x0003":
        return "ieee-float-two-channel"
    raise DialogueStemRenderError("dialogue float program stereo layout is unproved")


def probe_program(
    path: str,
    request: ValidatedDialogueProgram,
) -> dict[str, object]:
    """Reobserve the exact stereo float premix without accepting legacy s32."""
    rows = _probe_streams(path, request.tools)
    if len(rows) != 1 or rows[0].get("codec_type") != "audio":
        raise DialogueStemRenderError("dialogue program is not audio-only")
    row = rows[0]
    expected_rate = request.dialogue_map["projectSampleRate"]
    expected_samples = request.dialogue_map["totalOutputSamples"]
    try:
        rate = int(row.get("sample_rate", 0))
        samples = int(row.get("duration_ts", -1))
    except (TypeError, ValueError) as exc:
        raise DialogueStemRenderError(
            "dialogue program clock is malformed") from exc
    valid = row.get("codec_name") == PROGRAM_CODEC
    valid = valid and row.get("sample_fmt") == PROGRAM_SAMPLE_FORMAT
    valid = valid and row.get("channels") == 2
    valid = valid and rate == expected_rate and samples == expected_samples
    valid = valid and row.get("time_base") == f"1/{expected_rate}"
    if not valid:
        raise DialogueStemRenderError(
            "dialogue program violates exact stereo float PCM authority")
    layout_evidence = _program_layout_evidence(row)
    return {
        "codec": PROGRAM_CODEC, "sampleFormat": PROGRAM_SAMPLE_FORMAT,
        "sampleRate": rate, "channels": 2, "channelLayout": "stereo",
        "channelLayoutEvidence": layout_evidence,
        "decodedSamples": samples,
    }


def render_dialogue_program_mix(
    request: ValidatedDialogueProgram,
    dialogue_path: str,
    auxiliary: tuple[AuxiliaryProof, ...],
    output_dir: str,
) -> tuple[str, dict[str, object]]:
    """Mix exact s32 stems into float PCM; delivery mastering is not performed."""
    total = request.dialogue_map["totalOutputSamples"]
    probe_pcm(
        dialogue_path, request.tools,
        request.dialogue_map["projectSampleRate"], total)
    script = os.path.join(output_dir, ".program-mix-filter.txt")
    _write_new(script, _mix_graph(len(auxiliary) + 1, total))
    output = os.path.join(output_dir, PROGRAM_NAME)
    command = [
        request.tools.ffmpeg_path, "-nostdin", "-v", "error", "-y",
        "-i", dialogue_path,
    ]
    for item in auxiliary:
        command.extend(["-i", item.stem.path])
    command.extend([
        "-filter_complex_script", script, "-map", "[out]",
        "-ar", str(request.dialogue_map["projectSampleRate"]),
        "-ac", "2", "-c:a", PROGRAM_CODEC, "-map_metadata", "-1",
        "-fflags", "+bitexact", "-flags:a", "+bitexact", output,
    ])
    run_media(command, "exact dialogue program mix")
    os.unlink(script)
    return output, probe_program(output, request)
