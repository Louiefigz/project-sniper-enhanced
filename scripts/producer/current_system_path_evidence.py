"""Validate retained manual evidence for paths literal discovery cannot infer."""
from __future__ import annotations

import json
from pathlib import Path

CONCERNS = {
    "caller-supplied-output-root",
    "dynamically-constructed-filename",
    "external-store",
    "non-prefixed-authority",
}
DISPOSITIONS = {
    "artifact-bound",
    "boundary-adapter",
    "ephemeral-non-authority",
}


def _strings(value: object, label: str, allow_empty: bool = False) -> tuple[str, ...]:
    if (type(value) is not list
            or (not allow_empty and not value)
            or any(type(item) is not str or not item for item in value)
            or len(set(value)) != len(value)):
        raise RuntimeError(f"{label} must be unique nonempty strings")
    return tuple(value)


def _load(repo: Path, relative: object) -> dict:
    if type(relative) is not str or not relative:
        raise RuntimeError("path-boundary evidence path is malformed")
    candidate = repo / relative
    if candidate.is_symlink() or not candidate.is_file():
        raise RuntimeError("path-boundary evidence is unavailable")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(repo)
    except ValueError as exc:
        raise RuntimeError("path-boundary evidence escapes repository") from exc
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("path-boundary evidence is unreadable") from exc
    if type(value) is not dict:
        raise RuntimeError("path-boundary evidence is malformed")
    return value


def _site(value: object, sources: dict[str, str], label: str) -> str:
    if type(value) is not dict or set(value) != {"path", "tokens"}:
        raise RuntimeError(f"{label} is malformed")
    path = value["path"]
    if type(path) is not str or path not in sources:
        raise RuntimeError(f"{label} names an unaudited source")
    tokens = _strings(value["tokens"], f"{label}.tokens")
    missing = [token for token in tokens if token not in sources[path]]
    if missing:
        raise RuntimeError(f"{label} evidence drift: {missing}")
    return path


def _record(
    value: object,
    sources: dict[str, str],
    artifact_ids: set[str],
    index: int,
) -> tuple[str, str, int]:
    label = f"pathBoundaryEvidence.records[{index}]"
    required = {
        "evidenceId", "concern", "disposition", "artifactIds",
        "finding", "sites",
    }
    if type(value) is not dict or set(value) != required:
        raise RuntimeError(f"{label} is malformed")
    evidence_id = value["evidenceId"]
    concern = value["concern"]
    disposition = value["disposition"]
    finding = value["finding"]
    if (type(evidence_id) is not str or not evidence_id
            or concern not in CONCERNS or disposition not in DISPOSITIONS
            or type(finding) is not str or not finding):
        raise RuntimeError(f"{label} classification is malformed")
    artifacts = _strings(
        value["artifactIds"], f"{label}.artifactIds", allow_empty=True)
    if set(artifacts) - artifact_ids:
        raise RuntimeError(f"{label} names an absent artifact")
    if ((disposition == "artifact-bound") != bool(artifacts)
            or (disposition == "ephemeral-non-authority" and artifacts)):
        raise RuntimeError(f"{label} artifact binding is incoherent")
    sites = value["sites"]
    if type(sites) is not list or not sites:
        raise RuntimeError(f"{label}.sites is empty")
    paths = {_site(site, sources, f"{label}.sites[{item}]")
             for item, site in enumerate(sites)}
    return str(evidence_id), str(concern), len(paths)


def verify_path_boundary_evidence(
    repo: Path,
    relative: object,
    sources: dict[str, str],
    artifact_ids: set[str],
) -> dict[str, int]:
    """Require exact, source-checked manual evidence for four blind spots."""
    value = _load(repo, relative)
    required = {
        "schemaVersion", "asOf", "concerns", "records", "knownLimitations",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schemaVersion") != 1:
        raise RuntimeError("path-boundary evidence has an unsupported schema")
    concerns = set(_strings(value["concerns"], "pathBoundaryEvidence.concerns"))
    if concerns != CONCERNS:
        raise RuntimeError("path-boundary evidence concerns are incomplete")
    limitations = _strings(
        value["knownLimitations"], "pathBoundaryEvidence.knownLimitations")
    records = value["records"]
    if type(records) is not list or not records:
        raise RuntimeError("path-boundary evidence records are empty")
    parsed = [
        _record(row, sources, artifact_ids, index)
        for index, row in enumerate(records)
    ]
    ids = [row[0] for row in parsed]
    covered = {row[1] for row in parsed}
    if len(set(ids)) != len(ids) or covered != CONCERNS:
        raise RuntimeError("path-boundary evidence repeats ids or misses concerns")
    return {
        "records": len(parsed),
        "sourceFiles": len({site["path"] for row in records for site in row["sites"]}),
        "knownLimitations": len(limitations),
    }
