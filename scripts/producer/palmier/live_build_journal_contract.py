"""Strict cross-runtime lifecycle contract for Palmier live-build JSONL."""
from __future__ import annotations

import json
import os
import re

from fingerprints import file_sha256
from palmier.mcp_client import PalmierError
from palmier.quality_hash import stable_hash

_SHA = re.compile(r"^[0-9a-f]{64}$")
_MAX_BYTES = 64 * 1024 * 1024
_MAX_ROW_BYTES = 16_000
_MUTATION_TOOLS = frozenset({
    "add_clips", "insert_clips", "split_clips", "move_clips",
    "remove_clips", "ripple_delete_ranges", "set_clip_properties",
    "set_keyframes", "add_texts", "update_text", "add_captions",
    "apply_color", "apply_effect", "apply_layout", "manage_tracks",
    "sync_clips", "remove_silence", "remove_words", "denoise_audio",
})


def is_live_build_mutation_tool(tool: str) -> bool:
    """Return whether a proved Palmier tool changes the candidate."""
    return tool in _MUTATION_TOOLS


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise PalmierError(f"Palmier live journal {label} is not an object")
    return value


def _strings(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(
            not isinstance(item, str) or not item for item in value) \
            or len(value) != len(set(value)):
        raise PalmierError(
            f"Palmier live journal {label} is not unique strings")
    return value


def _input_hash(row: dict) -> str:
    if row.get("truncated") is True:
        raise PalmierError("Palmier live journal mutation payload is truncated")
    return stable_hash({
        "tool": row.get("tool"),
        "input": _object(row.get("input", {}), "operation input"),
    })


def _applied_ids(ledger: dict) -> list[str]:
    return sorted(operation["operationId"]
                  for operation in ledger["operations"].values()
                  if operation["mutation"]
                  and operation["status"] == "applied")


def _unsafe_duplicate(ledger: dict, current: dict) -> bool:
    return any(
        operation["operationId"] != current["operationId"]
        and operation["mutation"]
        and operation["status"] != "not-applied"
        and operation["tool"] == current["tool"]
        and operation["inputHash"] == current["inputHash"]
        for operation in ledger["operations"].values()
    )


def _apply_operation(ledger: dict, row: dict, index: int) -> None:
    operation_id, tool = row.get("operationId"), row.get("tool")
    if row.get("status") != "applying" \
            or not isinstance(operation_id, str) or not operation_id \
            or not isinstance(tool, str) or not tool:
        raise PalmierError("Palmier live journal applying operation is malformed")
    operation = {
        "operationId": operation_id, "tool": tool,
        "inputHash": _input_hash(row),
        "mutation": is_live_build_mutation_tool(tool),
        "status": "applying", "transitionIndex": index,
    }
    prior = ledger["operations"].get(operation_id)
    if prior:
        if (prior["tool"], prior["inputHash"]) != (
                operation["tool"], operation["inputHash"]):
            raise PalmierError("Palmier live journal operation id was rebound")
        if prior["status"] != "applying":
            raise PalmierError(
                "Palmier live journal replayed a terminal operation identity")
        return
    if operation["mutation"] and _unsafe_duplicate(ledger, operation):
        raise PalmierError(
            "Palmier live journal fail-closed replay fence rejected payload")
    ledger["operations"][operation_id] = operation


def _apply_result(ledger: dict, row: dict, index: int) -> None:
    operation_id, status = row.get("operationId"), row.get("status")
    if not isinstance(operation_id, str) or status not in {"applied", "failed"}:
        raise PalmierError("Palmier live journal operation result is malformed")
    operation = ledger["operations"].get(operation_id)
    if not operation:
        raise PalmierError("Palmier live journal result has no applying operation")
    if operation["status"] == status:
        return
    if operation["status"] != "applying":
        raise PalmierError(
            "Palmier live journal operation has conflicting or late results")
    operation.update({"status": status, "transitionIndex": index})


def _resolve(ledger: dict, ids: list[str], index: int) -> None:
    for operation_id in ids:
        operation = ledger["operations"].get(operation_id)
        if not operation or not operation["mutation"] \
                or operation["status"] not in {"applying", "failed"}:
            raise PalmierError(
                "Palmier live journal reconciliation is ineligible")
        operation.update({"status": "not-applied", "transitionIndex": index})


def _apply_head(ledger: dict, row: dict, index: int) -> None:
    fingerprint = row.get("fingerprint")
    if not isinstance(fingerprint, str) or not _SHA.fullmatch(fingerprint):
        raise PalmierError(
            "Palmier live journal controller fingerprint is malformed")
    resolved = (_strings(row.get("resolvedNotAppliedIds"),
                         "resolved operation ids")
                if row.get("event") == "live_build_reconciliation" else [])
    _resolve(ledger, resolved, index)
    if any(operation["mutation"]
           and operation["status"] in {"applying", "failed"}
           for operation in ledger["operations"].values()):
        raise PalmierError(
            "Palmier live journal head leaves unresolved mutations")
    prior = ledger["heads"][-1] if ledger["heads"] else None
    applied_since = prior and any(
        operation["mutation"] and operation["status"] == "applied"
        and operation["transitionIndex"] > prior["index"]
        for operation in ledger["operations"].values())
    if prior and applied_since and prior["fingerprint"] == fingerprint:
        raise PalmierError(
            "Palmier live journal applied mutation produced no candidate delta")
    verified = sorted(_strings(
        row.get("verifiedOperationIds"), "verified operation ids"))
    if verified != _applied_ids(ledger):
        raise PalmierError(
            "Palmier live journal head omits or invents operations")
    ledger["heads"].append({
        "fingerprint": fingerprint, "verifiedOperationIds": verified,
        "index": index,
    })


def _apply_row(ledger: dict, row: dict) -> None:
    if not isinstance(row.get("at"), str) or not row["at"]:
        raise PalmierError("Palmier live journal row has no timestamp")
    index = ledger["rowCount"] + 1
    event = row.get("event")
    if event == "palmier_op":
        _apply_operation(ledger, row, index)
    elif event == "palmier_op_result":
        _apply_result(ledger, row, index)
    elif event in {"live_build_head", "live_build_reconciliation"}:
        _apply_head(ledger, row, index)
    else:
        raise PalmierError(f"Palmier live journal event is unsupported: {event}")
    ledger["rowCount"] = index


def read_live_build_journal(path: str) -> dict:
    """Parse every row; malformed, oversized, or torn JSONL blocks QC."""
    try:
        size = os.path.getsize(path)
        if size > _MAX_BYTES:
            raise PalmierError("Palmier live journal exceeds 64 MiB")
        with open(path, "rb") as handle:
            payload = handle.read()
    except OSError as exc:
        raise PalmierError(f"cannot read Palmier live journal: {exc}") from exc
    if payload and not payload.endswith(b"\n"):
        raise PalmierError("Palmier live journal has a torn final row")
    ledger = {"operations": {}, "heads": [], "rowCount": 0}
    try:
        lines = payload.decode("utf-8").split("\n")
        for line in filter(None, lines):
            if len(line.encode("utf-8")) > _MAX_ROW_BYTES:
                raise PalmierError(
                    "Palmier live journal row exceeds durable limit")
            _apply_row(ledger, _object(json.loads(line), "row"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PalmierError(
            f"Palmier live journal contains invalid JSON: {exc}") from exc
    return ledger


def close_live_build_journal(path: str, expected_fingerprint: str) -> dict:
    """Return the frozen closed-journal authority or fail closed."""
    try:
        before_hash = file_sha256(path)
    except OSError as exc:
        raise PalmierError(
            f"cannot hash Palmier live journal: {exc}") from exc
    ledger = read_live_build_journal(path)
    try:
        digest = file_sha256(path)
    except OSError as exc:
        raise PalmierError(
            f"cannot rehash Palmier live journal: {exc}") from exc
    head = ledger["heads"][-1] if ledger["heads"] else None
    unresolved = [row for row in ledger["operations"].values()
                  if row["mutation"]
                  and row["status"] in {"applying", "failed"}]
    if not head or head["index"] != ledger["rowCount"] \
            or head["fingerprint"] != expected_fingerprint or unresolved:
        raise PalmierError(
            "Palmier live journal is not closed at exact candidate readback")
    operations = sorted(({
        key: row[key] for key in ("operationId", "tool", "inputHash", "status")
    } for row in ledger["operations"].values() if row["mutation"]),
        key=lambda row: row["operationId"])
    completed = sum(row["status"] == "applied" for row in operations)
    if digest != before_hash or completed < 1:
        raise PalmierError(
            "Palmier live journal changed or has no applied mutation")
    return {
        "path": path, "hash": digest, "operationCount": completed,
        "lifecycleDigest": stable_hash({
            "fingerprint": head["fingerprint"], "operations": operations,
        }),
        "headFingerprint": head["fingerprint"],
    }
