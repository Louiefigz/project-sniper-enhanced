"""Crash-safe cut-timebase authority shared by refit callers."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone

RECEIPT_NAME = ".sniper-plan-refit.json"
PENDING_NAME = ".sniper-plan-refit.pending.json"


def _stable(value):
    if isinstance(value, list):
        return [_stable(item) for item in value]
    if isinstance(value, dict):
        return {key: _stable(value[key]) for key in sorted(value)}
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _canonical(value) -> str:
    return json.dumps(_stable(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _hash_value(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_json(file_path: str, value: dict) -> None:
    directory = os.path.dirname(file_path)
    fd, staged = tempfile.mkstemp(prefix=f".{os.path.basename(file_path)}.",
                                  suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, file_path)
    finally:
        if os.path.exists(staged):
            os.remove(staged)


def _validate(value: object, label: str) -> dict:
    if not isinstance(value, dict) or value.get("schemaVersion") != 2:
        raise RuntimeError(f"{label} is malformed or uses an unsupported schema")
    if value.get("transactionState") not in ("staged", "committed"):
        raise RuntimeError(f"{label} has an invalid transaction state")
    if value.get("source") not in ("surgical-cut", "saved-plan"):
        raise RuntimeError(f"{label} has an invalid refit source")
    if not isinstance(value.get("inputPlanHash"), str) \
            or not isinstance(value.get("planHash"), str) \
            or not isinstance(value.get("changes"), list):
        raise RuntimeError(f"{label} is missing its plan proof")
    if not isinstance(value.get("sourceCutTrack"), list) \
            or not isinstance(value.get("targetCutTrack"), list) \
            or not isinstance(value.get("remapped"), int) \
            or not isinstance(value.get("dropped"), int):
        raise RuntimeError(f"{label} is missing its cut-timebase proof")
    if _hash_value(value.get("sourceCutTrack")) != value.get("sourceCutHash") \
            or _hash_value(value.get("targetCutTrack")) != value.get("targetCutHash"):
        raise RuntimeError(f"{label} has conflicting cut-timebase hashes")
    return value


def _read(file_path: str, label: str) -> dict | None:
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, encoding="utf-8") as handle:
            return _validate(json.load(handle), label)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} is not valid JSON") from exc


def _same(left: object, right: object) -> bool:
    return _canonical(left) == _canonical(right)


def make_receipt(source_cut: object, target_cut: object, plan_path: str,
                 input_plan_path: str, changes: list[dict],
                 source: str = "saved-plan") -> dict:
    """Build a staged receipt for the exact refitted plan bytes."""
    with open(plan_path, "rb") as handle:
        plan_hash = _hash_bytes(handle.read())
    with open(input_plan_path, "rb") as handle:
        input_hash = _hash_bytes(handle.read())
    return {
        "schemaVersion": 2, "transactionState": "staged",
        "source": source, "createdAt": datetime.now(timezone.utc).isoformat(),
        "inputPlanHash": input_hash, "planHash": plan_hash,
        "sourceCutHash": _hash_value(source_cut),
        "targetCutHash": _hash_value(target_cut),
        "sourceCutTrack": source_cut, "targetCutTrack": target_cut,
        "remapped": sum(row.get("remapped") is True for row in changes),
        "dropped": sum(row.get("dropped") is True for row in changes),
        "changes": changes,
    }


def stage_receipt(out_dir: str, receipt: dict) -> None:
    staged = {**_validate(receipt, "plan refit receipt"),
              "transactionState": "staged"}
    _atomic_json(os.path.join(out_dir, PENDING_NAME), staged)


def commit_pending(out_dir: str, plan_path: str) -> dict:
    """Promote a pending receipt only when exact promoted plan bytes prove it."""
    pending_path = os.path.join(out_dir, PENDING_NAME)
    receipt = _read(pending_path, "pending plan refit receipt")
    if receipt is None:
        raise RuntimeError("pending plan refit receipt disappeared")
    with open(plan_path, "rb") as handle:
        plan_bytes = handle.read()
    plan = json.loads(plan_bytes)
    if receipt["planHash"] != _hash_bytes(plan_bytes) \
            or not _same(receipt["targetCutTrack"], plan.get("cutTrack")):
        raise RuntimeError("pending refit receipt does not match the promoted plan")
    committed = {**receipt, "transactionState": "committed"}
    _atomic_json(os.path.join(out_dir, RECEIPT_NAME), committed)
    os.remove(pending_path)
    return committed


def _recover_pending(out_dir: str, plan_path: str, plan: dict) -> dict | None:
    pending_path = os.path.join(out_dir, PENDING_NAME)
    receipt = _read(pending_path, "pending plan refit receipt")
    if receipt is None:
        return None
    with open(plan_path, "rb") as handle:
        current_hash = _hash_bytes(handle.read())
    if receipt["planHash"] == current_hash \
            and _same(receipt["targetCutTrack"], plan.get("cutTrack")):
        return commit_pending(out_dir, plan_path)
    if receipt["inputPlanHash"] == current_hash:
        os.remove(pending_path)
        return None
    if _same(receipt["sourceCutTrack"], plan.get("cutTrack")):
        os.remove(pending_path)
        return None
    raise RuntimeError("pending plan refit conflicts with the current cut timebase")


def resolve_refit_source(out_dir: str, plan_path: str, plan: dict,
                         base_plan: dict) -> tuple[str, dict | None]:
    """Return unchanged/already-applied/refit plus the proven source plan."""
    _recover_pending(out_dir, plan_path, plan)
    receipt = _read(os.path.join(out_dir, RECEIPT_NAME),
                    "plan refit receipt")
    if receipt is not None:
        if receipt.get("transactionState") != "committed":
            raise RuntimeError("canonical plan refit receipt is not committed")
        if _same(receipt["targetCutTrack"], plan.get("cutTrack")):
            return "already-applied", None
        return "refit", {"cutTrack": receipt["targetCutTrack"]}
    if _same(base_plan.get("cutTrack"), plan.get("cutTrack")):
        return "unchanged", None
    return "refit", base_plan
