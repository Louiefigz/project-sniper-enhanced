"""Durable, hash-bound contracts for Palmier-native candidate QC."""
from __future__ import annotations

import json
import hashlib
import os
import re
from datetime import datetime, timezone

from fingerprints import file_sha256
from palmier.mcp_client import PalmierError
from palmier.native_plan import validate_native_plan
from palmier.quality_hash import authority_snapshot, request_key, stable_hash
from palmier.timeline_authority import atomic_write_record

QC_NAME = "palmier.native-qc.json"
AUDIT_NAME = "palmier.native-audit.json"
EXPORT_NAME = "palmier.candidate.mp4"
EXPORT_TEMP_NAME = ".palmier.candidate.tmp.mp4"
QC_STATUSES = {"prepared", "deterministic-passed", "qc-approved", "promoted",
               "superseded-manual", "qc-rejected", "discarded"}
_SHA = re.compile(r"^[0-9a-f]{64}$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def qc_path(out_dir: str) -> str:
    return os.path.join(out_dir, QC_NAME)


def audit_path(out_dir: str) -> str:
    return os.path.join(out_dir, AUDIT_NAME)


def export_path(out_dir: str) -> str:
    return os.path.join(out_dir, EXPORT_NAME)


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise PalmierError(f"Palmier native QC {label} is not an object")
    return value


def _json(path: str, label: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            return _object(json.load(handle), label)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read Palmier native QC {label}: {exc}") from exc


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise PalmierError(f"Palmier native QC {label} is not a SHA-256 digest")
    return value


def load_qc(out_dir: str, statuses: set[str] | None = None) -> dict:
    """Load a receipt and require a supported lifecycle state."""
    receipt = _json(qc_path(out_dir), "receipt")
    status = receipt.get("status")
    if receipt.get("schemaVersion") != 1 or status not in QC_STATUSES:
        raise PalmierError("Palmier native QC receipt has an unsupported schema/state")
    if statuses is not None and status not in statuses:
        expected = ", ".join(sorted(statuses))
        raise PalmierError(f"Palmier native QC requires {expected}; current state is {status}")
    return receipt


def save_qc(out_dir: str, receipt: dict) -> dict:
    if receipt.get("schemaVersion") != 1 or receipt.get("status") not in QC_STATUSES:
        raise PalmierError("refusing to save malformed Palmier native QC receipt")
    atomic_write_record(qc_path(out_dir), receipt)
    return receipt


def _identity(value: dict) -> dict:
    return {key: value.get(key) for key in
            ("projectId", "timelineId", "fingerprint")}


def _pinned_context(value: object, out_dir: str) -> tuple[dict, dict, str]:
    envelope = _object(value, "authority input")
    ctx = _object(envelope.get("ctx"), "authority input.ctx")
    request_hash = envelope.get("requestHash")
    capture_id = envelope.get("captureId")
    if envelope.get("schemaVersion") != 1 or not _SHA.fullmatch(str(request_hash)) \
            or not isinstance(capture_id, str) or not capture_id:
        raise PalmierError("Palmier native QC authority input is malformed")
    if os.path.realpath(str(ctx.get("dir"))) != os.path.realpath(out_dir):
        raise PalmierError("Palmier native QC context targets another project")
    doctrine, pipeline = ctx.get("doctrine"), ctx.get("pipeline")
    if not isinstance(doctrine, dict) or not isinstance(pipeline, dict):
        raise PalmierError("Palmier native QC requires pinned doctrine and pipeline authority")
    if doctrine.get("runId") != capture_id or pipeline.get("runId") != capture_id:
        raise PalmierError("Palmier native QC requires a dedicated matching authority capture")
    return envelope, ctx, str(request_hash)


def _native_input(envelope: dict, ctx: dict, request_hash: str) -> dict:
    receipt = _object(envelope.get("nativeInput"), "authority input.nativeInput")
    expected = {"path", "hash", "requestTextHash", "lanes", "parent",
                "nativePlanHash"}
    if set(receipt) != expected:
        raise PalmierError("Palmier native QC input receipt has unknown or missing fields")
    path = receipt.get("path")
    if not isinstance(path, str) or not os.path.isabs(path) \
            or os.path.realpath(str(ctx.get("planPath"))) != os.path.realpath(path):
        raise PalmierError("Palmier native QC context does not name its native input")
    digest = _sha(receipt.get("hash"), "nativeInput.hash")
    if not os.path.isfile(path) or os.path.islink(path) or file_sha256(path) != digest:
        raise PalmierError("Palmier native QC input artifact changed")
    value = _json(path, "native candidate input")
    return _validate_native_input(value, receipt, request_hash)


def _validate_native_input(value: dict, receipt: dict,
                           request_hash: str) -> dict:
    required = {"schemaVersion", "kind", "request", "controller", "parent",
                "nativePlan"}
    if set(value) != required or value.get("schemaVersion") != 1 \
            or value.get("kind") != "palmier-native-candidate-input":
        raise PalmierError("Palmier native candidate input has an invalid envelope")
    request = _object(value.get("request"), "native input.request")
    controller = _object(value.get("controller"), "native input.controller")
    if set(request) != {"text", "hash"} or set(controller) != {"lanes"}:
        raise PalmierError("Palmier native request/controller authority is malformed")
    text = request.get("text")
    text_hash = hashlib.sha256(str(text).encode("utf-8")).hexdigest()
    if not isinstance(text, str) or not text.strip() or request.get("hash") != text_hash \
            or text_hash != request_hash or receipt.get("requestTextHash") != text_hash:
        raise PalmierError("Palmier native exact request text authority changed")
    parent = _object(value.get("parent"), "native input.parent")
    plan = validate_native_plan(value.get("nativePlan"), parent)
    lanes = controller.get("lanes")
    if lanes != plan.get("lanes") or lanes != receipt.get("lanes") \
            or plan.get("requestHash") != request_hash \
            or _identity(plan.get("parent") or {}) != _identity(parent) \
            or _identity(parent) != _identity(_object(receipt.get("parent"),
                                                    "nativeInput.parent")) \
            or stable_hash(plan) != receipt.get("nativePlanHash"):
        raise PalmierError("Palmier native controller lanes/plan authority changed")
    return {"request": {"text": text, "hash": text_hash}, "lanes": lanes,
            "parent": parent, "nativePlan": plan}


def authority_from_input(out_dir: str, input_path: str,
                         candidate: dict, parent: dict) -> dict:
    """Independently verify pinned input bytes; never trust a summary from TS."""
    envelope = _json(input_path, "authority input")
    envelope, ctx, request_hash = _pinned_context(envelope, out_dir)
    if candidate.get("requestHash") != request_hash:
        raise PalmierError("Palmier candidate request hash does not match QC authority input")
    return _native_authority(envelope, ctx, request_hash, {
        "candidate": candidate, "parent": parent})


def validate_current_authority(receipt: dict) -> dict:
    """Recompute every mutable input/pinned-copy proof stored at prepare time."""
    authority = _object(receipt.get("authority"), "receipt.authority")
    candidate = _object(receipt.get("candidate"), "receipt.candidate")
    parent = _object(receipt.get("parent"), "receipt.parent")
    envelope = {"schemaVersion": 1, "requestHash": authority.get("requestHash"),
                "captureId": authority.get("captureId"),
                "ctx": authority.get("context"),
                "nativeInput": authority.get("nativeInput")}
    current = authority_from_value(envelope, receipt.get("outDir"), {
        "candidate": candidate, "parent": parent})
    compared = ("captureId", "requestKey", "inputDigest", "pipelineDigest",
                "doctrineHash", "planHash", "manifestHash", "requestTextHash",
                "lanes", "nativePlanHash")
    if any(current.get(key) != authority.get(key) for key in compared):
        raise PalmierError("Palmier native QC input/pipeline/doctrine authority changed")
    return current


def authority_from_value(value: object, out_dir: object,
                         evidence: dict) -> dict:
    """In-memory counterpart used when revalidating the durable receipt."""
    if not isinstance(out_dir, str):
        raise PalmierError("Palmier native QC receipt has no output directory")
    envelope, ctx, request_hash = _pinned_context(value, out_dir)
    candidate = _object(evidence.get("candidate"), "authority candidate")
    parent = _object(evidence.get("parent"), "authority parent")
    if candidate.get("requestHash") != request_hash:
        raise PalmierError("Palmier native QC request authority changed")
    return _native_authority(envelope, ctx, request_hash, {
        "candidate": candidate, "parent": parent})


def _native_authority(envelope: dict, ctx: dict, request_hash: str,
                      evidence: dict) -> dict:
    """Verify shared inputs while explicitly excluding stale Sniper plan bytes."""
    candidate = _object(evidence.get("candidate"), "native candidate")
    parent = _object(evidence.get("parent"), "native parent")
    native = _native_input(envelope, ctx, request_hash)
    plan, lanes = native["nativePlan"], native["lanes"]
    if _identity(native["parent"]) != _identity(parent) \
            or candidate.get("lanes") != lanes \
            or candidate.get("nativePlanHash") != stable_hash(plan):
        raise PalmierError("Palmier native candidate is not bound to its input plan")
    native_plan_hash = stable_hash(plan)
    try:
        snapshot = authority_snapshot(ctx)
        key = request_key(ctx)
    except (KeyError, OSError, ValueError) as exc:
        raise PalmierError(f"Palmier native QC input authority is invalid: {exc}") from exc
    doctrine = _object(ctx.get("doctrine"), "pinned doctrine")
    summary = {
        "schemaVersion": 1, "scope": snapshot["scope"],
        "requestHash": request_hash, "requestTextHash": request_hash,
        "lanes": lanes, "nativePlanHash": native_plan_hash,
        "parent": {key: parent.get(key) for key in
                   ("projectId", "timelineId", "fingerprint")},
        "candidate": {key: candidate.get(key) for key in
                      ("projectId", "timelineId", "fingerprint")},
        "manifestHash": snapshot["manifestHash"],
        "operatorIntentDigest": snapshot["operatorIntentDigest"],
        "transcriptDigest": snapshot["transcriptDigest"],
        "referenceDigest": snapshot["referenceDigest"],
        "pipelineDigest": snapshot["pipelineDigest"],
    }
    return {"requestHash": request_hash, "requestKey": key,
            "requestTextHash": request_hash, "request": native["request"],
            "lanes": lanes,
            "captureId": ctx["pipeline"]["runId"],
            "inputDigest": stable_hash(summary),
            "pipelineDigest": snapshot["pipelineDigest"],
            "doctrineHash": _sha(doctrine.get("doctrineHash"), "doctrineHash"),
            "planHash": native_plan_hash, "nativePlanHash": native_plan_hash,
            "manifestHash": snapshot["manifestHash"], "summary": summary,
            "nativePlan": plan, "nativeInput": envelope["nativeInput"],
            "nativeParent": native["parent"], "context": ctx}


def validate_export(receipt: dict) -> dict:
    export = _object(receipt.get("export"), "receipt.export")
    path = export.get("path")
    digest = _sha(export.get("hash"), "export.hash")
    if not isinstance(path, str) or path != export_path(str(receipt.get("outDir"))):
        raise PalmierError("Palmier candidate export path is not canonical")
    if not os.path.isfile(path) or os.path.islink(path) or file_sha256(path) != digest:
        raise PalmierError("Palmier candidate export bytes changed after QC")
    if export.get("audioPresent") is not True:
        raise PalmierError("Palmier candidate export has no preserved audio")
    return export


def validate_reviews(value: object, receipt: dict) -> dict:
    payload = _object(value, "rendered reviews")
    rows = payload.get("reviews")
    if payload.get("schemaVersion") != 1 or not isinstance(rows, list) or len(rows) != 2:
        raise PalmierError("Palmier native QC requires exactly two rendered reviews")
    expected = {"composition", "editorial"}
    found = {row.get("lens") for row in rows if isinstance(row, dict)}
    if found != expected:
        raise PalmierError("Palmier native QC requires composition and editorial reviews")
    for row_value in rows:
        _validate_review(_object(row_value, "rendered review"), receipt)
    return {row["lens"]: row for row in rows}


def _validate_review(row: dict, receipt: dict) -> None:
    candidate = _object(receipt.get("candidate"), "receipt.candidate")
    export = _object(receipt.get("export"), "receipt.export")
    authority = _object(receipt.get("authority"), "receipt.authority")
    deterministic = _object(receipt.get("deterministic"), "receipt.deterministic")
    valid = (row.get("schemaVersion") == 1 and row.get("stage") == "rendered"
             and row.get("lens") in ("composition", "editorial")
             and row.get("verdict") == "pass" and row.get("materialIssues") == []
             and row.get("candidateFingerprint") == candidate.get("fingerprint")
             and row.get("exportHash") == export.get("hash")
             and row.get("inputAuthorityDigest") == authority.get("inputDigest")
             and row.get("deterministicDigest") == deterministic.get("digest"))
    if not valid:
        raise PalmierError(f"Palmier native QC {row.get('lens')} review is stale or did not pass")


def approval_digest(receipt: dict) -> str:
    content = {key: value for key, value in receipt.items()
               if key not in ("approvalDigest", "status", "promotedAt",
                              "approvedHead")}
    return stable_hash(content)


def file_ref(path: str) -> dict:
    return {"path": path, "hash": file_sha256(path)}
