#!/usr/bin/env python3
"""Bounded deterministic intent search across complete catalog metadata."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from graphics.catalog_discovery import Catalog, SearchFilters, tokenize

MIN_INTENTS = 1
MAX_INTENTS = 4
DEFAULT_LIMIT = 5
MAX_LIMIT = 20
_FIELD_WEIGHT = {"jobs": 12, "name": 8, "title": 7, "tags": 6,
                 "family": 6, "description": 4, "profile": 4, "inputs": 3,
                 "variables": 3, "mechanism": 3, "fit": 2, "sync": 2,
                 "resource": 1, "port": 1}
_CONCEPTS = {
    "proof": {"proof", "prove", "evidence", "credible", "trust", "testimonial",
              "quote", "result", "metric", "stats", "customer"},
    "compare": {"compare", "comparison", "versus", "difference", "before", "after",
                "replace", "contrast", "swap"},
    "process": {"process", "step", "workflow", "pipeline", "sequence", "progress",
                "journey", "flow"},
    "explain": {"explain", "teach", "diagram", "relationship", "system", "concept",
                "framework", "map", "annotate"},
    "demonstrate": {"demonstrate", "demo", "show", "interface", "screen", "browser",
                    "app", "device", "cursor", "product"},
    "emphasize": {"emphasize", "emphasis", "highlight", "focus", "callout", "marker",
                  "underline", "spotlight", "pointer"},
    "transition": {"transition", "handoff", "seam", "cut", "wipe", "morph", "whip",
                   "bridge", "reveal"},
    "title": {"title", "chapter", "heading", "intro", "definition", "headline",
              "kicker", "section"},
    "data": {"data", "number", "count", "chart", "graph", "stat", "metric",
             "percentage", "trend"},
    "code": {"code", "terminal", "command", "diff", "snippet", "typing", "editor"},
    "social": {"social", "comment", "message", "chat", "notification", "post",
               "follow", "thread"},
    "location": {"location", "map", "route", "travel", "city", "country", "world"},
}
_STOP_WORDS = {
    "a", "an", "and", "as", "at", "be", "for", "from", "in", "is",
    "it", "of", "on", "or", "that", "the", "this", "to", "with",
}
_SPECIFIC_FIELDS = {"jobs", "name", "title", "tags", "family", "profile"}
_CREDIBILITY_POLICY = "semantic-credibility-v1"


@dataclass(frozen=True)
class SemanticSearchRequest:
    """A bounded group of alternative descriptions for one visual job."""

    intents: tuple[str, ...]
    filters: SearchFilters = field(default_factory=lambda: SearchFilters(limit=DEFAULT_LIMIT))

    def issue(self) -> str | None:
        """Why this request is not safe to execute, or None."""
        if not MIN_INTENTS <= len(self.intents) <= MAX_INTENTS:
            return f"semantic search needs {MIN_INTENTS}-{MAX_INTENTS} intents"
        if any(not tokenize(intent) for intent in self.intents):
            return "semantic search intents must contain alphanumeric terms"
        if not 1 <= self.filters.limit <= MAX_LIMIT:
            return f"semantic search limit must be in [1,{MAX_LIMIT}]"
        copy = SearchFilters(**{**asdict(self.filters), "limit": 1})
        return copy.issue()


def _concepts(terms: set[str]) -> dict[str, set[str]]:
    """Return controlled expansions only when an intent names that concept."""
    return {name: words for name, words in _CONCEPTS.items() if terms & words}


def _hits(fields: dict[str, frozenset[str]], term: str) -> list[str]:
    """Whole-token hits with the discovery layer's plural tolerance."""
    return [name for name, words in fields.items()
            if term in words or term + "s" in words
            or (term.endswith("s") and term[:-1] in words)]


def _passes(record: dict, filters: SearchFilters) -> bool:
    """Apply the shared factual filters without inferring adaptability."""
    upstream = record.get("upstream") or {}
    return not ((filters.type and filters.type not in (record["type"], upstream.get("type")))
                or (filters.status and record["integration"]["status"] != filters.status)
                or (filters.tag and filters.tag not in record["tags"] + upstream.get("tags", []))
                or (filters.declared_aspect
                    and filters.declared_aspect not in record["declared"]["aspects"]))


def _score(record: dict, fields: dict[str, frozenset[str]],
           direct: set[str], concepts: dict[str, set[str]]) -> dict | None:
    """Score direct language above controlled semantic expansion."""
    direct_hits = {term: hit for term in sorted(direct) if (hit := _hits(fields, term))}
    expanded_hits: dict[str, list[str]] = {}
    score = sum(max(_FIELD_WEIGHT.get(name, 1) for name in hit)
                for hit in direct_hits.values()) * 5
    for concept, words in concepts.items():
        hit_fields = sorted({name for term in words for name in _hits(fields, term)})
        if not hit_fields:
            continue
        expanded_hits[concept] = hit_fields
        score += 12 + max(_FIELD_WEIGHT.get(name, 1) for name in hit_fields)
        if concept in set(record.get("metadata", {}).get("jobs") or []):
            score += 30
    if not direct_hits and not expanded_hits:
        return None
    return {"score": score, "directTerms": direct_hits,
            "semanticConcepts": expanded_hits,
            "unmatchedDirectTerms": sorted(direct - set(direct_hits))}


def _credibility(match: dict) -> dict:
    """Separate plausible finalists from incidental metadata matches."""
    direct = {term: fields for term, fields in match["directTerms"].items()
              if term not in _STOP_WORDS}
    specific_direct = sorted(term for term, fields in direct.items()
                             if set(fields) & _SPECIFIC_FIELDS)
    specific_concepts = sorted(
        concept for concept, fields in match["semanticConcepts"].items()
        if set(fields) & _SPECIFIC_FIELDS)
    credible = bool(specific_direct or specific_concepts or len(direct) >= 2)
    basis = []
    if specific_direct:
        basis.append("specific-direct-term")
    if specific_concepts:
        basis.append("specific-semantic-concept")
    if len(direct) >= 2:
        basis.append("multiple-direct-terms")
    if not basis:
        basis.append("incidental-or-generic-metadata-match")
    return {"policyVersion": _CREDIBILITY_POLICY,
            "status": "credible" if credible else "weak",
            "basis": basis, "directTerms": sorted(direct),
            "specificDirectTerms": specific_direct,
            "specificConcepts": specific_concepts}


def semantic_search_catalog(catalog: Catalog, request: SemanticSearchRequest) -> dict:
    """Search all metadata rows and return only a bounded shortlist."""
    issue = request.issue()
    if issue:
        raise ValueError(issue)
    direct = {term for intent in request.intents for term in tokenize(intent)
              if len(term) >= 2}
    concepts = _concepts(direct)
    scored = []
    for record in catalog.records:
        if not _passes(record, request.filters):
            continue
        match = _score(record, catalog.tokens[record["ref"]], direct, concepts)
        if match:
            scored.append({**record, "semanticMatch": match,
                           "credibility": _credibility(match)})
    scored.sort(key=lambda row: (
        row["credibility"]["status"] != "credible",
        -row["semanticMatch"]["score"], row["ref"]))
    limit = request.filters.limit
    return {"schemaVersion": 1,
            "scope": "metadata-discovery-not-execution-or-visual-approval",
            "intents": list(request.intents), "directTerms": sorted(direct),
            "expandedConcepts": {key: sorted(value) for key, value in concepts.items()},
            "filters": asdict(request.filters), "catalogSnapshot":
                catalog.provenance.get("snapshotId"),
            "provenance": catalog.provenance,
            "total": len(scored), "returned": min(limit, len(scored)),
            "limited": len(scored) > limit, "results": scored[:limit]}
