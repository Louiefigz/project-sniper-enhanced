"""Synthetic worker attestations in literal TEST files, never actual native proof.

All hashes identify these TEST bytes. No Docker, decoder, source color claim,
pipeline qualification or live observation owner is constructed by this data.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from _grade_bt709_identity_fixture import identity_lines, identity_records
from color.grade_bt709_identity import validate_bt709_identity_records
from color.grade_observation_profile import V1
from color.grade_observation_read import _ARGS, _EXACT_VERSION
from cut_preview_io import digest
from guided_source_color_observation_execution import CAVEATS
from guided_source_color_observation_pins import recorded_command_hash
from guided_source_color_observation_replay import record_projection
from test_grade_frame_adapter import decoder_terminal


def raw_records(fixture: object, prepared: dict, directory: Path) -> tuple:
    """Write supplied 32x18/24fps records and run the actual pure metadata validator."""
    source, _unused, probe, rows = identity_records(source=prepared["binding"])
    probe["streams"][0].update(width=32, height=18)
    for row in rows:
        row.update(width=32, height=18)
    probe_ref = fixture.write(directory / "execution/result/probe.json", probe)
    text = "".join(identity_lines(rows)).encode()
    frames_ref = fixture.write(directory / "execution/result/frames.ffprobe", text)
    terminal = {**decoder_terminal(len(rows)), "bytes": len(text), "sha256": frames_ref["sha256"]}
    result = validate_bt709_identity_records((source, prepared["declaration"], probe), identity_lines(rows), terminal)
    return probe_ref, frames_ref, terminal, record_projection(result.records), asdict(result.metadata)


def _network() -> dict:
    """Explicitly fabricated original-worker network assertions; no sockets are opened."""
    return {"schemaVersion": 1, "hostDecoyPositive": True, "hostDecoyPort": 12345,
        "hostDecoyNonceSha256": "5" * 64, "container": {"schemaVersion": 1, "decoyPort": 12345,
        "ownLoopback": {"ok": True, "port": 12346}, "dns": {"resolved": False, "error": "TEST_DENIED"},
        **{name: {"reached": False, "error": "TEST_DENIED"} for name in ("hostLoopbackDecoy", "externalIpv4", "externalIpv6")}}}


def execution_record(fixture: object, job: dict, claim: dict, raw: tuple) -> dict:
    """Synthesize the exact complete owned V1 record shape without invoking a worker."""
    probe, _frames, terminal, _records, _identity = raw
    request = {"sourceSha256": claim["sourceSha256"], "frameCount": claim["frameCount"], "timeoutSeconds": 120}
    command_hash = recorded_command_hash(claim, request, fixture.worker_text)
    intent = fixture.write(Path(job["executionDir"]) / "launch-intent.json", {"schemaVersion": 1,
        "kind": "owned-grade-launch-intent", "claimSha256": job["launchClaim"]["sha256"],
        "containerName": job["containerName"], "inputSha256": job["input"]["sha256"], "requestHash": digest(request),
        "runtimeHash": digest(fixture.runtime), "launchCommandHash": command_hash})
    worker = {"schemaVersion": 1, "policy": V1.policy, "request": request, "status": "complete",
        "gradeApplicable": False, "deliveryApproved": False, "decodedFrameFlagsAvailable": False,
        "invocation": {"executable": "/usr/bin/ffprobe", "args": list(_ARGS)}, "timing": {"decodeMs": 1, "elapsedMs": 2},
        "sourceBeforeSha256": claim["sourceSha256"], "sourceAfterSha256": claim["sourceSha256"],
        "tool": {"version": _EXACT_VERSION, "sha256": "6" * 64},
        "probe": {"sha256": probe["sha256"], "bytes": probe["sizeBytes"]}, "decoder": terminal}
    result = {"schemaVersion": 1, "kind": "private-grade-observation-execution", "policy": V1.policy,
        "request": request, "requestHash": digest(request), "sourcePath": claim["sourcePath"], "status": "complete",
        "launchAttempted": True, "cleanupVerified": True, "gradeApplicable": False, "deliveryApproved": False,
        "workDeadlineMonotonicNs": "1120000000000", "caveats": list(CAVEATS),
        "workerScriptSha256": fixture.worker_ref["sha256"], "launchCommandHash": command_hash,
        "executionSources": list(fixture.inventory), "sourceBeforeSha256": claim["sourceSha256"],
        "sourceAfterSha256": claim["sourceSha256"], "imageId": fixture.runtime["imageId"], "launchIntentSha256": intent["sha256"],
        "isolation": {"imageId": fixture.runtime["imageId"], "containerId": "7" * 64, "networkMode": "none",
                      "nonrootUser": fixture.runtime["userId"], "readonlyRoot": True, "mountSource": claim["sourcePath"]},
        "network": _network(), "worker": worker, "removal": {"containerRef": "7" * 64, "canonicalAbsenceProved": True,
            "method": "docker-force-remove-plus-exact-inspect-absence"}, "cleanupBudgetSeconds": 90, "cleanupMs": 1, "elapsedMs": 3}
    return {**result, "artifactHash": digest(result)}


def observation_record(fixture: object, row: dict) -> dict:
    """Join TEST raw records to the original unmodified project summary domain."""
    records, refs = row["records"], row["artifacts"]
    summary = {key: records[key] for key in ("decodedFrames", "firstPts", "timeBase", "stepTicks", "width", "height")}
    summary.update(source=row["binding"], recordsSha256=records["sha256"], rawFramesSha256=refs["frames"]["sha256"],
        executionSha256=refs["execution"]["sha256"], decodedFrameFlagsAvailable=False, gradeApplicable=False, deliveryApproved=False)
    result = {"schemaVersion": 1, "policy": V1.project_policy, "jobId": row["jobId"], "inputSha256": refs["input"]["sha256"],
        "status": "complete", "cleanupVerified": True, "cleanupMs": 1, "workerPhaseMs": 4, "replayMs": 1,
        "gradeApplicable": False, "deliveryApproved": False, "parentsSha256": refs["parents"]["sha256"],
        "observation": summary, "implementation": list(fixture.inventory), "elapsedMs": 6}
    return {**result, "artifactHash": digest(result)}
