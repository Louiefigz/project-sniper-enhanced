#!/usr/bin/env python3
"""Narrow transcript cues for high-retention longform intro information shapes.

These are evidence detectors, not copy generators: every emitted row quotes a
real contiguous transcript span.  Multi-phrase rules require the transcript to
say the structural relationship; they never infer a topic from a lone noun.
"""
from __future__ import annotations

from planner import motion_triggers as mt
from planner.graphics_planner_rules import is_generic_entity, resolve_icon

# Catalog data: phrase groups are source-language evidence, not template copy.
_CUE_SPECS = (
    {"trigger": "audience-list", "shape": "list", "min_hits": 2,
     "phrases": (("content", "for", "clients"), ("media", "team"),
                 ("small", "team"), ("one", "person", "shop"),
                 ("solo", "creator"))},
    {"trigger": "promise", "shape": "thesis", "min_hits": 1,
     "phrases": (("helpful", "for", "you", "to", "watch"),
                 ("what", "you", "will", "learn"),
                 ("what", "you'll", "learn"), ("show", "you", "how"))},
    {"trigger": "maturity-stage", "shape": "process", "min_hits": 2,
     "phrases": (("content", "system"), ("at", "this", "stage"),
                 ("workflow", "stage"), ("maturity", "stage"))},
    {"trigger": "limitation", "shape": "comparison", "min_hits": 1,
     "phrases": (("using", "only", "prompts"), ("only", "prompts"),
                 ("prompts", "can", "probably", "even", "be", "better"),
                 ("limited", "to", "prompts"))},
    {"trigger": "building-proof", "shape": "evidence", "min_hits": 1,
     "sentence": True,
     "phrases": (("i'm", "building"), ("i", "am", "building"),
                 ("we're", "building"), ("we", "are", "building"))},
    {"trigger": "exact-proof", "shape": "evidence", "min_hits": 2,
     "phrases": (("exact", "engine"), ("i", "use"), ("we", "use"),
                 ("my", "own", "brand"), ("client", "accounts"))},
)
_TOOL_CONTEXT = frozenset({"use", "using", "tool", "tools", "app", "apps",
                           "platform", "platforms", "software", "stack"})
_ASSET_ALIASES = {"gpt": "openai", "chat gpt": "openai",
                  "chatgpt": "openai"}
_BRAND_COLOR_ASSETS = {
    "openai": "openai-color.svg",
    "claude": "claude-color.svg",
    "gemini": "gemini-color.svg",
}


def _phrase_hits(cleaned: list[str], phrases: tuple[tuple[str, ...], ...]
                 ) -> list[tuple[int, int]]:
    hits = []
    for phrase in phrases:
        width = len(phrase)
        hits.extend((index, index + width - 1)
                    for index in range(len(cleaned) - width + 1)
                    if tuple(cleaned[index:index + width]) == phrase)
    return sorted(set(hits))


def _row(words: list[dict], spec: dict,
         hits: list[tuple[int, int]]) -> dict:
    first, last = hits[0][0], hits[-1][1]
    if spec.get("sentence"):
        last = mt._sentence_end(words, first)
    indices = list(range(first, last + 1))
    return {"shape": spec["shape"], "trigger": spec["trigger"],
            "outStart": float(words[first].get("start", 0.0)),
            "outEnd": float(words[last].get("end", 0.0)),
            "evidence": " ".join(mt._word_text(words[i]) for i in indices),
            "confidence": "high"}


def _local_hits(words: list[dict], hits: list[tuple[int, int]],
                required: int) -> list[tuple[int, int]]:
    """First <=10s phrase cluster satisfying one cue; distant repeats differ."""
    for position, first in enumerate(hits):
        start = float(words[first[0]].get("start", 0.0))
        group = [hit for hit in hits[position:]
                 if float(words[hit[0]].get("start", 0.0)) - start <= 10.0]
        if len(group) >= required:
            return group
    return []


def _declared_cues(words: list[dict], window_s: float) -> list[dict]:
    cleaned = [mt._clean(mt._word_text(word)) for word in words]
    rows = []
    for spec in _CUE_SPECS:
        hits = _phrase_hits(cleaned, spec["phrases"])
        hits = _local_hits(words, hits, int(spec["min_hits"]))
        if not hits:
            continue
        row = _row(words, spec, hits)
        if row["outStart"] < window_s:
            rows.append(row)
    return rows


def resolve_transcript_asset(value: str) -> dict:
    """Exact spoken identity plus its local icon selector, if one exists."""
    evidence = value.strip()
    cleaned = mt._clean(evidence)
    identity = _ASSET_ALIASES.get(cleaned, cleaned)
    selector = _BRAND_COLOR_ASSETS.get(identity) or resolve_icon(identity)
    return {"evidence": evidence, "selector": selector}


def _tool_entities(words: list[dict]) -> list[dict]:
    spans = []
    for candidate in mt.detect_all(words):
        raw = str(candidate.get("text") or "")
        resolvable = bool(resolve_transcript_asset(raw)["selector"])
        if candidate.get("trigger") != "entity" \
                or candidate.get("confidence") != "high" \
                or (is_generic_entity(raw) and not resolvable):
            continue
        indices = candidate.get("wordIndices") or []
        if indices:
            first, last = indices[0], indices[-1]
            if mt._clean(str(candidate.get("text") or "")) == "gpt" \
                    and first > 0 and mt._clean(mt._word_text(words[first - 1])) == "chat":
                first -= 1
            evidence = " ".join(mt._word_text(words[index])
                                for index in range(first, last + 1))
            spans.append({"first": first, "last": last,
                          **resolve_transcript_asset(evidence)})
    return spans


def _tool_list(words: list[dict], window_s: float) -> list[dict]:
    spans = _tool_entities(words)
    groups: list[list[dict]] = []
    for span in spans:
        if groups and span["first"] - groups[-1][-1]["last"] <= 5:
            groups[-1].append(span)
        else:
            groups.append([span])
    rows = []
    cleaned = [mt._clean(mt._word_text(word)) for word in words]
    for group in groups:
        first, last = group[0]["first"], group[-1]["last"]
        context = set(cleaned[max(0, first - 5):first])
        if len(group) < 2 or not context & _TOOL_CONTEXT:
            continue
        lead = max(0, first - 3)
        spec = {"shape": "list", "trigger": "tool-list"}
        row = _row(words, spec, [(lead, last)])
        row["namedAssets"] = [{"evidence": item["evidence"],
                               "selector": item["selector"]}
                              for item in group]
        row["resolvedAssets"] = [item["selector"] for item in group
                                 if item["selector"]]
        row["assetSelectorsComplete"] = len(group) <= 3 and all(
            item["selector"] for item in group)
        if row["outStart"] < window_s:
            rows.append(row)
    return rows


def cue_rows(words: list[dict], window_s: float) -> list[dict]:
    """Return high-confidence, transcript-quoted semantic intro cues."""
    return _declared_cues(words, window_s) + _tool_list(words, window_s)
