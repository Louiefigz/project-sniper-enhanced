#!/usr/bin/env python3
"""Read-only mirror/study/registry loaders; catalog text is data, not instructions.
Keep sources distinct; only comp_capability_artifact grants measured status.
No HTML execution, rendering, fetching or writing."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from graphics.visual_source_policy import require_integrated
from graphics import comp_capabilities
from graphics import comp_capability_artifact as artifact
from graphics.template_contract import composition_dimensions, declared_variables
from graphics.catalog_discovery_validation import (  # noqa: F401 (legacy exports)
    ITEM_TYPES, NAME_RE, STUDY_TEXT, index_record_issue, study_record_issue, validated_lock,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_ROOT = os.environ.get(
    "SNIPER_PIPELINE_ROOT",
    os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "..")))
CATALOG_DIR = os.path.join(PIPELINE_ROOT, "vendor", "hyperframes-catalog")
STUDY_PATH = os.path.join(PIPELINE_ROOT, "docs", "producer", "catalog-study",
                          "catalog-study.json")
INDEX_NAME = "catalog-index.json"
LOCK_NAME = "hyperframes-catalog-lock.json"
_TYPE_DIRS = {"block": ("compositions",),
              "component": ("compositions", "components")}
_HEADER_MAX = 1200
# The literal a ported template carries to declare where it came from.
PROVENANCE_MARK = "vendor/hyperframes-catalog"
# Port waves A/B: require declared provenance AND an indexed upstream name.
# Similar names/titles never inherit capability.
PORTED_KINDS: dict[str, str] = {
    "chart-story": "chart-story",
    "count-up": "count-up",
    "hw-callout-circle": "hw-callout-circle",
    "hw-scribble-transition": "hw-scribble-transition",
    "line-swap": "line-swap",
    "marker-highlight": "marker-highlight",
    "ui-focus-zoom": "ui-focus-zoom",
}


@dataclass(frozen=True)
class DiscoveryPaths:
    """Where discovery reads from; the motion root is the artifact module's."""

    catalog_dir: str = CATALOG_DIR
    study_path: str = STUDY_PATH
    capability_path: str | None = None

    def capability(self) -> str:
        """Default to the same measured artifact as the plan-time predicates."""
        return self.capability_path or comp_capabilities._MATRIX_PATH


@dataclass(frozen=True)
class CatalogSources:
    """Everything discovery reads, loaded once, with loader findings."""

    catalog_dir: str
    index: dict[str, dict]
    lock: dict
    study: dict[str, dict]
    local: dict[str, dict]
    ported: dict[str, str]
    ready: dict[str, dict]
    row_issues: dict[str, str]
    artifact_error: str
    issues: list[str]


def _read_json(path: str, label: str) -> object:
    """Parse one regular JSON file or fail loudly (no fallback source)."""
    if not os.path.isfile(path) or os.path.islink(path):
        raise RuntimeError(f"{label} is not a regular file: {path}")
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} unreadable: {path} — {exc}") from exc


def load_index(path: str) -> tuple[dict[str, dict], list[str]]:
    """Validated index records by name; malformed/duplicate rows reported."""
    data = _read_json(path, "catalog index")
    if not isinstance(data, list):
        raise RuntimeError(f"catalog index is not a list: {path}")
    records: dict[str, dict] = {}
    issues: list[str] = []
    for position, record in enumerate(data):
        issue = index_record_issue(record)
        if issue:
            issues.append(f"index record #{position} dropped: {issue}")
            continue
        if record["name"] in records:
            issues.append(f"index record #{position} dropped: duplicate name "
                          f"{record['name']!r} (first occurrence kept)")
            continue
        records[record["name"]] = record
    return records, issues


def load_lock(path: str) -> tuple[dict, list[str]]:
    """Recorded mirror facts (snapshot provenance, never a fresh inventory)."""
    data = _read_json(path, "catalog lock")
    if not isinstance(data, dict):
        raise RuntimeError(f"catalog lock is not an object: {path}")
    return validated_lock(data)


def load_study(path: str) -> tuple[dict[str, dict], list[str]]:
    """Historical mechanism-study records by name (claims, kept verbatim)."""
    data = _read_json(path, "catalog study")
    if not isinstance(data, list):
        raise RuntimeError(f"catalog study is not a list: {path}")
    records: dict[str, dict] = {}
    issues: list[str] = []
    for position, row in enumerate(data):
        issue = study_record_issue(row)
        if issue:
            issues.append(f"study record #{position} dropped: {issue}")
            continue
        name = row["name"]
        if name in records:
            issues.append(f"study record #{position} dropped: duplicate {name!r}")
            continue
        records[name] = {
            **{key: row.get(key) for key in STUDY_TEXT},
            "type": row.get("type"),
            "variables": list(row.get("variables") or []),
            "scrubSafe": row.get("scrubSafe"),
            "selfContained": row.get("selfContained"),
        }
    return records, issues


def reference_source(catalog_dir: str, record: dict) -> dict:
    """The mirror path an item's source must occupy, and whether it does."""
    parts = _TYPE_DIRS[record["type"]] + (f"{record['name']}.html",)
    relative = os.path.join(*parts)
    root = os.path.realpath(catalog_dir)
    lexical = os.path.join(root, relative)
    candidate = os.path.realpath(lexical)
    exists = (os.path.commonpath((root, candidate)) == root
              and candidate == lexical and not os.path.islink(lexical)
              and os.path.isfile(lexical))
    return {"path": os.path.join("vendor", "hyperframes-catalog", relative),
            "absolutePath": lexical,
            "exists": exists,
            "sizeBytes": os.path.getsize(lexical) if exists else None}


def _header_comment(html: str) -> str:
    """The template's leading authored comment, bounded (data, not code)."""
    start = html.find("<!--")
    end = html.find("-->", start + 4) if start >= 0 else -1
    if start < 0 or end < 0:
        return ""
    return " ".join(html[start + 4:end].split())[:_HEADER_MAX]


def _local_record(kind: str, html: str) -> tuple[dict, str | None]:
    """Read template declarations and report malformed local metadata."""
    record = {"kind": kind, "declared": None, "variables": {},
              "header": _header_comment(html),
              "declaresUpstream": PROVENANCE_MARK in html}
    try:
        record["declared"] = list(composition_dimensions(html))
        record["variables"] = {
            key: str(row.get("label", "")) for key, row in declared_variables(html).items()}
    except ValueError as exc:
        return record, f"local template {kind}: {exc}"
    return record, None


def load_local() -> tuple[dict[str, dict], list[str]]:
    """Every registered local template (the inventory the artifact covers)."""
    records: dict[str, dict] = {}
    issues: list[str] = []
    for path in artifact.composition_paths():
        kind = os.path.splitext(os.path.basename(path))[0]
        require_integrated(kind)
        with open(path, encoding="utf-8") as handle:
            html = handle.read()
        records[kind], issue = _local_record(kind, html)
        records[kind]["source"] = {"path": os.path.abspath(path),
            "exists": os.path.realpath(path) == os.path.abspath(path)
            and not os.path.islink(path) and os.path.isfile(path)}
        if issue:
            issues.append(issue)
    return records, issues


def _port_issue(kind: str, name: str, local: dict[str, dict],
                index: dict[str, dict]) -> str | None:
    """Why one mapping row fails identity verification, or None."""
    row = local.get(kind)
    if row is None:
        return f"ported mapping {kind}->{name}: local template absent"
    if not row["declaresUpstream"]:
        return (f"ported mapping {kind}->{name}: local template does not "
                f"declare {PROVENANCE_MARK} provenance")
    if name not in index:
        return f"ported mapping {kind}->{name}: upstream name not indexed"
    return None


def verify_ported(local: dict[str, dict],
                  index: dict[str, dict]) -> tuple[dict[str, str], list[str]]:
    """Only mapping rows whose identity checks out join local to upstream."""
    verified: dict[str, str] = {}
    issues: list[str] = []
    for kind, name in sorted(PORTED_KINDS.items()):
        issue = _port_issue(kind, name, local, index)
        if issue:
            issues.append(issue)
            continue
        verified[kind] = name
    return verified, issues


def capability_join(path: str) -> tuple[dict[str, dict], dict[str, str], str]:
    """Delegate freshness and row completeness to the existing artifact reader."""
    rows, error = artifact.load_artifact(path)
    if rows is None:
        return {}, {}, error
    ready, issues = {}, {}
    for kind, row in rows.items():
        issue = artifact.capability_row_issue(row)
        if issue is None:
            ready[kind] = row
        else:
            issues[kind] = issue
    return ready, issues, ""


def load_sources(paths: DiscoveryPaths | None = None) -> CatalogSources:
    """Load every recorded source once; loader findings ride along."""
    paths = paths or DiscoveryPaths()
    index, issues = load_index(os.path.join(paths.catalog_dir, INDEX_NAME))
    lock, lock_issues = load_lock(os.path.join(paths.catalog_dir, LOCK_NAME))
    study, study_issues = load_study(paths.study_path)
    local, local_issues = load_local()
    ported, port_issues = verify_ported(local, index)
    ready, row_issues, artifact_error = capability_join(paths.capability())
    return CatalogSources(
        catalog_dir=paths.catalog_dir, index=index, lock=lock, study=study, local=local, ported=ported,
        ready=ready, row_issues=row_issues, artifact_error=artifact_error,
        issues=issues + lock_issues + study_issues + local_issues + port_issues)
