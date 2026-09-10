"""Closed inventory for every released external-byte ingress boundary."""
from __future__ import annotations

import json
from pathlib import Path

from contracts.schema_validator import validate_document

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = (
    PROJECT_ROOT / "docs" / "producer" / "command-driven-editing"
    / "contracts" / "external-ingress-registry-v1.json"
)
_EXCLUDED_PARTS = {
    "tests", "__tests__", "node_modules", ".next", "__pycache__",
}


def load_external_ingress_registry() -> dict:
    """Load and schema-check the canonical registry artifact."""
    value = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return validate_document(
        "external-ingress-registry-v1.schema.json", value)


def _files(root: Path, rule: dict) -> list[Path]:
    result: set[Path] = set()
    suffixes = set(rule["suffixes"])
    for relative in rule["roots"]:
        base = root / relative
        candidates = [base] if base.is_file() else base.rglob("*")
        result.update(
            path for path in candidates
            if path.is_file() and path.suffix in suffixes
            and not (_EXCLUDED_PARTS & set(path.relative_to(root).parts))
        )
    return sorted(result)


def _file_occurrences(
    root: Path,
    rule: dict,
    path: Path,
) -> list[dict[str, object]]:
    relative = path.relative_to(root).as_posix()
    result = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, 1):
        if rule["token"] in line:
            result.append({
                "ruleId": rule["ruleId"],
                "path": relative,
                "line": line_number,
                "text": line.strip(),
            })
    return result


def _rule_occurrences(
    root: Path,
    rule: dict,
) -> list[dict[str, object]]:
    result = []
    for path in _files(root, rule):
        result.extend(_file_occurrences(root, rule, path))
    return result


def discover_ingress_occurrences(
    root: Path,
    registry: dict,
) -> list[dict[str, object]]:
    """Find every occurrence covered by the registry's closed scan rules."""
    occurrences = []
    for rule in registry["scanRules"]:
        occurrences.extend(_rule_occurrences(root, rule))
    return occurrences


def _owners(registry: dict) -> list[dict]:
    return [
        row for family in registry["families"]
        for row in family["ownership"]
    ]


def _matching_owners(
    occurrence: dict[str, object],
    owners: list[dict],
) -> list[dict]:
    text = str(occurrence["text"])
    return [
        row for row in owners
        if (
            row["ruleId"] == occurrence["ruleId"]
            and row["path"] == occurrence["path"]
            and row["sourceToken"] in text
        )
    ]


def _missing_family_paths(
    root: Path,
    family: dict,
    field: str,
) -> list[str]:
    errors = []
    for relative in family[field]:
        if not (root / relative).exists():
            errors.append(
                f"{family['id']}: missing {field} path {relative}")
    return errors


def _path_errors(root: Path, family: dict) -> list[str]:
    errors = []
    for field in (
            "entryPoints", "authorityPaths", "promotionPaths", "testPaths"):
        errors.extend(_missing_family_paths(root, family, field))
    if family["released"] and (
            not family["entryPoints"]
            or not family["authorityPaths"]
            or not family["testPaths"]):
        errors.append(
            f"{family['id']}: released family lacks executable evidence")
    if family["released"] and family["classification"] in {
            "disabled", "non-production-migration"}:
        errors.append(
            f"{family['id']}: disabled/migration family cannot be released")
    return errors


def _ownership_errors(
    root: Path,
    registry: dict,
    occurrences: list[dict[str, object]],
) -> list[str]:
    rule_ids = {row["ruleId"] for row in registry["scanRules"]}
    errors = []
    for row in _owners(registry):
        path = root / row["path"]
        if row["ruleId"] not in rule_ids or not path.is_file():
            errors.append(f"invalid ingress owner {row}")
            continue
        count = path.read_text(encoding="utf-8").count(row["sourceToken"])
        if count != row["expectedOccurrences"]:
            errors.append(
                f"{row['path']}: token {row['sourceToken']!r} occurs "
                f"{count}, expected {row['expectedOccurrences']}")
        if not any(
                item["ruleId"] == row["ruleId"]
                and item["path"] == row["path"]
                and row["sourceToken"] in str(item["text"])
                for item in occurrences):
            errors.append(f"ingress owner matches no discovered line: {row}")
    return errors


def _token_field_errors(
    root: Path,
    invariant: dict,
    field: str,
) -> list[str]:
    errors = []
    for row in invariant[field]:
        path = root / row["path"]
        if not path.is_file():
            errors.append(
                f"{invariant['id']}: missing token path {row['path']}")
            continue
        count = path.read_text(encoding="utf-8").count(row["token"])
        if count != row["expectedOccurrences"]:
            errors.append(
                f"{invariant['id']}: {row['path']} token "
                f"{row['token']!r} occurs {count}, expected "
                f"{row['expectedOccurrences']}")
    return errors


def _token_errors(root: Path, invariant: dict) -> list[str]:
    errors = []
    for field in ("requiredTokens", "forbiddenTokens"):
        errors.extend(_token_field_errors(root, invariant, field))
    for relative in invariant["testPaths"]:
        if not (root / relative).is_file():
            errors.append(
                f"{invariant['id']}: missing test path {relative}")
    return errors


def _identity_errors(registry: dict) -> list[str]:
    errors = []
    for field in ("scanRules", "families", "invariants"):
        key = "ruleId" if field == "scanRules" else "id"
        values = [row[key] for row in registry[field]]
        if len(values) != len(set(values)):
            errors.append(f"external ingress registry repeats {field} IDs")
    owners = [
        (row["ruleId"], row["path"], row["sourceToken"])
        for row in _owners(registry)
    ]
    if len(owners) != len(set(owners)):
        errors.append("external ingress registry repeats an owner")
    return errors


def _scan_rule_errors(
    root: Path,
    registry: dict,
    occurrences: list[dict[str, object]],
) -> list[str]:
    errors = []
    for rule in registry["scanRules"]:
        if not rule["roots"]:
            errors.append(f"{rule['ruleId']}: scan roots are empty")
        missing = [
            relative for relative in rule["roots"]
            if not (root / relative).exists()
        ]
        if missing:
            errors.append(
                f"{rule['ruleId']}: missing scan roots {missing}")
        count = sum(
            row["ruleId"] == rule["ruleId"] for row in occurrences)
        if count != rule["expectedOccurrenceCount"]:
            errors.append(
                f"{rule['ruleId']}: discovered {count} occurrences, "
                f"expected {rule['expectedOccurrenceCount']}")
    return errors


def validate_external_ingress_registry(
    root: Path = PROJECT_ROOT,
) -> dict[str, int | str]:
    """Require exact discovery ownership and every named authority invariant."""
    registry = load_external_ingress_registry()
    occurrences = discover_ingress_occurrences(root, registry)
    owners = _owners(registry)
    errors = _identity_errors(registry)
    errors.extend(_scan_rule_errors(root, registry, occurrences))
    errors.extend(
        error for family in registry["families"]
        for error in _path_errors(root, family)
    )
    errors.extend(_ownership_errors(root, registry, occurrences))
    errors.extend(
        error for invariant in registry["invariants"]
        for error in _token_errors(root, invariant)
    )
    owner_matches = [
        (row, _matching_owners(row, owners)) for row in occurrences
    ]
    unowned = [
        f"{row['ruleId']}:{row['path']}:{row['line']} {row['text']}"
        for row, matches in owner_matches if not matches
    ]
    if unowned:
        errors.append(f"unowned external ingress occurrences: {unowned}")
    multiply_owned = [
        f"{row['ruleId']}:{row['path']}:{row['line']}"
        for row, matches in owner_matches if len(matches) > 1
    ]
    if multiply_owned:
        errors.append(
            f"multiply-owned external ingress occurrences: {multiply_owned}")
    if errors:
        raise ValueError("; ".join(errors))
    families = registry["families"]
    return {
        "status": "pass",
        "familyCount": len(families),
        "releasedFamilyCount": sum(row["released"] for row in families),
        "occurrenceCount": len(occurrences),
        "ownerCount": len(owners),
        "invariantCount": len(registry["invariants"]),
    }


if __name__ == "__main__":
    print(json.dumps(
        validate_external_ingress_registry(), sort_keys=True))
