"""New-only TEST metadata topology; no source admission, real approval or native work."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from _guided_body_control_fixture import budget_documents
from _source_color_staging_fixture import staging_fixture
from cut_preview_io import digest, file_hash, write_new
from guided_body_contract import BodyInvocation
from guided_body_source_color_replay import SCOPE
from test_guided_body_contract import body_input, body_activation


def _publish(path: Path, value: dict, pretty: bool = False) -> dict:
    """Publish a named private TEST file before any reader captures it."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if pretty:
        with path.open("xb") as stream:
            stream.write(json.dumps(value, indent=2).encode())
        path.chmod(0o600)
    else:
        write_new(path, value)
    return {"path": str(path), "sha256": file_hash(path)}


def _opening(root: Path) -> tuple[dict, dict, dict, dict]:
    """All original opening/color values are finalized BEFORE first publication."""
    sidecar, archive = staging_fixture()
    sidecar, archive = json.loads(json.dumps([sidecar, archive]).replace(sidecar["producerDir"], str(root)))
    opening = sidecar["opening"]
    execution = Path(opening["claimPath"]).parent
    source = {"profile": "unity-source-float-own-screen-v1", "executionId": opening["executionId"],
        "executionInputHash": opening["executionInputHash"], "pipeline": {"snapshotRoot": str(root / "TEST-snapshot")},
        "documents": {name: {"path": str(root / f"TEST-{name}.json"), "sha256": "5" * 64} for name in ("candidatePlan", "manifest")}}
    source_ref = _publish(Path(opening["inputPath"]), source)
    opening["inputSha256"] = source_ref["sha256"]
    claim = {key: opening[key] for key in ("executionId", "inputPath", "inputSha256", "executionInputHash", "clockHash",
                                          "generationStartedAt", "budgetAdmissionHash", "beforeJournalHash")}
    claim.update(schemaVersion=1, kind="guided-opening-execution-claim", scope="private-opening-owned-execution-not-approval",
        requestId=execution.parents[1].name, outputRoot=str(execution / "media-output"), selectedGraphicOrders=[], runtime=archive["runtime"])
    claim_ref = _publish(Path(opening["claimPath"]), claim, True)
    opening["claimSha256"] = claim_ref["sha256"]
    archive["opening"] = deepcopy(opening)
    archived = execution / "cleanup-attempts/00000000-0000-4000-8000-000000000003/reservation.json"
    archive_ref = _publish(archived, archive)
    archive_ref["sizeBytes"] = archived.stat().st_size
    sidecar["reservation"] = {**archive_ref, "path": str(root / ".sniper-color-resource/active.json")}
    sidecar_ref = _publish(Path(archive["sidecarPath"]), sidecar)
    sidecar_ref["sizeBytes"] = Path(sidecar_ref["path"]).stat().st_size
    return source, claim, {"input": sidecar_ref, "reservationArchive": archive_ref, "sourceColorHash": archive["sourceColorHash"]}, opening


def _result(source: dict, claim: dict, opening: dict) -> tuple[dict, dict]:
    """Inert source2 receipt metadata only; no evidence or media payload exists."""
    output = Path(claim["outputRoot"])
    record = {"schemaVersion": 2, "kind": "guided-opening-media-result", "status": "complete",
        **{key: claim[key] for key in ("inputPath", "inputSha256", "executionId", "executionInputHash")},
        "documents": source["documents"], "authority": {"TEST": "not source authority"},
        "openingApproved": False, "deliveryApproved": False,
        "executionClaim": {"path": opening["claimPath"], "sha256": opening["claimSha256"]},
        "sourceColorEvidence": {"path": str(output / "source-color-evidence.json"), "sha256": "9" * 64, "sizeBytes": 123, "receiptHash": "a" * 64},
        "fullProgram": {"base": {"path": str(output / "full-program-base/final.mp4"), "sha256": "b" * 64},
            "fullMasterSelectionEventPath": str(output / "full-program-base/selection-event.json"), "fullMasterSelectionEventSha256": "d" * 64}}
    record["receiptHash"] = digest(record)
    ref = _publish(output / "media-result.json", record)
    original = {key: opening[key] for key in ("claimPath", "claimSha256", "inputPath", "inputSha256", "executionInputHash")}
    return record, {**original, "outputRoot": str(output), "resultPath": ref["path"], "resultSha256": ref["sha256"]}


def body_source_color_control_fixture(root: Path, origin: int) -> tuple[BodyInvocation, Path]:
    """Build one source2 wire without changing any previously held fixture capability."""
    source, claim, raw, opening = _opening(root)
    record, original = _result(source, claim, opening)
    selection_hash, cleanup_hash = "2" * 64, "6" * 64
    replay = {"schemaVersion": 2, "kind": "guided-body-source-color-replay-references", "scope": SCOPE, **raw,
        "opening": {"selectionHash": selection_hash, "claimHash": digest(claim), "cleanupHash": cleanup_hash,
            "executionId": claim["executionId"], "inputSha256": original["inputSha256"], "executionInputHash": claim["executionInputHash"],
            "mediaResultSha256": original["resultSha256"], "receiptHash": record["receiptHash"]},
        "executable": False, "bodyApproved": False, "deliveryApproved": False}
    full = record["fullProgram"]
    held = {"schemaVersion": 2, "scope": "held-body-input-not-launch-body-readiness-or-delivery-approval",
        "submission": {}, "authority": record["authority"], "bindings": {}, "verification": {}, "sourceColorReplay": replay,
        "approvalHash": "1" * 64, "selectionHash": selection_hash, "readinessHash": "3" * 64, "draftRevisionHash": "4" * 64,
        "origin": {"clockHash": claim["clockHash"], "startedAt": claim["generationStartedAt"]},
        "references": {"base": full["base"], "masterSelection": {"path": full["fullMasterSelectionEventPath"],
            "sha256": full["fullMasterSelectionEventSha256"]}, **source["documents"]},
        "executable": False, "bodyReadiness": "not-qualified", "bodyGenerated": False, "deliveryApproved": False}
    snapshot = {"ctx": {"dir": str(root)}, "status": "treatment_admitted", "guidedHandoffV2": {"openingCleanupHash": cleanup_hash,
        **{pointer: held[key] for pointer, key in (("openingApprovalHash", "approvalHash"), ("openingMediaSelectionHash", "selectionHash"),
            ("proposalReadinessHash", "readinessHash"), ("treatmentDraftRevisionHash", "draftRevisionHash"))}}}
    temporary = root / "human-cut-job-snapshots/TEST-snapshot.json"
    snapshot_ref = _publish(temporary, snapshot)
    destination = temporary.with_name(f"{snapshot_ref['sha256']}.json")
    temporary.rename(destination)
    snapshot_ref["path"] = str(destination)
    held["journalHash"] = snapshot_ref["sha256"]
    return _controls(root, (held, original), snapshot_ref, origin)


def _controls(root: Path, context: tuple, snapshot: dict, origin: int) -> tuple[BodyInvocation, Path]:
    """Publish closed body controls with the unchanged activation1/seven-reference protocol."""
    held, opening = context
    value, activation = body_input(), body_activation()
    value.update(schemaVersion=2, sourceColorReplay=held["sourceColorReplay"])
    execution = root / "guided-v2-operations" / value["requestId"] / "executions" / value["executionId"]
    output = execution / "body-media-output"
    output.mkdir(parents=True, mode=0o700)
    refs = value["references"]
    refs["approvedSnapshot"] = snapshot
    refs["heldInput"] = _publish(execution / "held-input.json", {"schemaVersion": 2, "kind": "guided-body-held-input", "input": held, "opening": opening})
    for name, filename, document in zip(("budgetAdmission", "budgetPrecommit"), ("budget-admission.json", "budget-precommit.json"), budget_documents(origin)):
        document["clockHash"] = held["origin"]["clockHash"]
        refs[name] = _publish(execution / filename, document)
    activation.update(inputPath=str(execution / "body-media-input.json"), outputRoot=str(output),
        clockHash=held["origin"]["clockHash"], generationStartedAt=held["origin"]["startedAt"], createdAt="2026-09-08T00:01:02.000Z",
        budgetAdmissionHash=refs["budgetAdmission"]["sha256"], budgetPrecommitHash=refs["budgetPrecommit"]["sha256"])
    claim = {"schemaVersion": 1, "kind": "guided-body-execution-claim", "scope": "private-body-admission-not-execution-or-approval",
        "beforeJournalHash": held["journalHash"], "heldInputHash": refs["heldInput"]["sha256"], "createdAt": "2026-09-08T00:01:01.000Z",
        "executable": False, "workerState": "not-installed", "bodyGenerated": False, "deliveryApproved": False,
        **{key: activation[key] for key in ("requestId", "executionId", "clockHash", "generationStartedAt", "budgetAdmissionHash", "budgetPrecommitHash")}}
    refs["admissionClaim"] = _publish(execution / "claim.json", claim)
    for name, prefix in (("openingInput", "input"), ("openingResult", "result")):
        refs[name] = {"path": opening[prefix + "Path"], "sha256": opening[prefix + "Sha256"]}
    raw = _publish(execution / "body-media-input.json", value)
    activation.update(inputSha256=raw["sha256"], admissionClaimHash=refs["admissionClaim"]["sha256"])
    active = _publish(execution / "body-execution-activation.json", activation)
    return BodyInvocation(Path(raw["path"]), raw["sha256"], Path(active["path"]), active["sha256"]), output
