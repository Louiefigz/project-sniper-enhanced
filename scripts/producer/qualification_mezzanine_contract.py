"""Strict evidence contract for isolated over-cap qualification conversion."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from headless.external_media_snapshot import MAX_EXTERNAL_MEDIA_BYTES
from ingest_admission_contract import canonical_bytes
from qualification_mezzanine_audio_contract import validate_audio
from qualification_mezzanine_clock_contract import (
    validate_output_clock,
    validate_source_clock,
)
from qualification_mezzanine_color_contract import validate_color
from qualification_mezzanine_files import FileFact, observe_qualified_output
from qualification_mezzanine_source_audio_contract import validate_source_audio

POLICY = "sniper-overcap-qualification-mezzanine-v1"
ADMISSION_POLICY = "sniper-external-media-probe-v2"
_SHA = set("0123456789abcdef")


@dataclass(frozen=True)
class EvidenceInput:
    """All exact authorities needed to construct one receipt."""

    source: FileFact
    output: FileFact
    output_path: str
    target_fps: int
    envelope: dict


def _parse_rate(value: object) -> tuple[int, int]:
    if type(value) is not str or "/" not in value:
        raise RuntimeError("qualification cadence rate is malformed")
    parts = value.split("/")
    if (len(parts) != 2 or not all(part.isdigit() for part in parts)
            or int(parts[0]) <= 0 or int(parts[1]) <= 0):
        raise RuntimeError("qualification cadence rate is malformed")
    return int(parts[0]), int(parts[1])


def _target_frames(source_frames: int, source_rate: str, target_fps: int) -> int:
    numerator, denominator = _parse_rate(source_rate)
    scaled = source_frames * target_fps * denominator
    return (scaled + numerator // 2) // numerator


def _sha_value(value: object, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in _SHA for char in value)):
        raise RuntimeError(f"{label} is not a lowercase SHA-256")
    return value


def _validate_tool(tool: object, name: str) -> None:
    keys = {"path", "resolvedPath", "sha256", "sizeBytes", "versionArgv",
            "versionOutput", "versionOutputSha256"}
    if type(tool) is not dict or set(tool) != keys:
        raise RuntimeError(f"qualification {name} tool facts are malformed")
    _sha_value(tool["sha256"], f"{name} binary")
    output = tool["versionOutput"]
    valid = (
        type(tool["path"]) is str and str(tool["path"]).startswith("/usr/bin/")
        and type(tool["resolvedPath"]) is str
        and type(tool["sizeBytes"]) is int and tool["sizeBytes"] > 0
        and type(output) is str
        and tool["versionArgv"] == [tool["resolvedPath"], "-version"]
        and hashlib.sha256(output.encode()).hexdigest()
        == _sha_value(tool["versionOutputSha256"], f"{name} version")
    )
    if not valid:
        raise RuntimeError(f"qualification {name} tool facts are inconsistent")


def _validate_cadence(worker: dict, target_fps: int) -> int:
    source, cadence = worker.get("sourceProbe"), worker.get("cadenceDecision")
    facts = source.get("facts") if type(source) is dict else None
    if type(facts) is not dict or type(cadence) is not dict:
        raise RuntimeError("qualification cadence evidence is missing")
    frames, source_rate = facts.get("frames"), facts.get("rate")
    expected = _target_frames(frames, source_rate, target_fps) \
        if type(frames) is int and not isinstance(frames, bool) else -1
    numerator, denominator = _parse_rate(source_rate)
    source_duration = frames * denominator / numerator
    target_duration = expected / target_fps
    valid = (
        cadence.get("mode") == "declared-palmier-integer-rate-approximation"
        and cadence.get("approvalPolicy") == "sniper-palmier-project-rate-v1"
        and cadence.get("sourceRate") == source_rate
        and cadence.get("targetRate") == f"{target_fps}/1"
        and cadence.get("sourceFrames") == frames
        and cadence.get("targetFrames") == expected
        and cadence.get("frameRounding") == "nearest-target-frame-half-up"
        and abs(cadence.get("sourceDurationSeconds", -1) - source_duration) < 1e-9
        and abs(cadence.get("targetDurationSeconds", -1) - target_duration) < 1e-9
        and abs(cadence.get("durationDeltaSeconds", 1e9)
                - (target_duration - source_duration)) < 1e-9
    )
    if not valid:
        raise RuntimeError("qualification cadence approximation is inconsistent")
    return expected


def _option_matches(argv: list, option: str, expected: object) -> bool:
    return (
        type(expected) is str
        and argv.count(option) == 1
        and argv.index(option) + 1 < len(argv)
        and argv[argv.index(option) + 1] == expected
    )


def _validate_argv(worker: dict) -> None:
    tools = worker["tools"]
    source_argv = worker["sourceProbe"].get("argv")
    output_argv = worker["outputProbe"].get("argv")
    ffmpeg_argv = worker["transcode"].get("argv")
    audio_argv = worker["outputProbe"].get("audioDecodeArgv")
    color_filter = (worker.get("colorDecision") or {}).get("filter")
    audio_filter = (worker.get("audioDecision") or {}).get("filter")
    output_entries = (
        "stream:format:frame=media_type,pts,pkt_pts,best_effort_timestamp,"
        "duration,pkt_duration,nb_samples,interlaced_frame,top_field_first"
    )
    valid = (
        type(source_argv) is list and source_argv[0] == tools["ffprobe"]["path"]
        and source_argv[-1] == "/input/source"
        and type(output_argv) is list and output_argv[0]
        == tools["ffprobe"]["path"] and output_argv[-1] == "/output/qualified.mp4"
        and type(ffmpeg_argv) is list and ffmpeg_argv[0]
        == tools["ffmpeg"]["path"] and ffmpeg_argv[-1] == "/output/qualified.mp4"
        and ffmpeg_argv.count("-n") == 1 and "-frames:v" not in ffmpeg_argv
        and "-shortest" not in ffmpeg_argv and "-t" not in ffmpeg_argv
        and _option_matches(ffmpeg_argv, "-vsync", "cfr")
        and _option_matches(ffmpeg_argv, "-vf", color_filter)
        and _option_matches(ffmpeg_argv, "-af", audio_filter)
        and output_argv.count("-show_frames") == 1
        and "-select_streams" not in output_argv
        and _option_matches(output_argv, "-show_entries", output_entries)
        and audio_argv == output_argv
    )
    if not valid:
        raise RuntimeError("qualification tool argv is inconsistent")


def _validate_output_profile(
    worker: dict,
    target_fps: int,
    target_frames: int,
    output: FileFact,
) -> None:
    facts = (worker.get("outputProbe") or {}).get("facts") or {}
    video, audio = facts.get("video") or {}, facts.get("audio") or {}
    decision = worker.get("audioDecision") or {}
    expected_duration = max(
        target_frames / target_fps,
        decision.get("targetTimelineDurationSeconds", -1),
    )
    validate_output_clock(video, target_frames, target_fps)
    valid = (
        facts.get("sizeBytes") == output.size_bytes
        and abs(facts.get("durationSeconds", -1) - expected_duration)
        <= 0.0000005
        and video.get("codec") == "h264" and video.get("profile") == "High"
        and video.get("level") == 42 and video.get("width") == 1920
        and video.get("height") == 1080 and video.get("pixelFormat") == "yuv420p"
        and video.get("sampleAspectRatio") == "1:1"
        and video.get("rate") == f"{target_fps}/1"
        and video.get("frames") == target_frames
        and video.get("timeBase") == f"1/{target_fps}"
        and video.get("startPts") == 0
        and video.get("durationFrames") == target_frames
        and abs(video.get("durationSeconds", -1)
                - target_frames / target_fps) <= 0.0000005
        and video.get("colorRange") == "tv"
        and video.get("colorSpace") == "bt709"
        and video.get("colorTransfer") == "bt709"
        and video.get("colorPrimaries") == "bt709"
        and audio.get("codec") == "aac"
        and audio.get("sampleRate") == 48000 and audio.get("channels") == 2
    )
    if not valid:
        raise RuntimeError("qualification output profile is inconsistent")


def validate_worker(
    envelope: dict,
    target_fps: int,
    source: FileFact,
    output: FileFact,
) -> dict:
    """Validate trusted-image output again before publication."""
    if (type(envelope) is not dict or type(envelope.get("worker")) is not dict
            or (envelope.get("removal") or {}).get(
                "canonicalAbsenceProved") is not True
            or type(envelope.get("isolation")) is not dict):
        raise RuntimeError("qualification container evidence is incomplete")
    worker = envelope["worker"]
    keys = {"schemaVersion", "ok", "tools", "sourceProbe", "cadenceDecision",
            "colorDecision", "audioDecision", "transcode", "outputProbe"}
    if set(worker) != keys or worker.get("schemaVersion") != 1 \
            or worker.get("ok") is not True:
        raise RuntimeError("qualification worker evidence is malformed")
    tools = worker.get("tools") or {}
    _validate_tool(tools.get("ffmpeg"), "ffmpeg")
    _validate_tool(tools.get("ffprobe"), "ffprobe")
    _validate_argv(worker)
    source_facts = (worker.get("sourceProbe") or {}).get("facts") or {}
    validate_source_clock(source_facts)
    validate_source_audio(source_facts)
    if (source_facts.get("sizeBytes") != source.size_bytes
            or source_facts.get("sha256") != source.sha256
            or source_facts.get("postTranscodeSha256") != source.sha256):
        raise RuntimeError("container source bytes differ from host authority")
    target_frames = _validate_cadence(worker, target_fps)
    validate_color(worker)
    validate_audio(worker, target_frames, target_fps)
    _validate_output_profile(worker, target_fps, target_frames, output)
    return worker


def build_evidence(authority: EvidenceInput) -> dict:
    """Build one digest-bound document that remains explicitly non-admitted."""
    worker, envelope = authority.envelope["worker"], authority.envelope
    body = {"schemaVersion": 1, "policy": POLICY,
            "immutableAdmissionCapBytes": MAX_EXTERNAL_MEDIA_BYTES,
            "source": asdict(authority.source),
            "target": {"width": 1920, "height": 1080,
                       "rate": f"{authority.target_fps}/1",
                       "videoCodec": "h264", "color": "bt709-sdr",
                       "audioCodec": "aac", "audioSampleRate": 48000,
                       "audioChannels": 2},
            "execution": {"image": envelope["image"],
                          "isolation": envelope["isolation"],
                          "removal": envelope["removal"],
                          "tools": worker["tools"],
                          "sourceByteBinding": {
                              "hostPreAndPostSha256": authority.source.sha256,
                              "containerPreSha256":
                                  worker["sourceProbe"]["facts"]["sha256"],
                              "containerPostSha256": worker[
                                  "sourceProbe"]["facts"][
                                      "postTranscodeSha256"],
                              "allMatch": True},
                          "ffprobeArgv": {
                              "source": worker["sourceProbe"]["argv"],
                              "output": worker["outputProbe"]["argv"],
                              "decodedAudio":
                                  worker["outputProbe"]["audioDecodeArgv"]},
                          "ffmpegArgv": worker["transcode"]["argv"],
                          "sourceStreamFacts": worker["sourceProbe"]["facts"],
                          "cadenceDecision": worker["cadenceDecision"],
                          "colorDecision": worker["colorDecision"],
                          "audioDecision": worker["audioDecision"]},
            "output": {"path": authority.output_path,
                       "sha256": authority.output.sha256,
                       "sizeBytes": authority.output.size_bytes,
                       "streamFacts": worker["outputProbe"]["facts"]},
            "sourceEligibility": {
                "eligible": False,
                "status": "blocked-pending-normal-external-media-admission-v2",
                "requiredPolicy": ADMISSION_POLICY,
                "nextInputPath": authority.output_path}}
    digest = hashlib.sha256(
        b"sniper-overcap-qualification-mezzanine-v1\0"
        + canonical_bytes(body)).hexdigest()
    return {**body, "evidenceDigest": digest}


def verify_evidence_document(document: dict) -> dict:
    """Rehash the receipt and published media; never upgrade eligibility."""
    keys = {"schemaVersion", "policy", "immutableAdmissionCapBytes", "source",
            "target", "execution", "output", "sourceEligibility",
            "evidenceDigest"}
    if type(document) is not dict or set(document) != keys:
        raise RuntimeError("qualification evidence schema is malformed")
    body = {key: value for key, value in document.items()
            if key != "evidenceDigest"}
    expected = hashlib.sha256(
        b"sniper-overcap-qualification-mezzanine-v1\0"
        + canonical_bytes(body)).hexdigest()
    output, eligibility = document["output"], document["sourceEligibility"]
    observed = observe_qualified_output(str(output.get("path", "")))
    pending = {
        "eligible": False,
        "status": "blocked-pending-normal-external-media-admission-v2",
        "requiredPolicy": ADMISSION_POLICY,
        "nextInputPath": output.get("path"),
    }
    if (document.get("schemaVersion") != 1 or document.get("policy") != POLICY
            or document.get("immutableAdmissionCapBytes")
            != MAX_EXTERNAL_MEDIA_BYTES or document.get("evidenceDigest") != expected
            or observed.sha256 != output.get("sha256")
            or observed.size_bytes != output.get("sizeBytes")
            or eligibility != pending):
        raise RuntimeError("qualification evidence authority mismatch")
    return document
