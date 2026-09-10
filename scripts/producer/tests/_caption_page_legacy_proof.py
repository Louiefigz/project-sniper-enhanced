"""TEST comparator ONLY: preserve the pre-consolidation three-decode algorithm.

The original argv, probe matching and proof/hash domain are retained. The one
intentional harness-only change is injecting a bounded owned process recorder
instead of invoking unbounded subprocess.run. No production fallback imports it.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from typing import Callable

_ALPHA_RE = re.compile(r"lavfi\.signalstats\.YMAX=([0-9.]+)")


@dataclass(frozen=True)
class LegacyPageProofContext:
    """TEST-only expected metadata, installed tools and exact command recorder."""

    expected: dict
    tools: dict
    run: Callable[[list[str]], subprocess.CompletedProcess[str]]


def _probe(path: str, context: LegacyPageProofContext) -> dict:
    """Run the original -count_frames probe and original selected-field checks."""
    command = [
        context.tools["ffprobe"]["path"], "-v", "error",
        "-select_streams", "v:0", "-count_frames", "-show_entries",
        "stream=codec_name,pix_fmt,width,height,r_frame_rate,nb_read_frames",
        "-of", "json", path,
    ]
    process = context.run(command)
    try:
        streams = json.loads(process.stdout).get("streams") or []
    except json.JSONDecodeError as exc:
        raise RuntimeError("caption page probe returned invalid JSON") from exc
    if process.returncode or len(streams) != 1:
        raise RuntimeError("caption page media does not decode")
    if any(streams[0].get(key) != value for key, value in context.expected.items()):
        raise RuntimeError("caption page stream facts are stale")
    return context.expected


def _decoded_proof(path: str, context: LegacyPageProofContext) -> dict:
    """Keep the old independent framemd5 and full-alpha argv and numeric behavior."""
    ffmpeg = context.tools["ffmpeg"]["path"]
    frame = context.run([
        ffmpeg, "-v", "error", "-i", path, "-map", "0:v:0",
        "-pix_fmt", "rgba", "-f", "framemd5", "-",
    ])
    alpha = context.run([
        ffmpeg, "-v", "error", "-i", path, "-vf",
        "alphaextract,signalstats,"
        "metadata=print:key=lavfi.signalstats.YMAX:file=-",
        "-an", "-f", "null", "-",
    ])
    if frame.returncode or alpha.returncode:
        raise RuntimeError("caption page decoded proof failed")
    maxima = [float(value) for value in _ALPHA_RE.findall(alpha.stdout + alpha.stderr)]
    if not maxima or max(maxima) <= 0 or max(maxima) > 255:
        raise RuntimeError("caption page has no bounded alpha occupancy")
    return {
        "decodedFrameMd5Sha256": hashlib.sha256(frame.stdout.encode("utf8")).hexdigest(),
        "alphaMax": max(maxima), "framesMeasured": len(maxima),
    }


def legacy_page_proof(path: str, context: LegacyPageProofContext) -> dict:
    """Return only the exact old result dictionary for an explicit A/B test."""
    proof = {"stream": _probe(path, context), **_decoded_proof(path, context)}
    if proof["framesMeasured"] != int(context.expected["nb_read_frames"]):
        raise RuntimeError("caption page alpha proof is frame-incomplete")
    return proof
