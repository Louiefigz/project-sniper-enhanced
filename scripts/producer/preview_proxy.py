#!/usr/bin/env python3
"""preview_proxy — a scrub-friendly preview next to the assembled final.

At the END of a successful assemble (after the YDIF gate + music) a
``final.proxy.mp4`` is written beside ``final.mp4``: short side 480 (even
dims), x264 CRF 28 veryfast, keyframe every 24 frames (dense enough to seek
anywhere while scrubbing), AAC 96k, faststart. Measured ~2.5s / ~22x smaller
on the 108s e2e final — the editor UI streams THIS, not the 160MB master.

DOCUMENTED fail-loudly EXCEPTION: the proxy is a PREVIEW asset produced after
the deliverable already succeeded — a proxy failure emits a ``proxy_failed``
WARN and the run continues (never fails a finished render over its preview).
"""
from __future__ import annotations

import json
import os
import subprocess
import time

from producer_config import PROXY


def emit(**fields) -> None:
    """One NDJSON status line on stdout (matches the render stages)."""
    print(json.dumps(fields), flush=True)


def proxy_path(final_path: str) -> str:
    """final.mp4 → final.proxy.mp4 (same directory)."""
    root, ext = os.path.splitext(final_path)
    return f"{root}.proxy{ext or '.mp4'}"


def build_proxy_cmd(src: str, dst: str) -> list[str]:
    """The proxy encode args (pure builder — unit-tested).

    Scale so the SHORT side lands at ``PROXY['short_side']`` whatever the
    aspect (portrait shorts scale width, landscape longforms scale height);
    ``-2`` keeps the derived dimension even for yuv420p. ``-g``/-keyint_min
    pin a keyframe every 24 frames so a scrub bar seeks cheaply.
    """
    side = int(PROXY["short_side"])
    scale = (f"scale=w='if(gt(iw,ih),-2,{side})':h='if(gt(iw,ih),{side},-2)'")
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src,
            "-vf", scale,
            "-c:v", "libx264", "-crf", str(PROXY["crf"]),
            "-preset", PROXY["preset"],
            "-g", str(PROXY["gop"]), "-keyint_min", str(PROXY["gop"]),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", PROXY["audio_bitrate"],
            "-movflags", "+faststart", dst]


def write_proxy(src: str) -> dict | None:
    """Encode the preview proxy next to ``src``; WARN-and-continue on failure.

    Emits ``{status: "proxy", path, ms, bytes}`` on success or
    ``{status: "proxy_failed", warning}`` on failure (the documented
    warn-and-continue exception — the deliverable already succeeded).
    """
    dst = proxy_path(src)
    t0 = time.monotonic()
    try:
        proc = subprocess.run(build_proxy_cmd(src, dst),
                              capture_output=True, text=True)
        if proc.returncode != 0 or not os.path.exists(dst):
            raise RuntimeError(proc.stderr.strip()[-300:] or "no output written")
        result = {"path": dst, "ms": int((time.monotonic() - t0) * 1000),
                  "bytes": os.path.getsize(dst)}
    except (OSError, RuntimeError) as exc:
        emit(status="proxy_failed", warning=f"proxy encode failed: {exc}",
             note="deliverable already succeeded; continuing without a proxy")
        return None
    emit(status="proxy", **result)
    return result
