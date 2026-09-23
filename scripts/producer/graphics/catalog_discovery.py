#!/usr/bin/env python3
"""catalog_discovery — bounded, deterministic catalog search + exact lookup.

Producer asks "find a subtle transition" / "show a comparison card" while
planning; this answers with candidates from the WHOLE recorded catalog (the
vendored mirror + the mechanism study + the integrated registry), each with
its evidence and its ACTUAL integration status (see
``catalog_discovery_records``): ``reference``, ``reference-missing-source``,
``integrated-measured`` (proposable through the existing plan/scene adapters)
or ``integrated-unmeasured`` (not proposable).

No label here approves copy, dimensions, duration, FPS, placement or Studio
compatibility: item/plan gates still apply (``scope`` says so in every
result). Matching is whole-word on recorded text with singular/plural
tolerance only — no prefix or fuzzy fallback; an exact id/ref in the query
is never dropped by the result limit. Ranking: more query terms matched,
then field-weighted score, then evidence availability, then ref; exact identity
precedes that keyword ranking so a ref prefix cannot hide its own result.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from graphics.catalog_discovery_records import (  # noqa: F401 (re-exported)
    ASPECTS, PROVENANCE_LOCAL, PROVENANCE_MIRROR, PROVENANCE_PORTED,
    STATUS_MEASURED, STATUS_REFERENCE, STATUS_REFERENCE_MISSING,
    STATUS_UNMEASURED, STATUSES, adaptation_notes, local_record,
    mirror_record, provenance_summary,
)
from graphics.catalog_discovery_sources import (
    NAME_RE, CatalogSources, DiscoveryPaths, load_sources,
)

SCHEMA_VERSION = 1
SCOPE = "discovery-evidence-not-plan-or-scene-admission"
TYPES = ("block", "component", "local")
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_TERM_CHARS = 2
_WEIGHTS = {"name": 6, "title": 5, "tags": 4, "description": 3,
            "variables": 2, "mechanism": 2, "fit": 2, "port": 1}
_EXACT_BONUS = 1000
_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Equal-score tie-break: items with current evidence sort before references
# (an ordering of EVIDENCE availability, not a recommendation).
_STATUS_RANK = {status: rank for rank, status in enumerate(
    (STATUS_MEASURED, STATUS_UNMEASURED, STATUS_REFERENCE, STATUS_REFERENCE_MISSING))}


@dataclass(frozen=True)
class SearchFilters:
    """The small filter set the CLI exposes."""

    type: str | None = None
    declared_aspect: str | None = None
    status: str | None = None
    tag: str | None = None
    limit: int = DEFAULT_LIMIT

    def issue(self) -> str | None:
        """Why the filters are unusable, or None."""
        if self.type is not None and self.type not in TYPES:
            return f"type must be one of {TYPES}"
        if self.declared_aspect is not None and self.declared_aspect not in ASPECTS:
            return f"declared aspect must be one of {ASPECTS}"
        if self.status is not None and self.status not in STATUSES:
            return f"status must be one of {STATUSES}"
        if type(self.limit) is not int or not 1 <= self.limit <= MAX_LIMIT:
            return f"limit must be an integer in [1,{MAX_LIMIT}]"
        return None


@dataclass(frozen=True)
class Catalog:
    """Unified records, their search tokens, and the provenance they carry."""

    records: list[dict]
    tokens: dict[str, dict[str, frozenset[str]]]
    provenance: dict


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens (hyphenated names split into parts)."""
    return _TOKEN_RE.findall(text.lower())


def _tokens(record: dict) -> dict[str, frozenset[str]]:
    """Tokenize only the recorded search fields."""
    study = record.get("study") or {}
    upstream = record.get("upstream") or {}
    template_variables = " ".join(
        f"{key} {label}" for key, label in (record.get("templateVariables") or {}).items())
    fields = {
        "name": record["id"] + " " + upstream.get("name", ""),
        "title": record["title"] + " " + upstream.get("title", ""),
        "tags": " ".join(record["tags"] + upstream.get("tags", [])),
        "description": record["description"] + " " + upstream.get("description", ""),
        "variables": " ".join(study.get("variables") or []) + " " + template_variables,
        "mechanism": study.get("mechanism") or "",
        "fit": (study.get("fit") or "") + " " + (study.get("quality") or ""),
        "port": study.get("port") or "",
    }
    return {key: frozenset(tokenize(text)) for key, text in fields.items()}


def build_catalog(sources: CatalogSources) -> Catalog:
    """Unified, deterministically ordered records from loaded sources."""
    records = [local_record(kind, sources) for kind in sorted(sources.local)]
    ported_names = set(sources.ported.values())
    records += [mirror_record(name, sources) for name in sorted(sources.index)
                if name not in ported_names]
    for record in records:
        record["adaptationNotes"] = adaptation_notes(record)
    tokens = {record["ref"]: _tokens(record) for record in records}
    return Catalog(records, tokens, provenance_summary(sources, records))


def load_catalog(paths: DiscoveryPaths | None = None) -> Catalog:
    """Read every recorded source once and build the searchable catalog."""
    return build_catalog(load_sources(paths or DiscoveryPaths()))


def inventory_catalog(catalog: Catalog) -> dict:
    """Expose every item for strategy without ranking or execution approval."""
    from pathlib import Path
    from cut_preview_io import file_hash

    records = []
    for record in catalog.records:
        source = record["source"]
        source_hash = (file_hash(Path(source["path"]), 16 * 1024 * 1024)
                       if source["exists"] else None)
        records.append({**record, "source": {**source, "sha256": source_hash},
                        "executionApproved": False})
    return {"schemaVersion": SCHEMA_VERSION, "scope": SCOPE,
            "provenance": catalog.provenance, "total": len(records),
            "returned": len(records), "limited": False, "items": records}


def _word_hit(term: str, words: frozenset[str]) -> bool:
    """Whole-word match, tolerating one trailing plural ``s`` either way."""
    return (term in words or term + "s" in words
            or (term.endswith("s") and term[:-1] in words))


def _match(tokens: dict[str, frozenset[str]], terms: list[str],
           exact: bool) -> dict | None:
    """Score whole-word hits while retaining exact-match and unmatched terms."""
    matched: dict[str, list[str]] = {}
    score = _EXACT_BONUS if exact else 0
    for term in terms:
        fields = [field for field, words in tokens.items()
                  if _word_hit(term, words)]
        if not fields:
            continue
        matched[term] = fields
        score += sum(_WEIGHTS[field] for field in fields)
    if not matched:
        return None
    return {"score": score, "exact": exact, "matchedTerms": matched,
            "unmatchedTerms": [term for term in terms if term not in matched]}


def _passes(record: dict, filters: SearchFilters) -> bool:
    """Apply explicit discovery filters without inferring capability."""
    upstream = record.get("upstream") or {}
    if filters.type and filters.type not in (record["type"], upstream.get("type")):
        return False
    if filters.status and record["integration"]["status"] != filters.status:
        return False
    if filters.tag and filters.tag not in record["tags"] + upstream.get("tags", []):
        return False
    if filters.declared_aspect and filters.declared_aspect not in record["declared"]["aspects"]:
        return False
    return True


def _terms(query: str) -> tuple[list[str], list[str]]:
    """Usable query terms and the ones too short to mean anything."""
    tokens = tokenize(query)
    terms = [token for token in tokens if len(token) >= MIN_TERM_CHARS]
    if not terms:
        raise ValueError(f"query needs at least one term of {MIN_TERM_CHARS}+ "
                         "alphanumeric characters")
    return terms, [token for token in tokens if len(token) < MIN_TERM_CHARS]


def search_catalog(catalog: Catalog, query: str,
                   filters: SearchFilters | None = None) -> dict:
    """Ranked, bounded, deterministic search; exact ids are never dropped."""
    filters = filters or SearchFilters()
    issue = filters.issue()
    if issue:
        raise ValueError(issue)
    terms, ignored = _terms(query)
    wanted = query.strip().lower()
    scored, excluded = [], []
    for record in catalog.records:
        exact = wanted in (record["id"], record["ref"])
        match = _match(catalog.tokens[record["ref"]], terms, exact)
        if match is None:
            continue
        passes = _passes(record, filters)
        scored += [{**record, "match": match}] if passes else []
        excluded += [record["ref"]] if exact and not passes else []
    scored.sort(key=lambda r: (not r["match"]["exact"], -len(r["match"]["matchedTerms"]),
                               -r["match"]["score"],
                               _STATUS_RANK[r["integration"]["status"]], r["ref"]))
    return {"schemaVersion": SCHEMA_VERSION, "scope": SCOPE, "query": query,
            "terms": terms, "ignoredTerms": ignored, "filters": asdict(filters),
            "total": len(scored), "returned": min(len(scored), filters.limit),
            "limited": len(scored) > filters.limit,
            "excludedExactMatches": excluded, "provenance": catalog.provenance,
            "results": scored[:filters.limit]}


def lookup_item(catalog: Catalog, name: str) -> dict:
    """Every record carrying this exact id (or ``mirror:``/``local:`` ref)."""
    bare = name.split(":", 1)[1] if name.startswith(("mirror:", "local:")) else name
    if not NAME_RE.fullmatch(bare):
        raise ValueError(f"not a valid catalog name: {name!r}")
    matches = [record for record in catalog.records
               if name in (record["id"], record["ref"])]
    return {"schemaVersion": SCHEMA_VERSION, "scope": SCOPE, "name": name,
            "found": bool(matches), "matches": matches,
            "provenance": catalog.provenance}
