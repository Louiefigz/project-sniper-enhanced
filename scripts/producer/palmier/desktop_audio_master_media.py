"""Atomic content-addressed PCM derivation for Desktop mastered-stereo."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Any

from fingerprints import file_sha256
from palmier.desktop_audio_master_contract import (
    PROOF_KIND, RECIPE_VERSION, SAMPLE_RATE, cache_key, derivation_argv,
    exact_timing, probe_pcm, read_proof, regular_file, run_argv, tool_binary,
    validate_mastered_stereo_assets)
from palmier.master import approved_master
from palmier.mcp_client import PalmierError
from palmier.timeline_authority import atomic_write_record


@dataclass(frozen=True)
class MasteredStereoRequest:
    """Inputs needed to derive one exact Desktop audio route asset."""

    inputs: Any
    authority: Any
    project: dict
    target_frames: int
    cache_dir: str


@dataclass(frozen=True)
class MasteredStereoAsset:
    """Immutable WAV and provenance facts copied into the worklist."""

    path: str
    sha256: str
    final_path: str
    final_sha256: str
    proof_path: str
    proof_sha256: str
    pcm: dict
    frame_rate: str
    frames: int


@dataclass(frozen=True)
class _Derivation:
    target: str
    proof_path: str
    source: str
    source_hash: str
    timing: tuple
    tools: dict
    cache_dir: str


def asset_dict(asset: MasteredStereoAsset) -> dict:
    """Project a derived asset into the shared validation vocabulary."""
    return {
        "assetPath": asset.path, "assetHash": asset.sha256,
        "sourceFinalPath": asset.final_path,
        "sourceFinalHash": asset.final_sha256,
        "derivationProofPath": asset.proof_path,
        "derivationProofHash": asset.proof_sha256,
        "pcm": asset.pcm, "projectFrameRate": asset.frame_rate,
        "endFrame": asset.frames,
    }


def _render(command: list[str], temporary: str,
            context: _Derivation) -> tuple[str, dict]:
    run_argv(command, "PCM derivation")
    pcm = probe_pcm(
        temporary, context.tools["ffprobePath"], context.timing[2])
    digest = file_sha256(temporary)
    with open(temporary, "rb") as handle:
        os.fsync(handle.fileno())
    if os.path.lexists(context.target):
        if os.path.islink(context.target) \
                or not os.path.isfile(context.target) \
                or file_sha256(context.target) != digest:
            raise PalmierError("mastered-stereo cache path has conflicting bytes")
    else:
        os.replace(temporary, context.target)
    return digest, pcm


def _from_values(context: _Derivation, proof: dict) -> MasteredStereoAsset:
    asset = MasteredStereoAsset(
        context.target, file_sha256(context.target),
        context.source, context.source_hash, context.proof_path,
        file_sha256(context.proof_path), proof.get("pcm"),
        context.timing[0], context.timing[3])
    validate_mastered_stereo_assets(asset_dict(asset))
    return asset


def _cached(context: _Derivation) -> MasteredStereoAsset | None:
    if os.path.isfile(context.target) and os.path.isfile(context.proof_path):
        return _from_values(context, read_proof(context.proof_path))
    if os.path.lexists(context.target) or os.path.lexists(context.proof_path):
        raise PalmierError("mastered-stereo cache pair is incomplete or unsafe")
    return None


def _proof(context: _Derivation, digest: str,
           pcm: dict, command: list[str]) -> dict:
    return {
        "schemaVersion": 1, "kind": PROOF_KIND,
        "recipeVersion": RECIPE_VERSION,
        "source": {
            "path": context.source, "sha256": context.source_hash},
        "output": {"path": context.target, "sha256": digest},
        "timing": {
            "frameRate": context.timing[0], "fps": context.timing[1],
            "frames": context.timing[3], "sampleRate": SAMPLE_RATE,
            "decodedSamples": context.timing[2],
            "duration": {
                "numerator": context.timing[3],
                "denominator": context.timing[1]},
        },
        "pcm": pcm, "tools": context.tools, "command": command,
    }


def _derive(context: _Derivation) -> MasteredStereoAsset:
    handle, temporary = tempfile.mkstemp(
        prefix=".mastered-stereo-", suffix=".wav", dir=context.cache_dir)
    os.close(handle)
    os.unlink(temporary)
    command = derivation_argv(
        context.tools["ffmpegPath"], context.source,
        temporary, context.timing[2])
    try:
        digest, pcm = _render(command, temporary, context)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    if file_sha256(context.source) != context.source_hash:
        raise PalmierError("mastered-stereo approved final changed during decode")
    atomic_write_record(
        context.proof_path, _proof(context, digest, pcm, command))
    return _from_values(context, read_proof(context.proof_path))


def prepare_mastered_stereo_asset(
        request: MasteredStereoRequest) -> MasteredStereoAsset:
    """Create or validate one content-addressed exact PCM WAV."""
    master = approved_master(
        request.inputs.out_dir, request.inputs.plan_path,
        request.inputs.manifest_path, request.authority.plan_hash)
    timing = exact_timing(master, request.project, request.target_frames)
    source, source_hash = os.path.abspath(master.path), master.content_hash
    if regular_file(source, "approved final") != source \
            or file_sha256(source) != source_hash:
        raise PalmierError("mastered-stereo approved final changed")
    ffmpeg = tool_binary("ffmpeg", "HYPERFRAMES_FFMPEG_PATH")
    ffprobe = tool_binary("ffprobe", "HYPERFRAMES_FFPROBE_PATH")
    tools = {
        "ffmpegPath": ffmpeg[0], "ffmpegSha256": ffmpeg[1],
        "ffprobePath": ffprobe[0], "ffprobeSha256": ffprobe[1],
    }
    os.makedirs(request.cache_dir, exist_ok=True)
    if not os.path.isabs(request.cache_dir) \
            or os.path.islink(request.cache_dir) \
            or not os.path.isdir(request.cache_dir):
        raise PalmierError("mastered-stereo cache directory is unsafe")
    key = cache_key(source_hash, source, timing, tools)
    target = os.path.join(request.cache_dir, f"mastered-stereo-{key}.wav")
    proof_path = target + ".proof.json"
    context = _Derivation(
        target, proof_path, source, source_hash, timing, tools,
        request.cache_dir)
    return _cached(context) or _derive(context)
