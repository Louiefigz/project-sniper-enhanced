#!/usr/bin/env python3
"""Stream-copy each kept segment of the main video into its own MP4, then
bundle them into a single ZIP. Segments are processed in parallel.

Args: <main_video> <segments_json> <output_zip>

segments_json: [{"title": str, "start": float, "end": float}, ...]

No re-encoding: ffmpeg input-seeks to the nearest keyframe at-or-before
(start - PAD_SECONDS) and remuxes (end + PAD_SECONDS) - padded_start seconds
of bitstream into a new MP4. Output begins at a keyframe, so clips may
include extra pre-roll and adjacent clips may overlap — both acceptable
for downstream NLE trimming.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed


_SNIPER_DEBUG = os.environ.get("SNIPER_DEBUG") != "0"


def dbg(scope: str, event: str, **data):
    if not _SNIPER_DEBUG:
        return
    try:
        extra = json.dumps(data, default=str)
    except Exception:
        extra = str(data)
    if len(extra) > 1500:
        extra = extra[:1500] + f"… (+{len(extra) - 1500} more chars)"
    print(f"[SNIPER:{scope}] {event} {extra}", file=sys.stderr, flush=True)


PAD_SECONDS = 5.0


def run_command(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-15:]
        raise RuntimeError("\n".join(tail) or "ffmpeg failed")
    return result.stdout.strip()


def safe_name(s: str) -> str:
    cleaned = re.sub(r"[^\w\-. ]+", "_", s).strip().strip(".")
    return cleaned or "segment"


def render_one(main_video, start, end, output_path):
    padded_start = max(0.0, start - PAD_SECONDS)
    padded_duration = (end + PAD_SECONDS) - padded_start
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{padded_start:.3f}",
        "-i", main_video,
        "-t", f"{padded_duration:.3f}",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        output_path,
    ]
    dbg("export", "render_one.start", output=os.path.basename(output_path),
        start=start, end=end, padded_start=round(padded_start, 3),
        padded_duration=round(padded_duration, 3), cmd=cmd)
    t0 = time.monotonic()
    run_command(cmd)
    size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
    dbg("export", "render_one.done", output=os.path.basename(output_path),
        size_mb=round(size / (1024 * 1024), 2), elapsed_s=round(time.monotonic() - t0, 2))


def main():
    if len(sys.argv) != 4:
        print(
            json.dumps({"error": "Usage: export_mp4.py <main> <segments_json> <output_zip>"}),
            file=sys.stderr, flush=True,
        )
        sys.exit(1)

    main_video = sys.argv[1]
    segments_json = sys.argv[2]
    output_zip = sys.argv[3]

    dbg("export", "main.args", main_video=main_video, output_zip=output_zip,
        pad_seconds=PAD_SECONDS, segments_json_len=len(segments_json))

    if not os.path.exists(main_video):
        print(json.dumps({"error": f"Main video not found: {main_video}"}), file=sys.stderr, flush=True)
        sys.exit(1)

    try:
        segments = json.loads(segments_json)
        if not isinstance(segments, list) or not segments:
            raise ValueError("segments must be a non-empty list")
        dbg("export", "segments.parsed", count=len(segments))

        jobs = []
        with tempfile.TemporaryDirectory(prefix="clipper-mp4-") as work_dir:
            pad = max(2, len(str(len(segments))))
            for i, seg in enumerate(segments):
                start = float(seg.get("start", 0))
                end = float(seg.get("end", 0))
                if end <= start:
                    continue
                title = safe_name(str(seg.get("title") or f"segment_{i + 1}"))
                arcname = f"{str(i + 1).zfill(pad)} - {title}.mp4"
                temp_path = os.path.join(work_dir, arcname)
                jobs.append((arcname, temp_path, start, end))

            if not jobs:
                raise ValueError("No valid segments (all empty or zero length)")

            dbg("export", "jobs.built", count=len(jobs),
                names=[arcname for arcname, _, _, _ in jobs])

            workers = 2
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {
                    ex.submit(render_one, main_video, start, end, temp_path): arcname
                    for arcname, temp_path, start, end in jobs
                }
                for fut in as_completed(futures):
                    fut.result()

            with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_STORED) as zf:
                for arcname, temp_path, _, _ in jobs:
                    zf.write(temp_path, arcname=arcname)

        zip_size = os.path.getsize(output_zip) if os.path.exists(output_zip) else 0
        dbg("export", "zip.written", output_zip=output_zip,
            clips=len(jobs), size_mb=round(zip_size / (1024 * 1024), 2))
        print(output_zip)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
