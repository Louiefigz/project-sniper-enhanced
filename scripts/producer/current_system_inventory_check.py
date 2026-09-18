"""Fail-closed repository audit for CurrentSystemInventoryV1 call sites."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from baseline_trace_validation import validate_trace_document
from current_system_inventory_discovery import verify_authority_discovery
from current_system_inventory_sources import (
    parse_audit_scope,
    source_files,
)
from current_system_path_evidence import verify_path_boundary_evidence
from current_system_persistence_audit import audit_persistence_calls
from current_system_persistence_dispositions import (
    verify_persistence_dispositions,
)

ALLOWED_DISPOSITIONS = {
    "path-owner",
    "reader",
    "writer",
    "reader-writer",
    "launcher",
    "non-authority",
}


def _strings(value: object, label: str) -> tuple[str, ...]:
    if (type(value) is not list or not value
            or any(type(item) is not str or not item for item in value)
            or len(set(value)) != len(value)):
        raise RuntimeError(f"{label} must be unique nonempty strings")
    return tuple(value)


def _mapping(value: object, label: str) -> dict[str, str]:
    if type(value) is not dict or not value:
        raise RuntimeError(f"{label} must be a nonempty object")
    result: dict[str, str] = {}
    for path, disposition in value.items():
        if (type(path) is not str or not path or type(disposition) is not str
                or disposition not in ALLOWED_DISPOSITIONS):
            raise RuntimeError(f"{label} has an invalid disposition")
        result[path] = disposition
    return result


def _evidence_path(repo: Path, relative: str) -> Path:
    candidate = repo / relative
    if candidate.is_symlink() or not candidate.is_file():
        raise RuntimeError(f"baseline evidence is unavailable: {relative}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(repo)
    except ValueError as exc:
        raise RuntimeError(
            f"baseline evidence escapes repository: {relative}") from exc
    return resolved


def _verify_baseline(repo: Path, value: object) -> int:
    if type(value) is not dict or set(value) != {
            "status", "requiredFixtures", "evidencePaths"}:
        raise RuntimeError("inventory baseline is malformed")
    status = value["status"]
    required = _strings(value["requiredFixtures"], "baseline.requiredFixtures")
    evidence = value["evidencePaths"]
    if (status not in {"required-unmeasured", "measured"}
            or type(evidence) is not list
            or any(type(item) is not str or not item for item in evidence)
            or len(set(evidence)) != len(evidence)):
        raise RuntimeError("inventory baseline is malformed")
    if status != "measured":
        return len(evidence)
    if len(evidence) != len(required):
        raise RuntimeError(
            "measured baseline must name every required fixture trace")
    traces = []
    for relative in evidence:
        path = _evidence_path(repo, relative)
        try:
            trace = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"baseline evidence is unreadable: {relative}") from exc
        if not validate_trace_document(trace):
            raise RuntimeError(
                f"baseline evidence is not one closed trace: {relative}")
        traces.append(trace)
    modes = {trace["fixture"].get("mode") for trace in traces}
    fixture_ids = {trace["fixture"].get("fixtureId") for trace in traces}
    if (modes != {"short", "longform"} or len(fixture_ids) != len(traces)
            or any(trace["fixture"].get("evidenceClass")
                   != "current-full-path-baseline" for trace in traces)):
        raise RuntimeError(
            "measured baseline must close distinct short and long full paths")
    return len(traces)


def _matches(sources: dict[str, str], tokens: tuple[str, ...]) -> set[str]:
    return {
        path for path, text in sources.items()
        if any(token in text for token in tokens)
    }


def _verify_tokens(
    artifact_id: str,
    tokens: tuple[str, ...],
    sources: dict[str, str],
) -> None:
    for token in tokens:
        if not any(token in text for text in sources.values()):
            raise RuntimeError(
                f"{artifact_id} authority token is absent: {token!r}")


def _verify_declaration_field(
    repo: Path, artifact: dict, field: str,
) -> None:
    artifact_id = artifact["artifactId"]
    raw = artifact.get(field)
    values = [raw] if field == "owner" else raw
    if (type(values) is not list or not values
            or any(type(item) is not str or not item for item in values)):
        raise RuntimeError(f"{artifact_id}.{field} is malformed")
    for value in values:
        target = repo / value
        if not target.exists() or target.is_symlink():
            raise RuntimeError(
                f"{artifact_id}.{field} path is absent: {value}")


def _verify_declarations(repo: Path, artifact: dict) -> None:
    for field in ("owner", "readers", "writers"):
        _verify_declaration_field(repo, artifact, field)


def _verify_artifact(
    repo: Path,
    artifact: object,
    sources: dict[str, str],
) -> None:
    if type(artifact) is not dict:
        raise RuntimeError("inventory artifact is malformed")
    artifact_id = artifact.get("artifactId")
    if type(artifact_id) is not str or not artifact_id:
        raise RuntimeError("inventory artifact id is malformed")
    tokens = _strings(
        artifact.get("authorityPathTokens"),
        f"{artifact_id}.authorityPathTokens",
    )
    dispositions = _mapping(
        artifact.get("callSiteDispositions"),
        f"{artifact_id}.callSiteDispositions",
    )
    _verify_tokens(artifact_id, tokens, sources)
    _verify_declarations(repo, artifact)
    actual, declared = _matches(sources, tokens), set(dispositions)
    if actual != declared:
        missing = sorted(actual - declared)
        stale = sorted(declared - actual)
        raise RuntimeError(
            f"{artifact_id} call-site audit drift; "
            f"undisposed={missing}, absent={stale}")


def _verify_exit_claim(inventory: dict, backlog: int, dispositions: dict) -> None:
    if inventory.get("completeness") != "complete":
        return
    if backlog:
        raise RuntimeError(
            "complete inventory has a blocking authority-discovery backlog")
    if dispositions["blockingSites"]:
        raise RuntimeError(
            "complete inventory has blocking persistence calls: "
            f"{dispositions['categories']}")


def validate_inventory(repo: Path, inventory_path: Path) -> dict:
    """Validate declared authority evidence against current production source."""
    repo = repo.resolve(strict=True)
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("current-system inventory is unreadable") from exc
    if type(inventory) is not dict or type(inventory.get("artifacts")) is not list:
        raise RuntimeError("current-system inventory is malformed")
    baseline_evidence = _verify_baseline(repo, inventory.get("baseline"))
    scope = parse_audit_scope(inventory.get("callSiteAudit"))
    sources = source_files(repo, scope)
    artifacts = inventory["artifacts"]
    for artifact in artifacts:
        _verify_artifact(repo, artifact, sources)
    discovered, backlog = verify_authority_discovery(
        inventory.get("authorityDiscovery"),
        sources,
        {
            artifact["artifactId"]: set(artifact["authorityPathTokens"])
            for artifact in artifacts
        },
    )
    path_evidence = verify_path_boundary_evidence(
        repo,
        inventory["authorityDiscovery"]["pathBoundaryEvidence"],
        sources,
        {artifact["artifactId"] for artifact in artifacts},
    )
    persistence = audit_persistence_calls(sources, artifacts)
    persistence_dispositions = verify_persistence_dispositions(
        repo,
        inventory["authorityDiscovery"]["persistenceDispositionEvidence"],
        persistence,
    )
    _verify_exit_claim(inventory, backlog, persistence_dispositions)
    return {
        "ok": True,
        "artifacts": len(artifacts),
        "baselineEvidence": baseline_evidence,
        "discoveredAuthorityLiterals": discovered,
        "discoveryBacklog": backlog,
        "pathBoundaryEvidence": path_evidence,
        "persistenceCallAudit": persistence,
        "persistenceDispositions": persistence_dispositions,
        "sourceFiles": len(sources),
        "disposedCallSites": sum(
            len(artifact["callSiteDispositions"]) for artifact in artifacts),
    }


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Verify current-system authority call-site inventory")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[2]),
    )
    parser.add_argument(
        "--inventory",
        default="docs/producer/command-driven-editing/contracts/"
        "current-system-inventory-v1.json",
    )
    args = parser.parse_args()
    repo = Path(args.repo_root).resolve()
    inventory = Path(args.inventory)
    if not inventory.is_absolute():
        inventory = repo / inventory
    try:
        result = validate_inventory(repo, inventory)
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
