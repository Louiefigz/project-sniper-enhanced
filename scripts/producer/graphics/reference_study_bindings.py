"""Save inspected catalog choices independently of their original edit project."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from cut_preview_io import bound_json, file_hash
from graphics.catalog_discovery import Catalog
from graphics.reference_reuse_map import (
    MAX_REFERENCE_EVIDENCE, _candidate, identifier, pin_file, read_checked_map, require,
)
from graphics.reference_reuse_validation import validate_decisions

SCOPE = "reference-study-catalog-bindings-not-render-approval"


def export_study_bindings(file: Path, catalog: Catalog) -> dict:
    """Retain verified planning evidence without binding future edits to a project."""
    checked = read_checked_map(file, catalog)
    record = bound_json(file, checked["sha256"])
    request = bound_json(Path(record["request"]["path"]), record["request"]["sha256"])
    return {"schemaVersion": 1, "scope": SCOPE,
            "originMap": {"path": str(file), "sha256": checked["sha256"]},
            "sourceFormat": record["format"], "references": request["references"],
            "candidates": deepcopy(record["candidates"]),
            "matches": deepcopy(record["shots"]), "renderApproved": False}


def read_study_bindings(file: Path, catalog: Catalog) -> dict:
    """Recheck reference evidence and exact component bytes, never re-run discovery."""
    hashed = file_hash(file)
    value = bound_json(file, hashed)
    require(value.get("schemaVersion") == 1 and value.get("scope") == SCOPE
            and value.get("renderApproved") is False, "invalid study bindings")
    require(value.get("sourceFormat") in ("short", "longform"), "invalid study source format")
    references = value.get("references")
    require(isinstance(references, list) and 1 <= len(references) <= MAX_REFERENCE_EVIDENCE,
            "study references must be bounded")
    require(all(isinstance(row, dict) for row in references), "invalid study reference")
    inputs: dict[str, str] = {}
    ids = [identifier(row.get("id"), "study reference id") for row in references]
    require(len(set(ids)) == len(ids), "duplicate study reference")
    for reference in references:
        pin_file(reference, inputs)
    candidates = value.get("candidates")
    require(isinstance(candidates, dict) and len(candidates) <= 15000,
            "study candidate inventory must be bounded")
    for ref, candidate in candidates.items():
        require(candidate == _candidate(catalog, ref, inputs), "study catalog candidate changed")
    matches = value.get("matches")
    require(isinstance(matches, list) and 1 <= len(matches) <= 500, "study matches must be bounded")
    require(all(isinstance(row, dict) for row in matches), "invalid study match")
    match_ids = [identifier(row.get("id"), "study match id") for row in matches]
    require(len(set(match_ids)) == len(match_ids), "duplicate study match")
    for row in matches:
        require(isinstance(row.get("target"), dict), "invalid study target")
        require(row["target"].get("referenceId") in ids, "unknown study reference")
        require(isinstance(row.get("candidateRefs"), list)
                and all(isinstance(ref, str) and ref in candidates
                        for ref in row["candidateRefs"]), "unknown study candidate")
    blocked = validate_decisions(matches, candidates)
    require(file_hash(file) == hashed, "study bindings changed during read")
    return {"path": str(file), "sha256": hashed, "bindings": value,
            "inputPins": inputs, "blockedMatches": blocked, "renderApproved": False}


def request_study_bindings(request: dict, catalog: Catalog, inputs: dict) -> dict:
    """Load only explicitly supplied saved matches; other requests stay unchanged."""
    pins = request.get("studyBindings", [])
    require(isinstance(pins, list) and len(pins) <= 100, "invalid study binding list")
    result = {}
    for pin in pins:
        require(isinstance(pin, dict), "study binding pin must be an object")
        key = identifier(pin.get("id"), "study binding id")
        require(key not in result, "duplicate study binding id")
        held = pin_file(pin, inputs)
        checked = read_study_bindings(Path(held["path"]), catalog)
        require(held["sha256"] == checked["sha256"], "study binding changed during read")
        for file, sha in checked["inputPins"].items():
            require(file not in inputs or inputs[file] == sha, "conflicting study input pins")
            inputs[file] = sha
        result[key] = checked["bindings"]
    return result


def saved_match(shot: dict, libraries: dict, references: dict) -> dict | None:
    """Reuse inspected mechanics only for the same reference beat and behavior."""
    selection = shot.get("studyMatch")
    if selection is None:
        return None
    require(isinstance(selection, dict), "studyMatch must be an object")
    library = libraries.get(selection.get("libraryId"))
    require(library is not None, "studyMatch names an unknown library")
    rows = [row for row in library["matches"] if row["id"] == selection.get("matchId")]
    require(len(rows) == 1, "studyMatch names an unknown saved match")
    row = rows[0]
    for field in ("referenceId", "referenceBeat", "requiredBehavior"):
        require(shot.get(field) == row["target"].get(field), f"saved study {field} differs; inspect the new behavior")
    previous = next(ref for ref in library["references"] if ref["id"] == shot["referenceId"])
    current = references[shot["referenceId"]]
    require(all(previous.get(key) == current.get(key) for key in ("path", "sha256")), "saved reference evidence differs")
    return row
