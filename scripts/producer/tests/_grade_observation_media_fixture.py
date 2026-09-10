"""Generate tiny synthetic hostile media; never change a creator/admitted source."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from cut_preview_io import bound_json, file_hash
from ingest_execution_authority import execution_media_authority_entries


def admitted_synthetic(producer: Path) -> dict:
    """Require a real previously admitted, explicitly synthetic small fixture."""
    project = bound_json(producer.parent / "project.json")
    manifest = bound_json(producer / "asset_manifest.json")
    plan = bound_json(producer / "edit_plan.json")
    if project.get("syntheticTestOnly") is not True:
        raise RuntimeError("grade media tests require explicit syntheticTestOnly fixture")
    entries = execution_media_authority_entries(plan, manifest, str(producer / "asset_manifest.json"))
    source = manifest["sources"][0]
    if not entries or source["sourceSizeBytes"] > 8 * 1024 ** 2 or source["fps"] != 2:
        raise RuntimeError("grade media test fixture exceeds its tiny synthetic budget")
    return source


def _run(tool: str, arguments: list[str]) -> bytes:
    """Trusted local encoder/probe is fixture construction, not production decode."""
    executable = shutil.which(tool)
    if executable is None:
        raise RuntimeError("synthetic grade tests require existing local ffmpeg/ffprobe")
    result = subprocess.run([executable, *arguments], stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=30, check=False)
    if result.returncode or result.stderr:
        raise RuntimeError(f"synthetic fixture {tool} failed: {result.stderr.decode('utf8')[:500]}")
    return result.stdout


def hostile_copies(source: dict, directory: Path) -> dict[str, Path]:
    """Corrupt a real packet beyond50s and truncate a separate private copy."""
    raw = Path(source["path"]).read_bytes()
    packet_raw = _run("ffprobe", ["-v", "error", "-select_streams", "v:0", "-show_packets",
        "-show_entries", "packet=pos,size,pts_time", "-of", "json", source["path"]])
    packets = json.loads(packet_raw)["packets"]
    late = next(row for row in packets if float(row["pts_time"]) >= 65)
    position, size = int(late["pos"]), int(late["size"])
    if size < 6 or position + size > len(raw):
        raise RuntimeError("synthetic late packet cannot be safely targeted")
    corrupted = bytearray(raw)
    corrupted[position:position + 4] = b"\xff\xff\xff\xff"
    paths = {"late-corrupt": directory / "late-corrupt.mp4", "truncated": directory / "truncated.mp4"}
    paths["late-corrupt"].write_bytes(corrupted)
    paths["truncated"].write_bytes(raw[:position + size // 2])
    if file_hash(Path(source["path"])) != source["sourceSha256"]:
        raise RuntimeError("original admitted test fixture unexpectedly changed")
    return paths


def late_metadata_source(directory: Path) -> Path:
    """Encode distinct in-band SPS color metadata after60s, then copy packets."""
    for name, duration, transfer in (("early", 60, "bt709"), ("late", 30, "smpte2084")):
        target = directory / f"{name}.ts"
        _run("ffmpeg", ["-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
            f"color=c=gray:s=160x90:r=2:d={duration}", "-an", "-vf",
            f"setparams=range=limited:color_primaries=bt709:color_trc={transfer}:colorspace=bt709",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", transfer, "-color_range", "tv", "-f", "mpegts", str(target)])
    concat = directory / "segments.txt"
    concat.write_text("file 'early.ts'\nfile 'late.ts'\n", encoding="utf8")
    target = directory / "late-metadata-last-header.mp4"
    _run("ffmpeg", ["-v", "error", "-nostdin", "-n", "-f", "concat", "-safe", "1",
        "-i", str(concat), "-c", "copy", "-movflags", "+faststart", str(target)])
    early = directory / "early-header.mp4"
    _run("ffmpeg", ["-v", "error", "-nostdin", "-n", "-i", str(directory / "early.ts"),
        "-c", "copy", "-movflags", "+faststart", str(early)])
    # Concat's muxer chooses the last segment's SPS for global avcC. Preserve
    # the FIRST segment's actual SPS there, while retaining both sets of in-band
    # packet metadata. This is deliberately mixed test media, never a repair.
    raw, first = target.read_bytes(), early.read_bytes()
    old, new = _avcc_box(raw), _avcc_box(first)
    if len(old) != len(new):
        raise RuntimeError("synthetic SPS box sizes differ; refuse guessed fixture edits")
    result = directory / "late-metadata.mp4"
    result.write_bytes(raw.replace(old, new, 1))
    return result


def _avcc_box(raw: bytes) -> bytes:
    """Select exactly one bounded AVC decoder configuration in created test media."""
    if raw.count(b"avcC") != 1:
        raise RuntimeError("synthetic AVC configuration is ambiguous")
    start = raw.index(b"avcC") - 4
    size = int.from_bytes(raw[start:start + 4], "big")
    if not 8 <= size <= 1024 or start + size > len(raw):
        raise RuntimeError("synthetic AVC configuration exceeds its box bounds")
    return raw[start:start + size]
