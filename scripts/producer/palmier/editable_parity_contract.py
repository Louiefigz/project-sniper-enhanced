"""Frozen, hash-bound master-versus-editable Palmier parity contract."""
from __future__ import annotations

import json
import os
from datetime import datetime
from fractions import Fraction

from fingerprints import file_sha256
from palmier.editable_parity_measure import compare_streams, probe
from palmier.mcp_client import PalmierError
from palmier.quality_hash import stable_hash
from palmier.timeline_authority import atomic_write_record

RECEIPT_NAME = "palmier.editable-parity.json"
APPROVALS_NAME = "palmier.editable-parity-approvals.json"
METRIC_IDS = {
    "picture.canvas", "timing.frame-rate", "timing.frame-count",
    "timing.duration-frames", "picture.mean-ssim", "audio.sample-rate",
    "audio.channels", "audio.sample-count", "audio.difference-rms-db",
    "audio.difference-peak-db",
}
POLICY = {
    "schemaVersion": 1,
    "policyId": "palmier-editable-parity-v1",
    "tolerances": {
        "canvas": "exact",
        "frameRate": "exact-rational",
        "maxFrameCountDelta": 1,
        "maxDurationDeltaFrames": 1.0,
        "minimumMeanSsim": 0.995,
        "audioSampleRate": "exact",
        "audioChannels": "exact",
        "maxAudioSampleDelta": 1024,
        "maximumAudioDifferenceRmsDb": -35.0,
        "maximumAudioDifferencePeakDb": -10.0,
    },
}


def receipt_path(out_dir: str) -> str:
    return os.path.join(out_dir, RECEIPT_NAME)


def approvals_path(out_dir: str) -> str:
    return os.path.join(out_dir, APPROVALS_NAME)


def policy_hash() -> str:
    return stable_hash(POLICY)


def _metric(metric_id: str, measured: object, tolerance: object,
            passed: bool) -> dict:
    return {"metricId": metric_id, "measured": measured,
            "tolerance": tolerance, "status": "pass" if passed else "mismatch"}


def _metrics(master: dict, candidate: dict, decoded: dict) -> list[dict]:
    limits = POLICY["tolerances"]
    master_fps = float(Fraction(master["frameRate"]))
    duration_delta = abs(
        master["durationSeconds"] - candidate["durationSeconds"])
    rows = [
        _metric("picture.canvas",
                [candidate["width"], candidate["height"]],
                [master["width"], master["height"]],
                (candidate["width"], candidate["height"])
                == (master["width"], master["height"])),
        _metric("timing.frame-rate", candidate["frameRate"],
                master["frameRate"],
                candidate["frameRate"] == master["frameRate"]),
        _metric("timing.frame-count",
                abs(master["frameCount"] - candidate["frameCount"]),
                limits["maxFrameCountDelta"],
                abs(master["frameCount"] - candidate["frameCount"])
                <= limits["maxFrameCountDelta"]),
        _metric("timing.duration-frames", duration_delta * master_fps,
                limits["maxDurationDeltaFrames"],
                duration_delta * master_fps <= limits["maxDurationDeltaFrames"]),
        _metric("picture.mean-ssim", decoded["meanSsim"],
                limits["minimumMeanSsim"],
                decoded["meanSsim"] >= limits["minimumMeanSsim"]),
        _metric("audio.sample-rate", candidate["audioSampleRate"],
                master["audioSampleRate"],
                candidate["audioSampleRate"] == master["audioSampleRate"]),
        _metric("audio.channels", candidate["audioChannels"],
                master["audioChannels"],
                candidate["audioChannels"] == master["audioChannels"]),
        _metric("audio.sample-count",
                abs(master["audioSampleCount"] - candidate["audioSampleCount"]),
                limits["maxAudioSampleDelta"],
                abs(master["audioSampleCount"] - candidate["audioSampleCount"])
                <= limits["maxAudioSampleDelta"]),
        _metric("audio.difference-rms-db", decoded["audioDifferenceRmsDb"],
                limits["maximumAudioDifferenceRmsDb"],
                decoded["audioDifferenceRmsDb"]
                <= limits["maximumAudioDifferenceRmsDb"]),
        _metric("audio.difference-peak-db", decoded["audioDifferencePeakDb"],
                limits["maximumAudioDifferencePeakDb"],
                decoded["audioDifferencePeakDb"]
                <= limits["maximumAudioDifferencePeakDb"]),
    ]
    return rows


def _load_json(path: str, label: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read Palmier editable parity {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError(f"Palmier editable parity {label} is not an object")
    return value


def _timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _approval_entries(value: dict, identity: dict,
                      mismatch_ids: set[str]) -> list[dict]:
    expected = {"schemaVersion", "kind", "masterHash", "candidateHash",
                "policyHash", "approver", "approvedAt", "approximations"}
    if set(value) != expected or value.get("schemaVersion") != 1 \
            or value.get("kind") != "palmier-editable-parity-approvals" \
            or any(value.get(key) != identity[key] for key in
                   ("masterHash", "candidateHash", "policyHash")) \
            or not _timestamp(value.get("approvedAt")):
        raise PalmierError("Palmier editable parity approval is stale or malformed")
    approver, rows = value.get("approver"), value.get("approximations")
    if not isinstance(approver, str) or not approver.strip() \
            or not isinstance(rows, list):
        raise PalmierError("Palmier editable parity approval has no approver/entries")
    ids = [row.get("metricId") for row in rows if isinstance(row, dict)]
    valid_rows = all(set(row) == {"metricId", "reason"}
                     and isinstance(row.get("reason"), str)
                     and 0 < len(row["reason"].strip()) <= 2_000
                     for row in rows if isinstance(row, dict))
    if not valid_rows or len(ids) != len(rows) or len(ids) != len(set(ids)) \
            or set(ids) != mismatch_ids:
        raise PalmierError(
            "Palmier editable parity requires one exact approval per mismatch")
    return rows


def _apply_approvals(out_dir: str, metrics: list[dict],
                     identity: dict) -> tuple[list[dict], dict | None]:
    mismatches = {row["metricId"] for row in metrics
                  if row["status"] == "mismatch"}
    if not mismatches:
        return metrics, None
    path = approvals_path(out_dir)
    if not os.path.isfile(path) or os.path.islink(path):
        return metrics, None
    value = _load_json(path, "approval")
    rows = _approval_entries(value, identity, mismatches)
    reasons = {row["metricId"]: row["reason"] for row in rows}
    approved = [{**row, "status": "approved-approximation",
                 "approvalReason": reasons[row["metricId"]]}
                if row["metricId"] in reasons else row for row in metrics]
    return approved, {"path": path, "hash": file_sha256(path),
                      "approver": value["approver"],
                      "approvedAt": value["approvedAt"]}


def run_parity(out_dir: str, candidate_path: str,
               expected_master_hash: str) -> dict:
    """Measure full media and persist a pass/blocked parity receipt."""
    master_path = os.path.join(out_dir, "final.mp4")
    canonical_candidate = os.path.join(out_dir, "palmier.candidate.mp4")
    if not os.path.isfile(master_path) or os.path.islink(master_path):
        raise PalmierError("Palmier editable parity has no regular approved final.mp4")
    if candidate_path != canonical_candidate or not os.path.isfile(candidate_path) \
            or os.path.islink(candidate_path):
        raise PalmierError("Palmier editable parity candidate path is not canonical")
    master_hash = file_sha256(master_path)
    if master_hash != expected_master_hash:
        raise PalmierError("Palmier editable parity approved master authority changed")
    identities = {
        "masterHash": master_hash,
        "candidateHash": file_sha256(candidate_path),
        "policyHash": policy_hash(),
    }
    metrics = _metrics(probe(master_path), probe(candidate_path),
                       compare_streams(master_path, candidate_path))
    metrics, approval = _apply_approvals(out_dir, metrics, identities)
    blocked = [row["metricId"] for row in metrics if row["status"] == "mismatch"]
    content = {
        "schemaVersion": 1, "kind": "palmier-editable-parity",
        "verdict": "pass" if not blocked else "blocked",
        "master": {"path": master_path, "hash": identities["masterHash"]},
        "candidate": {"path": candidate_path, "hash": identities["candidateHash"]},
        "policy": {**POLICY, "hash": identities["policyHash"]},
        "metrics": metrics, "blockedMetricIds": blocked,
        "approval": approval,
    }
    receipt = {**content, "digest": stable_hash(content)}
    atomic_write_record(receipt_path(out_dir), receipt)
    return receipt


def _validate_approval_ref(out_dir: str, approval: object,
                           metrics: list[dict], identity: dict) -> None:
    approved_ids = {row["metricId"] for row in metrics
                    if row.get("status") == "approved-approximation"}
    if approval is None:
        if approved_ids:
            raise PalmierError("Palmier editable parity approvals are missing")
        return
    path = approval.get("path") if isinstance(approval, dict) else None
    if not isinstance(path, str) or path != approvals_path(out_dir) \
            or not os.path.isfile(path) or os.path.islink(path) \
            or file_sha256(path) != approval.get("hash"):
        raise PalmierError("Palmier editable parity approval changed")
    value = _load_json(path, "approval")
    _approval_entries(value, identity, approved_ids)
    if approval.get("approver") != value.get("approver") \
            or approval.get("approvedAt") != value.get("approvedAt"):
        raise PalmierError("Palmier editable parity approval identity changed")


def validate_parity(out_dir: str, candidate_hash: str,
                    expected_master_hash: str) -> dict:
    """Revalidate current bytes, fixed policy, approvals, and receipt digest."""
    value = _load_json(receipt_path(out_dir), "receipt")
    master, candidate, policy = (value.get("master") or {},
                                 value.get("candidate") or {},
                                 value.get("policy") or {})
    content = {key: item for key, item in value.items() if key != "digest"}
    valid = (value.get("schemaVersion") == 1
             and value.get("kind") == "palmier-editable-parity"
             and value.get("verdict") == "pass"
             and value.get("blockedMetricIds") == []
             and policy == {**POLICY, "hash": policy_hash()}
             and value.get("digest") == stable_hash(content)
             and master.get("hash") == expected_master_hash
             and master.get("path") == os.path.join(out_dir, "final.mp4")
             and candidate.get("hash") == candidate_hash
             and candidate.get("path") == os.path.join(
                 out_dir, "palmier.candidate.mp4"))
    if not valid:
        raise PalmierError("Palmier editable parity receipt is not a passing authority")
    for row in (master, candidate):
        path, digest = row.get("path"), row.get("hash")
        if not isinstance(path, str) or not os.path.isfile(path) \
                or os.path.islink(path) or file_sha256(path) != digest:
            raise PalmierError("Palmier editable parity media authority changed")
    metrics = value.get("metrics") or []
    ids = [row.get("metricId") for row in metrics if isinstance(row, dict)]
    if len(ids) != len(metrics) or set(ids) != METRIC_IDS \
            or len(ids) != len(set(ids)):
        raise PalmierError("Palmier editable parity metric set is incomplete")
    identity = {"masterHash": master["hash"],
                "candidateHash": candidate["hash"],
                "policyHash": policy_hash()}
    _validate_approval_ref(out_dir, value.get("approval"), metrics, identity)
    statuses = {row.get("status") for row in metrics if isinstance(row, dict)}
    if not statuses or not statuses <= {"pass", "approved-approximation"}:
        raise PalmierError("Palmier editable parity has unresolved metrics")
    return value
