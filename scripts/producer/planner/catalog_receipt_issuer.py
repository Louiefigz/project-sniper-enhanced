#!/usr/bin/env python3
"""Controller-only issuer for static catalog source-inspection receipts."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import secrets
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from planner.visual_plan_authority_admission import load_catalog_authority  # noqa: E402
from planner.catalog_receipt_pipeline import catalog_receipt_pipeline_sha256  # noqa: E402
from planner.visual_plan_fields import (  # noqa: E402
    VisualPlanContractError, canonical_hash, sha_field,
)
from planner.visual_plan_receipts import (  # noqa: E402
    AUTHORITY_NAME, MAX_ARTIFACT_BYTES, MAX_RECEIPT_BYTES, RUNNER,
    authority_pin, controller_identities, read_exact, receipt_binding,
)

@dataclass
class IssuerRun:
    """One private controller run and its sealed result inventory."""

    plan: dict
    authority: dict
    root: Path
    pipeline_sha256: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    nonce: str = field(default_factory=lambda: secrets.token_hex(32))
    records: list[dict] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IssuedCatalogReceipts:
    """Patched pending plan and out-of-band controller authority pin."""

    plan: dict
    authority: dict
    directory: str


@dataclass(frozen=True)
class IssueTarget:
    """One catalog candidate operation selected by the controller."""

    opportunity: dict
    candidate: dict
    catalog: dict
    kind: str


@dataclass(frozen=True)
class Attempt:
    """Observed subprocess result for one exact target."""

    target: IssueTarget
    binding: dict
    process: subprocess.CompletedProcess
    artifact: Path


def _write(path: Path, data: bytes) -> dict:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        offset = 0
        while offset < len(data):
            offset += os.write(descriptor, data[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(data).hexdigest()}


def _write_json(path: Path, value: object) -> dict:
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()
    return _write(path, data)


def _private_run(parent: str) -> Path:
    requested = Path(parent).expanduser()
    if not requested.exists() or requested.is_symlink() or not requested.is_dir():
        raise VisualPlanContractError("catalog receipt authority parent must be canonical")
    root = requested.resolve()
    destination = root / f"catalog-receipts-{uuid.uuid4()}"
    destination.mkdir(mode=0o700)
    return destination.resolve()


def _record_catalog(run: IssuerRun, candidate: dict) -> dict:
    record = run.authority["records"].get(candidate["source"]["recordId"])
    if not isinstance(record, dict):
        raise VisualPlanContractError("catalog receipt candidate is absent from authority")
    admission = candidate["catalogAdmission"]
    return {**{key: admission[key] for key in (
        "catalogRecordSha256", "executionStatus", "resourceClass",
        "runtimeQualificationRequired")}, "routeClass": candidate["routeClass"],
        "record": record}


def _required_kinds(candidate: dict, catalog: dict) -> list[str]:
    if catalog["executionStatus"] == "reference-missing-source":
        return []
    evidence = candidate["catalogAdmission"]["sourceInspectionEvidence"]
    return [] if evidence is not None else ["source-inspection"]


def _header(run: IssuerRun) -> dict:
    runner, runtime = controller_identities()
    return {"schemaVersion": 1, "kind": "visual-plan-catalog-receipt-authority",
            "runId": run.run_id, "nonce": run.nonce,
            "projectSha256": canonical_hash(run.plan["project"]),
            "catalogPinSha256": canonical_hash(run.plan["catalogPin"]),
            "pipelineAuthoritySha256": run.pipeline_sha256,
            "runnerIdentity": runner, "runtimeIdentity": runtime}


def _request(candidate: dict, catalog: dict, kind: str) -> dict:
    source = candidate["source"]
    return {"schemaVersion": 1, "kind": kind,
            "source": {key: source[key] for key in ("path", "sha256")},
            "catalogRecordSha256": catalog["catalogRecordSha256"],
            "resourceClass": catalog["resourceClass"],
            "resourceEvidence": catalog["record"]["resourceEvidence"]}


def _runner_process(request_path: Path, artifact_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(RUNNER), str(request_path), str(artifact_path)],
        cwd=str(request_path.parent), env={"PYTHONDONTWRITEBYTECODE": "1",
                                           "PYTHONHASHSEED": "0", "PYTHONUTF8": "1"},
        capture_output=True, timeout=30, check=False)


def _failed(run: IssuerRun, attempt: Attempt) -> None:
    process, target, binding = attempt.process, attempt.target, attempt.binding
    run.failures.append({"kind": target.kind,
                         "opportunityId": binding["opportunityId"],
                         "candidateId": target.candidate["id"],
                         "bindingSha256": canonical_hash(binding),
                         "exitStatus": process.returncode,
                         "stdoutSha256": hashlib.sha256(process.stdout).hexdigest(),
                         "stderrSha256": hashlib.sha256(process.stderr).hexdigest()})


def _passed(run: IssuerRun, attempt: Attempt) -> None:
    target, binding = attempt.target, attempt.binding
    candidate, catalog, kind = target.candidate, target.catalog, target.kind
    process, artifact = attempt.process, attempt.artifact
    if process.stderr or not 1 <= len(process.stdout) <= MAX_RECEIPT_BYTES:
        _failed(run, attempt)
        artifact.unlink(missing_ok=True)
        return
    artifact_data = read_exact(str(artifact), "issued catalog artifact", MAX_ARTIFACT_BYTES)
    artifact_pin = {"path": str(artifact),
                    "sha256": hashlib.sha256(artifact_data).hexdigest()}
    index = len(run.records)
    stdout_pin = _write(run.root / f"{index:04d}-{kind}-stdout.json", process.stdout)
    issuer = {**{key: _header(run)[key] for key in (
        "runId", "nonce", "projectSha256", "pipelineAuthoritySha256")},
              "authorityId": canonical_hash(_header(run))}
    observation = json.loads(process.stdout)
    receipt = {"schemaVersion": 1,
               "scope": f"visual-plan-catalog-{kind}-receipt", "status": "passed",
               "issuer": issuer, "binding": binding,
               "inspection": {"resourceClass": catalog["resourceClass"],
                             "toolIdentity": _header(run)["runnerIdentity"],
                             "runtimeIdentity": _header(run)["runtimeIdentity"],
                             "approvalClaims": {
                                 "runtime": False, "render": False, "quality": False}},
               "result": {"status": "passed", "exitStatus": 0,
                          "artifact": artifact_pin, "stdoutSha256": stdout_pin["sha256"],
                          "observationsSha256": canonical_hash(observation)}}
    receipt_pin = _write_json(run.root / f"{index:04d}-{kind}-receipt.json", receipt)
    run.files.extend([artifact.name, Path(stdout_pin["path"]).name,
                      Path(receipt_pin["path"]).name])
    run.records.append({"kind": kind, "opportunityId": binding["opportunityId"],
                        "candidateId": candidate["id"],
                        "bindingSha256": canonical_hash(binding),
                        "receipt": receipt_pin, "artifact": artifact_pin,
                        "stdout": stdout_pin, "exitStatus": 0})


def _issue_one(run: IssuerRun, target: IssueTarget) -> None:
    opportunity, candidate = target.opportunity, target.candidate
    catalog, kind = target.catalog, target.kind
    prefix = f"attempt-{len(run.records) + len(run.failures):04d}-{kind}"
    request_path = run.root / f"{prefix}-request.json"
    artifact = run.root / f"{prefix}-artifact.json"
    binding = receipt_binding(run.plan, opportunity, candidate, catalog)
    _write_json(request_path, _request(candidate, catalog, kind))
    try:
        process = _runner_process(request_path, artifact)
    finally:
        request_path.unlink(missing_ok=True)
    if process.returncode != 0 or not artifact.exists():
        artifact.unlink(missing_ok=True)
        _failed(run, Attempt(target, binding, process, artifact))
        return
    _passed(run, Attempt(target, binding, process, artifact))


def _patch_plan(plan: dict, records: list[dict]) -> None:
    lookup = {(row["opportunityId"], row["candidateId"], row["kind"]): row
              for row in records}
    for opportunity in plan["opportunities"]:
        for candidate in opportunity["candidates"]:
            if candidate["modality"] != "catalog":
                continue
            admission = candidate["catalogAdmission"]
            kind = "source-inspection"
            record = lookup.get((opportunity["id"], candidate["id"], kind))
            if record is not None:
                admission["sourceInspectionEvidence"] = record["receipt"]
            _patch_candidate_state(candidate)


def _patch_candidate_state(candidate: dict) -> None:
    admission = candidate["catalogAdmission"]
    status = admission["executionStatus"]
    missing = []
    if status != "reference-missing-source" \
            and admission["sourceInspectionEvidence"] is None:
        missing.append("catalog-static-source-inspection-evidence")
    if status == "integrated-unmeasured":
        missing.append("catalog-integration-unmeasured")
    candidate["eligibility"] = ("blocked" if status == "reference-missing-source"
                                else "prerequisite" if missing else "eligible")
    candidate["prerequisites"] = missing


def issue_catalog_receipts(plan: dict, parent: str) -> IssuedCatalogReceipts:
    """Run fixed tools, patch successful candidates, and seal controller authority."""
    pipeline_sha256 = catalog_receipt_pipeline_sha256()
    sha_field(pipeline_sha256, "pipeline authority SHA-256")
    from planner.visual_plan_contract import validate_visual_plan
    validated = validate_visual_plan(plan)
    patched = copy.deepcopy(validated)
    patched["allocation"] = {"status": "pending",
                             "allocatorVersion": "visual-plan-allocator-v1",
                             "route": "pending", "decisions": [],
                             "unresolvedAmbiguity": []}
    run = IssuerRun(patched, load_catalog_authority(patched["catalogPin"]),
                    _private_run(parent), pipeline_sha256)
    for opportunity in patched["opportunities"]:
        for candidate in opportunity["candidates"]:
            if candidate["modality"] != "catalog":
                continue
            catalog = _record_catalog(run, candidate)
            for kind in _required_kinds(candidate, catalog):
                _issue_one(run, IssueTarget(opportunity, candidate, catalog, kind))
    _patch_plan(patched, run.records)
    core = {**_header(run), "authorityId": canonical_hash(_header(run)),
            "records": run.records, "failures": run.failures,
            "allowedFiles": sorted(run.files + [AUTHORITY_NAME])}
    manifest = run.root / AUTHORITY_NAME
    _write_json(manifest, {**core, "digest": canonical_hash(core)})
    pin = authority_pin(str(manifest))
    validate_visual_plan(patched, receipt_authority=pin)
    from planner.visual_plan_allocator import allocate_visual_plan
    try:
        patched = allocate_visual_plan(patched, pin)
    except VisualPlanContractError as exc:
        if "no eligible allocation" not in str(exc):
            raise
    return IssuedCatalogReceipts(patched, pin, str(run.root))
