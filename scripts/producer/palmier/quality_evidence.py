"""Fail-closed validation of managed Auto Edit schema-v2 QC approval evidence."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from fingerprints import file_sha256
from palmier.mcp_client import PalmierError
from palmier.quality_hash import stable_hash

_SHA = re.compile(r"^[0-9a-f]{64}$")


def _record(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise PalmierError(f"managed QC {label} is not an object")
    return value


def _json(path: str, label: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            return _record(json.load(handle), label)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read managed QC {label} {path}: {exc}") from exc


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise PalmierError(f"managed QC {label} is not a SHA-256 digest")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PalmierError(f"managed QC {label} must be a positive integer")
    return value


def _timestamp(value: object, label: str) -> None:
    if not isinstance(value, str):
        raise PalmierError(f"managed QC {label} is not a timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PalmierError(f"managed QC {label} is not a timestamp") from exc


def _inside(out_dir: str, path: str) -> bool:
    root = os.path.abspath(out_dir)
    target = os.path.abspath(path)
    if not os.path.isabs(path) or target == root:
        return False
    try:
        if os.path.commonpath([root, target]) != root:
            return False
        cursor = root
        for part in os.path.relpath(target, root).split(os.sep):
            cursor = os.path.join(cursor, part)
            if not os.path.exists(cursor) or os.path.islink(cursor):
                return False
        return os.path.commonpath([os.path.realpath(root), os.path.realpath(target)]) \
            == os.path.realpath(root)
    except ValueError:
        return False


def _artifact(out_dir: str, value: object, label: str) -> str:
    ref = _record(value, label)
    path = ref.get("path")
    digest = _sha(ref.get("hash"), f"{label}.hash")
    if not isinstance(path, str) or not _inside(out_dir, path):
        raise PalmierError(f"managed QC {label} path escapes the producer output")
    try:
        stat = os.lstat(path)
    except OSError as exc:
        raise PalmierError(f"managed QC {label} is missing: {path}") from exc
    if os.path.islink(path) or not os.path.isfile(path) or stat.st_size < 0:
        raise PalmierError(f"managed QC {label} is not a regular file")
    if file_sha256(path) != digest:
        raise PalmierError(f"managed QC {label} hash changed")
    return path


def _nested(value: object, key: str) -> object:
    return value.get(key) if isinstance(value, dict) else None


def _packet_binding(binding: object, item: dict, packet: dict) -> bool:
    if not isinstance(binding, dict):
        return False
    packet_ref = item.get("packet")
    return (isinstance(packet_ref, dict)
            and binding.get("path") == packet_ref.get("path")
            and binding.get("hash") == packet_ref.get("hash")
            and binding.get("round") == item.get("round")
            and binding.get("authorityDigest") == item.get("authorityDigest")
            and binding.get("contentDigest") == packet.get("contentDigest")
            and binding.get("gateDigest") == packet.get("gateDigest"))


def _template_usage_snapshot(value: object) -> str:
    bundle = _record(value, "planning gate bundle")
    gates = _record(bundle.get("gates"), "planning gate results")
    operator = _record(gates.get("operatorIntent"), "operator intent gate")
    template = _record(gates.get("templateUsage"), "template usage gate")
    metrics = _record(template.get("metrics"), "template usage gate metrics")
    if operator.get("ok") is not True:
        raise PalmierError("managed QC operator intent gate did not pass")
    if template.get("ok") is not True:
        raise PalmierError("managed QC template usage gate did not pass")
    return _sha(metrics.get("snapshotDigest"), "template usage snapshot digest")


def _planning_row(out_dir: str, item: dict, approval: dict) -> int:
    round_number = _positive_int(item.get("round"), "planning round")
    if (item.get("authorityDigest") != approval["authorityDigest"]
            or item.get("planHash") != approval["planHash"]):
        raise PalmierError("managed QC planning review authority is stale")
    packet = _json(_artifact(out_dir, item.get("packet"), "planning packet"),
                   "planning packet")
    gates = _json(_artifact(out_dir, item.get("gates"), "planning gates"),
                  "planning gates")
    review = _json(_artifact(out_dir, item.get("review"), "planning review"),
                   "planning review")
    _template_usage_snapshot(gates.get("gates"))
    content = {key: value for key, value in packet.items() if key != "contentDigest"}
    valid = (packet.get("schemaVersion") == 1
             and packet.get("kind") == "producer-plan-review-packet"
             and packet.get("stage") == "plan" and packet.get("round") == round_number
             and stable_hash(content) == packet.get("contentDigest")
             and _nested(packet.get("inputAuthority"), "digest") == approval["authorityDigest"]
             and _nested(packet.get("plan"), "byteHash") == approval["planHash"]
             and _nested(packet.get("manifest"), "byteHash") == approval["manifestHash"]
             and stable_hash(packet.get("gateVerdict")) == packet.get("gateDigest")
             and gates.get("schemaVersion") == 1 and gates.get("stage") == "plan-gates"
             and gates.get("round") == round_number and gates.get("gates", {}).get("ok") is True
             and _nested(gates.get("inputAuthority"), "digest") == approval["authorityDigest"]
             and stable_hash(gates.get("gates")) == packet.get("gateDigest")
             and _packet_binding(gates.get("inputPacket"), item, packet)
             and review.get("schemaVersion") == 1 and review.get("stage") == "plan"
             and review.get("round") == round_number
             and _nested(review.get("inputAuthority"), "digest") == approval["authorityDigest"]
             and _nested(review.get("review"), "verdict") == "pass"
             and _packet_binding(review.get("inputPacket"), item, packet))
    if not valid:
        raise PalmierError("managed QC planning review receipt did not pass")
    return round_number


def _planning(out_dir: str, rows: list, approval: dict) -> None:
    required = approval["planningRoundsRequired"]
    if len(rows) != required:
        raise PalmierError("managed QC planning evidence count is incomplete")
    rounds = []
    for item_value in rows:
        item = _record(item_value, "planning review")
        rounds.append(_planning_row(out_dir, item, approval))
    if len(set(rounds)) != len(rounds):
        raise PalmierError("managed QC planning review rounds are duplicated")


def _audit(out_dir: str, approval: dict) -> dict:
    audit = _record(approval.get("audit"), "audit authority")
    _sha(audit.get("candidateHash"), "audit.candidateHash")
    _sha(audit.get("assembledProofHash"), "audit.assembledProofHash")
    if (audit["candidateHash"] != approval["finalHash"]
            or audit["assembledProofHash"] != approval["assembledProofHash"]):
        raise PalmierError("managed QC audit authority does not match the final")
    digest = _sha(audit.get("digest"), "audit.digest")
    content = {key: value for key, value in audit.items() if key != "digest"}
    if stable_hash(content) != digest:
        raise PalmierError("managed QC audit authority digest is invalid")
    machine_path = _artifact(out_dir, audit.get("machine"), "audit machine")
    _artifact(out_dir, audit.get("report"), "audit report")
    frames = audit.get("frames")
    if not isinstance(frames, list) or not frames:
        raise PalmierError("managed QC has no audited frames")
    for index, frame in enumerate(frames):
        _artifact(out_dir, frame, f"audit frame {index + 1}")
    machine = _json(machine_path, "audit machine")
    checks = machine.get("checks")
    if (machine.get("overall") not in ("pass", "warn") or not isinstance(checks, list)
            or any(_nested(check, "status") == "fail" for check in checks)):
        raise PalmierError("managed deterministic audit is not passing")
    return audit


def _rendered(out_dir: str, rows: list, approval: dict, audit: dict) -> None:
    lenses = sorted(item.get("lens") for item in rows if isinstance(item, dict))
    if lenses != ["composition", "editorial"]:
        raise PalmierError("managed QC requires composition and editorial reviews")
    for item in rows:
        lens = item["lens"]
        review = _json(_artifact(out_dir, item, f"{lens} review"), f"{lens} review")
        valid = (review.get("schemaVersion") == 1
                 and review.get("stage") == "rendered"
                 and review.get("lens") == lens
                 and _nested(review.get("inputAuthority"), "digest")
                 == approval["authorityDigest"]
                 and _nested(review.get("evidence"), "digest") == audit["digest"]
                 and _nested(review.get("review"), "verdict") == "pass")
        if not valid:
            raise PalmierError(f"managed QC {lens} review did not pass")


def _summary(out_dir: str, approval: dict, audit: dict) -> None:
    summary = _json(_artifact(out_dir, approval.get("qualitySummary"),
                              "quality summary"), "quality summary")
    aggregate = summary.get("aggregate")
    valid = (summary.get("schemaVersion") == 1
             and summary.get("stage") == "quality-summary"
             and summary.get("qcRound") == approval["qcRound"]
             and _nested(summary.get("inputAuthority"), "digest")
             == approval["authorityDigest"]
             and _nested(summary.get("evidence"), "digest") == audit["digest"]
             and _nested(summary.get("audit"), "failure") is None
             and _nested(aggregate, "verdict") == "pass"
             and isinstance(_nested(aggregate, "materialIssues"), list)
             and not _nested(aggregate, "materialIssues"))
    if not valid:
        raise PalmierError("managed QC quality summary is not passing")


def validate_approval(out_dir: str, final_path: str, approval: dict,
                      authority: dict) -> None:
    """Validate the complete schema-v2 approval and every hash-bound receipt."""
    if approval.get("schemaVersion") != 2 or approval.get("qualityPolicyVersion") != 1:
        raise PalmierError("managed QC approval must use schemaVersion 2 / policy 1")
    for key in ("authorityDigest", "planHash", "manifestHash", "finalHash",
                "candidateHash", "assembledProofHash"):
        _sha(approval.get(key), f"approval.{key}")
    approval["qcRound"] = _positive_int(approval.get("qcRound"), "approval.qcRound")
    approval["planningRoundsRequired"] = _positive_int(
        approval.get("planningRoundsRequired"), "approval.planningRoundsRequired")
    _timestamp(approval.get("approvedAt"), "approval.approvedAt")
    expected = {"planHash": authority["planHash"],
                "manifestHash": authority["manifestHash"],
                "authorityDigest": authority["digest"]}
    if any(approval.get(key) != value for key, value in expected.items()):
        raise PalmierError("managed QC approval authority is stale")
    if (approval["finalHash"] != approval["candidateHash"]
            or file_sha256(final_path) != approval["finalHash"]):
        raise PalmierError("managed QC approved final bytes changed")
    proof_path = final_path + ".assembled.json"
    if file_sha256(proof_path) != approval["assembledProofHash"]:
        raise PalmierError("managed QC assembly proof changed")
    proof = _json(proof_path, "assembly proof")
    if (proof.get("authorityHash") != approval["finalHash"]
            or proof.get("inputAuthorityDigest") != approval["authorityDigest"]
            or proof.get("qualityPolicyVersion") != 1):
        raise PalmierError("managed QC assembly authority is stale")
    planning = approval.get("planningReviews")
    rendered = approval.get("renderedReviews")
    if not isinstance(planning, list) or not isinstance(rendered, list):
        raise PalmierError("managed QC approval review evidence is malformed")
    audit = _audit(out_dir, approval)
    _planning(out_dir, planning, approval)
    _rendered(out_dir, rendered, approval, audit)
    _summary(out_dir, approval, audit)
