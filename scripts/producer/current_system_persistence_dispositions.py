"""Validate exact retained dispositions for unbound persistence primitives."""
from __future__ import annotations

import json
from pathlib import Path

CATEGORY_DISPOSITIONS = {
    "tests-fixtures": "excluded-non-production",
    "docs-build-tooling": "excluded-non-production",
    "temp-cache": "excluded-ephemeral",
    "governed-production-authority": "blocking-artifact-binding",
    "delivery-output": "blocking-artifact-binding",
    "unknown": "blocking-unknown",
}
BLOCKING = {"blocking-artifact-binding", "blocking-unknown"}


def _strings(
    value: object,
    label: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if (type(value) is not list
            or (not allow_empty and not value)
            or any(type(item) is not str or not item for item in value)
            or len(set(value)) != len(value)):
        raise RuntimeError(f"{label} must be unique nonempty strings")
    return tuple(value)


def _load(repo: Path, relative: object) -> dict:
    if type(relative) is not str or not relative:
        raise RuntimeError("persistence-disposition evidence path is malformed")
    candidate = repo / relative
    if candidate.is_symlink() or not candidate.is_file():
        raise RuntimeError("persistence-disposition evidence is unavailable")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(repo)
    except ValueError as exc:
        raise RuntimeError(
            "persistence-disposition evidence escapes repository") from exc
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "persistence-disposition evidence is unreadable") from exc
    if type(value) is not dict:
        raise RuntimeError("persistence-disposition evidence is malformed")
    return value


def _category(
    prefix: str,
    name: str,
    value: object,
) -> tuple[str, tuple[str, ...]]:
    label = f"{prefix}.categories.{name}"
    if type(value) is not dict or set(value) != {
            "disposition", "rationale", "paths"}:
        raise RuntimeError(f"{label} is malformed")
    disposition = value["disposition"]
    rationale = value["rationale"]
    if disposition != CATEGORY_DISPOSITIONS[name] \
            or type(rationale) is not str or not rationale:
        raise RuntimeError(f"{label} has an invalid disposition or rationale")
    paths = _strings(value["paths"], f"{label}.paths", allow_empty=True)
    return str(disposition), paths


def _category_summary(
    parsed: dict[str, tuple[str, tuple[str, ...]]],
    counts: dict[str, int],
) -> tuple[dict[str, dict[str, object]], int, int]:
    summary: dict[str, dict[str, object]] = {}
    excluded = blocking = 0
    for name, (disposition, paths) in parsed.items():
        sites = sum(counts[path] for path in paths)
        summary[name] = {
            "disposition": disposition,
            "files": len(paths),
            "sites": sites,
        }
        if disposition in BLOCKING:
            blocking += sites
        else:
            excluded += sites
    return summary, excluded, blocking


def _classified_set(
    label: str,
    value: object,
    audit: object,
) -> dict[str, object]:
    required = {"siteCount", "fileCount", "siteSetDigest", "categories"}
    if type(value) is not dict or set(value) != required or type(audit) is not dict:
        raise RuntimeError(f"{label} is malformed")
    categories = value["categories"]
    if type(categories) is not dict \
            or set(categories) != set(CATEGORY_DISPOSITIONS):
        raise RuntimeError(f"{label} categories are incomplete")
    parsed = {
        name: _category(label, name, categories[name])
        for name in CATEGORY_DISPOSITIONS
    }
    all_paths = [path for _, paths in parsed.values() for path in paths]
    if (len(all_paths) != len(set(all_paths))
            or sorted(all_paths) != audit.get("unboundFiles")):
        raise RuntimeError(f"{label} file set drifted")
    if (value["siteCount"] != audit.get("unboundSites")
            or value["fileCount"] != len(all_paths)
            or value["siteSetDigest"] != audit.get("unboundSiteDigest")):
        raise RuntimeError(f"{label} site set drifted")
    counts = audit.get("unboundFileSiteCounts")
    if type(counts) is not dict \
            or set(counts) != set(all_paths) \
            or any(type(item) is not int or item < 1 for item in counts.values()):
        raise RuntimeError(f"{label} audit file counts are malformed")
    summary, excluded, blocking = _category_summary(parsed, counts)
    return {
        "categories": summary,
        "classifiedFiles": len(all_paths),
        "excludedSites": excluded,
        "blockingSites": blocking,
        "unknownSites": summary["unknown"]["sites"],
    }


def verify_persistence_dispositions(
    repo: Path,
    relative: object,
    persistence: dict[str, object],
) -> dict[str, object]:
    """Require every raw unbound site to retain one exact reviewed category."""
    value = _load(repo, relative)
    required = {
        "schemaVersion", "asOf", "siteCount", "fileCount", "siteSetDigest",
        "categories", "sideEffectBoundaries", "knownLimitations",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schemaVersion") != 1:
        raise RuntimeError(
            "persistence-disposition evidence has an unsupported schema")
    direct = _classified_set(
        "persistenceDispositionEvidence",
        {
            key: value[key]
            for key in ("siteCount", "fileCount", "siteSetDigest", "categories")
        },
        persistence,
    )
    boundaries = _classified_set(
        "persistenceDispositionEvidence.sideEffectBoundaries",
        value["sideEffectBoundaries"],
        persistence.get("sideEffectBoundaryAudit"),
    )
    limitations = _strings(
        value["knownLimitations"],
        "persistenceDispositionEvidence.knownLimitations",
    )
    return {
        **direct,
        "directBlockingSites": direct["blockingSites"],
        "sideEffectBoundaries": boundaries,
        "blockingSites": (
            int(direct["blockingSites"]) + int(boundaries["blockingSites"])
        ),
        "unknownSites": (
            int(direct["unknownSites"]) + int(boundaries["unknownSites"])
        ),
        "knownLimitations": len(limitations),
    }
