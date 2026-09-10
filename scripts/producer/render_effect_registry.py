#!/usr/bin/env python3
"""Closed, versioned registry for current renderer document effects."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from contracts.schema_validator import validate_document

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = (
    PROJECT_ROOT / "docs" / "producer" / "command-driven-editing"
    / "contracts" / "render-effect-registry-v1.json"
)
SCHEMA_NAME = "render-effect-registry-v1.schema.json"


class RenderEffectError(ValueError):
    """A render document or registry violates the closed effect contract."""


@dataclass
class _SemanticState:
    """Mutable uniqueness and ownership state for one registry validation."""

    stages: set[str]
    effects: set[str]
    cases: set[str]
    owned: dict[str, set[str]]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _pattern_matches(pattern: str, pointer: str, document: str) -> bool:
    """Match the registry's JSON-pointer ``*``/terminal-``**`` vocabulary."""
    if document == "manifest" and pointer.startswith("/manifest/"):
        pointer = pointer.removeprefix("/manifest")
    expected = pattern.strip("/").split("/")
    observed = pointer.strip("/").split("/")
    for index, part in enumerate(expected):
        if part == "**":
            return index == len(expected) - 1 and len(observed) >= index
        if index >= len(observed):
            return False
        if part != "*" and part != observed[index]:
            return False
    return len(expected) == len(observed)


def _check_mutation(
    row: dict[str, Any], mutation: dict[str, Any], state: _SemanticState,
) -> None:
    case_id = mutation["caseId"]
    if case_id in state.cases:
        raise RenderEffectError(f"duplicate mutation case {case_id}")
    matches = any(
        _pattern_matches(pattern, mutation["pointer"], row["document"])
        for pattern in row["patterns"]
    )
    if not matches:
        raise RenderEffectError(
            f"{case_id} does not exercise a declared "
            f"{row['effectId']} pattern")
    state.cases.add(case_id)


def _check_effect(row: dict[str, Any], state: _SemanticState) -> None:
    effect_id = row["effectId"]
    if effect_id in state.effects:
        raise RenderEffectError(f"duplicate render effect {effect_id}")
    state.effects.add(effect_id)
    document = row["document"]
    overlap = state.owned[document] & set(row["rootFields"])
    if overlap:
        raise RenderEffectError(
            f"render-effect root fields have duplicate owners: "
            f"{sorted(overlap)}")
    state.owned[document].update(row["rootFields"])
    if not set(row["stageRoots"]) <= state.stages:
        raise RenderEffectError(f"{effect_id} names an unknown stage")
    classification = row["classification"]
    no_stage = {
        "authority-only", "render-irrelevant", "unreleased-rejected",
    }
    if classification == "render-affecting" and not row["stageRoots"]:
        raise RenderEffectError(f"{effect_id} has no render stage")
    if classification in no_stage and row["stageRoots"]:
        raise RenderEffectError(f"{effect_id} cannot own a render stage")
    for mutation in row["mutations"]:
        _check_mutation(row, mutation, state)


def _check_document_roots(
    document: str, spec: dict[str, Any], state: _SemanticState,
) -> None:
    expected = set(spec["rootFields"])
    if state.owned[document] == expected:
        return
    missing = sorted(expected - state.owned[document])
    extra = sorted(state.owned[document] - expected)
    raise RenderEffectError(
        f"{document} root ownership mismatch: "
        f"missing={missing}, extra={extra}")


def _semantic_checks(value: dict[str, Any]) -> dict[str, Any]:
    state = _SemanticState(
        set(value["stages"]), set(), set(),
        {"plan": set(), "manifest": set()},
    )
    for row in value["effects"]:
        _check_effect(row, state)
    for document, spec in value["documents"].items():
        _check_document_roots(document, spec, state)
    return value


@lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    """Load, schema-check, and semantically close the canonical registry."""
    try:
        value = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        validate_document(SCHEMA_NAME, value)
        return _semantic_checks(value)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RenderEffectError(f"render-effect registry is invalid: {exc}") from exc


def registry_hash() -> str:
    """Full SHA-256 identity included in every compiler-owned stage root."""
    return hashlib.sha256(_canonical(load_registry())).hexdigest()


def registered_root_fields(document: str) -> set[str]:
    """Return the exact public root vocabulary for ``plan`` or ``manifest``."""
    documents = load_registry()["documents"]
    if document not in documents:
        raise RenderEffectError(f"unknown render document {document!r}")
    return set(documents[document]["rootFields"])


def validate_root_fields(document: str, value: object) -> dict[str, Any]:
    """Reject any unregistered public root field before a renderer can read it."""
    if type(value) is not dict:
        raise RenderEffectError(f"{document} must be a JSON object")
    allowed = registered_root_fields(document)
    prefix = load_registry()["documents"][document]["privatePrefix"]
    unknown = sorted(
        key for key in value
        if key not in allowed and not str(key).startswith(prefix)
    )
    if unknown:
        raise RenderEffectError(
            f"{document} has unregistered render-effect fields: {unknown}")
    rejected = {
        field
        for row in load_registry()["effects"]
        if row["document"] == document
        and row["classification"] == "unreleased-rejected"
        for field in row["rootFields"]
    }
    present = sorted(rejected & set(value))
    if present:
        raise RenderEffectError(
            f"{document} contains unreleased renderer fields: {present}")
    return value


def validate_render_documents(
    plan: object, manifest: object | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Validate plan and optional asset-manifest roots as one render boundary."""
    checked_plan = validate_root_fields("plan", plan)
    checked_manifest = (
        validate_root_fields("manifest", manifest)
        if manifest is not None else None
    )
    return checked_plan, checked_manifest


def effects() -> list[dict[str, Any]]:
    """Return registry rows for generated discovery/mutation gates."""
    return list(load_registry()["effects"])
