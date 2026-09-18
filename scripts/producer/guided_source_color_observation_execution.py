"""Closed historical worker attestations, not fresh isolation or cleanup proof.

The enclosing reader authenticates execution/claim/intent/approval raw bytes.
This module validates their exact original joins without querying a daemon,
current installed tools, a PID or implementation discovery. V2 is not relabeled.
"""
from __future__ import annotations

import re
from pathlib import Path

from color.grade_contract import closed, integer
from color.grade_observation_profile import V1, parse_request
from color.grade_observation_read import _ARGS, _EXACT_VERSION, _profile_evidence, _worker_state
from cut_preview_io import digest
from guided_source_color_observation_pins import EXECUTION_ROOTS, WORKER, recorded_command_hash, recorded_inventory
from guided_source_color_observation_rows import same_observation_data as same
from guided_source_color_staging_contract import _hash, _literal
from headless.grade_launch_intent import _claim

EXECUTION_FIELDS = {"schemaVersion", "kind", "policy", "request", "requestHash", "sourcePath", "status",
    "launchAttempted", "cleanupVerified", "gradeApplicable", "deliveryApproved", "workDeadlineMonotonicNs",
    "caveats", "workerScriptSha256", "launchCommandHash", "executionSources", "sourceBeforeSha256", "imageId",
    "launchIntentSha256", "isolation", "network", "worker", "removal", "cleanupBudgetSeconds", "cleanupMs",
    "sourceAfterSha256", "elapsedMs", "artifactHash"}
CAVEATS = ["Decoder warnings/errors are rejected; this is not a perfect corruption oracle.",
           "Per-frame corrupt/decode-error flags are unavailable in the pinned decoder.",
           "Current admitted source/declaration and every decoded record need separate validation."]


def artifact(value: dict, fields: set[str]) -> None:
    """Verify the exact original artifact hash domain, without resealing supplied JSON."""
    closed(value, fields, "cold original artifact")
    if _hash(value["artifactHash"]) != digest({key: row for key, row in value.items() if key != "artifactHash"}):
        raise ValueError("cold original artifact semantic hash differs")


def _network(value: dict) -> None:
    """Check only the closed original-worker network attestation, never run probes."""
    closed(value, {"schemaVersion", "hostDecoyPositive", "hostDecoyPort", "hostDecoyNonceSha256", "container"}, "cold network")
    _literal(value, {"schemaVersion": 1, "hostDecoyPositive": True})
    port = integer(value["hostDecoyPort"], 1, 65535)
    _hash(value["hostDecoyNonceSha256"])
    container = closed(value["container"], {"schemaVersion", "decoyPort", "ownLoopback", "hostLoopbackDecoy",
                                          "externalIpv4", "externalIpv6", "dns"}, "cold network container")
    _literal(container, {"schemaVersion": 1, "decoyPort": port})
    own = closed(container["ownLoopback"], {"ok", "port"}, "cold own loopback")
    _literal(own, {"ok": True})
    integer(own["port"], 1, 65535)
    for key in ("hostLoopbackDecoy", "externalIpv4", "externalIpv6", "dns"):
        flag = "resolved" if key == "dns" else "reached"
        row = closed(container[key], {flag, "error"}, "cold network denial")
        _literal(row, {flag: False})
        if type(row["error"]) is not str or not 1 <= len(row["error"]) <= 1000:
            raise ValueError("cold original network denial lacks its error attestation")


def _isolation(execution: dict, claim: dict) -> None:
    """Bind the original exact container identity and absence attestation together."""
    row = closed(execution["isolation"], {"imageId", "containerId", "networkMode", "nonrootUser", "readonlyRoot", "mountSource"},
                 "cold isolation")
    container_id = _hash(row["containerId"])
    same(row, {"imageId": claim["runtime"]["imageId"], "containerId": container_id, "networkMode": "none",
               "nonrootUser": claim["runtime"]["userId"], "readonlyRoot": True, "mountSource": claim["sourcePath"]})
    same(execution["removal"], {"containerRef": container_id, "canonicalAbsenceProved": True,
                               "method": "docker-force-remove-plus-exact-inspect-absence"})
    _network(execution["network"])


def _worker(execution: dict, row: dict, approval: dict) -> dict:
    """Keep exact V1 request/tool/probe/terminal fields and original byte references."""
    worker, binding = execution["worker"], row["binding"]
    _worker_state(worker, binding)
    same(worker["request"], execution["request"])
    same(worker["invocation"], {"executable": "/usr/bin/ffprobe", "args": _ARGS})
    same(worker["tool"], {"version": _EXACT_VERSION,
                          "sha256": _hash(approval["probedClosure"]["sha256"]["/usr/bin/ffprobe"])})
    timing = closed(worker["timing"], {"decodeMs", "elapsedMs"}, "cold worker timing")
    elapsed = integer(timing["elapsedMs"], 0, 120001)
    integer(timing["decodeMs"], 0, elapsed)
    probe, frames = row["artifacts"]["probe"], row["artifacts"]["frames"]
    same(worker["probe"], {"sha256": probe["sha256"], "bytes": probe["sizeBytes"]})
    expected = {"exitCode": 0, "signal": None, "stderrBytes": 0, "stderr": "", "frames": binding["frameCount"],
        "bytes": frames["sizeBytes"], "sha256": frames["sha256"], "reachedEof": True,
        "perFrameCorruptFlag": "unavailable", "perFrameDecodeErrorFlags": "unavailable"}
    same(worker["decoder"], expected)
    if elapsed > execution["elapsedMs"] + 1:
        raise ValueError("cold original worker exceeds its enclosing recorded duration")
    return worker


def validate_recorded_execution(documents: dict, row: dict, job: dict, pins: dict) -> dict:
    """Validate original execution only as read evidence; return its terminal metadata."""
    execution, claim, intent = (documents[key] for key in ("execution", "launchClaim", "intent"))
    artifact(execution, EXECUTION_FIELDS)
    _profile_evidence(execution, V1)
    binding = row["binding"]
    request = parse_request(execution["request"])
    same(request, {"sourceSha256": binding["sourceSha256"], "frameCount": binding["frameCount"],
                   "timeoutSeconds": request["timeoutSeconds"]})
    _literal(execution, {"kind": "private-grade-observation-execution", "policy": V1.policy, "status": "complete",
        "launchAttempted": True, "cleanupVerified": True, "gradeApplicable": False, "deliveryApproved": False,
        "requestHash": digest(request), "sourcePath": row["source"]["path"], "sourceBeforeSha256": binding["sourceSha256"],
        "sourceAfterSha256": binding["sourceSha256"], "imageId": pins["runtime"]["imageId"], "cleanupBudgetSeconds": 90})
    same(execution["caveats"], CAVEATS)
    if type(execution["workDeadlineMonotonicNs"]) is not str \
            or re.fullmatch(r"[1-9][0-9]{0,23}", execution["workDeadlineMonotonicNs"]) is None:
        raise ValueError("cold original phase deadline spelling is invalid")
    integer(execution["elapsedMs"], 0, 120001)
    integer(execution["cleanupMs"], 0, min(90001, execution["elapsedMs"] + 1))
    _claim(claim, row["source"]["path"], request, Path(job["executionDir"]))
    recorded_inventory(execution["executionSources"], pins, EXECUTION_ROOTS)
    command_hash = recorded_command_hash(claim, request, pins["worker"])
    same(execution["launchCommandHash"], command_hash)
    same(execution["workerScriptSha256"], pins["expected"][str(Path(pins["snapshot"]) / WORKER)])
    same(intent, {"schemaVersion": 1, "kind": "owned-grade-launch-intent", "claimSha256": job["launchClaim"]["sha256"],
        "containerName": job["containerName"], "inputSha256": job["input"]["sha256"], "requestHash": digest(request),
        "runtimeHash": digest(pins["runtime"]), "launchCommandHash": command_hash})
    _isolation(execution, claim)
    return _worker(execution, row, pins["approval"])
