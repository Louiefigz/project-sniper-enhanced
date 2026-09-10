"""Frame/sample-bounded media compositor for private scene-unit review."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from audio.channel_normalization import verify_channel_receipt
from edit.exact_timing import FrameRange, PositiveRational, ProjectClock
from fingerprints import file_sha256
from graphics.render_tools import resolve_tools
from graphics.scene_contract import SceneContractError, validate_scene


@dataclass(frozen=True)
class SceneReviewMediaRequest:
    """Exact authorities for one local review-fragment encode."""

    scene: dict
    bindings: dict
    base_path: str
    output_path: str
    channel_receipt: dict
    sample_rate: int = 48_000


def _run(command: list[str], binary: bool = False) -> bytes | str:
    result = subprocess.run(
        command, stdin=subprocess.DEVNULL, capture_output=True,
        text=not binary, check=False)
    if result.returncode:
        error = result.stderr
        if isinstance(error, bytes):
            error = error.decode("utf-8", errors="replace")
        detail = str(error or result.stdout or "").strip().splitlines()[-12:]
        raise SceneContractError(
            "\n".join(detail) or f"{command[0]} failed")
    return result.stdout


def _regular(path: str, label: str) -> str:
    valid = isinstance(path, str) and os.path.isabs(path) \
        and os.path.normpath(path) == path and os.path.realpath(path) == path
    if not valid or os.path.islink(path) or not os.path.isfile(path):
        raise SceneContractError(f"{label} must be a canonical regular file")
    if os.stat(path, follow_symlinks=False).st_nlink != 1:
        raise SceneContractError(f"{label} must be a single-link snapshot")
    return path


def _output(path: str) -> tuple[str, str]:
    if not isinstance(path, str) or not os.path.isabs(path) \
            or os.path.normpath(path) != path or not path.endswith(".mov"):
        raise SceneContractError(
            "scene review output must be an absolute normalized .mov path")
    parent = os.path.dirname(path)
    if os.path.realpath(parent) != parent or os.path.islink(parent) \
            or not os.path.isdir(parent) or os.path.lexists(path):
        raise SceneContractError(
            "scene review output needs a canonical directory and unused name")
    return path, parent


def media_identity(path: str) -> dict:
    """Hash one immutable media file without treating its atime as identity."""
    canonical = _regular(path, "scene review media")
    stat = os.stat(canonical, follow_symlinks=False)
    return {
        "path": canonical, "sha256": file_sha256(canonical),
        "sizeBytes": stat.st_size, "mtimeNs": str(stat.st_mtime_ns),
    }


def _probe(path: str, ffprobe: str, count: bool = False) -> list[dict]:
    entries = (
        "stream=codec_type,width,height,pix_fmt,r_frame_rate,"
        "sample_rate,channels,nb_read_frames")
    command = [ffprobe, "-v", "error"]
    if count:
        command.append("-count_frames")
    command.extend(["-show_entries", entries, "-of", "json", path])
    raw = _run(command)
    return json.loads(str(raw)).get("streams") or []


def _base_facts(
    request: SceneReviewMediaRequest, scene: dict, ffprobe: str,
) -> dict:
    streams = _probe(request.base_path, ffprobe)
    videos = [row for row in streams if row.get("codec_type") == "video"]
    audios = [row for row in streams if row.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise SceneContractError(
            "scene review base needs one video stream and one audio stream")
    video, audio = videos[0], audios[0]
    fps = scene["timing"]["fps"]
    expected_rate = f"{fps['numerator']}/{fps['denominator']}"
    canvas = scene["canvas"]
    observed = {
        "width": int(video["width"]), "height": int(video["height"]),
        "frameRate": video["r_frame_rate"],
        "sampleRate": int(audio["sample_rate"]),
        "audioChannels": int(audio["channels"]),
    }
    expected = {
        "width": canvas["width"], "height": canvas["height"],
        "frameRate": expected_rate, "sampleRate": request.sample_rate,
    }
    if any(observed[key] != value for key, value in expected.items()):
        raise SceneContractError(
            "scene review base differs from scene canvas/rate/audio clock")
    return observed


def _unit_paths(scene: dict, bindings: dict) -> list[str]:
    rows = bindings.get("entries")
    if bindings.get("sceneId") != scene["sceneId"] \
            or not isinstance(rows, list):
        raise SceneContractError("scene review bindings target another scene")
    indexed = {row.get("unitId"): row for row in rows
               if isinstance(row, dict)}
    units = sorted(scene["renderUnits"], key=lambda row: row["zIndex"])
    expected = {row["unitId"] for row in units}
    if set(indexed) != expected \
            or any(row["palmierGranularity"] != "unit"
                   or row["compositeMode"] != "normal" for row in units):
        raise SceneContractError(
            "scene review currently requires normal independent units")
    return [
        _regular(indexed[row["unitId"]]["media"]["path"], "scene unit media")
        for row in units
    ]


def _filters(
    frames: FrameRange, clock: ProjectClock, unit_count: int,
    audio_filter: str,
) -> tuple[str, str]:
    samples = clock.samples_for_frames(frames)
    parts = [
        f"[0:v]trim=start_frame={frames.start_frame}:"
        f"end_frame={frames.end_frame_exclusive},"
        "setpts=PTS-STARTPTS[base]",
        f"[0:a]{audio_filter},"
        f"atrim=start_sample={samples.start_sample}:"
        f"end_sample={samples.end_sample_exclusive},"
        f"asetpts=PTS-STARTPTS,atrim=end_sample={samples.length}[audio]",
    ]
    previous = "[base]"
    for index in range(unit_count):
        unit, output = f"[unit{index}]", f"[overlay{index}]"
        parts.append(
            f"[{index + 1}:v]setpts=PTS-STARTPTS{unit}")
        parts.append(
            f"{previous}{unit}overlay=0:0:format=auto:"
            f"eof_action=pass{output}")
        previous = output
    parts.append(f"{previous}format=yuv420p[video]")
    return ";".join(parts), "[video]"


def _render(
    request: SceneReviewMediaRequest, units: list[str],
    staged: str, ffmpeg: str,
) -> None:
    scene = request.scene
    timing = scene["timing"]
    frames = FrameRange(
        timing["startFrame"], timing["endFrameExclusive"])
    rate = PositiveRational.from_value(timing["fps"])
    clock = ProjectClock(rate, request.sample_rate)
    audio_filter = str(
        request.channel_receipt["decision"]["stereoFilter"])
    graph, video = _filters(
        frames, clock, len(units), audio_filter)
    command = [ffmpeg, "-y", "-nostdin", "-v", "error",
               "-i", request.base_path]
    for path in units:
        command.extend(["-i", path])
    command.extend([
        "-filter_complex", graph, "-map", video, "-map", "[audio]",
        "-frames:v", str(frames.length), "-c:v", "libx264", "-qp", "0",
        "-preset", "fast", "-pix_fmt", "yuv420p", "-fps_mode", "cfr",
        "-r", f"{rate.numerator}/{rate.denominator}",
        "-c:a", "pcm_s32le", "-ar", str(request.sample_rate), "-ac", "2",
        staged,
    ])
    _run(command)


def _pcm(path: str, ffmpeg: str, sample_rate: int) -> tuple[str, int]:
    raw = _run([
        ffmpeg, "-v", "error", "-xerror", "-i", path, "-map", "0:a:0",
        "-f", "s32le", "-ac", "2", "-ar", str(sample_rate), "-",
    ], binary=True)
    if not isinstance(raw, bytes) or len(raw) % 8:
        raise SceneContractError("scene review decoded PCM is malformed")
    return hashlib.sha256(raw).hexdigest(), len(raw) // 8


def _prove(
    path: str, scene: dict, sample_rate: int, tools: dict[str, str],
) -> dict:
    streams = _probe(path, tools["ffprobe"], count=True)
    videos = [row for row in streams if row.get("codec_type") == "video"]
    audios = [row for row in streams if row.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise SceneContractError("scene review output stream closure is invalid")
    timing = scene["timing"]
    frames = FrameRange(
        timing["startFrame"], timing["endFrameExclusive"])
    clock = ProjectClock(
        PositiveRational.from_value(timing["fps"]), sample_rate)
    pcm_hash, samples = _pcm(path, tools["ffmpeg"], sample_rate)
    video = videos[0]
    facts = {
        "decodedFrames": int(video["nb_read_frames"]),
        "decodedSamplesPerChannel": samples,
        "decodedPcmSha256": pcm_hash,
        "frameRate": video["r_frame_rate"],
        "width": int(video["width"]), "height": int(video["height"]),
        "audioStreamCount": 1, "fullDecode": "ffmpeg-xerror-av-v1",
    }
    expected = {
        "decodedFrames": frames.length,
        "decodedSamplesPerChannel": clock.samples_for_frames(frames).length,
        "frameRate":
            f"{clock.fps.numerator}/{clock.fps.denominator}",
        "width": scene["canvas"]["width"],
        "height": scene["canvas"]["height"],
    }
    if any(facts[key] != value for key, value in expected.items()):
        raise SceneContractError(
            "scene review output misses exact frame/sample authority")
    _run([tools["ffmpeg"], "-v", "error", "-xerror",
          "-i", path, "-f", "null", "-"])
    return facts


def render_review_fragment(request: SceneReviewMediaRequest) -> dict:
    """Encode only one scene window; never construct a full-program candidate."""
    scene = validate_scene(request.scene)
    if scene["renderMode"] != "overlay-alpha":
        raise SceneContractError(
            "scene review compositor currently supports alpha overlays only")
    if type(request.sample_rate) is not int or request.sample_rate < 8_000:
        raise SceneContractError("scene review sample rate is invalid")
    base = _regular(request.base_path, "scene review base")
    output, parent = _output(request.output_path)
    tools = resolve_tools()
    channel = verify_channel_receipt(request.channel_receipt)
    source = channel["source"]
    if source["path"] != base or source["sha256"] != file_sha256(base) \
            or source["selector"] != "a:0" \
            or channel["stream"]["channels"] != 2 \
            or channel["stream"]["sampleRate"] != request.sample_rate:
        raise SceneContractError(
            "scene review base lacks exact stereo channel authority")
    base_facts = _base_facts(request, scene, tools["ffprobe"])
    units = _unit_paths(scene, request.bindings)
    with tempfile.TemporaryDirectory(
            prefix=".scene-review-", dir=parent) as attempt:
        staged = str(Path(attempt) / "review.mov")
        _render(request, units, staged, tools["ffmpeg"])
        evidence = _prove(staged, scene, request.sample_rate, tools)
        os.link(staged, output, follow_symlinks=False)
    return {
        "baseFacts": base_facts, "output": media_identity(output),
        "decode": evidence,
        "channelNormalization": {
            "receiptHash": channel["receiptHash"],
            "status": channel["decision"]["status"],
            "stereoFilter": channel["decision"]["stereoFilter"],
        },
        "toolchain": {
            name: {"path": tools[name], "sha256": file_sha256(tools[name])}
            for name in ("ffmpeg", "ffprobe")
        },
    }
