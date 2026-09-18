#!/usr/bin/env python3
"""Compare an incremental render with an independent forced-full control."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from current_render_graph_contract import canonical_bytes, file_hash, object_hash

CODEC_FLOOR_POLICY = {
    "schemaVersion": 1,
    "policyId": "sniper-libx264-codec-floor-v1",
    "meanSsimMinimum": 0.995,
    "minimumFrameSsim": 0.985,
    "minimumControlPairs": 3,
    "pictureClaim": "codec-floor-equivalent-not-pixel-identical",
}
_SSIM_ALL = re.compile(r"(?:^|\s)All:([0-9]+(?:\.[0-9]+)?)")

@dataclass(frozen=True)
class MediaObservation:
    """Exact bytes plus fully decoded elementary-stream evidence."""

    path: str
    fileSha256: str
    sizeBytes: int
    pictureFrameMd5Sha256: str
    pcmSha256: str | None
    pcmBytes: int
    streamFacts: dict

def _run(command: list[str]) -> bytes:
    result = subprocess.run(
        command, stdin=subprocess.DEVNULL, capture_output=True, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).decode(
            "utf-8", errors="replace")[-500:]
        raise RuntimeError(f"media oracle command failed: {detail}")
    return result.stdout

def _stream_hash(command: list[str]) -> tuple[str, int]:
    process = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    assert process.stdout is not None
    digest, size = hashlib.sha256(), 0
    while chunk := process.stdout.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    stderr = process.stderr.read() if process.stderr else b""
    code = process.wait()
    process.stdout.close()
    if process.stderr:
        process.stderr.close()
    if code:
        raise RuntimeError(
            "media oracle decode failed: "
            + stderr.decode("utf-8", errors="replace")[-500:])
    return digest.hexdigest(), size

def _picture_hash(command: list[str]) -> tuple[str, int]:
    process = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    assert process.stdout is not None
    digest, frames = hashlib.sha256(), 0
    for line in iter(process.stdout.readline, b""):
        digest.update(line)
        if line.strip() and not line.startswith(b"#"):
            frames += 1
    stderr = process.stderr.read() if process.stderr else b""
    code = process.wait()
    process.stdout.close()
    if process.stderr:
        process.stderr.close()
    if code:
        raise RuntimeError(
            "media oracle picture decode failed: "
            + stderr.decode("utf-8", errors="replace")[-500:])
    return digest.hexdigest(), frames


def _rational(raw: object) -> str:
    try:
        value = Fraction(str(raw))
    except (ValueError, ZeroDivisionError) as exc:
        raise RuntimeError("oracle media has an invalid frame rate") from exc
    if value <= 0:
        raise RuntimeError("oracle media has a non-positive frame rate")
    return f"{value.numerator}/{value.denominator}"


def _facts(path: Path) -> dict:
    payload = _run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,width,height,pix_fmt,r_frame_rate,"
        "sample_rate,channels", "-of", "json", str(path),
    ])
    streams = json.loads(payload).get("streams") or []
    videos = [row for row in streams if row.get("codec_type") == "video"]
    audios = [row for row in streams if row.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) > 1:
        raise RuntimeError("oracle requires one video and at most one audio stream")
    video = videos[0]
    audio = audios[0] if audios else None
    return {
        "streamTypes": [row.get("codec_type") for row in streams],
        "video": {
            "width": int(video["width"]), "height": int(video["height"]),
            "pixelFormat": str(video["pix_fmt"]),
            "frameRate": _rational(video["r_frame_rate"]),
        },
        "audio": None if audio is None else {
            "sampleRate": int(audio["sample_rate"]),
            "channels": int(audio["channels"]),
        },
    }


def observe(path: Path) -> MediaObservation:
    """Fully decode one candidate and hash normalized picture/audio authority."""
    path = path.resolve(strict=True)
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("oracle media is not a regular file")
    facts = _facts(path)
    picture, frames = _picture_hash([
        "ffmpeg", "-v", "error", "-xerror", "-i", str(path),
        "-map", "0:v:0", "-f", "framemd5", "-",
    ])
    facts["video"]["decodedFrames"] = frames
    pcm, pcm_bytes = (None, 0)
    if facts["audio"] is not None:
        pcm, pcm_bytes = _stream_hash([
            "ffmpeg", "-v", "error", "-xerror", "-i", str(path),
            "-map", "0:a:0", "-vn", "-ac", "2", "-ar", "48000",
            "-c:a", "pcm_s32le", "-f", "s32le", "-",
        ])
    return MediaObservation(
        str(path), file_hash(path), path.stat().st_size,
        picture, pcm, pcm_bytes, facts)


def _parse_ssim(path: Path) -> dict:
    values: list[float] = []
    minimum_index = 0
    for index, line in enumerate(path.read_text().splitlines(), 1):
        match = _SSIM_ALL.search(line)
        if not match:
            raise RuntimeError("SSIM emitted a malformed frame record")
        values.append(float(match.group(1)))
        if values[-1] <= values[minimum_index]:
            minimum_index = index - 1
    if not values:
        raise RuntimeError("SSIM emitted no frame records")
    return {
        "comparedFrames": len(values),
        "meanSsim": round(math.fsum(values) / len(values), 9),
        "minimumFrameSsim": round(values[minimum_index], 9),
        "minimumFrameIndex": minimum_index,
    }


def picture_similarity(left: Path, right: Path) -> dict:
    """Measure complete-frame SSIM without trusting container timestamps."""
    descriptor, name = tempfile.mkstemp(prefix="sniper-ssim-", suffix=".txt")
    os.close(descriptor)
    stats = Path(name)
    try:
        graph = (
            "[0:v:0]settb=AVTB,setpts=PTS-STARTPTS[a];"
            "[1:v:0]settb=AVTB,setpts=PTS-STARTPTS[b];"
            f"[a][b]ssim=stats_file='{stats}'[v]"
        )
        _run([
            "ffmpeg", "-v", "error", "-xerror", "-i", str(left),
            "-i", str(right), "-filter_complex", graph,
            "-map", "[v]", "-an", "-f", "null", "-",
        ])
        return _parse_ssim(stats)
    finally:
        stats.unlink(missing_ok=True)


def codec_floor_passes(metrics: dict) -> bool:
    """Apply only the pinned policy; never self-calibrate from candidates."""
    return (
        type(metrics.get("comparedFrames")) is int
        and metrics["comparedFrames"] > 0
        and metrics.get("meanSsim", -1) >= CODEC_FLOOR_POLICY["meanSsimMinimum"]
        and metrics.get("minimumFrameSsim", -1)
        >= CODEC_FLOOR_POLICY["minimumFrameSsim"]
    )


def _tool_facts() -> dict:
    rows = {}
    for name in ("ffmpeg", "ffprobe"):
        resolved = shutil.which(name)
        if not resolved:
            raise RuntimeError(f"media oracle cannot resolve {name}")
        path = Path(os.path.realpath(resolved))
        rows[name] = {"path": str(path), "sha256": file_hash(path)}
    rows["oracle"] = {
        "path": str(Path(__file__).resolve()), "sha256": file_hash(Path(__file__)),
    }
    return rows


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staged = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        try:
            os.unlink(staged)
        except FileNotFoundError:
            pass


def prove(incremental: Path, forced_full: Path, output: Path) -> dict:
    """Require exact clocks/PCM and exact pixels or pinned codec-floor parity."""
    left, right = observe(incremental), observe(forced_full)
    exact_picture = (
        left.pictureFrameMd5Sha256 == right.pictureFrameMd5Sha256)
    metrics = None if exact_picture else picture_similarity(
        Path(left.path), Path(right.path))
    expected_frames = left.streamFacts["video"]["decodedFrames"]
    codec_equivalent = exact_picture or (
        left.streamFacts == right.streamFacts
        and metrics is not None
        and metrics["comparedFrames"] == expected_frames
        and codec_floor_passes(metrics)
    )
    audio_match = (
        left.pcmSha256 == right.pcmSha256
        and left.pcmBytes == right.pcmBytes)
    facts_match = left.streamFacts == right.streamFacts
    passed = codec_equivalent and audio_match and facts_match
    receipt = {
        "schemaVersion": 1, "kind": "current-render-forced-full-oracle",
        "policy": CODEC_FLOOR_POLICY,
        "policyHash": object_hash(CODEC_FLOOR_POLICY),
        "toolchain": _tool_facts(),
        "incremental": vars(left), "forcedFull": vars(right),
        "pictureComparison": {
            "method": "exact-framemd5" if exact_picture else "full-frame-ssim",
            "pixelIdentical": exact_picture,
            "codecFloorEquivalent": codec_equivalent,
            "metrics": metrics,
            "claim": CODEC_FLOOR_POLICY["pictureClaim"],
        },
        "decodedAudioMatch": audio_match,
        "streamFactsMatch": facts_match,
        "byteIdentical": left.fileSha256 == right.fileSha256,
        "passed": passed,
    }
    receipt["receiptHash"] = object_hash(receipt)
    _write(output, receipt)
    if not passed:
        raise RuntimeError(
            "incremental render is not codec-floor equivalent to forced-full")
    return receipt


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("incremental", type=Path)
    parser.add_argument("forced_full", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        result = prove(args.incremental, args.forced_full, args.output)
        print(json.dumps({"status": "oracle_passed",
                          "receiptHash": result["receiptHash"]}))
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
