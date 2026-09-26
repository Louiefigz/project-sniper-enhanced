"""Native full-decode admission for one immutable external-media snapshot.

Same observations and ceilings as the container probe (``NODE_PROBE`` in
external_media_probe_policy.py): a font/SVG recogniser, ffprobe facts, the
size/stream/dimension/duration/frame limits, then a complete ffmpeg decode that
must finish without a single error line. Every step that reads the untrusted
bytes runs alone in the native jail (native_media_sandbox.py): the recogniser in
the launcher's inspection mode, the decoders by exec. Fonts and SVG are never
decoded.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict

from headless.external_media_probe_document import validate_probe_document
from headless.external_media_probe_policy import MediaProbeLimits
from headless.external_media_snapshot import ExternalMediaSnapshot, verify_external_media_snapshot
from headless.native_media_sandbox import JailLimits, JailRejection, run_decoder, run_inspect, verified_runtime

POLICY_VERSION = "sniper-external-media-probe-v4-native"  # headless/admission_receipt.py NATIVE_POLICY
_PROBE_ENTRIES = "stream=codec_type,width,height,nb_frames,avg_frame_rate:format=duration,size"
def js_number(value: object) -> float:
    """``Number(value || 0)`` as the container's JavaScript probe computed it."""
    if value in (None, "", 0, False):
        return 0.0
    if isinstance(value, bool):
        return 1.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip() or "0")
    except ValueError:
        return math.nan


def _json_number(value: float) -> int | float:
    """Integral values serialise as integers, exactly like JSON.stringify."""
    return int(value) if math.isfinite(value) and value == int(value) else value


def _stream_totals(streams: list, duration: float) -> dict:
    """Video/audio counts, largest frame size and declared frames per stream."""
    totals = {"video": 0, "audio": 0, "width": 0.0, "height": 0.0, "frames": 0.0}
    for stream in streams:
        stream = stream if isinstance(stream, dict) else {}
        if stream.get("codec_type") == "video":
            totals["video"] += 1
            totals["width"] = max(totals["width"], js_number(stream.get("width")))
            totals["height"] = max(totals["height"], js_number(stream.get("height")))
            frames = js_number(stream.get("nb_frames"))
            if not frames or math.isnan(frames):
                rate = [js_number(part) for part in str(stream.get("avg_frame_rate") or "0/1").split("/")]
                frames = math.ceil(duration * rate[0] / rate[1]) if len(rate) > 1 and rate[1] else 0
            totals["frames"] += frames
        if stream.get("codec_type") == "audio":
            totals["audio"] += 1
    return totals


def probe_facts(document: dict, limits: MediaProbeLimits) -> dict:
    """Apply the container probe's metadata ceilings to ffprobe's JSON."""
    streams = document.get("streams") or []
    if len(streams) < 1 or len(streams) > limits.max_streams:
        raise JailRejection("STREAM_LIMIT")
    fmt = document.get("format") or {}
    duration, size = js_number(fmt.get("duration")), js_number(fmt.get("size"))
    if not math.isfinite(size) or size <= 0 or size > limits.max_bytes:
        raise JailRejection("SIZE_LIMIT")
    t = _stream_totals(streams, duration)
    if t["width"] > limits.max_width or t["height"] > limits.max_height:
        raise JailRejection("DIMENSION_LIMIT")
    still = t["video"] > 0 and t["audio"] == 0 and (not math.isfinite(duration) or duration <= 0)
    if not still and (not math.isfinite(duration) or duration <= 0 or duration > limits.max_duration_seconds):
        raise JailRejection("DURATION_LIMIT")
    frames = max(1, t["frames"]) if still else t["frames"]
    if frames > limits.max_frames:
        raise JailRejection("FRAME_LIMIT")
    return {"mediaKind": "still-image" if still else "timed-media",
            "durationSeconds": 0 if still else _json_number(duration), "sizeBytes": _json_number(size),
            "width": _json_number(t["width"]), "height": _json_number(t["height"]),
            "videoStreams": t["video"], "audioStreams": t["audio"], "streamCount": len(streams),
            "declaredFrames": _json_number(frames)}


def _decode(runtime, path: str, limits: MediaProbeLimits) -> tuple[dict, list[dict]]:
    """Jailed ffprobe, metadata ceilings, then one jailed complete decode."""
    probe = run_decoder(runtime, runtime.ffprobe, ("-v", "error", "-show_entries", _PROBE_ENTRIES, "-of", "json",
                                                   path), (path, JailLimits(10, 10)))
    if probe.stderr.strip():
        raise JailRejection("DECODER_STDERR", probe.stderr.strip()[-400:])
    try:
        facts = probe_facts(json.loads(probe.stdout), limits)
    except json.JSONDecodeError as error:
        raise JailRejection("PROBE_OUTPUT", "ffprobe output is not JSON") from error
    decode_seconds = limits.max_decode_seconds
    decode = run_decoder(runtime, runtime.ffmpeg, (
        "-nostdin", "-v", "error", "-xerror", "-threads", "4", "-i", path, "-map", "0:v?", "-map", "0:a?",
        "-fps_mode", "vfr", "-f", "null", "-"), (path, JailLimits(decode_seconds, decode_seconds * 4 + 30)))
    if decode.stderr.strip():
        raise JailRejection("DECODER_STDERR", decode.stderr.strip()[-400:])
    return facts, [probe.attestation, decode.attestation]


def native_isolation(runtime, attestations: list[dict]) -> dict:
    """What confined the observations, as recorded in the receipt."""
    windows = runtime.identity["kind"] == "windows-appcontainer"
    return {"kind": runtime.identity["kind"], "policy": runtime.identity["policy"],
            "profileSha256": runtime.identity["profileSha256"], "network": "denied",
            "processCreation": "job-limited" if windows else "denied",
            "writes": "ephemeral profile only" if windows else "/dev/null only",
            "otherProcesses": "denied", "memoryMiB": attestations[0]["memoryMiB"],
            "watchdog": "job-object" if windows else "footprint+cpu", "jailRuns": attestations}


def inspected_facts(runtime, path: str, limits: MediaProbeLimits) -> tuple[dict | None, dict]:
    """Font/SVG facts from the jailed inspection (None: timed media or a still), plus its attestation."""
    result, attestation = run_inspect(runtime, path, {"maxBytes": limits.max_bytes, "maxWidth": limits.max_width,
                                                      "maxHeight": limits.max_height})
    if isinstance(result, dict) and isinstance(result.get("rejected"), str):
        raise JailRejection(result["rejected"])
    if not isinstance(result, dict) or set(result) != {"special"}:
        raise JailRejection("INSPECT_OUTPUT", "inspection result is malformed")
    return result["special"], attestation


def probe_native_snapshot(path: str, limits: MediaProbeLimits) -> dict:
    """Observe one snapshot; return runtime, isolation and the validated decode document."""
    runtime = verified_runtime()
    special, inspection = inspected_facts(runtime, path, limits)
    facts, attestations = (special, []) if special is not None else _decode(runtime, path, limits)
    attestations = [inspection, *attestations]
    document = validate_probe_document({"schemaVersion": 1, "ok": True, "decoded": True, "facts": facts}, limits)
    return {"runtime": runtime.identity, "isolation": native_isolation(runtime, attestations), "decoded": document}


def native_admission_receipt(snapshot: ExternalMediaSnapshot, limits: MediaProbeLimits) -> dict:
    """Admission receipt for one immutable snapshot, re-verified after the decode."""
    verify_external_media_snapshot(snapshot)
    try:
        evidence = probe_native_snapshot(snapshot.path, limits)
    except JailRejection as error:
        raise RuntimeError(f"external-media decode rejected: {error.code}: {error}") from error
    verify_external_media_snapshot(snapshot)
    return {"schemaVersion": 1, "policy": POLICY_VERSION,
            "snapshot": {"path": snapshot.path, "sha256": snapshot.sha256, "sizeBytes": snapshot.size_bytes},
            "limits": asdict(limits), **evidence}
