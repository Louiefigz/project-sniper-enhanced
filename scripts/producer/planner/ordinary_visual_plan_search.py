#!/usr/bin/env python3
"""Run bounded semantic queries against one controller-frozen catalog authority."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graphics.catalog_discovery import (  # noqa: E402
    Catalog,
    SearchFilters,
    catalog_from_records,
)
from graphics.catalog_semantic_search import (  # noqa: E402
    SemanticSearchRequest,
    semantic_search_catalog,
)

MAX_AUTHORITY_BYTES = 4 * 1024 * 1024
MAX_QUERY_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_QUERIES = 256
MAX_INTENT_CHARS = 500
OPPORTUNITY_ID = re.compile(r"[A-Za-z0-9:_-]{1,128}")
FILTER_KEYS = frozenset(("type", "declaredAspect", "status", "tag", "limit"))
SEARCH_SCOPE = "frozen-catalog-semantic-search-not-execution-approval"


def _read_json(path: Path, label: str, maximum: int) -> tuple[bytes, dict]:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be one absolute regular non-symlink file")
    size = path.stat().st_size
    if size < 2 or size > maximum:
        raise ValueError(f"{label} exceeds its bounded read size")
    data = path.read_bytes()
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be an object")
    return data, value


def _catalog(
    authority_path: Path,
    context: dict,
) -> tuple[Catalog, str, int]:
    data, authority = _read_json(
        authority_path, "catalog authority", MAX_AUTHORITY_BYTES)
    pin = context.get("catalogPin")
    if not isinstance(pin, dict):
        raise ValueError("visual-plan context lacks catalogPin")
    digest = hashlib.sha256(data).hexdigest()
    expected_paths = (pin.get("indexPath"), pin.get("resourceIndexPath"))
    if any(not isinstance(item, str)
           or os.path.realpath(item) != str(authority_path.resolve())
           for item in expected_paths):
        raise ValueError("catalog authority path differs from controller context")
    if pin.get("indexSha256") != digest or pin.get("resourceIndexSha256") != digest:
        raise ValueError("catalog authority bytes differ from controller context")
    rows = authority.get("items")
    provenance = authority.get("provenance")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4096:
        raise ValueError("catalog authority items are invalid or unbounded")
    if not isinstance(provenance, dict):
        raise ValueError("catalog authority provenance is invalid")
    if any(not isinstance(row, dict) or not isinstance(row.get("ref"), str)
           for row in rows):
        raise ValueError("catalog authority contains an invalid record")
    if len({row["ref"] for row in rows}) != len(rows):
        raise ValueError("catalog authority contains duplicate record refs")
    return catalog_from_records(rows, provenance), digest, len(rows)


def _filters(value: object) -> SearchFilters:
    if value is None:
        return SearchFilters(limit=5)
    if not isinstance(value, dict) or set(value) - FILTER_KEYS:
        raise ValueError("query filters contain unsupported fields")
    filters = SearchFilters(
        type=value.get("type"),
        declared_aspect=value.get("declaredAspect"),
        status=value.get("status"),
        tag=value.get("tag"),
        limit=value.get("limit", 5),
    )
    issue = filters.issue()
    if issue:
        raise ValueError(issue)
    if filters.limit != 5 or any((filters.type, filters.declared_aspect,
                                  filters.status, filters.tag)):
        raise ValueError(
            "planning queries must search the full catalog with limit 5 and no narrowing filters")
    return filters


def _query_rows(query: dict) -> list[tuple[str, SemanticSearchRequest]]:
    if set(query) != {"schemaVersion", "scope", "queries"} \
            or query.get("schemaVersion") != 1 \
            or query.get("scope") != "ordinary-visual-semantic-queries":
        raise ValueError("query file has the wrong schema or fields")
    rows = query.get("queries")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_QUERIES:
        raise ValueError(f"query file needs 1-{MAX_QUERIES} opportunity queries")
    parsed, seen = [], set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) not in (
                {"opportunityId", "intents"},
                {"opportunityId", "intents", "filters"}):
            raise ValueError(f"query {index} has unsupported fields")
        opportunity_id = row.get("opportunityId")
        intents = row.get("intents")
        if not isinstance(opportunity_id, str) \
                or not OPPORTUNITY_ID.fullmatch(opportunity_id) \
                or opportunity_id in seen:
            raise ValueError(f"query {index} opportunityId is invalid or duplicated")
        if not isinstance(intents, list) or any(
                not isinstance(item, str) or not item.strip()
                or len(item) > MAX_INTENT_CHARS or "\0" in item for item in intents):
            raise ValueError(f"query {index} intents are invalid")
        request = SemanticSearchRequest(tuple(intents), _filters(row.get("filters")))
        issue = request.issue()
        if issue:
            raise ValueError(f"query {index}: {issue}")
        seen.add(opportunity_id)
        parsed.append((opportunity_id, request))
    return parsed


def _search(catalog: Catalog, rows: list[tuple[str, SemanticSearchRequest]]) -> list[dict]:
    searches = []
    for opportunity_id, request in rows:
        result = semantic_search_catalog(catalog, request)
        result.pop("provenance", None)
        searches.append({"opportunityId": opportunity_id, **result})
    return searches


def _document_digest(value: dict) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


def _core(authority_path: Path, query_path: Path, query_data: bytes,
          catalog: Catalog, catalog_hash: str, total: int,
          rows: list[tuple[str, SemanticSearchRequest]]) -> dict:
    return {
        "schemaVersion": 1, "scope": SEARCH_SCOPE,
        "catalog": {"path": str(authority_path.resolve()),
                    "sha256": catalog_hash, "total": total},
        "query": {"path": str(query_path.resolve()),
                  "sha256": hashlib.sha256(query_data).hexdigest(),
                  "count": len(rows)},
        "provenance": catalog.provenance,
        "searches": _search(catalog, rows),
    }


def _write_output(path: Path, value: dict, allowed_parent: Path) -> None:
    if not path.is_absolute() or path.parent.resolve() != allowed_parent.resolve():
        raise ValueError("search output must be an absolute project-local file")
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()
    if len(data) > MAX_OUTPUT_BYTES:
        raise ValueError("semantic search output exceeds 32 MiB")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False)
    try:
        with handle:
            handle.write(data)
        os.replace(handle.name, path)
    finally:
        if os.path.exists(handle.name):
            os.unlink(handle.name)


def run(authority_path: Path, context_path: Path,
        query_path: Path, output_path: Path) -> dict:
    """Validate exact controller/query inputs and return bounded semantic results."""
    _, context = _read_json(context_path, "visual-plan context", MAX_QUERY_BYTES)
    query_data, query = _read_json(query_path, "semantic query", MAX_QUERY_BYTES)
    if any(item.parent.resolve() != context_path.parent.resolve()
           for item in (authority_path, query_path, output_path)):
        raise ValueError("semantic search paths must share the controller project directory")
    catalog, catalog_hash, total = _catalog(authority_path, context)
    rows = _query_rows(query)
    core = _core(authority_path, query_path, query_data, catalog,
                 catalog_hash, total, rows)
    value = {**core, "digest": _document_digest(core)}
    _write_output(output_path, value, context_path.parent)
    return value


def validate_search_authority(pin: dict, catalog_pin: dict) -> dict:
    """Recompute a pinned search receipt from its exact query and catalog."""
    required = {"schemaVersion", "path", "sha256", "digest"}
    if not isinstance(pin, dict) or set(pin) != required or pin.get("schemaVersion") != 1:
        raise ValueError("searchAuthority pin is malformed")
    result_path = Path(pin.get("path", ""))
    result_data, result = _read_json(
        result_path, "search authority", MAX_OUTPUT_BYTES)
    if hashlib.sha256(result_data).hexdigest() != pin.get("sha256"):
        raise ValueError("search authority SHA-256 differs from its pin")
    digest = result.get("digest")
    core = {key: value for key, value in result.items() if key != "digest"}
    if digest != pin.get("digest") or digest != _document_digest(core):
        raise ValueError("search authority digest differs from its content")
    query = result.get("query")
    if not isinstance(query, dict) or set(query) != {"path", "sha256", "count"}:
        raise ValueError("search authority query pin is malformed")
    query_path = Path(query["path"])
    query_data, query_value = _read_json(query_path, "semantic query", MAX_QUERY_BYTES)
    if hashlib.sha256(query_data).hexdigest() != query["sha256"]:
        raise ValueError("semantic query bytes differ from search authority")
    catalog_path = Path(catalog_pin["indexPath"])
    catalog, catalog_hash, total = _catalog(catalog_path, {"catalogPin": catalog_pin})
    rows = _query_rows(query_value)
    expected = _core(catalog_path, query_path, query_data, catalog,
                     catalog_hash, total, rows)
    if core != expected:
        raise ValueError("search authority differs from deterministic full-catalog search")
    return result


def main(argv: list[str] | None = None) -> int:
    """Search exact fixed paths; emit a small receipt while results go to disk."""
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 4:
        sys.stderr.write("usage: ordinary_visual_plan_search.py AUTHORITY CONTEXT QUERY OUTPUT\n")
        return 2
    try:
        value = run(*(Path(item).expanduser() for item in argv))
        output = Path(argv[3]).resolve()
        print(json.dumps({"ok": True, "catalog": value["catalog"],
                          "query": value["query"],
                          "authority": {"schemaVersion": 1,
                              "path": str(output),
                              "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                              "digest": value["digest"]}}, sort_keys=True))
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"visual-plan-search: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
