"""Native jailed color sampling for the editor's private color diagnostic.

A port of ``color_diagnostic_worker.js`` (which ran inside the approved
container) to the native admission jail: the same request validation, source
identity checks, ffprobe metadata ceiling, one-frame 320-pixel samples with
``showinfo`` frame metadata and the same luma/chroma statistics. ffprobe and
each ffmpeg sample run alone in the jail (native_media_sandbox.py) with no
network, no writes, no process creation and a kernel memory limit; the frame
statistics are computed here from the bounded raw bytes they return.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import time

from headless.native_media_sandbox import JailLimits, JailRejection, run_decoder, verified_runtime
from headless.process_runner import ProcessReapError

_SHA256 = re.compile(r"[a-f0-9]{64}")
_MAX_SOURCE_BYTES = 8 * 1024 ** 3
_HDR = re.compile(r"mastering|content light|dovi|hdr", re.I)
_FILTERS = ("showinfo@source,scale=320:320:force_original_aspect_ratio=decrease:force_divisible_by=2:"
            "flags=area:in_range=tv:out_range=tv,format=yuv444p,showinfo@sample")
_SAMPLE_INFO = re.compile(r"\bn:\s*0\s+pts:\s*-?\d+\s+pts_time:([-+\d.e]+).*?\bs:(\d+)x(\d+)")


class _Stop(Exception):
    """Abort the whole analysis with the container worker's error token."""


def validate(request: dict) -> None:
    """The container worker's request contract, unchanged."""
    if sorted(request) != ["samples", "sourceSha256", "timeoutSeconds"] \
            or not _SHA256.fullmatch(str(request.get("sourceSha256"))) \
            or type(request.get("timeoutSeconds")) is not int or not 30 <= request["timeoutSeconds"] <= 120 \
            or type(request.get("samples")) is not list or not 1 <= len(request["samples"]) <= 64:
        raise _Stop("INVALID_REQUEST")
    ids = set()
    for sample in request["samples"]:
        time_ok = type(sample.get("sourceTime")) in (int, float) and math.isfinite(sample["sourceTime"])
        if type(sample.get("id")) is not str or len(sample["id"]) > 200 or sample["id"] in ids \
                or not time_ok or not 0 <= sample["sourceTime"] <= 21600:
            raise _Stop("INVALID_SAMPLE")
        ids.add(sample["id"])


def source_hash(path: str, deadline: float) -> str:
    """Hash the admitted snapshot through one descriptor; refuse growth or change."""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= _MAX_SOURCE_BYTES:
            raise _Stop("UNSAFE_SOURCE")
        digest, total = hashlib.sha256(), 0
        while chunk := os.read(descriptor, 1 << 20):
            if time.monotonic() > deadline:
                raise _Stop("ATTEMPT_TIMEOUT")
            total += len(chunk)
            if total > before.st_size:
                raise _Stop("SOURCE_GREW")
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if total != before.st_size or (after.st_mtime_ns, after.st_ctime_ns) != (before.st_mtime_ns, before.st_ctime_ns):
        raise _Stop("SOURCE_CHANGED")
    return digest.hexdigest()


def supported(probe: dict) -> bool:
    """Only single-stream 8-bit BT.709 SDR yuv420p sources are sampled."""
    video = [row for row in probe.get("streams") or [] if row.get("codec_type") == "video"]
    if len(video) != 1:
        return False
    row = video[0]
    hdr = any(_HDR.search(str(item.get("side_data_type") or "")) for item in row.get("side_data_list") or [])
    return (row.get("color_range") == "tv" and row.get("color_space") == "bt709"
            and row.get("color_transfer") == "bt709" and row.get("color_primaries") == "bt709"
            and row.get("pix_fmt") == "yuv420p" and row.get("bits_per_raw_sample") in (None, 0, 8, "0", "8")
            and not hdr)


def _percentile(histogram: list[int], count: int, fraction: float) -> int:
    total, needed = 0, max(1, math.ceil(count * fraction))
    for index, value in enumerate(histogram):
        total += value
        if total >= needed:
            return index
    raise _Stop("EMPTY_HISTOGRAM")


def statistics(raw: bytes, pixels: int) -> dict:
    """Luma histogram percentiles, chroma means and nominal black/white fractions."""
    if len(raw) != pixels * 3 or not 1 <= pixels <= 320 * 320:
        raise ValueError("FRAME_SIZE")
    luma = raw[:pixels]
    histogram = [0] * 256
    for value in luma:
        histogram[value] += 1
    return {"yMin": _percentile(histogram, pixels, 0), "yP10": _percentile(histogram, pixels, 0.1),
            "yMedian": _percentile(histogram, pixels, 0.5), "yMean": sum(luma) / pixels,
            "yP90": _percentile(histogram, pixels, 0.9), "yMax": _percentile(histogram, pixels, 1),
            "uMean": sum(raw[pixels:2 * pixels]) / pixels, "vMean": sum(raw[2 * pixels:]) / pixels,
            "nominalBlackFraction": sum(histogram[:17]) / pixels,
            "nominalWhiteFraction": sum(histogram[235:]) / pixels}


def frame_facts(text: str) -> dict:
    """Decoded-frame colour metadata from the first ``showinfo@source`` frame block."""
    lines = [line for line in text.split("\n") if re.match(r"^\[showinfo@source\s+@", line)]
    first = next((i for i, line in enumerate(lines) if re.search(r"\bn:\s*0\s+pts:", line)), -1)
    if first < 0:
        raise ValueError("MISSING_SOURCE_FRAME_METADATA")
    following = [i for i in range(first + 1, len(lines)) if re.search(r"\bn:\s*\d+\s+pts:", lines[i])]
    block = "\n".join(lines[first:following[0] if following else None])
    fmt = re.search(r"\bfmt:(\S+)", block)
    value = {"pixelFormat": fmt.group(1) if fmt else None}
    for key, field in (("range", "color_range"), ("matrix", "color_space"),
                       ("primaries", "color_primaries"), ("transfer", "color_trc")):
        found = re.search(rf"\b{field}:(\S+)", block)
        value[key] = found.group(1) if found else None
    value["hdrSignaled"] = bool(_HDR.search(block)) or value["transfer"] in ("smpte2084", "arib-std-b67")
    return value


def supported_frame(value: dict) -> bool:
    return (value["pixelFormat"] == "yuv420p" and value["range"] == "tv" and value["matrix"] == "bt709"
            and value["primaries"] == "bt709" and value["transfer"] == "bt709" and value["hdrSignaled"] is False)


def _jail_seconds(deadline: float, limit: float = 8.0) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _Stop("ATTEMPT_TIMEOUT")
    return max(0.5, min(limit, remaining))


def _extract(runtime, path: str, sample: dict, deadline: float):
    """One jailed single-frame extraction: raw yuv444p on stdout, showinfo on stderr."""
    wall = _jail_seconds(deadline)
    return run_decoder(runtime, runtime.ffmpeg, (
        "-nostdin", "-hide_banner", "-v", "info", "-nostats", "-threads", "1", "-filter_threads", "1",
        "-protocol_whitelist", "file,pipe", "-ss", repr(float(sample["sourceTime"])), "-copyts", "-i", path,
        "-map", "0:v:0", "-an", "-vf", _FILTERS, "-frames:v", "1", "-threads", "1", "-f", "rawvideo", "pipe:1"),
        (path, JailLimits(wall, int(wall) + 5, 2 * 1024 * 1024, binary_stdout=True)))


def _sampled(base: dict, probe: dict, done, begin: float) -> dict:
    """Project one successful extraction into the worker's sample row."""
    metadata = frame_facts(done.stderr)
    if not supported_frame(metadata):
        return {**base, "frameMetadata": metadata, "status": "skipped",
                "error": "UNSUPPORTED_SOURCE_FRAME_METADATA", "elapsedMs": round((time.monotonic() - begin) * 1000)}
    info_text = "\n".join(line for line in done.stderr.split("\n") if re.match(r"^\[showinfo@sample\s+@", line))
    info = _SAMPLE_INFO.search(info_text)
    if not info:
        raise ValueError("MISSING_ACTUAL_FRAME_PTS")
    video = next(row for row in probe["streams"] if row.get("codec_type") == "video")
    origin, pts = float(video.get("start_time") or 0), float(info.group(1))
    if not math.isfinite(origin) or not math.isfinite(pts):
        raise ValueError("INVALID_ACTUAL_FRAME_PTS")
    width, height = int(info.group(2)), int(info.group(3))
    return {**base, "frameMetadata": metadata, "status": "sampled", "actualPtsTime": pts,
            "actualSourceTime": pts - origin, "width": width, "height": height,
            "statistics": statistics(done.stdout, width * height),
            "elapsedMs": round((time.monotonic() - begin) * 1000)}


def sample_frame(runtime, path: str, sample: dict, context: tuple[dict, float]) -> dict:
    """Sample one requested time; failures are recorded per sample, like the worker."""
    probe, deadline = context
    begin = time.monotonic()
    base = {"id": sample["id"], "requestedTime": sample["sourceTime"]}
    if not supported(probe):
        return {**base, "status": "skipped", "error": "UNSUPPORTED_COLOR_METADATA", "elapsedMs": 0}
    try:
        return _sampled(base, probe, _extract(runtime, path, sample, deadline), begin)
    except (JailRejection, ValueError, _Stop, StopIteration) as error:
        token = error.code if isinstance(error, JailRejection) else str(error) or type(error).__name__
        return {**base, "status": "failed", "error": token[:160], "elapsedMs": round((time.monotonic() - begin) * 1000)}


def _probe(runtime, path: str, deadline: float) -> dict:
    """Jailed ffprobe metadata with the worker's 24 KiB ceiling."""
    done = run_decoder(runtime, runtime.ffprobe, ("-v", "error", "-protocol_whitelist", "file,pipe",
                                                  "-show_streams", "-show_format", "-of", "json", path),
                       (path, JailLimits(_jail_seconds(deadline), 10, 64 * 1024)))
    if len(done.stdout.encode("utf-8")) > 24576:
        raise _Stop("PROBE_METADATA_LIMIT")
    return json.loads(done.stdout)


def analyze(path: str, request: dict) -> dict:
    """The worker's result document for one admitted source."""
    started = time.monotonic()
    value = {"schemaVersion": 1, "sourceSha256": request.get("sourceSha256"), "probe": None,
             "samples": [], "tools": {}, "timing": {}}
    try:
        validate(request)
        deadline = started + request["timeoutSeconds"]
        if source_hash(path, deadline) != request["sourceSha256"]:
            raise _Stop("ADMITTED_SOURCE_HASH_MISMATCH")
        runtime = verified_runtime()
        value["probe"] = _probe(runtime, path, deadline)
        value["tools"] = {name: runtime.identity["tools"][name]["version"] for name in ("ffmpeg", "ffprobe")}
        value["samples"] = [sample_frame(runtime, path, row, (value["probe"], deadline))
                            for row in request["samples"]]
        if source_hash(path, deadline) != request["sourceSha256"]:
            raise _Stop("SOURCE_CHANGED_DURING_ANALYSIS")
        value["status"] = "complete" if all(row["status"] == "sampled" for row in value["samples"]) else "partial"
    except ProcessReapError:
        raise  # cleanup was not proved; the caller must not report it as verified
    except (_Stop, JailRejection, OSError, ValueError, RuntimeError) as error:
        value["status"], value["error"] = "failed", (getattr(error, "code", None) or str(error))[:160]
    value["timing"]["elapsedMs"] = round((time.monotonic() - started) * 1000)
    return value
