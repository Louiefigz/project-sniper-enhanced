"""Actual bounded body control files and original, unchanged opening references.

The foreground controller supplies external raw input/activation hashes only
after authenticating current journal/approval/lease. This reader checks the
same files and internal cross-bindings; it does not authenticate self-hashed
JSON, invent human consent, or select an attempt by directory discovery.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from pathlib import Path
import stat

from cut_preview_io import digest, real_directory
from guided_body_contract import (BodyInvocation, body_path, body_timestamp,
                                  parse_body_activation, parse_current_body_input)
from guided_presenter_intake import current_body_profile
from guided_body_execution import (BodyHeldFile, hold_body_file, _identity as file_identity,
                                   _parent_paths, _directory_states)
from guided_body_source_color_replay import body_source_color_control_refs, join_body_source_color_controls
from guided_opening_claim import verify_runtime_controls
from guided_opening_inputs import _document, _json, closed, hash_value
from guided_source_color_observation_rows import same_observation_data

_CLAIM_KEYS = {"schemaVersion", "kind", "scope", "requestId", "executionId", "beforeJournalHash",
    "heldInputHash", "budgetAdmissionHash", "budgetPrecommitHash", "clockHash", "generationStartedAt",
    "createdAt", "executable", "workerState", "bodyGenerated", "deliveryApproved"}
_HELD_KEYS = {"schemaVersion", "scope", "submission", "journalHash", "approvalHash", "selectionHash",
    "readinessHash", "draftRevisionHash", "authority", "bindings", "origin", "references", "verification",
    "executable", "bodyReadiness", "bodyGenerated", "deliveryApproved"}
_OPENING_KEYS = {"claimPath", "claimSha256", "inputPath", "inputSha256", "executionInputHash",
                 "outputRoot", "resultPath", "resultSha256"}


@dataclass(frozen=True)
class BodyControl:
    """Current metadata only; media admission and cleanup observations are separate."""

    invocation: BodyInvocation
    root: Path
    value: dict
    activation: dict
    documents: dict
    held_files: tuple[BodyHeldFile, ...]


def _same(actual: object, expected: object, label: str) -> None:
    """Reject bool/int coercion and every unexpected source/clock/graph mutation."""
    if digest(actual) != digest(expected):
        raise RuntimeError(f"body {label} differs from its exact held invocation")


def _topology(invocation: BodyInvocation, root: Path, value: dict, activation: dict) -> Path:
    """All worker paths derive from the single admitted execution, never caller roots."""
    execution = invocation.input_path.parent
    if len(execution.parents) < 4:
        raise RuntimeError("body execution path is too short")
    producer = execution.parents[3]
    expected = producer / "guided-v2-operations" / value["requestId"] / "executions" / value["executionId"]
    if execution != expected or invocation.input_path.name != "body-media-input.json" \
            or invocation.activation_path != execution / "body-execution-activation.json" \
            or root != execution / "body-media-output" or activation["outputRoot"] != str(root):
        raise RuntimeError("body invocation is outside its exact admission execution")
    for directory in (producer, execution, root):
        real_directory(directory)
    paths = {"admissionClaim": "claim.json", "heldInput": "held-input.json",
             "budgetAdmission": "budget-admission.json", "budgetPrecommit": "budget-precommit.json"}
    for name, filename in paths.items():
        if value["references"][name]["path"] != str(execution / filename):
            raise RuntimeError("body control reference escaped its admitted execution")
    return producer


def _activation(invocation: BodyInvocation, value: dict, activation: dict) -> None:
    """Bind activation to this exact external input SHA, runtime and complete order."""
    expected = {"requestId": value["requestId"], "executionId": value["executionId"],
        "inputPath": str(invocation.input_path), "inputSha256": invocation.input_sha256,
        "admissionClaimHash": value["references"]["admissionClaim"]["sha256"],
        "budgetAdmissionHash": value["references"]["budgetAdmission"]["sha256"],
        "budgetPrecommitHash": value["references"]["budgetPrecommit"]["sha256"],
        "runtime": value["runtime"], "selectedGraphicOrders": value["selectedGraphicOrders"]}
    for key, item in expected.items():
        _same(activation[key], item, f"activation {key}")


def _claim(value: dict, activation: dict, docs: dict) -> dict:
    """Retain admission's explicit non-executable scope; never toggle its flags."""
    row = closed(docs["admissionClaim"], _CLAIM_KEYS, "body admission claim")
    expected = {"schemaVersion": 1, "kind": "guided-body-execution-claim",
        "scope": "private-body-admission-not-execution-or-approval", "executable": False,
        "workerState": "not-installed", "bodyGenerated": False, "deliveryApproved": False,
        "heldInputHash": value["references"]["heldInput"]["sha256"]}
    for key in ("requestId", "executionId", "budgetAdmissionHash", "budgetPrecommitHash", "clockHash", "generationStartedAt"):
        expected[key] = activation[key]
    for key, item in expected.items():
        _same(row[key], item, f"admission {key}")
    if body_timestamp(row["createdAt"]) > body_timestamp(activation["createdAt"]) \
            or body_timestamp(row["createdAt"]) < body_timestamp(row["generationStartedAt"]):
        raise RuntimeError("body activation/admission clock order differs")
    hash_value(row["beforeJournalHash"])
    return row


def _held(value: dict, docs: dict, claim: dict, producer: Path) -> tuple[dict, dict]:
    """Bind preserved approved snapshot and original authority, not filenames alone."""
    held = closed(docs["heldInput"], {"schemaVersion", "kind", "input", "opening"}, "body held document")
    version = value["schemaVersion"]
    if type(held["schemaVersion"]) is not int or held["schemaVersion"] != version or held["kind"] != "guided-body-held-input":
        raise RuntimeError("body held document role differs")
    original = closed(held["opening"], _OPENING_KEYS, "body original opening")
    row = closed(held["input"], _HELD_KEYS | ({"sourceColorReplay"} if version == 2 else set()), "body held input")
    expected = {"schemaVersion": version, "scope": "held-body-input-not-launch-body-readiness-or-delivery-approval",
        "executable": False, "bodyReadiness": "not-qualified", "bodyGenerated": False, "deliveryApproved": False,
        "journalHash": claim["beforeJournalHash"],
        "origin": {"clockHash": claim["clockHash"], "startedAt": claim["generationStartedAt"]}}
    for key, item in expected.items():
        _same(row[key], item, f"held {key}")
    if type(row["schemaVersion"]) is not int:
        raise RuntimeError("body held input version differs")
    if version == 2:
        same_observation_data(row["sourceColorReplay"], value["sourceColorReplay"])
    snapshot = value["references"]["approvedSnapshot"]
    _same(snapshot, {"path": str(producer / "human-cut-job-snapshots" / f"{claim['beforeJournalHash']}.json"),
        "sha256": claim["beforeJournalHash"]}, "approved snapshot reference")
    approved = docs["approvedSnapshot"]
    if approved["ctx"]["dir"] != str(producer) or approved["status"] != "treatment_admitted":
        raise RuntimeError("body approved snapshot project/state differs")
    pointer = approved["guidedHandoffV2"]
    for key, held_key in (("openingApprovalHash", "approvalHash"), ("openingMediaSelectionHash", "selectionHash"),
                          ("proposalReadinessHash", "readinessHash"), ("treatmentDraftRevisionHash", "draftRevisionHash")):
        _same(hash_value(pointer[key]), row[held_key], f"approved {key}")
    return row, original


def _source_color_files(value: dict, docs: dict, original: dict, remaining: int) -> tuple[list[BodyHeldFile], int]:
    """Capture and read only original replay/claim metadata within the SAME64MiB sum."""
    refs = body_source_color_control_refs(value["sourceColorReplay"], original)
    files = []
    for name, ref in refs.items():
        maximum = min(ref.get("sizeBytes", 128 * 1024), remaining)
        held = hold_body_file(Path(ref["path"]), ref["sha256"], maximum)
        document, size = _document({key: ref[key] for key in ("path", "sha256")}, maximum)
        if "sizeBytes" in ref and size != ref["sizeBytes"]:
            raise RuntimeError("body source-color raw reference size differs")
        docs[name] = document
        files.append(held)
        remaining -= size
    return files, remaining


def _opening(value: dict, docs: dict, held: dict, original: dict) -> None:
    """Preserve original14 documents/execution ID and held full base/master selection."""
    refs = value["references"]
    for name, prefix in (("openingInput", "input"), ("openingResult", "result")):
        _same(refs[name], {"path": original[prefix + "Path"], "sha256": original[prefix + "Sha256"]}, name)
    source, record = docs["openingInput"], docs["openingResult"]
    _same(value["profile"], current_body_profile(source["profile"]), "opening/body geometry class")
    _same(record["inputSha256"], refs["openingInput"]["sha256"], "original result input SHA")
    _same(record["inputPath"], refs["openingInput"]["path"], "original result input path")
    _same(record["executionId"], source["executionId"], "original execution ID")
    _same(record["executionInputHash"], original["executionInputHash"], "original semantic input")
    _same(record["documents"], source["documents"], "original14 documents")
    _same(record["authority"], held["authority"], "original media authority")
    _same(record["executionClaim"], {"path": original["claimPath"], "sha256": original["claimSha256"]}, "original claim")
    _same(record["receiptHash"], digest({key: item for key, item in record.items() if key != "receiptHash"}), "original result digest")
    full = record["fullProgram"]
    expected = {"base": {key: full["base"][key] for key in ("path", "sha256")},
        "masterSelection": {"path": full["fullMasterSelectionEventPath"], "sha256": full["fullMasterSelectionEventSha256"]},
        "candidatePlan": source["documents"]["candidatePlan"], "manifest": source["documents"]["manifest"]}
    _same(held["references"], expected, "unchanged full-program preparation")
    if original["resultPath"] != str(body_path(original["outputRoot"]) / "media-result.json"):
        raise RuntimeError("body original result escaped its original output root")


def read_body_control_header(invocation: BodyInvocation, root: Path) -> tuple[dict, dict, Path]:
    """Read only actual activation/input and derived paths before dependent reads."""
    value = parse_current_body_input(_json(invocation.input_path, invocation.input_sha256, 128 * 1024)[0])
    activation = parse_body_activation(_json(invocation.activation_path, invocation.activation_sha256, 128 * 1024)[0])
    _activation(invocation, value, activation)
    producer = _topology(invocation, root, value, activation)
    return value, activation, producer


def _invocation_files(invocation: BodyInvocation) -> list[BodyHeldFile]:
    """Hold the same original two small controls; no new metadata allocation."""
    return [hold_body_file(path, sha, 128 * 1024) for path, sha in (
        (invocation.input_path, invocation.input_sha256), (invocation.activation_path, invocation.activation_sha256))]


def _source_color_replay_stats(value: dict, remaining: int) -> tuple:
    """Pin three exact additional files before parsers reveal the original claim SHA."""
    replay = value["sourceColorReplay"]
    claim = Path(replay["input"]["path"]).parent.parent / "execution-claim.json"
    refs = [replay["input"], replay["reservationArchive"], {"path": str(claim)}]
    held = []
    for ref in refs:
        path = Path(ref["path"])
        real_directory(path.parent)
        info = path.lstat()
        maximum = min(ref.get("sizeBytes", 128 * 1024), remaining)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= maximum \
                or ("sizeBytes" in ref and info.st_size != ref["sizeBytes"]):
            raise RuntimeError("body source-color initial metadata exceeds its original bound")
        held.append((path, file_identity(info)))
        remaining -= info.st_size
    return tuple(held)


def _source_color_initial_files(invocation: BodyInvocation, data: tuple) -> tuple[list[BodyHeldFile], tuple]:
    """Capture original controls before any dependent parser, within existing limits."""
    value, _activation_value = data
    origin = (tuple((key, id(item), item) for key, item in vars(invocation).items()), deepcopy(data))
    files = _invocation_files(invocation)
    remaining = 64 * 1024 * 1024
    for ref in value["references"].values():
        held = hold_body_file(Path(ref["path"]), ref["sha256"], min(16 * 1024 * 1024, remaining))
        files.append(held)
        remaining -= held.identity[5]
    replay_files = _source_color_replay_stats(value, remaining)
    parents = set(_parent_paths(tuple(files)))
    for key in ("input", "reservationArchive"):
        parents.update(Path(value["sourceColorReplay"][key]["path"]).parents)
    paths = tuple(sorted(parents, key=lambda item: (len(item.parts), str(item))))
    return files, (paths, _directory_states(paths), origin, replay_files)


def _source_color_metadata(files: list[BodyHeldFile], ancestry: tuple) -> None:
    """Finite original-file and ancestor sweep without a clock or caller callback."""
    parents, original, _origin, replay_files = ancestry
    if _directory_states(parents) != original \
            or any(file_identity(row.path.lstat()) != row.identity for row in files) \
            or any(file_identity(path.lstat()) != identity for path, identity in replay_files) \
            or _directory_states(parents) != original:
        raise RuntimeError("body source-color metadata changed during runtime control validation")


def _source_color_runtime(invocation: BodyInvocation, data: tuple, files: list[BodyHeldFile], ancestry: tuple) -> None:
    """Capture all controls before current runtime admission, never admit old runtime."""
    value, _activation_value, docs = data
    original_data = deepcopy(data)
    original_invocation, original_values = ancestry[2]
    same_observation_data(data[:2], original_values)
    if tuple((key, id(item), item) for key, item in vars(invocation).items()) != original_invocation:
        raise RuntimeError("body source-color original invocation changed during metadata reads")
    _source_color_metadata(files, ancestry)
    verify_runtime_controls(value["runtime"], docs["openingInput"]["pipeline"]["snapshotRoot"])
    _source_color_metadata(files, ancestry)
    if tuple((key, id(item), item) for key, item in vars(invocation).items()) != original_invocation:
        raise RuntimeError("body source-color original invocation changed during runtime control validation")
    same_observation_data(data, original_data)


def read_body_control(invocation: BodyInvocation, root: Path) -> BodyControl:
    """Read all held execution metadata; no current source decode or approval."""
    value, activation, producer = read_body_control_header(invocation, root)
    source_color = value["schemaVersion"] == 2
    docs, remaining, files = {}, 64 * 1024 * 1024, []
    ancestry = ()
    if source_color:
        files, ancestry = _source_color_initial_files(invocation, (value, activation))
    for name, ref in value["references"].items():
        document, size = _document(ref, min(16 * 1024 * 1024, remaining))
        remaining -= size
        docs[name] = document
        if not ancestry:
            files.append(hold_body_file(Path(ref["path"]), ref["sha256"], size))
    claim = _claim(value, activation, docs)
    held, original = _held(value, docs, claim, producer)
    _opening(value, docs, held, original)
    replay_files = []
    if source_color:
        replay_files, remaining = _source_color_files(value, docs, original, remaining)
        files.extend(replay_files)
        join_body_source_color_controls(value["sourceColorReplay"], docs, original, producer)
    elif docs["openingResult"].get("schemaVersion") == 2 or "sourceColorEvidence" in docs["openingResult"]:
        raise RuntimeError("legacy body control cannot drop source-color replay obligations")
    if replay_files:
        _source_color_runtime(invocation, (value, activation, docs), files, ancestry)
    else:
        verify_runtime_controls(value["runtime"], docs["openingInput"]["pipeline"]["snapshotRoot"])
        files.extend(_invocation_files(invocation))
    return BodyControl(invocation, root, value, activation, docs, tuple(files))
