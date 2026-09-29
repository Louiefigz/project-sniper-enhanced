"""Controller-owned catalog receipt authority and validation."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from planner.visual_plan_fields import (
    VisualPlanContractError, canonical_hash, object_field, sha_field,
)

MAX_RECEIPT_BYTES, MAX_ARTIFACT_BYTES = 4 * 1024 * 1024, 16 * 1024 * 1024
AUTHORITY_NAME = "CATALOG-RECEIPT-AUTHORITY.json"
RUNNER = Path(__file__).resolve().parents[1] / "graphics/catalog_receipt_runner.py"


@dataclass(frozen=True)
class ReceiptRequest:
    """Trusted catalog facts plus the out-of-band controller authority pin."""
    kind: str
    pin: dict
    plan: dict
    opportunity: dict
    candidate: dict
    catalog: dict
    receipt_authority: dict | None = None


def _file_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_nlink)


def read_exact(path: str, label: str, maximum: int,
               expected_sha: str | None = None) -> bytes:
    """Read one bounded single-link file from one no-follow descriptor."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = None
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 \
                or not 1 <= before.st_size <= maximum:
            raise VisualPlanContractError(
                f"{label} must be one bounded single-link file")
        chunks, remaining = [], before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise VisualPlanContractError(f"{label} changed during its read")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise VisualPlanContractError(f"{label} is unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if _file_identity(before) != _file_identity(after):
        raise VisualPlanContractError(f"{label} changed during its read")
    data = b"".join(chunks)
    if expected_sha is not None and hashlib.sha256(data).hexdigest() != expected_sha:
        raise VisualPlanContractError(f"{label} SHA-256 differs from controller authority")
    return data

def _json_bytes(data: bytes, label: str) -> dict:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VisualPlanContractError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise VisualPlanContractError(f"{label} must be an object")
    return value

def file_identity(path: str, name: str) -> dict:
    """Return a fixed executable file identity."""
    canonical = os.path.realpath(path)
    data = read_exact(canonical, f"{name} identity", MAX_ARTIFACT_BYTES)
    return {"name": name, "path": canonical, "sha256": hashlib.sha256(data).hexdigest()}

def controller_identities() -> tuple[dict, dict]:
    """Re-derive the only admitted runner and Python runtime identities."""
    return (file_identity(str(RUNNER), "catalog-receipt-runner"),
            file_identity(sys.executable, "python-runtime"))

def receipt_binding(plan: dict, opportunity: dict, candidate: dict,
                    catalog: dict) -> dict:
    """Exact catalog and editorial context a receipt must claim."""
    context = {
        "project": plan["project"],
        "opportunity": {key: value for key, value in opportunity.items()
                        if key != "candidates"},
        "candidate": {key: candidate[key] for key in (
            "id", "modality", "routeClass", "source", "composition",
            "expectedVisibleResult", "reviewTarget")},
        "catalog": catalog,
    }
    return {
        "catalogId": plan["catalogPin"]["catalogId"],
        "snapshotVersion": plan["catalogPin"]["version"],
        "recordId": candidate["source"]["recordId"],
        "catalogRecordSha256": catalog["catalogRecordSha256"],
        "sourceSha256": candidate["source"]["sha256"],
        "planId": plan["planId"], "opportunityId": opportunity["id"],
        "candidateId": candidate["id"], "contextSha256": canonical_hash(context),
    }

def authority_pin(path: str) -> dict:
    """Freeze a controller authority manifest as an out-of-band pin."""
    canonical = os.path.realpath(path)
    data = read_exact(canonical, "catalog receipt authority", MAX_RECEIPT_BYTES)
    value = _json_bytes(data, "catalog receipt authority")
    fields = ("digest", "authorityId", "runId", "nonce", "pipelineAuthoritySha256")
    if any(not isinstance(value.get(key), str) for key in fields):
        raise VisualPlanContractError("catalog receipt authority header is invalid")
    return {"schemaVersion": 1, "path": canonical,
            "sha256": hashlib.sha256(data).hexdigest(),
            **{key: value[key] for key in fields}}


def _authority_document(pin: dict, request: ReceiptRequest) -> dict:
    keys = {"schemaVersion", "path", "sha256", "digest", "authorityId",
            "runId", "nonce", "pipelineAuthoritySha256"}
    row = object_field(pin, "catalog receipt authority pin", keys, set())
    if row["schemaVersion"] != 1:
        raise VisualPlanContractError("catalog receipt authority pin version is invalid")
    for key in ("sha256", "digest", "authorityId", "nonce",
                "pipelineAuthoritySha256"):
        sha_field(row[key], f"catalog receipt authority pin {key}")
    data = read_exact(row["path"], "catalog receipt authority",
                      MAX_RECEIPT_BYTES, row["sha256"])
    value = _json_bytes(data, "catalog receipt authority")
    required = {"schemaVersion", "kind", "runId", "nonce", "authorityId",
                "projectSha256", "catalogPinSha256", "pipelineAuthoritySha256",
                "runnerIdentity", "runtimeIdentity", "records", "failures",
                "allowedFiles", "digest"}
    document = object_field(value, "catalog receipt authority", required, set())
    core = {key: document[key] for key in required - {"digest"}}
    if document["schemaVersion"] != 1 \
            or document["kind"] != "visual-plan-catalog-receipt-authority" \
            or canonical_hash(core) != document["digest"]:
        raise VisualPlanContractError("catalog receipt authority seal is invalid")
    for key in ("digest", "authorityId", "runId", "nonce", "pipelineAuthoritySha256"):
        if document[key] != row[key]:
            raise VisualPlanContractError(f"catalog receipt authority {key} is stale")
    _validate_authority_context(document, request)
    _validate_authority_directory(row["path"], document["allowedFiles"])
    return document


def _validate_authority_context(document: dict, request: ReceiptRequest) -> None:
    from planner.catalog_receipt_pipeline import catalog_receipt_pipeline_sha256
    runner, runtime = controller_identities()
    if document["runnerIdentity"] != runner or document["runtimeIdentity"] != runtime:
        raise VisualPlanContractError("catalog receipt tool or runtime identity is invalid")
    if document["projectSha256"] != canonical_hash(request.plan["project"]) or \
            document["catalogPinSha256"] != canonical_hash(request.plan["catalogPin"]):
        raise VisualPlanContractError("catalog receipt project or snapshot authority is stale")
    if document["pipelineAuthoritySha256"] != catalog_receipt_pipeline_sha256():
        raise VisualPlanContractError("catalog receipt pipeline authority is stale")
    header = {key: document[key] for key in (
        "schemaVersion", "kind", "runId", "nonce", "projectSha256",
        "catalogPinSha256", "pipelineAuthoritySha256", "runnerIdentity",
        "runtimeIdentity")}
    if document["authorityId"] != canonical_hash(header):
        raise VisualPlanContractError("catalog receipt authority ID is invalid")


def _validate_authority_directory(manifest: str, allowed: object) -> None:
    if not isinstance(allowed, list) or not 1 <= len(allowed) <= 4096 \
            or len(allowed) != len(set(allowed)):
        raise VisualPlanContractError("catalog receipt authority file inventory is invalid")
    if any(not isinstance(name, str) or os.path.basename(name) != name for name in allowed):
        raise VisualPlanContractError("catalog receipt authority file name is invalid")
    directory = os.path.dirname(manifest)
    if os.path.realpath(directory) != directory or stat.S_ISLNK(os.lstat(directory).st_mode):
        raise VisualPlanContractError("catalog receipt authority directory is not canonical")
    actual = sorted(entry.name for entry in os.scandir(directory))
    if actual != sorted(allowed) or AUTHORITY_NAME not in actual:
        raise VisualPlanContractError("catalog receipt authority directory has extra or missing files")
    for name in actual:
        info = os.lstat(os.path.join(directory, name))
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise VisualPlanContractError("catalog receipt authority contains a linked file")

def _matching_record(document: dict, request: ReceiptRequest) -> dict:
    records = document["records"]
    if not isinstance(records, list) or len(records) > 4096:
        raise VisualPlanContractError("catalog receipt records are invalid")
    matches = [row for row in records if isinstance(row, dict)
               and row.get("kind") == request.kind
               and row.get("opportunityId") == request.opportunity["id"]
               and row.get("candidateId") == request.candidate["id"]]
    if len(matches) != 1:
        raise VisualPlanContractError("catalog receipt is absent from controller authority")
    return matches[0]

def _receipt_document(record: dict, request: ReceiptRequest) -> dict:
    keys = {"kind", "opportunityId", "candidateId", "bindingSha256",
            "receipt", "artifact", "stdout", "exitStatus"}
    row = object_field(record, "catalog receipt authority record", keys, set())
    if row["exitStatus"] != 0 or row["receipt"] != request.pin:
        raise VisualPlanContractError("catalog receipt did not complete successfully")
    data = read_exact(request.pin["path"], "catalog receipt", MAX_RECEIPT_BYTES,
                      request.pin["sha256"])
    return _json_bytes(data, "catalog receipt")


def _expected_observation(request: ReceiptRequest, artifact: bytes) -> dict:
    missing, unsupported = _dependency_findings(request)
    return {"schemaVersion": 1,
            "scope": "catalog-controller-static-source-inspection",
            "kind": request.kind,
            "sourceSha256": request.candidate["source"]["sha256"],
            "catalogRecordSha256": request.catalog["catalogRecordSha256"],
            "resourceClass": request.catalog["resourceClass"],
            "artifactSha256": hashlib.sha256(artifact).hexdigest(),
            "artifactBytes": len(artifact), "missingDependencies": missing,
            "unsupportedDependencies": unsupported}


def _dependency_findings(request: ReceiptRequest) -> tuple[list[str], list[str]]:
    resource = request.catalog["record"].get("resourceEvidence")
    dependency = resource.get("dependencySize") if isinstance(resource, dict) else None
    missing = dependency.get("missingReferences") if isinstance(dependency, dict) else None
    external = dependency.get("externalReferences") if isinstance(dependency, dict) else None
    missing = missing if isinstance(missing, list) else []
    external = external if isinstance(external, list) else []
    allowed = {"https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"}
    return sorted(set(missing)), sorted(set(external) - allowed)


def _expected_artifact(request: ReceiptRequest) -> bytes:
    missing, unsupported = _dependency_findings(request)
    value = {
        "schemaVersion": 1,
        "scope": "catalog-static-source-inspection",
        "sourceSha256": request.candidate["source"]["sha256"],
        "resourceClass": request.catalog["resourceClass"],
        "catalogRecordSha256": request.catalog["catalogRecordSha256"],
        "staticDependencyStatus": (
            "unresolved" if missing or unsupported else "statically-closed"),
        "missingReferences": missing,
        "unsupportedExternalReferences": unsupported,
        "approvalClaims": {"runtime": False, "render": False, "quality": False},
    }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _validate_receipt_result(receipt: dict, record: dict,
                             request: ReceiptRequest) -> None:
    artifact_pin, stdout_pin = record["artifact"], record["stdout"]
    artifact = read_exact(artifact_pin["path"], "catalog receipt artifact",
                          MAX_ARTIFACT_BYTES, artifact_pin["sha256"])
    stdout = read_exact(stdout_pin["path"], "catalog receipt stdout",
                        MAX_RECEIPT_BYTES, stdout_pin["sha256"])
    observation = _json_bytes(stdout, "catalog receipt stdout")
    expected = _expected_observation(request, artifact)
    result = receipt["result"]
    if artifact != _expected_artifact(request) or observation != expected or result != {
            "status": "passed", "exitStatus": 0, "artifact": artifact_pin,
            "stdoutSha256": stdout_pin["sha256"],
            "observationsSha256": canonical_hash(observation)}:
        raise VisualPlanContractError("catalog receipt result differs from observed execution")


def validate_catalog_receipt(request: ReceiptRequest) -> None:
    """Accept only an exact receipt listed by an out-of-band controller authority."""
    if request.kind != "source-inspection":
        raise VisualPlanContractError("catalog receipt kind is unsupported")
    if request.receipt_authority is None:
        raise VisualPlanContractError(
            "catalog receipt needs out-of-band controller authority")
    document = _authority_document(request.receipt_authority, request)
    record = _matching_record(document, request)
    receipt = _receipt_document(record, request)
    required = {"schemaVersion", "scope", "status", "issuer", "binding",
                "inspection", "result"}
    value = object_field(receipt, "catalog receipt", required, set())
    issuer = {key: document[key] for key in (
        "authorityId", "runId", "nonce", "projectSha256",
        "pipelineAuthoritySha256")}
    inspection = {"resourceClass": request.catalog["resourceClass"],
                  "toolIdentity": document["runnerIdentity"],
                  "runtimeIdentity": document["runtimeIdentity"],
                  "approvalClaims": {
                      "runtime": False, "render": False, "quality": False}}
    binding = receipt_binding(request.plan, request.opportunity,
                              request.candidate, request.catalog)
    if value["schemaVersion"] != 1 or value["scope"] != \
            f"visual-plan-catalog-{request.kind}-receipt" \
            or value["status"] != "passed" or value["issuer"] != issuer \
            or value["binding"] != binding or value["inspection"] != inspection \
            or record["bindingSha256"] != canonical_hash(binding):
        raise VisualPlanContractError("catalog receipt provenance or binding is invalid")
    _validate_receipt_result(value, record, request)
