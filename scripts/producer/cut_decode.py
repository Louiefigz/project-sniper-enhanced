"""Optional native HEVC decoding with explicit evidence of the decoder used."""
from __future__ import annotations

import json
import platform
import subprocess
from collections.abc import Callable

from media_probe import run_ff


def eligible_source(path: str) -> bool:
    """Restrict acceleration to the measured high-resolution HEVC 4:2:0 family."""
    if platform.system() != "Darwin":
        return False
    raw = run_ff(["ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,pix_fmt", "-of", "json", path])
    streams = json.loads(raw).get("streams", [])
    if not streams:
        return False
    stream = streams[0]
    return (stream.get("codec_name") == "hevc"
            and stream.get("pix_fmt") in {"yuv420p", "yuv420p10le"}
            and stream["width"] * stream["height"] >= 3840 * 2160)


def hardware_command(command: list[str]) -> list[str]:
    """Accelerate only the first picture input; retain all audio inputs/filters."""
    result = list(command)
    index = result.index("-i")
    result[index:index] = ["-hwaccel", "videotoolbox"]
    result[result.index("-loglevel") + 1] = "debug"
    return result


def decoder_evidence(stderr: str) -> str:
    """Exit zero alone does not prove VideoToolbox initialized successfully."""
    failed = ("hwaccel initialisation returned error", "Failed setup for format",
              "VideoToolbox malfunction", "Failed to initialise")
    if any(marker in stderr for marker in failed):
        return "software-fallback"
    if "Format videotoolbox_vld chosen by get_format()" in stderr:
        return "videotoolbox"
    return "unverified"


def execute(command: list[str], runner: Callable[[list[str]], str],
            accelerate: bool) -> dict:
    """Keep software compatibility, recording every attempted native argv."""
    if not accelerate:
        runner(command)
        return {"decoder": "software", "attempts": [{"argv": command, "exitCode": 0}]}
    native = hardware_command(command)
    result = subprocess.run(native, capture_output=True, text=True)
    observed = decoder_evidence(result.stderr)
    attempts = [{"argv": native, "exitCode": result.returncode,
                 "decoder": observed}]
    if result.returncode == 0 and observed == "videotoolbox":
        return {"decoder": observed, "attempts": attempts}
    # Never describe an unproved or failed accelerated execution as hardware.
    # Re-run software explicitly so the published command has a known decoder.
    runner(command)
    attempts.append({"argv": command, "exitCode": 0, "decoder": "software"})
    return {"decoder": "software", "attempts": attempts,
            "fallbackReason": observed if not result.returncode else "hardware-command-failed"}
