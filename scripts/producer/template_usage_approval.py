#!/usr/bin/env python3
"""Verify the controller-issued template-history approval before delivery."""
from __future__ import annotations

import json
import os
import re

from edit_scope import lane_required, resolve_scope, resolve_lanes
from fingerprints import file_sha256
from palmier.quality_hash import stable_hash

APPROVAL_FILE = ".sniper-template-usage-approved.json"
_SHA = re.compile(r"^[0-9a-f]{64}$")


def stored_operator_intent(producer_dir: str) -> dict:
    """Read immutable delivery authority from project.json, never plan.target."""
    candidates = [os.path.join(os.path.dirname(os.path.abspath(producer_dir)),
                               "project.json"),
                  os.path.join(os.path.abspath(producer_dir), "project.json")]
    project_path = next((item for item in candidates if os.path.isfile(item)), None)
    if not project_path:
        raise ValueError("delivery needs a valid stored operator intent in project.json")
    project = _json(project_path, "project intent")
    intent = project.get("resolvedIntent") or project.get("intent")
    if not isinstance(intent, dict) or intent.get("mode") not in ("short", "longform"):
        raise ValueError("delivery needs a valid stored operator intent in project.json")
    resolve_lanes(intent)
    return intent


def approval_required(producer_dir: str) -> bool:
    """Whether stored operator intent owns produced/full graphic choices."""
    intent = stored_operator_intent(producer_dir)
    return resolve_scope(intent) in ("produced", "full") \
        and lane_required(intent, "graphics")


def _json(path: str, label: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError(f"{label} is not a SHA-256 digest")
    return value


def _transcript_digest(manifest: dict, manifest_path: str,
                       transcripts_dir: str) -> str:
    rows = []
    sources = manifest.get("sources") or []
    if not isinstance(sources, list):
        raise ValueError("manifest sources must be an array")
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"manifest source {index} must be an object")
        source_id = str(source.get("id", index))
        transcript = source.get("transcriptPath")
        if transcript is None:
            rows.append([source_id, None, None])
            continue
        if not isinstance(transcript, str) or not transcript:
            raise ValueError(f"manifest source {source_id} has invalid transcriptPath")
        resolved = transcript if os.path.isabs(transcript) \
            else os.path.join(transcripts_dir, transcript)
        if not os.path.isfile(resolved):
            raise ValueError(f"referenced transcript is missing: {resolved}")
        rows.append([source_id, transcript, file_sha256(resolved)])
    return stable_hash(rows)


def _history_digest(producer_dir: str, history_path: str) -> str:
    root = os.path.realpath(os.path.join(producer_dir, ".sniper-learning", "runs"))
    target = os.path.realpath(history_path)
    try:
        inside = os.path.commonpath([root, target]) == root and target != root
    except ValueError:
        inside = False
    if not inside or os.path.islink(history_path) or not os.path.isfile(history_path):
        raise ValueError("template usage history is missing or unsafe")
    history = _json(history_path, "template usage history")
    found = _sha(history.get("digest"), "template usage history digest")
    core = {key: value for key, value in history.items() if key != "digest"}
    if found != stable_hash(core):
        raise ValueError("template usage history digest is invalid")
    return found


def _receipt(producer_dir: str) -> dict:
    path = os.path.join(producer_dir, APPROVAL_FILE)
    try:
        receipt = _json(path, "template usage approval")
    except ValueError as exc:
        raise ValueError("produced/full delivery needs a current template-history "
                         "review; review the saved plan first") from exc
    digest = _sha(receipt.get("digest"), "template usage approval digest")
    core = {key: value for key, value in receipt.items() if key != "digest"}
    if receipt.get("schemaVersion") != 1 \
            or receipt.get("kind") != "producer-template-usage-approval" \
            or digest != stable_hash(core):
        raise ValueError("template usage approval is malformed or tampered")
    return receipt


def require_current(plan_path: str, manifest_path: str, producer_dir: str,
                    transcripts_dir: str | None = None) -> None:
    """Fail closed unless exact plan/media/contract/history inputs were approved."""
    plan = _json(plan_path, "edit plan")
    intent = stored_operator_intent(producer_dir)
    if not approval_required(producer_dir):
        return
    manifest = _json(manifest_path, "asset manifest")
    receipt = _receipt(producer_dir)
    history_digest = _history_digest(producer_dir, str(receipt.get("historyPath")))
    contract = os.path.join(os.path.dirname(__file__), "template_usage_contract.py")
    operator_contract = os.path.join(os.path.dirname(__file__), "operator_intent_contract.py")
    current = {
        "planHash": file_sha256(plan_path),
        "planContentHash": stable_hash(plan),
        "manifestHash": file_sha256(manifest_path),
        "transcriptDigest": _transcript_digest(
            manifest, manifest_path, transcripts_dir or os.path.dirname(manifest_path)),
        "contractHash": file_sha256(contract),
        "operatorIntentDigest": stable_hash(
            {key: value for key, value in intent.items() if key != "preset"}),
        "operatorIntentContractHash": file_sha256(operator_contract),
    }
    stale = any(receipt.get(key) != value for key, value in current.items())
    if stale or receipt.get("historyDigest") != history_digest:
        raise ValueError("template-history approval is stale; review the current "
                         "saved plan before delivery")
