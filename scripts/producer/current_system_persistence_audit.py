"""Bounded persistence-call discovery for the P0 production-source inventory."""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from current_system_python_persistence import (
    python_persistence_rows,
    python_process_rows,
)

SUPPORTED = {".py", ".ts", ".tsx"}
TS_SCANNER = Path(__file__).with_name(
    "current_system_ts_persistence_scan.mjs")


@dataclass(frozen=True)
class PersistenceSite:
    """One filesystem persistence primitive at a stable source location."""

    path: str
    language: str
    callee: str
    line: int


def _python_groups(
    path: str,
    text: str,
) -> tuple[list[PersistenceSite], list[PersistenceSite]]:
    persistence = [
        PersistenceSite(path, "python", callee, line)
        for callee, line in python_persistence_rows(path, text)
    ]
    boundaries = [
        PersistenceSite(path, "python", callee, line)
        for callee, line in python_process_rows(path, text)
    ]
    return persistence, boundaries


def _typescript_row(value: dict, key: str) -> list[PersistenceSite]:
    rows = value.get(key)
    if type(rows) is not list:
        raise RuntimeError(
            "TypeScript persistence AST scanner output is malformed")
    try:
        return [PersistenceSite(
            row["path"], row["language"], row["callee"], row["line"])
            for row in rows]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            "TypeScript persistence AST site is malformed") from exc


def _typescript_groups(
    sources: dict[str, str],
) -> tuple[list[PersistenceSite], list[PersistenceSite]]:
    if not TS_SCANNER.is_file():
        raise RuntimeError("TypeScript persistence AST scanner is unavailable")
    try:
        completed = subprocess.run(
            ["node", str(TS_SCANNER)],
            input=json.dumps(sources),
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
        value = json.loads(completed.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise RuntimeError("TypeScript persistence AST scanner failed") from exc
    if completed.returncode or type(value) is not dict or value.get("ok") is not True:
        detail = value.get("error") if type(value) is dict else completed.stderr
        raise RuntimeError(f"TypeScript persistence AST scanner failed: {detail}")
    return _typescript_row(value, "sites"), _typescript_row(
        value, "boundaries")


def _site_groups(
    sources: dict[str, str],
) -> tuple[list[PersistenceSite], list[PersistenceSite]]:
    sites: list[PersistenceSite] = []
    boundaries: list[PersistenceSite] = []
    unsupported = sorted(
        path for path in sources if Path(path).suffix not in SUPPORTED)
    if unsupported:
        raise RuntimeError(
            f"persistence audit has unsupported source languages: {unsupported}")
    python = {
        path: text for path, text in sources.items() if path.endswith(".py")}
    typescript = {
        path: text for path, text in sources.items() if not path.endswith(".py")}
    for path, text in python.items():
        found, process = _python_groups(path, text)
        sites.extend(found)
        boundaries.extend(process)
    found, process = _typescript_groups(typescript)
    sites.extend(found)
    boundaries.extend(process)
    key = lambda row: (row.path, row.line, row.callee)
    return sorted(sites, key=key), sorted(boundaries, key=key)


def persistence_sites(sources: dict[str, str]) -> list[PersistenceSite]:
    """Extract every call matching the declared filesystem primitives."""
    return _site_groups(sources)[0]


def side_effect_boundary_sites(
    sources: dict[str, str],
) -> list[PersistenceSite]:
    """Extract direct process and selected process-wrapper call boundaries."""
    return _site_groups(sources)[1]


def _merge_owner(
    artifact: dict,
    exact: dict[str, set[str]],
    roots: list[tuple[str, str]],
) -> None:
    artifact_id = artifact["artifactId"]
    for writer in artifact["writers"]:
        if Path(writer).suffix in SUPPORTED:
            exact.setdefault(writer, set()).add(artifact_id)
        else:
            roots.append((writer.rstrip("/") + "/", artifact_id))


def _owners(
    artifacts: list[dict],
) -> tuple[dict[str, set[str]], list[tuple[str, str]]]:
    exact: dict[str, set[str]] = {}
    roots: list[tuple[str, str]] = []
    for artifact in artifacts:
        _merge_owner(artifact, exact, roots)
    return exact, roots


def _site_id(site: PersistenceSite) -> str:
    return f"{site.path}:{site.line}:{site.callee}"


def _unbound_summary(
    sites: list[PersistenceSite],
) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for site in sites:
        counts[site.path] = counts.get(site.path, 0) + 1
    encoded = ("\n".join(sorted(_site_id(site) for site in sites)) + "\n"
               ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), counts


def _owned_sites(
    sites: list[PersistenceSite],
    exact: dict[str, set[str]],
    roots: list[tuple[str, str]],
) -> tuple[int, list[PersistenceSite]]:
    unbound = []
    bound = 0
    for site in sites:
        owners = set(exact.get(site.path, set()))
        owners.update(
            artifact_id for prefix, artifact_id in roots
            if site.path.startswith(prefix))
        if owners:
            bound += 1
        else:
            unbound.append(site)
    return bound, unbound


def _group_report(
    sites: list[PersistenceSite],
    exact: dict[str, set[str]],
    roots: list[tuple[str, str]],
) -> dict[str, object]:
    bound, unbound = _owned_sites(sites, exact, roots)
    digest, file_counts = _unbound_summary(unbound)
    return {
        "sites": len(sites),
        "pythonSites": sum(site.language == "python" for site in sites),
        "typescriptSites": sum(
            site.language == "typescript" for site in sites),
        "artifactBoundSites": bound,
        "unboundSites": len(unbound),
        "unboundFiles": sorted({site.path for site in unbound}),
        "unboundFileSiteCounts": file_counts,
        "unboundSiteDigest": digest,
        "unboundExamples": [_site_id(site) for site in unbound[:40]],
    }


def audit_persistence_calls(
    sources: dict[str, str],
    artifacts: list[dict],
) -> dict[str, object]:
    """Classify discovered persistence sites against artifact writer ownership."""
    sites, boundaries = _site_groups(sources)
    exact, roots = _owners(artifacts)
    result = _group_report(sites, exact, roots)
    result["sideEffectBoundaryAudit"] = _group_report(
        boundaries, exact, roots)
    return result
