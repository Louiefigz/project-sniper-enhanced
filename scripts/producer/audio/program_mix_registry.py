"""Executable ownership gate for every producer audio-mix occurrence."""
from __future__ import annotations

import json
from pathlib import Path

from contracts.schema_validator import validate_document

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = (
    PROJECT_ROOT / "docs" / "producer" / "command-driven-editing"
    / "contracts" / "program-audio-mix-registry-v1.json"
)


def load_program_mix_registry() -> dict:
    """Load the one closed registry artifact."""
    value = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return validate_document(
        "program-audio-mix-registry-v1.schema.json", value)


def _production_python(root: Path, scan_root: str) -> list[Path]:
    base = root / scan_root
    return sorted(
        path for path in base.rglob("*.py")
        if "tests" not in path.relative_to(base).parts
    )


def _line_occurrences(
    path: Path,
    root: Path,
    tokens: list[str],
) -> list[dict[str, object]]:
    relative = path.relative_to(root).as_posix()
    results = []
    for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1):
        matched = [token for token in tokens if token in line]
        if matched:
            results.append({
                "path": relative,
                "line": line_number,
                "text": line.strip(),
                "discoveryTokens": matched,
            })
    return results


def discover_mix_occurrences(
    root: Path,
    registry: dict,
) -> list[dict[str, object]]:
    """Discover every literal owned by the registry's closed scan grammar."""
    results = []
    for path in _production_python(root, registry["scanRoot"]):
        results.extend(
            _line_occurrences(path, root, registry["discoveryTokens"]))
    return results


def _registered_occurrence(
    occurrence: dict[str, object],
    consumers: list[dict],
) -> bool:
    text = str(occurrence["text"])
    return any(
        row["path"] == occurrence["path"]
        and row["sourceToken"] in text
        for row in consumers
    )


def _consumer_errors(root: Path, row: dict) -> list[str]:
    errors = []
    source_path = root / row["path"]
    if not source_path.is_file():
        return [f"{row['id']}: source path does not exist"]
    source = source_path.read_text(encoding="utf-8")
    count = source.count(row["sourceToken"])
    if count != row["expectedOccurrences"]:
        errors.append(
            f"{row['id']}: source token occurs {count} times, "
            f"expected {row['expectedOccurrences']}")
    for field in ("authorityPaths", "testPaths"):
        missing = [path for path in row[field] if not (root / path).is_file()]
        if missing:
            errors.append(f"{row['id']}: missing {field} {missing}")
    if row["consumerKind"] == "asset-only-mix" \
            and row["exemption"] is None:
        errors.append(f"{row['id']}: asset-only mix needs an exemption")
    if row["consumerKind"] != "asset-only-mix" \
            and row["exemption"] is not None:
        errors.append(f"{row['id']}: program consumer cannot be exempt")
    return errors


def _boundary_errors(root: Path, row: dict) -> list[str]:
    errors = []
    if not (root / row["path"]).is_file():
        errors.append(f"{row['id']}: boundary path does not exist")
    for field in ("authorityPaths", "testPaths"):
        missing = [path for path in row[field] if not (root / path).is_file()]
        if missing:
            errors.append(f"{row['id']}: missing {field} {missing}")
    return errors


def _dependency_errors(root: Path, row: dict) -> list[str]:
    errors = []
    for enforcement in row["enforcementTokens"]:
        path = root / enforcement["path"]
        if not path.is_file():
            errors.append(
                f"{row['consumerId']}: enforcement path missing "
                f"{enforcement['path']}")
            continue
        count = path.read_text(encoding="utf-8").count(
            enforcement["token"])
        if count < 1:
            errors.append(
                f"{row['consumerId']}: enforcement token was removed from "
                f"{enforcement['path']}")
    return errors


def _validation_result(
    registry: dict,
    consumers: list[dict],
    occurrences: list[dict[str, object]],
) -> dict:
    """Summarize the exact inventory after all gates have passed."""
    return {
        "status": "pass",
        "consumerCount": len(consumers),
        "occurrenceCount": len(occurrences),
        "programConsumers": sum(
            row["consumerKind"] != "asset-only-mix"
            for row in consumers),
        "assetOnlyExemptions": sum(
            row["consumerKind"] == "asset-only-mix"
            for row in consumers),
        "boundaryCount": len(registry["boundaries"]),
        "dependencyCount": len(registry["dependencies"]),
    }


def validate_program_mix_registry(root: Path = PROJECT_ROOT) -> dict:
    """Fail if discovery and owned registry are not an exact bijection."""
    registry = load_program_mix_registry()
    consumers = registry["consumers"]
    errors = [
        error for row in consumers for error in _consumer_errors(root, row)
    ]
    errors.extend(
        error for row in registry["boundaries"]
        for error in _boundary_errors(root, row)
    )
    program_ids = {
        row["id"] for row in consumers
        if row["consumerKind"] != "asset-only-mix"
    }
    dependency_ids = {
        row["consumerId"] for row in registry["dependencies"]
    }
    if dependency_ids != program_ids:
        errors.append(
            "program consumers and dependency rules are not an exact set")
    errors.extend(
        error for row in registry["dependencies"]
        for error in _dependency_errors(root, row)
    )
    occurrences = discover_mix_occurrences(root, registry)
    unowned = [
        f"{row['path']}:{row['line']} {row['text']}"
        for row in occurrences
        if not _registered_occurrence(row, consumers)
    ]
    if unowned:
        errors.append(f"unowned mix occurrences: {unowned}")
    owned_pairs = {
        (row["path"], row["sourceToken"]) for row in consumers
    }
    if len(owned_pairs) != len(consumers):
        errors.append("registry repeats a source path/token ownership pair")
    if errors:
        raise ValueError("; ".join(errors))
    return _validation_result(registry, consumers, occurrences)


if __name__ == "__main__":
    print(json.dumps(
        validate_program_mix_registry(), sort_keys=True))
