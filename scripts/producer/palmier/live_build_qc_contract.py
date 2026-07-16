"""Independent authority validation for full-plan skilled-agent candidates."""
from __future__ import annotations

import hashlib
import json
import os
import re

from fingerprints import file_sha256
from palmier.mcp_client import PalmierError
from palmier.quality_hash import authority_snapshot, request_key, stable_hash

_SHA = re.compile(r"^[0-9a-f]{64}$")


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise PalmierError(f"Palmier live QC {label} is not an object")
    return value


def _json(path: str, label: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            return _object(json.load(handle), label)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read Palmier live QC {label}: {exc}") from exc


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise PalmierError(f"Palmier live QC {label} is not SHA-256")
    return value


def _identity(value: dict) -> dict:
    return {key: value.get(key) for key in
            ("projectId", "timelineId", "fingerprint")}


def _inside(out_dir: str, path: object, label: str) -> str:
    if not isinstance(path, str) or not os.path.isabs(path):
        raise PalmierError(f"Palmier live QC {label} path is not absolute")
    root, target = os.path.realpath(out_dir), os.path.realpath(path)
    try:
        inside = os.path.commonpath([root, target]) == root
    except ValueError:
        inside = False
    if not inside or os.path.islink(path) or not os.path.isfile(path):
        raise PalmierError(f"Palmier live QC {label} is outside its project")
    return path


def _artifact(out_dir: str, value: object, label: str) -> dict:
    row = _object(value, label)
    if set(row) != {"path", "hash"}:
        raise PalmierError(f"Palmier live QC {label} receipt is malformed")
    path = _inside(out_dir, row.get("path"), label)
    digest = _sha(row.get("hash"), f"{label}.hash")
    if file_sha256(path) != digest:
        raise PalmierError(f"Palmier live QC {label} changed")
    return {"path": path, "hash": digest}


def _planning(out_dir: str, rows: object, snapshot: dict) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise PalmierError("Palmier live QC has no approved planning reviews")
    validated = []
    for row_value in rows:
        row = _object(row_value, "planning review receipt")
        if row.get("authorityDigest") != snapshot["digest"] \
                or row.get("planHash") != snapshot["planHash"]:
            raise PalmierError("Palmier live QC planning review is stale")
        refs = {key: _artifact(out_dir, row.get(key), f"planning {key}")
                for key in ("packet", "gates", "review")}
        packet = _json(refs["packet"]["path"], "planning packet")
        gates = _json(refs["gates"]["path"], "planning gates")
        review = _json(refs["review"]["path"], "planning review")
        authority = lambda value: (_object(value, "planning authority")
                                   .get("digest"))
        valid = (isinstance(row.get("round"), int) and row["round"] > 0
                 and packet.get("stage") == "plan"
                 and gates.get("stage") == "plan-gates"
                 and review.get("stage") == "plan"
                 and packet.get("round") == row["round"]
                 and gates.get("round") == row["round"]
                 and review.get("round") == row["round"]
                 and authority(packet.get("inputAuthority")) == snapshot["digest"]
                 and authority(gates.get("inputAuthority")) == snapshot["digest"]
                 and authority(review.get("inputAuthority")) == snapshot["digest"]
                 and _object(gates.get("gates"), "planning gate verdict")
                 .get("ok") is True
                 and _object(review.get("review"), "planning critic verdict")
                 .get("verdict") == "pass")
        if not valid:
            raise PalmierError("Palmier live QC planning evidence did not pass")
        validated.append({**row, **refs})
    rounds = [row["round"] for row in validated]
    if len(rounds) != len(set(rounds)):
        raise PalmierError("Palmier live QC planning reviews are duplicated")
    return validated


def _input(envelope: dict, out_dir: str) -> dict:
    ref = _object(envelope.get("liveInput"), "authority liveInput")
    expected = {"path", "hash", "planHash", "journalHash", "lanes",
                "parent", "operationCount", "sessionId"}
    if set(ref) != expected:
        raise PalmierError("Palmier live QC input receipt has unknown fields")
    path = _inside(out_dir, ref.get("path"), "live input")
    if file_sha256(path) != _sha(ref.get("hash"), "liveInput.hash"):
        raise PalmierError("Palmier live QC input artifact changed")
    value = _json(path, "live input")
    required = {"schemaVersion", "kind", "captureId", "request", "controller",
                "parent", "plan", "journal", "planningReviews", "sessionId"}
    if set(value) != required or value.get("schemaVersion") != 1 \
            or value.get("kind") != "palmier-live-build-input" \
            or value.get("captureId") != envelope.get("captureId"):
        raise PalmierError("Palmier live QC input envelope is malformed")
    return _input_content(value, ref, envelope, out_dir)


def _input_content(value: dict, ref: dict, envelope: dict,
                   out_dir: str) -> dict:
    request = _object(value.get("request"), "live request")
    text = request.get("text")
    request_hash = hashlib.sha256(str(text).encode("utf-8")).hexdigest()
    controller = _object(value.get("controller"), "live controller")
    plan, journal = (_object(value.get("plan"), "live plan"),
                     _object(value.get("journal"), "live journal"))
    plan_path = _inside(out_dir, plan.get("path"), "approved plan")
    journal_path = _inside(out_dir, journal.get("path"), "operation journal")
    lanes = controller.get("lanes")
    valid = (isinstance(text, str) and text.strip()
             and request.get("hash") == request_hash
             and request_hash == envelope.get("requestHash")
             and isinstance(lanes, list) and lanes == ref.get("lanes")
             and file_sha256(plan_path) == plan.get("hash") == ref.get("planHash")
             and file_sha256(journal_path) == journal.get("hash")
             == ref.get("journalHash")
             and isinstance(journal.get("operationCount"), int)
             and journal.get("operationCount") == ref.get("operationCount")
             and value.get("sessionId") == ref.get("sessionId")
             and _identity(_object(value.get("parent"), "live parent"))
             == _identity(_object(ref.get("parent"), "live input parent")))
    if not valid:
        raise PalmierError("Palmier live QC plan, journal, request, or scope changed")
    return {"request": request, "lanes": lanes, "parent": value["parent"],
            "planPath": plan_path, "journalPath": journal_path,
            "planningReviews": value["planningReviews"]}


def authority_from_input(out_dir: str, input_path: str,
                         candidate: dict, parent: dict) -> dict:
    return authority_from_value(_json(input_path, "authority input"), out_dir,
                                {"candidate": candidate, "parent": parent})


def authority_from_value(value: object, out_dir: object,
                         evidence: dict) -> dict:
    if not isinstance(out_dir, str):
        raise PalmierError("Palmier live QC receipt has no output directory")
    envelope = _object(value, "authority input")
    required = {"schemaVersion", "kind", "requestHash", "captureId",
                "liveInput", "ctx"}
    if set(envelope) != required or envelope.get("schemaVersion") != 1 \
            or envelope.get("kind") != "palmier-live-build-qc-authority":
        raise PalmierError("Palmier live QC authority envelope is malformed")
    ctx = _object(envelope.get("ctx"), "authority context")
    if os.path.realpath(str(ctx.get("dir"))) != os.path.realpath(out_dir):
        raise PalmierError("Palmier live QC context targets another project")
    live = _input(envelope, out_dir)
    parent = _object(evidence.get("parent"), "authority parent")
    candidate = _object(evidence.get("candidate"), "authority candidate")
    if _identity(live["parent"]) != _identity(parent) \
            or candidate.get("requestHash") != envelope.get("requestHash") \
            or candidate.get("lanes") != live["lanes"]:
        raise PalmierError("Palmier live candidate is not bound to its approved input")
    snapshot = authority_snapshot(ctx)
    if snapshot.get("planHash") != file_sha256(live["planPath"]):
        raise PalmierError("Palmier live plan authority changed")
    planning = _planning(out_dir, live["planningReviews"], snapshot)
    plan = _json(live["planPath"], "approved edit plan")
    summary = {"schemaVersion": 1, "kind": "live-build",
               "requestHash": envelope["requestHash"], "lanes": live["lanes"],
               "parent": _identity(parent), "candidate": _identity(candidate),
               "planHash": snapshot["planHash"],
               "journalHash": envelope["liveInput"]["journalHash"],
               "planningReviewDigests": [stable_hash(row) for row in planning],
               "authorityDigest": snapshot["digest"]}
    doctrine = _object(ctx.get("doctrine"), "pinned doctrine")
    return {"kind": "live-build", "requestHash": envelope["requestHash"],
            "requestKey": request_key(ctx), "request": live["request"],
            "lanes": live["lanes"], "captureId": envelope["captureId"],
            "inputDigest": stable_hash(summary),
            "pipelineDigest": snapshot["pipelineDigest"],
            "doctrineHash": _sha(doctrine.get("doctrineHash"), "doctrineHash"),
            "planHash": snapshot["planHash"],
            "manifestHash": snapshot["manifestHash"], "summary": summary,
            "editPlan": plan, "liveInput": envelope["liveInput"],
            "nativeParent": {**live["parent"]}, "context": ctx}


def validate_current_authority(receipt: dict) -> dict:
    authority = _object(receipt.get("authority"), "receipt authority")
    envelope = {"schemaVersion": 1,
                "kind": "palmier-live-build-qc-authority",
                "requestHash": authority.get("requestHash"),
                "captureId": authority.get("captureId"),
                "liveInput": authority.get("liveInput"),
                "ctx": authority.get("context")}
    current = authority_from_value(envelope, receipt.get("outDir"), {
        "candidate": receipt.get("candidate"), "parent": receipt.get("parent")})
    compared = ("requestHash", "requestKey", "inputDigest", "pipelineDigest",
                "doctrineHash", "planHash", "manifestHash", "lanes")
    if any(current.get(key) != authority.get(key) for key in compared):
        raise PalmierError("Palmier live QC authority changed")
    return current
