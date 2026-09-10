"""Policy approval for one explicit Palmier cadence approximation."""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path

from ingest_admission_contract import canonical_bytes
from qualification_cadence_approval_store import publish_canonical
from qualification_mezzanine import verify_qualification_evidence
from qualification_mezzanine_files import (
    read_canonical_evidence,
)

POLICY = "sniper-palmier-cadence-approval-v1"
APPROVER = "sniper-palmier-project-rate-v1"
SUPPORTED_PAIRS = (("24000/1001", "24/1"),)
POLICY_SPEC = {
    "schemaVersion": 1,
    "approvedPairs": [{"sourceRate": source, "targetRate": target}
                      for source, target in SUPPORTED_PAIRS],
    "maximumAbsoluteDurationDeltaTargetFrames": "1/2",
    "frameSelection": "rounded-input-pts-latest-not-after-target",
    "interpolation": "forbidden",
    "epoch": "zero-based",
}


def _rate(value: str) -> tuple[int, int]:
    parts = value.split("/") if type(value) is str else []
    if (len(parts) != 2 or not all(part.isdigit() for part in parts)
            or int(parts[0]) <= 0 or int(parts[1]) <= 0):
        raise RuntimeError("cadence approval rate is malformed")
    return int(parts[0]), int(parts[1])


def _rounded(numerator: int, denominator: int) -> int:
    return (numerator + denominator // 2) // denominator


def _frame_map(
    source_frames: int,
    target_frames: int,
    rates: tuple[str, str],
) -> list[int]:
    source_num, source_den = _rate(rates[0])
    target_num, target_den = _rate(rates[1])
    rounded_pts = [
        _rounded(index * source_den * target_num,
                 source_num * target_den)
        for index in range(source_frames)
    ]
    result, source_index = [], 0
    for target_index in range(target_frames):
        while (source_index + 1 < source_frames
               and rounded_pts[source_index + 1] <= target_index):
            source_index += 1
        result.append(source_index)
    if result[0] != 0 or result[-1] != source_frames - 1:
        raise RuntimeError("cadence approval does not preserve endpoint frames")
    return result


def _mapping(cadence: dict) -> dict:
    source_frames, target_frames = (
        cadence["sourceFrames"], cadence["targetFrames"])
    rates = cadence["sourceRate"], cadence["targetRate"]
    frame_map = _frame_map(source_frames, target_frames, rates)
    used = set(frame_map)
    duplicates = [
        index for index in range(1, len(frame_map))
        if frame_map[index] == frame_map[index - 1]
    ]
    dropped = [index for index in range(source_frames) if index not in used]
    if len(duplicates) - len(dropped) != target_frames - source_frames:
        raise RuntimeError("cadence approval frame accounting is inconsistent")
    digest = hashlib.sha256(
        b"sniper-palmier-target-source-frame-map-v1\0"
        + canonical_bytes(frame_map)).hexdigest()
    return {
        "algorithm": "ffmpeg-fps-round-near-latest-not-after-target-v1",
        "targetToSourceIndexSha256": digest,
        "duplicateTargetFrameIndices": duplicates,
        "droppedSourceFrameIndices": dropped,
        "sourceFrameCount": source_frames,
        "targetFrameCount": target_frames,
        "firstSourceFrameIndex": frame_map[0],
        "lastSourceFrameIndex": frame_map[-1],
        "interpolation": False,
    }


def _duration(cadence: dict) -> dict:
    source_num, source_den = _rate(cadence["sourceRate"])
    target_num, target_den = _rate(cadence["targetRate"])
    numerator = (
        cadence["targetFrames"] * target_den * source_num
        - cadence["sourceFrames"] * source_den * target_num
    )
    denominator = target_num * source_num
    divisor = math.gcd(abs(numerator), denominator)
    reduced = f"{numerator // divisor}/{denominator // divisor}"
    within = (
        2 * abs(numerator) * target_num
        <= denominator * target_den
    )
    if not within:
        raise RuntimeError("cadence approval exceeds half a target frame")
    return {
        "sourceDurationSeconds": cadence["sourceDurationSeconds"],
        "targetDurationSeconds": cadence["targetDurationSeconds"],
        "durationDeltaSeconds": cadence["durationDeltaSeconds"],
        "durationDeltaRationalSeconds": reduced,
        "absoluteDeltaWithinHalfTargetFrame": True,
    }


def _option_matches(argv: list, option: str, expected: object) -> bool:
    return (
        type(expected) is str
        and argv.count(option) == 1
        and argv.index(option) + 1 < len(argv)
        and argv[argv.index(option) + 1] == expected
    )


def _transcode(execution: dict, cadence: dict) -> dict:
    argv, tools = execution["ffmpegArgv"], execution["tools"]
    joined = "\0".join(argv)
    if ("minterpolate" in joined or "-vsync" not in argv
            or argv[argv.index("-vsync") + 1] != "cfr"
            or not _option_matches(
                argv, "-vf", execution["colorDecision"].get("filter"))
            or not _option_matches(
                argv, "-af", execution["audioDecision"].get("filter"))
            or "-frames:v" in argv
            or f"trim=end_frame={cadence['targetFrames']}" not in
            execution["colorDecision"]["filter"]):
        raise RuntimeError("cadence approval transcode is not noninterpolated CFR")
    return {
        "argv": argv,
        "argvSha256": hashlib.sha256(canonical_bytes(argv)).hexdigest(),
        "ffmpegSha256": tools["ffmpeg"]["sha256"],
        "ffprobeSha256": tools["ffprobe"]["sha256"],
        "ffmpegVersionOutputSha256":
            tools["ffmpeg"]["versionOutputSha256"],
        "ffprobeVersionOutputSha256":
            tools["ffprobe"]["versionOutputSha256"],
        "noInterpolation": True,
    }


def _media(evidence: dict) -> dict:
    source = evidence["execution"]["sourceStreamFacts"]
    target = evidence["output"]["streamFacts"]
    video, audio = target["video"], target["audio"]
    return {
        "source": {
            "sha256": evidence["source"]["sha256"],
            "sizeBytes": evidence["source"]["size_bytes"],
            "rate": source["rate"], "frames": source["frames"],
            "timeBase": source["timeBase"],
            "firstPts": source["firstPts"], "lastPts": source["lastPts"],
            "frameStepPts": source["frameStepPts"],
            "zeroBasedEpoch": source["zeroBasedEpoch"],
            "progressive": source["progressive"],
            "streamFieldOrder": source["streamFieldOrder"],
            "decodedProgressiveFrames": source["decodedProgressiveFrames"],
            "rotationDegrees": source["rotationDegrees"],
            "width": source["width"], "height": source["height"],
            "color": evidence["execution"]["colorDecision"]["sourceTags"],
            "audio": source["sourceAudio"],
        },
        "normalized": {
            "path": evidence["output"]["path"],
            "sha256": evidence["output"]["sha256"],
            "sizeBytes": evidence["output"]["sizeBytes"],
            "video": video, "audio": audio,
        },
    }


def _approved_by() -> dict:
    policy_hash = hashlib.sha256(canonical_bytes(POLICY_SPEC)).hexdigest()
    return {
        "kind": "deterministic-policy",
        "policyId": APPROVER,
        "policyVersion": 1,
        "policySha256": policy_hash,
        "humanApprovalClaimed": False,
    }


def _audio_clock(evidence: dict, cadence: dict) -> dict:
    audio = evidence["output"]["streamFacts"]["audio"]
    source = evidence["execution"]["sourceStreamFacts"]["sourceAudio"]
    source_duration = source["durationSeconds"]
    rate_num, rate_den = _rate(cadence["sourceRate"])
    maximum = rate_den / rate_num
    timeline_delta = audio["timelineDurationSeconds"] - source_duration
    decoded_delta = audio["decodedDurationSeconds"] - source_duration
    if abs(timeline_delta) > maximum or abs(decoded_delta) > maximum:
        raise RuntimeError("cadence approval audio delta exceeds one source frame")
    return {
        "source": source,
        "normalized": {
            "sampleRate": audio["sampleRate"],
            "timelineSamplesPerChannel": audio["timelineSamplesPerChannel"],
            "decodedSamplesPerChannel": audio["decodedSamplesPerChannel"],
            "programSamplesPerChannel": audio["programSamplesPerChannel"],
            "silentTailSamplesPerChannel":
                audio["silentTailSamplesPerChannel"],
            "codecPaddingSamplesPerChannel":
                audio["codecPaddingSamplesPerChannel"],
            "timelineDurationSeconds": audio["timelineDurationSeconds"],
            "decodedDurationSeconds": audio["decodedDurationSeconds"],
            "fullProgramCoverage": audio["fullProgramCoverage"],
        },
        "normalizedTimelineDeltaFromSourceSeconds": timeline_delta,
        "normalizedDecodedDeltaFromSourceSeconds": decoded_delta,
        "absoluteDeltasWithinOneSourceFrame": True,
    }


def _body(evidence_path: str, evidence: dict) -> dict:
    execution, cadence = evidence["execution"], \
        evidence["execution"]["cadenceDecision"]
    pair = cadence["sourceRate"], cadence["targetRate"]
    if pair not in SUPPORTED_PAIRS:
        raise RuntimeError("cadence pair is not policy approved")
    implementation = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {
        "schemaVersion": 1,
        "policy": POLICY,
        "decision": "policy-approved-approximation",
        "approvedBy": _approved_by(),
        "implementationSha256": implementation,
        "qualification": {
            "evidencePath": evidence_path,
            "evidenceDigest": evidence["evidenceDigest"],
            "evidenceFileSha256":
                hashlib.sha256(canonical_bytes(evidence)).hexdigest(),
            "qualificationPolicy": evidence["policy"],
        },
        "media": _media(evidence),
        "frameMapping": _mapping(cadence),
        "duration": _duration(cadence),
        "audioClock": _audio_clock(evidence, cadence),
        "transcode": _transcode(execution, cadence),
        "downstreamTimeAuthority": {
            "mediaPath": evidence["output"]["path"],
            "mediaSha256": evidence["output"]["sha256"],
            "clock": "normalized-target-frame-clock",
            "transcriptAndCutsMustBindThisAsset": True,
            "rawSourceIsNotEditTimeAuthority": True,
        },
    }


def build_cadence_approval(evidence_path: str) -> dict:
    """Build a deterministic approval; this does not admit the media."""
    path = os.path.abspath(evidence_path)
    evidence = verify_qualification_evidence(path)
    body = _body(path, evidence)
    digest = hashlib.sha256(
        b"sniper-palmier-cadence-approval-v1\0"
        + canonical_bytes(body)).hexdigest()
    return {**body, "approvalDigest": digest}


def verify_cadence_approval(path: str) -> dict:
    """Rebuild the exact policy decision from retained qualification facts."""
    document = read_canonical_evidence(os.path.abspath(path))
    evidence_path = (document.get("qualification") or {}).get("evidencePath")
    if type(evidence_path) is not str:
        raise RuntimeError("cadence approval lacks qualification authority")
    expected = build_cadence_approval(evidence_path)
    if document != expected:
        raise RuntimeError("cadence approval authority mismatch")
    return document


def publish_cadence_approval(evidence_path: str, output_path: str) -> dict:
    """Publish one immutable canonical approval without overwrite."""
    output = Path(os.path.abspath(output_path))
    document = build_cadence_approval(evidence_path)
    publish_canonical(output, document)
    return verify_cadence_approval(str(output))
