"""TEST-only metadata topology; intentionally no real source/approval authority.

Only the runtime validator is stubbed by tests using this helper. No media,
actual human attestation, model request or approved project is created here.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import digest, file_hash, write_new
from guided_body_budget import BODY_POLICY, _stamp
from guided_body_contract import BodyInvocation
from guided_body_inputs import _HELD_KEYS
from test_guided_body_contract import body_activation, body_input


def budget_documents(origin_ms: int) -> tuple[dict, dict]:
    """Exact TEST accounting mirrors the original two-hour/55-minute allocation."""
    observed = origin_ms + 60_000
    admission = {"schemaVersion": 1, "kind": "guided-body-deadline-admission", "policy": BODY_POLICY,
        "clockHash": "c" * 64, "generationStartedAt": _stamp(origin_ms), "observedAt": _stamp(observed),
        "requestDeadlineAt": _stamp(origin_ms + 7_200_000), "phaseDeadlineAt": _stamp(origin_ms + 5_700_000),
        "elapsedRequestWallMs": 60_000, "remainingBodyPhaseWallMs": 5_640_000,
        "admitted": True, "reason": "within-declared-allocation", "attemptDeadlineAt": _stamp(observed + 3_300_000),
        "excludedUserWaitMs": None}
    precommit = {"schemaVersion": 1, "kind": "guided-body-deadline-observation", "clockHash": "c" * 64,
        "observedAt": _stamp(observed + 1000), "elapsedMs": 1000, "remainingMs": 3_299_000, "state": "within-deadline"}
    return admission, precommit


def _ref(path: Path, value: dict) -> dict:
    """New immutable TEST bytes, not approval by file existence."""
    write_new(path, value)
    return {"path": str(path), "sha256": file_hash(path)}


def _original(root: Path) -> tuple[dict, dict, dict]:
    """Small internally related old input/result, deliberately no executable media."""
    old = root / "TEST-original-opening"
    old.mkdir(mode=0o700)
    authority = {"TEST": "not source authority"}
    source = {"profile": "unity-source-float-own-screen-v1",
        "executionId": "22223333-4444-4555-8666-777788889999", "executionInputHash": "e" * 64,
        "documents": {name: {"path": str(root / name), "sha256": "f" * 64} for name in ("candidatePlan", "manifest")},
        "pipeline": {"snapshotRoot": str(root / "TEST-snapshot")}}
    input_ref = _ref(old / "input.json", source)
    claim = _ref(old / "claim.json", {"TEST": "not executable claim"})
    body = {"inputPath": input_ref["path"], "inputSha256": input_ref["sha256"],
        "executionId": source["executionId"], "executionInputHash": source["executionInputHash"],
        "documents": source["documents"], "authority": authority, "executionClaim": claim,
        "fullProgram": {"base": {"path": str(old / "full-program-base/final.mp4"), "sha256": "b" * 64},
            "fullMasterSelectionEventPath": str(old / "full-program-base/master-selection.json"),
            "fullMasterSelectionEventSha256": "d" * 64}}
    result = {**body, "receiptHash": digest(body)}
    result_ref = _ref(old / "media-result.json", result)
    opening = {"claimPath": claim["path"], "claimSha256": claim["sha256"],
        "inputPath": input_ref["path"], "inputSha256": input_ref["sha256"],
        "executionInputHash": source["executionInputHash"], "outputRoot": str(old),
        "resultPath": result_ref["path"], "resultSha256": result_ref["sha256"]}
    return opening, source, result


def control_fixture(root: Path, origin_ms: int) -> tuple[BodyInvocation, Path]:
    """Actual new-only files exercise the whole bounded control reader, not spawn."""
    value, activation = body_input(), body_activation()
    value["runtime"]["imageApprovalPath"] = str(root / "TEST-snapshot/scripts/producer/headless/render_image_approval.json")
    activation["runtime"] = value["runtime"]
    execution = root / "guided-v2-operations" / value["requestId"] / "executions" / value["executionId"]
    execution.mkdir(parents=True, mode=0o700)
    output = execution / "body-media-output"
    output.mkdir(mode=0o700)
    snapshots = root / "human-cut-job-snapshots"
    snapshots.mkdir(mode=0o700)
    opening, source, result = _original(root)
    held = {key: {} for key in _HELD_KEYS}
    held.update(schemaVersion=1, scope="held-body-input-not-launch-body-readiness-or-delivery-approval",
        executable=False, bodyReadiness="not-qualified", bodyGenerated=False, deliveryApproved=False,
        origin={"clockHash": "c" * 64, "startedAt": _stamp(origin_ms)}, authority=result["authority"],
        approvalHash="1" * 64, selectionHash="2" * 64, readinessHash="3" * 64, draftRevisionHash="4" * 64)
    snapshot = {"ctx": {"dir": str(root)}, "status": "treatment_admitted", "guidedHandoffV2": {
        "openingApprovalHash": held["approvalHash"], "openingMediaSelectionHash": held["selectionHash"],
        "proposalReadinessHash": held["readinessHash"], "treatmentDraftRevisionHash": held["draftRevisionHash"]}}
    temporary = snapshots / "TEST-snapshot.json"
    snapshot_ref = _ref(temporary, snapshot)
    destination = snapshots / f"{snapshot_ref['sha256']}.json"
    temporary.rename(destination)
    value["references"]["approvedSnapshot"] = {"path": str(destination), "sha256": snapshot_ref["sha256"]}
    held["journalHash"] = snapshot_ref["sha256"]
    full = result["fullProgram"]
    held["references"] = {"base": full["base"], "masterSelection": {"path": full["fullMasterSelectionEventPath"],
        "sha256": full["fullMasterSelectionEventSha256"]}, **source["documents"]}
    return _controls(execution, output, (value, activation, held), (opening, origin_ms))


def _controls(execution: Path, output: Path, values: tuple, context: tuple) -> tuple[BodyInvocation, Path]:
    """Write independently bound parent control files with their exact fixed names."""
    value, activation, held = values
    opening, origin_ms = context
    refs = value["references"]
    refs["heldInput"] = _ref(execution / "held-input.json", {"schemaVersion": 1,
        "kind": "guided-body-held-input", "input": held, "opening": opening})
    for name, filename, document in zip(("budgetAdmission", "budgetPrecommit"),
            ("budget-admission.json", "budget-precommit.json"), budget_documents(origin_ms)):
        refs[name] = _ref(execution / filename, document)
    activation.update(clockHash="c" * 64, generationStartedAt=_stamp(origin_ms), createdAt=_stamp(origin_ms + 62_000),
        inputPath=str(execution / "body-media-input.json"), outputRoot=str(output),
        budgetAdmissionHash=refs["budgetAdmission"]["sha256"], budgetPrecommitHash=refs["budgetPrecommit"]["sha256"])
    claim = {"schemaVersion": 1, "kind": "guided-body-execution-claim",
        "scope": "private-body-admission-not-execution-or-approval", "beforeJournalHash": held["journalHash"],
        "heldInputHash": refs["heldInput"]["sha256"], "createdAt": _stamp(origin_ms + 61_000),
        "executable": False, "workerState": "not-installed", "bodyGenerated": False, "deliveryApproved": False}
    claim.update({key: activation[key] for key in ("requestId", "executionId", "clockHash", "generationStartedAt",
                                                  "budgetAdmissionHash", "budgetPrecommitHash")})
    refs["admissionClaim"] = _ref(execution / "claim.json", claim)
    for name, prefix in (("openingInput", "input"), ("openingResult", "result")):
        refs[name] = {"path": opening[prefix + "Path"], "sha256": opening[prefix + "Sha256"]}
    input_ref = _ref(execution / "body-media-input.json", value)
    activation.update(inputSha256=input_ref["sha256"], admissionClaimHash=refs["admissionClaim"]["sha256"])
    activation_ref = _ref(execution / "body-execution-activation.json", activation)
    return BodyInvocation(Path(input_ref["path"]), input_ref["sha256"],
        Path(activation_ref["path"]), activation_ref["sha256"]), output
