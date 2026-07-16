#!/usr/bin/env python3
"""Compile two bound frame reviews into a reusable reference style pack."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from study.reference_review import canonical_hash, file_sha256, load_object

CLASSIFICATION_KEYS = (
    "kind", "informationForm", "layoutFamily",
    "transitionFamily", "animationFamily",
)
VALID_LENSES = {"mechanics", "editorial", "adjudication"}
GRAPHIC_KINDS = {"graphic", "panel", "title-card", "lower-third", "data-viz"}


@dataclass(frozen=True)
class PackInputs:
    """Paths required to compile one style pack."""

    worklist: str
    mechanics_review: str
    editorial_review: str
    templates: str
    deep_study: str
    adjudication: str | None = None


def _rows(value: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = value.get(key)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{key} must be an array of objects")
    return rows


def _classification(row: dict[str, Any], label: str) -> dict[str, str]:
    value = row.get("classification")
    if not isinstance(value, dict):
        raise ValueError(f"{label} has no classification")
    missing = [key for key in CLASSIFICATION_KEYS
               if not isinstance(value.get(key), str) or not value[key].strip()]
    if missing:
        raise ValueError(f"{label} classification missing {', '.join(missing)}")
    return {key: str(value[key]) for key in CLASSIFICATION_KEYS}


def _review_map(review: dict[str, Any], lens: str, worklist: dict[str, Any]
                ) -> dict[str, dict[str, Any]]:
    if lens not in VALID_LENSES or review.get("lens") != lens:
        raise ValueError(f"review lens must be {lens!r}")
    if review.get("schemaVersion") != 1:
        raise ValueError(f"{lens} review schemaVersion must be 1")
    expected_hash = canonical_hash(worklist)
    if review.get("worklistHash") != expected_hash:
        raise ValueError(f"{lens} review is not bound to the worklist")
    if review.get("sourceHash") != worklist.get("source", {}).get("sha256"):
        raise ValueError(f"{lens} review is not bound to the source")
    rows = _rows(review, "items")
    mapped = {str(row.get("itemId")): row for row in rows}
    expected = {str(row.get("id")) for row in worklist.get("items") or []}
    if set(mapped) != expected or len(mapped) != len(rows):
        raise ValueError(f"{lens} review item coverage is incomplete or duplicated")
    for item_id, row in mapped.items():
        if row.get("verdict") != "pass" or row.get("materialIssues") != []:
            raise ValueError(f"{lens} review did not pass {item_id}")
        confidence = row.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ValueError(f"{lens} review confidence missing for {item_id}")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError(f"{lens} review confidence invalid for {item_id}")
        _classification(row, f"{lens}:{item_id}")
    return mapped


def _mismatches(first: dict[str, dict[str, Any]], second: dict[str, dict[str, Any]]
                ) -> dict[str, dict[str, tuple[str, str]]]:
    conflicts: dict[str, dict[str, tuple[str, str]]] = {}
    for item_id in first:
        left = _classification(first[item_id], f"mechanics:{item_id}")
        right = _classification(second[item_id], f"editorial:{item_id}")
        delta = {key: (left[key], right[key]) for key in CLASSIFICATION_KEYS
                 if left[key] != right[key]}
        if delta:
            conflicts[item_id] = delta
    return conflicts


def _resolved_classifications(worklist: dict[str, Any], inputs: PackInputs
                              ) -> tuple[dict[str, dict[str, Any]],
                                         dict[str, dict[str, Any]],
                                         dict[str, dict[str, str]]]:
    mechanics = _review_map(load_object(inputs.mechanics_review), "mechanics", worklist)
    editorial = _review_map(load_object(inputs.editorial_review), "editorial", worklist)
    conflicts = _mismatches(mechanics, editorial)
    resolved = {item_id: _classification(row, f"mechanics:{item_id}")
                for item_id, row in mechanics.items()}
    if not conflicts:
        return mechanics, editorial, resolved
    if not inputs.adjudication:
        raise ValueError(f"review disagreement requires adjudication: {sorted(conflicts)}")
    adjudication = _review_map(load_object(inputs.adjudication), "adjudication", worklist)
    for item_id in conflicts:
        resolved[item_id] = _classification(adjudication[item_id],
                                            f"adjudication:{item_id}")
    return mechanics, editorial, resolved


def _template_map(registry: dict[str, Any], worklist: dict[str, Any]
                  ) -> dict[str, dict[str, Any]]:
    if registry.get("schemaVersion") != 1:
        raise ValueError("template registry schemaVersion must be 1")
    if registry.get("worklistHash") != canonical_hash(worklist):
        raise ValueError("template registry is not bound to the worklist")
    rows = _rows(registry, "bindings")
    mapped = {str(row.get("itemId")): row for row in rows}
    if len(mapped) != len(rows):
        raise ValueError("template registry contains duplicate bindings")
    allowed = {str(row.get("id")) for row in worklist.get("items") or []}
    unknown = sorted(set(mapped) - allowed)
    if unknown:
        raise ValueError(f"template registry contains unknown items: {unknown}")
    for item_id, row in mapped.items():
        if row.get("status") not in {"matched", "built"}:
            raise ValueError(f"template binding did not pass: {item_id}")
        if not isinstance(row.get("templateId"), str) or not row["templateId"]:
            raise ValueError(f"template binding has no templateId: {item_id}")
        proof = row.get("proofPath")
        if not isinstance(proof, str) or not os.path.isfile(proof) \
                or os.path.islink(proof):
            raise ValueError(f"template proof missing for {item_id}: {proof}")
        if row.get("structureOnly") is not True:
            raise ValueError(f"template binding must transfer structure only: {item_id}")
    return mapped


def _observation(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("observations")
    return value if isinstance(value, dict) else {}


def _windows(worklist: dict[str, Any], mechanics: dict[str, dict[str, Any]],
             editorial: dict[str, dict[str, Any]], resolved: dict[str, dict[str, str]],
             templates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    windows = []
    for item in worklist.get("items") or []:
        item_id = str(item["id"])
        classification = resolved[item_id]
        template = templates.get(item_id)
        if classification["kind"] in GRAPHIC_KINDS and template is None:
            raise ValueError(f"graphic review item has no verified template: {item_id}")
        windows.append({
            "id": item_id, "kind": item["kind"],
            "frames": [item["startFrame"], item["endFrame"]],
            "time": [item["startS"], item["endS"]],
            "eventIds": item.get("eventIds", []),
            "eventTypes": item.get("eventTypes", []),
            "classification": classification,
            "mechanics": _observation(mechanics[item_id]),
            "editorial": _observation(editorial[item_id]),
            "template": template,
            "evidence": {"contactSheets": item.get("contactSheets", []),
                         "visualFrameCount": item.get("visualFrameCount", 0)},
        })
    return windows


def _vocabulary(windows: list[dict[str, Any]], key: str) -> list[str]:
    values = {row["classification"][key] for row in windows}
    return sorted(value for value in values if value != "none")


def compile_style_pack(inputs: PackInputs) -> dict[str, Any]:
    """Validate exhaustive reviews and compile one release-ready style pack."""
    worklist = load_object(inputs.worklist)
    deep = load_object(inputs.deep_study)
    if worklist.get("deepStudy", {}).get("unclassifiedRuns") not in (0, 0.0):
        raise ValueError("unclassified motion runs block a release-ready style pack")
    mechanics, editorial, resolved = _resolved_classifications(worklist, inputs)
    templates = _template_map(load_object(inputs.templates), worklist)
    windows = _windows(worklist, mechanics, editorial, resolved, templates)
    source = worklist.get("source", {})
    review_paths = [inputs.mechanics_review, inputs.editorial_review]
    if inputs.adjudication:
        review_paths.append(inputs.adjudication)
    return {
        "schemaVersion": 1, "kind": "reference-style-pack",
        "referenceId": worklist.get("referenceId"), "releaseReady": True,
        "source": source,
        "provenance": {
            "worklistPath": os.path.abspath(inputs.worklist),
            "worklistHash": canonical_hash(worklist),
            "deepStudyPath": os.path.abspath(inputs.deep_study),
            "deepStudyHash": file_sha256(inputs.deep_study),
            "reviewHashes": [file_sha256(path) for path in review_paths],
            "templateRegistryHash": file_sha256(inputs.templates),
        },
        "coverage": worklist.get("coverage"),
        "policy": {"structureOnly": True, "copyIdentityAssets": False,
                   "requiredReviewLenses": ["mechanics", "editorial"]},
        "grammar": {
            "windows": windows,
            "informationForms": _vocabulary(windows, "informationForm"),
            "layoutFamilies": _vocabulary(windows, "layoutFamily"),
            "transitionFamilies": _vocabulary(windows, "transitionFamily"),
            "animationFamilies": _vocabulary(windows, "animationFamily"),
            "eventCounts": _event_counts(deep),
        },
    }


def _event_counts(deep: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in deep.get("events") or []:
        if isinstance(event, dict) and isinstance(event.get("type"), str):
            key = event["type"]
            counts[key] = counts.get(key, 0) + 1
    return counts


def template_registry_skeleton(worklist_path: str, mechanics_review: str,
                               editorial_review: str,
                               adjudication: str | None = None) -> dict[str, Any]:
    """Create bound pending rows for every twice-reviewed graphic window."""
    worklist = load_object(worklist_path)
    inputs = PackInputs(worklist_path, mechanics_review, editorial_review,
                        "", "", adjudication)
    _mechanics, editorial, resolved = _resolved_classifications(worklist, inputs)
    bindings = []
    for item in worklist.get("items") or []:
        item_id = str(item["id"])
        if resolved[item_id]["kind"] not in GRAPHIC_KINDS:
            continue
        recommendation = _observation(editorial[item_id]).get(
            "templateRecommendation")
        bindings.append({
            "itemId": item_id, "status": "pending", "templateId": "",
            "proofPath": "", "structureOnly": True,
            "classification": resolved[item_id],
            "recommendation": recommendation if isinstance(recommendation, dict) else {},
        })
    return {"schemaVersion": 1, "worklistHash": canonical_hash(worklist),
            "bindings": bindings}
