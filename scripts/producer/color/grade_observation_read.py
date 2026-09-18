"""Revalidate private raw evidence against a HELD actual worker result.

This is not an API accepting caller-supplied receipts. Digests alone authenticate
nothing; the caller must retain the exact live execution value, current admitted
source/context observations and leases. No plan/grade/approval is written.
"""
from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from color.grade_frame_adapter import validate_records
from color.grade_observation_profile import ObservationProfile, V1, V2, observation_profile, parse_request
from color.grade_source_class import SourceRecordValidation
from cut_preview_io import bound_json, digest, read_bytes, real_directory
from headless.grade_observation_policy import implementation_sources
from headless.container_policy import _read_approval

_MAX_BYTES = 128 * 1024 ** 2
_EXACT_VERSION = "ffprobe version 4.4.2-0ubuntu0.22.04.1 Copyright (c) 2007-2021 the FFmpeg developers"
_ARGS = ["-v", "warning", "-err_detect", "explode", "-threads", "1",
    "-protocol_whitelist", "file,pipe", "-select_streams", "v:0", "-show_frames",
    "-of", "default=noprint_wrappers=0:nokey=0", "/input/media"]


@dataclass(frozen=True)
class BoundGradeObservation:
    """Matched held invocation plus supplied-record validation; no grade power."""

    records: SourceRecordValidation
    execution_sha256: str
    raw_frames_sha256: str
    raw_probe_sha256: str | None = None
    grade_applicable: bool = field(default=False, init=False)
    delivery_approved: bool = field(default=False, init=False)


def _lines(path: Path, expected: dict) -> Iterator[str]:
    """Stream unchanged bounded UTF-8 metadata; reject FIFO/links before read."""
    real_directory(path.parent)
    parent_before = path.parent.stat()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 \
                or before.st_uid != os.geteuid() or not 0 < before.st_size <= _MAX_BYTES \
                or before.st_size != expected["bytes"]:
            raise RuntimeError("grade raw records are not one bounded owned regular file")
        digest_bytes, total = hashlib.sha256(), 0
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            while raw := stream.readline(32770):
                total += len(raw)
                if total > before.st_size or len(raw) > 32769 or not raw.endswith(b"\n"):
                    raise RuntimeError("grade raw metadata line is oversized or truncated")
                digest_bytes.update(raw)
                yield raw.decode("utf8", errors="strict")
        after, current = os.fstat(descriptor), path.lstat()
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink")
        if total != before.st_size or digest_bytes.hexdigest() != expected["sha256"] \
                or any(getattr(before, key) != getattr(after, key) or getattr(before, key) != getattr(current, key) for key in fields):
            raise RuntimeError("grade raw records changed during validation")
        parent_after = path.parent.stat()
        if (parent_before.st_dev, parent_before.st_ino) != (parent_after.st_dev, parent_after.st_ino):
            raise RuntimeError("grade raw record directory changed during validation")
    finally:
        os.close(descriptor)


def _held_execution(directory: Path, held: dict, binding: dict, raw_sha256: str) -> dict:
    """Require live-held exact receipt and immutable decoder/runtime identities."""
    current = bound_json(directory / "execution.json", raw_sha256)
    body = {key: value for key, value in current.items() if key != "artifactHash"}
    if current != held or digest(body) != held.get("artifactHash"):
        raise RuntimeError("grade execution differs from held invocation")
    request = parse_request(current.get("request"))
    profile = observation_profile(request.get("profile"))
    _profile_evidence(current, profile)
    if current.get("policy") != profile.policy or current.get("status") != "complete" \
            or current.get("cleanupVerified") is not True or current.get("gradeApplicable") is not False \
            or current.get("deliveryApproved") is not False or current.get("launchAttempted") is not True \
            or current.get("removal", {}).get("canonicalAbsenceProved") is not True:
        raise RuntimeError("grade invocation lacks clean private execution evidence")
    for key in ("sourceBeforeSha256", "sourceAfterSha256"):
        if current.get(key) != binding["sourceSha256"]:
            raise RuntimeError("grade observation source identity differs")
    if current.get("executionSources") != implementation_sources():
        raise RuntimeError("grade worker/validator implementation changed")
    approval = _read_approval()
    if current.get("imageId") != approval["imageId"]:
        raise RuntimeError("grade observation is not the current approved image")
    worker = current["worker"]
    _worker_state(worker, binding, profile.token)
    args = [*_ARGS]
    args[5] = str(profile.threads)
    if worker.get("invocation") != {"executable": "/usr/bin/ffprobe", "args": args} \
            or worker.get("tool") != {"version": _EXACT_VERSION,
                "sha256": approval["probedClosure"]["sha256"]["/usr/bin/ffprobe"]}:
        raise RuntimeError("grade strict original-source decoder command/tool changed")
    expected = {"sourceSha256": binding["sourceSha256"], "frameCount": binding["frameCount"],
                "timeoutSeconds": current["request"]["timeoutSeconds"]}
    if profile is V2:
        expected.update(schemaVersion=2, profile=profile.token)
    if current["request"] != expected or worker.get("request") != expected \
            or current.get("requestHash") != digest(expected):
        raise RuntimeError("grade request does not bind the source/frame declaration")
    return worker


def _profile_evidence(value: dict, profile: ObservationProfile) -> None:
    """No limits/profile coercion or historical receipt upgrade is permitted."""
    if type(value.get("schemaVersion")) is not int or value["schemaVersion"] != profile.version:
        raise RuntimeError("grade observation receipt version differs from its request")
    if profile is V1 and ("profile" in value or "limits" in value):
        raise RuntimeError("legacy grade observation cannot carry upgraded limits")
    if profile is V2 and digest({key: value.get(key) for key in ("profile", "limits")}) != digest(profile.evidence()):
        raise RuntimeError("v2 grade observation profile/limits differ from current code")


def _worker_state(worker: dict, binding: dict, profile: str | None = None) -> None:
    """No internally inconsistent or apparently upgraded worker result is valid."""
    keys = {"schemaVersion", "policy", "request", "status", "gradeApplicable", "deliveryApproved",
        "decodedFrameFlagsAvailable", "invocation", "timing", "sourceBeforeSha256", "tool",
        "probe", "decoder", "sourceAfterSha256"}
    config = observation_profile(profile)
    if config is V2:
        keys |= {"profile", "limits"}
    expected = {"schemaVersion": config.version, "policy": config.policy, "status": "complete", "gradeApplicable": False,
        "deliveryApproved": False, "decodedFrameFlagsAvailable": False,
        "sourceBeforeSha256": binding["sourceSha256"], "sourceAfterSha256": binding["sourceSha256"]}
    if type(worker) is not dict or set(worker) != keys \
            or any(type(worker[key]) is not type(value) or worker[key] != value for key, value in expected.items()):
        raise RuntimeError("grade worker success/source/authority state is inconsistent")
    _profile_evidence(worker, config)


def read_observation(directory: Path, context: tuple[dict, dict],
                     held_execution: dict) -> BoundGradeObservation:
    """Check exact raw source records; the caller still owns parent revalidation."""
    binding, declaration = context
    real_directory(directory)
    execution_path = directory / "execution.json"
    execution_bytes = read_bytes(execution_path)
    execution_sha256 = hashlib.sha256(execution_bytes).hexdigest()
    worker = _held_execution(directory, held_execution, binding, execution_sha256)
    result_dir = directory / "result"
    probe = bound_json(result_dir / "probe.json", worker["probe"]["sha256"])
    raw = result_dir / "frames.ffprobe"
    lines = _lines(raw, worker["decoder"])
    try:
        records = validate_records((binding, declaration, probe), lines, worker["decoder"], worker.get("profile"))
    finally:
        lines.close()
    if implementation_sources() != held_execution["executionSources"] \
            or bound_json(result_dir / "probe.json", worker["probe"]["sha256"]) != probe \
            or read_bytes(execution_path) != execution_bytes:
        raise RuntimeError("grade execution authority changed during record validation")
    return BoundGradeObservation(records, execution_sha256, worker["decoder"]["sha256"], worker["probe"]["sha256"])
