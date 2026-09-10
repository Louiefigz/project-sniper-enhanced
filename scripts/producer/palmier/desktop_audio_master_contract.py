"""Freshness and PCM evidence contract for a Desktop mastered-stereo asset."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from fractions import Fraction
from typing import Any

from fingerprints import file_sha256
from palmier.mcp_client import PalmierError

SAMPLE_RATE = 48_000
PCM_CODEC = "pcm_s32le"
PROOF_KIND = "palmier-mastered-stereo-pcm"
RECIPE_VERSION = 1


def regular_file(path: object, label: str) -> str:
    """Return one absolute, non-symlink regular file."""
    if not isinstance(path, str) or not os.path.isabs(path) \
            or os.path.islink(path) or not os.path.isfile(path):
        raise PalmierError(f"mastered-stereo {label} is not a regular file")
    return path


def tool_binary(name: str, pin: str) -> tuple[str, str]:
    """Resolve and hash one executable media tool."""
    found = os.environ.get(pin, "").strip() or shutil.which(name)
    if not found:
        raise PalmierError(f"mastered-stereo requires local {name}")
    path = os.path.realpath(found)
    if not os.path.isabs(path) or not os.path.isfile(path) \
            or not os.access(path, os.X_OK):
        raise PalmierError(f"mastered-stereo {name} is not executable")
    return path, file_sha256(path)


def run_argv(command: list[str], label: str) -> str:
    """Run an exact argv without a shell and return stdout."""
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise PalmierError(
            f"mastered-stereo {label} could not run: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout)[-1600:].strip()
        raise PalmierError(f"mastered-stereo {label} failed: {detail}")
    return result.stdout


def derivation_argv(ffmpeg: str, source: str,
                    output: str, samples: int) -> list[str]:
    """Build the only admitted PCM derivation argv."""
    return [
        ffmpeg, "-nostdin", "-v", "error", "-n", "-i", source,
        "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-af", f"aresample={SAMPLE_RATE},aformat=sample_fmts=s32:"
        "channel_layouts=stereo,asetpts=N/SR/TB,apad,"
        f"atrim=end_sample={samples}",
        "-ar", str(SAMPLE_RATE), "-ac", "2", "-c:a", PCM_CODEC,
        "-map_metadata", "-1", "-fflags", "+bitexact",
        "-flags:a", "+bitexact", output,
    ]


def probe_pcm(path: str, ffprobe: str, samples: int) -> dict:
    """Prove exact codec, channel layout, clock, and decoded sample count."""
    raw = run_argv([
        ffprobe, "-v", "error", "-show_streams", "-of", "json", path,
    ], "PCM probe")
    try:
        streams = json.loads(raw).get("streams")
    except (AttributeError, json.JSONDecodeError) as exc:
        raise PalmierError("mastered-stereo PCM probe is malformed") from exc
    audio = [row for row in streams or []
             if isinstance(row, dict) and row.get("codec_type") == "audio"]
    if not isinstance(streams, list) or len(streams) != 1 or len(audio) != 1:
        raise PalmierError("mastered-stereo WAV is not one audio-only stream")
    row = audio[0]
    try:
        rate = int(row.get("sample_rate", 0))
        channels = int(row.get("channels", 0))
        decoded = int(row.get("duration_ts", -1))
    except (TypeError, ValueError) as exc:
        raise PalmierError("mastered-stereo PCM clock is malformed") from exc
    valid = row.get("codec_name") == PCM_CODEC \
        and row.get("sample_fmt") == "s32" \
        and rate == SAMPLE_RATE and channels == 2 \
        and row.get("channel_layout") == "stereo" \
        and row.get("time_base") == f"1/{SAMPLE_RATE}" \
        and decoded == samples
    if not valid:
        raise PalmierError("mastered-stereo WAV violates exact PCM authority")
    return {
        "codec": PCM_CODEC, "sampleFormat": "s32",
        "sampleRate": rate, "channels": channels,
        "channelLayout": "stereo", "decodedSamples": decoded,
    }


def exact_timing(master: Any, project: dict,
                 target_frames: int) -> tuple[str, int, int, int]:
    """Cross-bind approved final, project fps, frames, and PCM samples."""
    fps = (project.get("projectSettings") or {}).get("fps")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) \
            or fps <= 0 or not float(fps).is_integer():
        raise PalmierError("mastered-stereo requires an integer Palmier rate")
    try:
        master_rate = Fraction(str(master.frame_rate))
    except (ValueError, ZeroDivisionError) as exc:
        raise PalmierError("mastered-stereo final has no exact frame rate") from exc
    integer_fps = int(fps)
    if master_rate != Fraction(integer_fps, 1) \
            or master.end_frame != target_frames or target_frames <= 0:
        raise PalmierError("mastered-stereo final differs from project duration/rate")
    sample_count = Fraction(target_frames * SAMPLE_RATE, integer_fps)
    if sample_count.denominator != 1:
        raise PalmierError("mastered-stereo duration is not sample-exact")
    return f"{integer_fps}/1", integer_fps, sample_count.numerator, target_frames


def cache_key(source_hash: str, source_path: str,
              timing: tuple, tools: dict) -> str:
    """Hash every fact that can change decoded PCM bytes or their window."""
    value = {
        "kind": PROOF_KIND, "recipeVersion": RECIPE_VERSION,
        "sourcePath": source_path, "sourceSha256": source_hash,
        "frameRate": timing[0], "frames": timing[3],
        "sampleRate": SAMPLE_RATE, "decodedSamples": timing[2],
        "tools": tools,
    }
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def read_proof(path: str) -> dict:
    """Read one derivation proof as an object."""
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"mastered-stereo proof is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError("mastered-stereo proof is malformed")
    return value


def _expected_timing(asset: dict) -> dict | None:
    value, frames = asset.get("projectFrameRate"), asset.get("endFrame")
    samples = (asset.get("pcm") or {}).get("decodedSamples")
    try:
        rate = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None
    valid = rate.denominator == 1 and rate.numerator > 0 \
        and isinstance(frames, int) and not isinstance(frames, bool) \
        and frames > 0 and isinstance(samples, int) \
        and not isinstance(samples, bool) and samples > 0
    if not valid or Fraction(frames * SAMPLE_RATE, rate.numerator) != samples:
        return None
    return {
        "frameRate": value, "fps": rate.numerator, "frames": frames,
        "sampleRate": SAMPLE_RATE, "decodedSamples": samples,
        "duration": {"numerator": frames, "denominator": rate.numerator},
    }


def _command_valid(proof: dict, asset: dict) -> bool:
    command, tools = proof.get("command"), proof.get("tools")
    if not isinstance(command, list) or not command \
            or any(not isinstance(value, str) for value in command) \
            or not isinstance(tools, dict):
        return False
    temporary = command[-1]
    valid_temp = os.path.isabs(temporary) \
        and os.path.dirname(temporary) == os.path.dirname(asset["assetPath"]) \
        and os.path.basename(temporary).startswith(".mastered-stereo-") \
        and temporary.endswith(".wav") and temporary != asset["assetPath"]
    samples = asset["pcm"].get("decodedSamples")
    return valid_temp and command == derivation_argv(
        tools.get("ffmpegPath"), asset["sourceFinalPath"],
        temporary, samples)


def _proof_valid(proof: dict, asset: dict) -> bool:
    required = {"schemaVersion", "kind", "recipeVersion", "source",
                "output", "timing", "pcm", "tools", "command"}
    output, source, timing = (
        proof.get("output"), proof.get("source"), proof.get("timing"))
    return set(proof) == required and proof.get("schemaVersion") == 1 \
        and proof.get("kind") == PROOF_KIND \
        and proof.get("recipeVersion") == RECIPE_VERSION \
        and isinstance(output, dict) and isinstance(source, dict) \
        and isinstance(timing, dict) \
        and output == {
            "path": asset["assetPath"], "sha256": asset["assetHash"]} \
        and source == {
            "path": asset["sourceFinalPath"],
            "sha256": asset["sourceFinalHash"]} \
        and proof.get("pcm") == asset["pcm"] \
        and timing == _expected_timing(asset) \
        and _command_valid(proof, asset)


def _validate_tools(proof: dict) -> tuple[str, str]:
    tools = proof.get("tools")
    expected = {
        "ffmpegPath", "ffmpegSha256", "ffprobePath", "ffprobeSha256"}
    if not isinstance(tools, dict) or set(tools) != expected:
        raise PalmierError("mastered-stereo proof tools are malformed")
    paths = (tools.get("ffmpegPath"), tools.get("ffprobePath"))
    hashes = (tools.get("ffmpegSha256"), tools.get("ffprobeSha256"))
    for path, digest, label in zip(paths, hashes, ("ffmpeg", "ffprobe")):
        if regular_file(path, f"proof {label}") != path \
                or file_sha256(path) != digest:
            raise PalmierError(f"mastered-stereo proof {label} changed")
    return paths[0], paths[1]


def validate_mastered_stereo_assets(value: dict) -> dict:
    """Reobserve WAV, final, proof, tools, and exact PCM facts."""
    asset = dict(value)
    asset["assetPath"] = regular_file(asset.get("assetPath"), "WAV")
    asset["sourceFinalPath"] = regular_file(
        asset.get("sourceFinalPath"), "approved final")
    proof_path = regular_file(asset.get("derivationProofPath"), "proof")
    expected = (
        asset.get("assetHash"), asset.get("sourceFinalHash"),
        asset.get("derivationProofHash"))
    actual = (
        file_sha256(asset["assetPath"]), file_sha256(asset["sourceFinalPath"]),
        file_sha256(proof_path))
    if expected != actual:
        raise PalmierError("mastered-stereo WAV/final/proof bytes changed")
    proof = read_proof(proof_path)
    if not isinstance(asset.get("pcm"), dict) or not _proof_valid(proof, asset):
        raise PalmierError("mastered-stereo derivation proof changed")
    _ffmpeg, ffprobe = _validate_tools(proof)
    samples = asset["pcm"].get("decodedSamples")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise PalmierError("mastered-stereo proof has no decoded sample count")
    if probe_pcm(asset["assetPath"], ffprobe, samples) != asset["pcm"]:
        raise PalmierError("mastered-stereo WAV no longer matches its PCM proof")
    return asset
