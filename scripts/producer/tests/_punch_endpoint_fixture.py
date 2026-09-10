"""Retained tiny native endpoint fixtures; no creator media or approval authority."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image

from motion import punch_in
from producer_config import ENCODE

CASES = (("30/1", 90, 30, 60), ("24/1", 72, 24, 48), ("30000/1001", 90, 30, 60))


def file_sha(path: Path) -> str:
    """Hash a specific original fixture, source or output file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes() -> dict[str, str]:
    """Retain the exact primitive/config and installed local tool bytes."""
    producer = Path(punch_in.__file__).resolve().parents[1]
    paths = [Path(punch_in.__file__), producer / "producer_config.py",
             producer / "color/deadline.py", Path(__file__), Path(__file__).with_name("test_punch_endpoints.py")]
    for name in ("ffmpeg", "ffprobe"):
        tool = Path(shutil.which(name) or "MISSING").resolve(strict=True)
        if tool != Path(f"/opt/homebrew/Cellar/ffmpeg/8.0_1/bin/{name}"):
            raise RuntimeError("TEST native qualification requires the explicitly installed FFmpeg 8.0_1")
        paths.append(tool)
    return {str(path): file_sha(path) for path in paths}


def run(argv: list[str]) -> str:
    """Run one synchronous local leaf inside the test's original POSIX wall budget."""
    return subprocess.run(argv, capture_output=True, text=True, check=True).stdout


def create_source(path: Path, rate: str) -> None:
    """Create a fixed three-second, 320x180 marker source and quiet synthetic AAC."""
    pattern = (f"color=c=0x202020:s=320x180:r={rate}:d=3,"
        "drawbox=x=60:y=35:w=20:h=110:color=red:t=fill,"
        "drawbox=x=240:y=35:w=20:h=110:color=lime:t=fill,"
        "drawbox=x=145:y=75:w=30:h=30:color=white:t=fill,"
        "drawbox=x=8:y=8:w=304:h=164:color=white:t=2")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", pattern,
         "-f", "lavfi", "-i", "sine=frequency=400:sample_rate=48000:duration=3",
         "-filter:a", "volume=0.1", "-t", "3", "-c:v", "libx264", "-crf", "12",
         "-preset", "fast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart", str(path)])


def metadata(path: Path) -> dict:
    """Retain counted frames, original PTS and exact audio packet payload/clock records."""
    base = ["ffprobe", "-v", "error"]
    streams = json.loads(run(base + ["-count_frames", "-count_packets", "-show_streams", "-of", "json", str(path)]))
    audio = json.loads(run(base + ["-select_streams", "a:0", "-show_packets", "-show_data_hash", "sha256",
        "-show_entries", "packet=pts,dts,duration,size,flags,data_hash,side_data_list", "-of", "json", str(path)]))
    frames = json.loads(run(base + ["-select_streams", "v:0", "-show_frames", "-show_entries",
        "frame=best_effort_timestamp,best_effort_timestamp_time", "-of", "json", str(path)]))
    return {"streams": streams["streams"], "audioPackets": audio["packets"], "frames": frames["frames"]}


def decoded_markers(path: Path, samples: tuple[int, ...]) -> dict[int, dict]:
    """Save and measure five actual decoded frames, retaining their original frame indices."""
    select = "+".join(f"eq(n,{frame})" for frame in samples)
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-vf", f"select='{select}'", "-fps_mode", "vfr", "-start_number", "0",
         str(path.parent / f"{path.stem}-sample-%02d.png")])
    return {frame: marker(path.parent / f"{path.stem}-sample-{index:02d}.png")
            for index, frame in enumerate(samples)}


def marker(path: Path) -> dict:
    """Use high-contrast marker geometry, not equality of distinct lossy encodes."""
    with Image.open(path) as image:
        pixels = np.asarray(image.convert("RGB"))
    mask = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 80) & (pixels[:, :, 2] < 80)
    ys, xs = np.nonzero(mask)
    if len(xs) < 100:
        raise RuntimeError("Original synthetic marker unavailable; native case is inconclusive")
    return {"path": str(path), "centerX": float(xs.mean()), "centerY": float(ys.mean()),
            "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], "sha256": file_sha(path)}


def render_variant(source: Path, raw: list[dict], label: str, samples: tuple[int, ...]) -> dict:
    """Call the actual primitive with unchanged encoder settings, then retain its actual evidence."""
    output = source.parent / f"{label}.mp4"
    windows = punch_in.parse_windows(raw) if raw else []
    began = time.monotonic()
    actual = punch_in.apply_punch_ins(str(source), windows, str(output))
    return {"result": actual, "applySeconds": time.monotonic() - began,
            "filter": punch_in.build_filter(320, 180, windows), "metadata": metadata(output),
            "markers": decoded_markers(output, samples), "sha256": file_sha(output)}


def endpoint_case(root: Path, case: tuple[str, int, int, int]) -> dict:
    """Create one original fixed source and same-quality control/static/animated outputs."""
    rate, count, start, end = case
    numerator, denominator = map(int, rate.split("/"))
    directory = root / rate.replace("/", "-")
    directory.mkdir()
    source = directory / "source.mp4"
    create_source(source, rate)
    samples = (start - 1, start, end - 1, end, end + 1)
    window = {"outStart": start * denominator / numerator,
              "outEnd": end * denominator / numerator, "zoom": 1.25}
    variants = {"control": [], "static": [window], "animated": [{**window, "attackS": 0.2}]}
    records = {label: render_variant(source, raw, label, samples) for label, raw in variants.items()}
    return {"rate": rate, "count": count, "start": start, "end": end, "samples": samples,
            "window": window, "sourceMetadata": metadata(source), "sourceSha256": file_sha(source),
            "encode": {key: ENCODE[key] for key in ("mezzanine_crf", "mezzanine_preset", "pix_fmt")},
            "variants": records}
