"""TEST-only retained media and exact pre-optimization observer for comparison."""
from __future__ import annotations

import json
import os
import shutil
import time
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

import guided_opening_picture as picture
import guided_picture_decode as decoder
from headless.process_runner import ProcessRequest, run_text
from palmier.process_deadline import process_timeout


def command(arguments: list[str]) -> str:
    """Run only installed local fixture tools under bounded owned-group capture."""
    executable = shutil.which(arguments[0])
    if executable is None:
        raise RuntimeError("TEST installed media tool missing")
    result = run_text(ProcessRequest((executable, *arguments[1:]), "", os.getcwd(), dict(os.environ),
        process_timeout(60), max_output_bytes=1024 * 1024))
    if result.returncode:
        raise RuntimeError("TEST fixture command failed: " + result.stderr[-1600:])
    return result.stdout


def encode(root: Path, name: str, options: tuple[str, int, str, list[str]]) -> Path:
    """Create fresh small H.264 fixtures; extra options declare each pathology."""
    rate, frames, canvas, extra = options
    path = root / f"{name}.mp4"
    command(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
        f"testsrc2=size={canvas}:rate={rate}", "-frames:v", str(frames), "-c:v", "libx264",
        "-preset", "veryfast", "-pix_fmt", "yuv420p", "-g", "24", "-movflags", "+faststart",
        "-fps_mode", "passthrough", *extra, str(path)])
    return path


def variant(source: Path, name: str, arguments: list[str]) -> Path:
    """Create new remux variants, never mutate the source fixture."""
    path = source.parent / f"{name}.mp4"
    command(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-i", str(source), *arguments, str(path)])
    return path


def corrupt_late(source: Path) -> Path:
    """Keep valid container metadata but destroy one actual late coded picture packet."""
    value = json.loads(command(["ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_packets", "-show_entries", "packet=pos,size", "-of", "json", str(source)]))
    rows = value["packets"]
    row = rows[len(rows) * 9 // 10]
    data = bytearray(source.read_bytes())
    start, size = int(row["pos"]), int(row["size"])
    data[start:start + size] = b"\xff" * size
    path = source.parent / "late-corrupt.mp4"
    path.write_bytes(data)
    return path


def old_observe(path: Path, expected: tuple[str, int, tuple[int, int]], tools: dict) -> dict:
    """Exact old observer algorithm; TEST baseline, never a production fallback."""
    rate, frames, canvas = expected
    before = picture.file_hash(path)
    raw = picture.run_audio([tools["ffprobe"]["path"], "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(path)])
    videos = [row for row in json.loads(raw)["streams"] if row.get("codec_type") == "video"]
    if len(videos) != 1:
        raise RuntimeError("opening picture does not have exactly one video stream")
    row = videos[0]
    if Fraction(row["r_frame_rate"]) != Fraction(rate) or Fraction(row["avg_frame_rate"]) != Fraction(rate) \
            or int(row.get("nb_read_frames", -1)) != frames or (row["width"], row["height"]) != canvas \
            or row.get("sample_aspect_ratio") != "1:1" or row.get("side_data_list") \
            or row.get("tags", {}).get("rotate", "0") != "0":
        raise RuntimeError("opening actual picture differs from its exact clock/canvas authority")
    picture.run_audio([tools["ffmpeg"]["path"], "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode",
        "-i", str(path), "-map", "0:v:0", "-an", "-f", "null", "-"])
    held = picture.observe_picture_source(str(path), float(Fraction(frames, 1) / Fraction(rate)), before)
    if picture.file_hash(path) != before:
        raise RuntimeError("opening picture bytes changed during complete observation")
    rows = [[str(item) if isinstance(item, Fraction) else item for item in row] for row in held.packets]
    return {"path": str(path), "sha256": before, "sizeBytes": path.stat().st_size,
        "frameRate": rate, "frames": frames, "width": canvas[0], "height": canvas[1],
        "startPts": 0, "timeBase": str(held.time_base), "videoDecodeSucceeded": True,
        "packetTimelineSha256": picture.digest(rows), "codec": videos[0]["codec_name"]}


def timed_observe(call: Callable[..., dict], inputs: tuple, measurements: list[dict], label: str) -> dict:
    """Time distinct hash/probe/decode phases without changing their results."""
    phases: dict[str, float] = {}
    def timed(name: str, function: Callable[..., Any], *args: Any) -> Any:
        """Accumulate actual leaf wall time, including retained failing observations."""
        started = time.perf_counter()
        try:
            return function(*args)
        finally:
            phases[name] = phases.get(name, 0) + (time.perf_counter() - started) * 1000
    original_audio, original_hash = picture.run_audio, picture.file_hash
    original_source, original_run = picture.observe_picture_source, decoder.run_text
    def audio(arguments: list[str]) -> bytes:
        """Label the old count decode separately from metadata and strict decode."""
        name = "count_probe_ms" if "-count_frames" in arguments else "strict_decode_ms" if "-xerror" in arguments else "metadata_probe_ms"
        return timed(name, original_audio, arguments)
    started = time.perf_counter()
    observed, failure = None, None
    try:
        with patch.object(picture, "run_audio", side_effect=audio), \
                patch.object(picture, "file_hash", side_effect=lambda *args: timed("hash_ms", original_hash, *args)), \
                patch.object(picture, "observe_picture_source", side_effect=lambda *args: timed("packet_clock_ms", original_source, *args)), \
                patch.object(decoder, "run_text", side_effect=lambda *args: timed("strict_decode_ms", original_run, *args)):
            observed = call(*inputs)
            return observed
    except Exception as error:
        failure = f"{type(error).__name__}: {error}"[:2000]
        raise
    finally:
        measurements.append({"case": label, "elapsed_ms": (time.perf_counter() - started) * 1000,
            "outcome": "observed" if observed is not None else "rejected", "observation": observed,
            "error": failure, **phases})
