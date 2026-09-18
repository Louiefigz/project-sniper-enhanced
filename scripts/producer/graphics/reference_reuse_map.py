"""Freeze shared catalog discovery for explicitly reference-driven shot plans.

This is planning evidence, never renderer admission or visual/style approval.
No work is inferred from background inspiration: a pinned request must explicitly
choose ``reference-match``. Authored inspections and choices remain agent work.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from cut_preview_io import bound_json, digest, file_hash, real_directory
from graphics.catalog_discovery import Catalog, lookup_item, search_catalog

SCHEMA_VERSION = 1
SCOPE = "reference-match-planning-only"
MAX_SHOTS = 500
MAX_REFERENCE_EVIDENCE = 1000
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")


def require(condition: object, message: str) -> None:
    """Fail closed on malformed or stale planning evidence."""
    if not condition:
        raise ValueError(message)


def text_field(value: object, label: str) -> str:
    """Require bounded, nonblank authored text without interpreting it."""
    require(isinstance(value, str) and 0 < len(value.strip()) <= 16000,
            f"{label} must be nonblank text of at most 16000 characters")
    return value


def identifier(value: object, label: str) -> str:
    """Require a stable bounded identifier, distinct from display prose."""
    require(isinstance(value, str) and _IDENTIFIER.fullmatch(value),
            f"{label} must be a stable identifier")
    return value


def pin_file(pin: object, inputs: dict[str, str]) -> dict:
    """Verify an exact, bounded, no-follow file using shared artifact I/O."""
    require(isinstance(pin, dict), "file pin must be an object")
    path = Path(text_field(pin.get("path"), "pin path"))
    sha = pin.get("sha256")
    require(isinstance(sha, str) and _SHA256.fullmatch(sha), "invalid file sha256")
    require(path.is_absolute(), "pinned files must use absolute canonical paths")
    require(file_hash(path) == sha, f"stale pinned file: {path}")
    require(str(path) not in inputs or inputs[str(path)] == sha, "conflicting file pins")
    inputs[str(path)] = sha
    return {"path": str(path), "sha256": sha}


def _unique_rows(value: object, label: str, maximum: int) -> dict[str, dict]:
    """Read a bounded inventory without silently replacing duplicate IDs."""
    require(isinstance(value, list) and 1 <= len(value) <= maximum,
            f"{label} requires 1..{maximum} records")
    result = {}
    for row in value:
        require(isinstance(row, dict), f"{label} record must be an object")
        key = identifier(row.get("id"), f"{label} id")
        require(key not in result, f"duplicate {label} id: {key}")
        result[key] = row
    return result


def _read_request(request: dict, inputs: dict[str, str]) -> dict:
    """Bind the full shot inventory to an immutable request file."""
    require(isinstance(request, dict), "request must be an object")
    pin = pin_file(request.get("request"), inputs)
    body = bound_json(Path(pin["path"]), pin["sha256"])
    require("request" not in body, "request file must not contain its own pin")
    require(body == {key: value for key, value in request.items() if key != "request"},
            "request body differs from its pinned file")
    require(body.get("scope") == "reference-match", "explicit reference-match scope required")
    require(body.get("format") in ("short", "longform"), "format must be short or longform")
    project = Path(text_field(body.get("project"), "project"))
    real_directory(project.parent)
    require(project.resolve() == project and not project.is_symlink(),
            "project must be an absolute canonical planned project path")
    require(not project.exists() or project.is_dir(), "project must be a directory")
    return body


def _candidate(catalog: Catalog, ref: str, inputs: dict[str, str]) -> dict:
    """Freeze one exact shared lookup and the actual source bytes it names."""
    matches = lookup_item(catalog, ref)["matches"]
    require(len(matches) == 1 and matches[0]["ref"] == ref,
            f"candidate needs an exact unambiguous catalog ref: {ref}")
    record = deepcopy(matches[0])
    source = record.get("source")
    require(isinstance(source, dict) and type(source.get("exists")) is bool,
            f"catalog source descriptor missing: {ref}")
    path = Path(text_field(source.get("path"), "catalog source path"))
    require(path.is_absolute(), "catalog source path must be absolute")
    frozen = {"path": str(path), "exists": source["exists"], "sha256": None}
    if source["exists"]:
        frozen["sha256"] = file_hash(path)
        require(str(path) not in inputs or inputs[str(path)] == frozen["sha256"], "conflicting source pins")
        inputs[str(path)] = frozen["sha256"]
    else:
        require(not path.exists() and not path.is_symlink(), f"catalog source status stale: {ref}")
    value = {"ref": ref, "record": record, "source": frozen}
    return {**value, "sha256": digest(value)}


def _search(shot: dict, catalog: Catalog) -> tuple[dict, list[str]]:
    """Use shared unrestricted discovery; ranking never admits execution."""
    result = search_catalog(catalog, text_field(shot.get("query"), "shot query"))
    extra = shot.get("additionalCandidates", [])
    require(isinstance(extra, list) and len(extra) <= 20
            and all(isinstance(ref, str) for ref in extra), "invalid additionalCandidates")
    require(len(set(extra)) == len(extra), "duplicate additionalCandidates")
    refs = [row["ref"] for row in result["results"]]
    candidates = list(dict.fromkeys([*refs, *extra]))
    snapshot = {key: result[key] for key in ("scope", "query", "filters", "total",
                "returned", "limited", "excludedExactMatches")}
    # Unrelated catalog/lock metadata must not invalidate an inspected shot.
    # Bind the actual query/ranking/results, including truncation and matches.
    evidence = {key: value for key, value in result.items() if key != "provenance"}
    return {**snapshot, "resultRefs": refs, "resultsSha256": digest(evidence)}, candidates


def _shot(shot: dict, references: dict[str, dict], catalog: Catalog,
          libraries: dict) -> dict:
    """Keep the authored reason for each reference shot alongside discovery."""
    require(isinstance(shot.get("referenceId"), str) and shot["referenceId"] in references,
            "shot names an unknown reference")
    for field in ("referenceBeat", "cue", "visualNeed", "requiredBehavior"):
        text_field(shot.get(field), field)
    from graphics.reference_study_bindings import saved_match
    saved = saved_match(shot, libraries, references)
    if saved is not None:
        return {"id": shot["id"], "target": deepcopy(shot),
                "search": {"source": "saved-study-binding", "selection": shot["studyMatch"]},
                "candidateRefs": list(saved["candidateRefs"]),
                "savedInspections": deepcopy(saved["inspections"]),
                "savedDecision": deepcopy(saved["decision"]),
                "inspections": [], "decision": {"route": "pending"}}
    search, candidates = _search(shot, catalog)
    return {"id": shot["id"], "target": deepcopy(shot), "search": search,
            "candidateRefs": candidates, "inspections": [], "decision": {"route": "pending"}}


def prepare_map(request: dict, catalog: Catalog) -> dict:
    """Prepare deterministic evidence with pending, never automatic, decisions."""
    inputs: dict[str, str] = {}
    body = _read_request(request, inputs)
    references = _unique_rows(body.get("references"), "reference", MAX_REFERENCE_EVIDENCE)
    for reference in references.values():
        pin_file(reference, inputs)
    from graphics.reference_study_bindings import request_study_bindings
    libraries = request_study_bindings(body, catalog, inputs)
    pin_file(body.get("shotPlan"), inputs)
    inventory = _unique_rows(body.get("shots"), "shot", MAX_SHOTS)
    shots = [_shot(shot, references, catalog, libraries) for shot in inventory.values()]
    refs = sorted({ref for shot in shots for ref in shot["candidateRefs"]})
    candidates = {ref: _candidate(catalog, ref, inputs) for ref in refs}
    return {"schemaVersion": SCHEMA_VERSION, "scope": SCOPE,
            "request": deepcopy(request["request"]), "requestSha256": digest(body),
            "project": body["project"], "format": body["format"],
            "inputPins": inputs, "candidates": candidates, "shots": shots,
            "styleApproved": False, "executionAdmitted": False}


def validate_map(record: dict, catalog: Catalog) -> dict:
    """Check complete planning records and freshness, never subjective truth."""
    from graphics.reference_reuse_validation import validate_decisions

    require(isinstance(record, dict), "map must be an object")
    pin = record.get("request")
    inputs: dict[str, str] = {}
    pin_file(pin, inputs)
    request = {**bound_json(Path(pin["path"]), pin["sha256"]), "request": pin}
    expected = prepare_map(request, catalog)
    shots = record.get("shots")
    require(isinstance(shots, list), "map shots must be a list")
    fixed = deepcopy(record)
    for shot in fixed["shots"]:
        require(isinstance(shot, dict), "map shot must be an object")
        shot["inspections"], shot["decision"] = [], {"route": "pending"}
    require(fixed == expected, "map inventory, catalog, source, or frozen evidence changed; prepare again")
    blocked = validate_decisions(shots, record["candidates"])
    return {"status": "blocked-planning-only" if blocked else "complete-planning-only",
            "scope": SCOPE, "ready": not blocked, "planningComplete": True, "blockedShots": blocked,
            "project": expected["project"], "format": expected["format"],
            "shotCount": len(shots), "inputPins": expected["inputPins"],
            "styleApproved": False, "qualityApproved": False, "renderApproved": False,
            "executionAdmitted": False}


def read_checked_map(file: Path, catalog: Catalog) -> dict:
    """Read one map with the same byte-stability check for CLI and native callers."""
    hashed = file_hash(file)
    report = validate_map(bound_json(file, hashed), catalog)
    require(file_hash(file) == hashed, "Reference reuse map changed during validation")
    return {"path": str(file), "sha256": hashed, "report": report}
