#!/usr/bin/env python3
"""Transcript-bound graphic decisions for produced longform intros.

The generic trigger planner may prune legal overlays for canvas/style reasons.
That must not erase the underlying editorial obligation.  This module preserves
each strong semantic beat, maps its information shape to compatible built
longform forms, and verifies the plan records what happened to that beat.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any

from edit_scope import resolve_scope
from graphics.form_allocation import is_gate_executable_kind
from graphics.intro_semantic_cues import cue_rows, resolve_transcript_asset
from graphics.intro_semantic_binding import (
    decision_error,
    decision_map,
    density_error,
    duplicate_beat_errors,
    reuse_errors,
)
from graphics.style_profiles import (compatible_kinds, forms_for_shape,
                                     profile as visual_profile,
                                     profile_name)
from graphics.template_contract import template_catalog
from planner import motion_triggers as mt
from planner.graphics_planner_rules import UNIT_NOUNS, is_generic_entity
from producer_config import MOTION

INTRO_WINDOW_S = 60.0
EARLY_WINDOW_S = 180.0
FIRST_MINUTE_GRAPHICS = 4
EARLY_GRAPHICS_MAX = 8

_TRIGGER_SHAPE = {
    "contrast": "comparison",
    "enumeration": "list",
    "sequence": "process",
    "entity": "evidence",
    "number": "scale",
    "thesis": "thesis",
    "topic-boundary": "chapter",
}
_SHAPE_PRIORITY = {
    "comparison": 8, "credibility": 7, "list": 6, "process": 5,
    "chapter": 4, "evidence": 3, "scale": 2, "thesis": 1,
}
_CREDIBILITY_CUES = (
    "decade", "years", "founder", "i built", "i've built", "i have built",
    "i started", "i run", "ceo", "my own brand", "my own clients",
)
_CHRONOLOGY_CUES = ("january", "february", "march", "april", "may", "june",
                    "july", "august", "september", "october", "november",
                    "december", "today", "tomorrow", "yesterday", "week",
                    "month", "year", "first", "then", "finally")
_PARALLEL_CUES = ("parallel", "simultaneously", "at once", "agents",
                  "in parallel", "concurrently")
_LIMIT_CUES = ("limit", "maximum", "minimum", "under", "below", "above",
               "cap", "threshold", "ceiling")
_QA_CUES = ("verify", "verified", "check", "checked", "quality", "qa",
            "inspect", "test", "passed", "failed")
_CONFIG_CUES = ("model", "setting", "configured", "configuration", "active",
                "version", "workflow", "stack")
_MECHANISM_CUES = ("how it works", "works by", "pipeline", "loop", "cycle",
                   "connects", "transcript", "word timed", "word-timed")
_ASSET_FORMS = frozenset({"icon-badge-wide", "logo-card"})
_TRIGGER_FORMS = {
    "audience-list": ("glass-rail", "nateherk-rail", "whiteboard-list",
                      "canvas-pip-list", "list-build"),
    "tool-list": ("glass-rail", "nateherk-rail", "whiteboard-list",
                  "canvas-pip-list", "list-build"),
    "credibility": ("avatar-bio-card", "nateherk-ledger-dark",
                    "whiteboard-connector"),
    "building-proof": ("angela-receipt-cell", "nateherk-ledger-dark",
                       "whiteboard-connector"),
    "exact-proof": ("angela-receipt-cell", "nateherk-ledger-dark",
                    "whiteboard-connector"),
}


def _text(words: list[dict], indices: list[int]) -> str:
    return " ".join(mt._word_text(words[index]) for index in indices).strip()


def _times(words: list[dict], indices: list[int]) -> tuple[float, float]:
    start = float(words[indices[0]].get("start", 0.0))
    end = float(words[indices[-1]].get("end", start))
    return start, max(start, end)


def _candidate_rows(words: list[dict], window_s: float) -> list[dict]:
    rows = []
    for candidate in mt.detect_all(words):
        trigger = str(candidate.get("trigger", ""))
        shape = _TRIGGER_SHAPE.get(trigger)
        indices = candidate.get("wordIndices") or []
        if not shape or candidate.get("confidence") != "high" or not indices:
            continue
        evidence = str(candidate.get("text") or _text(words, indices)).strip()
        if trigger == "enumeration" and \
                (mt._clean(evidence).split() or [""])[-1] in UNIT_NOUNS:
            shape = "scale"
        if shape == "evidence" and is_generic_entity(evidence):
            continue
        start, end = _times(words, indices)
        if start < window_s:
            row = {"shape": shape, "trigger": trigger,
                   "outStart": start, "outEnd": end,
                   "evidence": evidence, "confidence": "high"}
            if trigger == "entity":
                asset = resolve_transcript_asset(evidence)
                row.update({"namedAssets": [asset],
                            "resolvedAssets": ([asset["selector"]]
                                               if asset["selector"] else []),
                            "assetSelectorsComplete": bool(asset["selector"])})
            rows.append(row)
    rows.extend(_credibility_rows(words, window_s))
    rows.extend(cue_rows(words, window_s))
    return rows


def _credibility_rows(words: list[dict], window_s: float) -> list[dict]:
    cleaned = [mt._clean(mt._word_text(word)) for word in words]
    joined = " ".join(cleaned)
    if not any(cue in joined for cue in _CREDIBILITY_CUES):
        return []
    for index in range(len(words)):
        lo, hi = max(0, index - 1), min(len(words), index + 4)
        phrase = " ".join(cleaned[lo:hi])
        if not any(cue in phrase for cue in _CREDIBILITY_CUES):
            continue
        start, end = _times(words, list(range(lo, hi)))
        if start < window_s:
            return [{"shape": "credibility", "trigger": "credibility",
                     "outStart": start, "outEnd": end,
                     "evidence": _text(words, list(range(lo, hi))),
                     "confidence": "high"}]
    return []


def _overlap(left: dict, right: dict) -> bool:
    return left["outStart"] < right["outEnd"] \
        and right["outStart"] < left["outEnd"]


def _dedupe(rows: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for row in sorted(rows, key=lambda item: (item["outStart"],
                                              -_SHAPE_PRIORITY[item["shape"]])):
        hit = next((i for i, prior in enumerate(kept)
                    if _overlap(prior, row)), None)
        if hit is None:
            kept.append(row)
            continue
        prior = kept[hit]
        if _SHAPE_PRIORITY[row["shape"]] > _SHAPE_PRIORITY[prior["shape"]]:
            kept[hit] = row
    return sorted(kept, key=lambda item: item["outStart"])


def _wide_forms(row: dict, catalog: dict[str, dict]) -> list[str]:
    trigger, shape = row["trigger"], row["shape"]
    forms = list(_TRIGGER_FORMS.get(trigger,
                 MOTION["card_form_map"].get(shape) or ()))
    assets = row.get("resolvedAssets") or []
    if trigger == "tool-list" and row.get("assetSelectorsComplete"):
        forms.insert(0, "icon-badge-wide")
    elif shape in ("evidence", "credibility") and assets:
        forms.append("logo-card" if len(assets) == 1 else "icon-badge-wide")
    forms = [kind for kind in forms if kind not in _ASSET_FORMS
             or row.get("assetSelectorsComplete")]
    return [kind for kind in forms if kind in catalog
            and catalog[kind]["dimensions"][0] > catalog[kind]["dimensions"][1]
            and is_gate_executable_kind(kind)]


def _beat_id(row: dict) -> str:
    raw = f"{row['shape']}|{round(row['outStart'] * 1000)}|{row['evidence']}"
    return "intro-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _profile_shape(row: dict) -> str:
    """Refine coarse trigger shapes into profile-facing information intent."""
    text = str(row.get("evidence") or "").lower()
    shape = str(row["shape"])
    trigger = str(row.get("trigger") or "")
    if trigger in ("tool-list", "audience-list"):
        return trigger
    if any(cue in text for cue in _PARALLEL_CUES):
        return "parallel-process"
    if any(cue in text for cue in _LIMIT_CUES) and shape in ("scale", "comparison"):
        return "limit"
    if any(cue in text for cue in _QA_CUES) and shape in ("list", "process", "evidence"):
        return "qa"
    if any(cue in text for cue in _MECHANISM_CUES) and shape in ("process", "evidence"):
        return "mechanism"
    if any(cue in text for cue in _CHRONOLOGY_CUES) and shape == "process":
        return "chronology"
    if any(cue in text for cue in _CONFIG_CUES) and shape in ("evidence", "credibility"):
        return "configuration"
    return shape


def semantic_beats(words: list[dict], out_dur: float,
                   selected_profile: str | None = None) -> list[dict]:
    """Strong intro/early beats with source-derived compatible 16:9 forms."""
    profile_cfg = visual_profile(selected_profile)
    ceiling = float(out_dur) if profile_cfg and \
        profile_cfg.get("semanticWindow") == "full" else EARLY_WINDOW_S
    window_s = min(max(0.0, float(out_dur)), ceiling)
    if window_s <= 0:
        return []
    catalog = template_catalog()
    beats = []
    for row in _dedupe(_candidate_rows(words, window_s)):
        shape = _profile_shape(row) if profile_cfg else row["shape"]
        shaped = {**row, "shape": shape}
        if shape != row["shape"]:
            shaped["sourceShape"] = row["shape"]
        info_forms = forms_for_shape(selected_profile, shape) if profile_cfg else []
        forms = compatible_kinds(selected_profile, info_forms) if profile_cfg \
            else _wide_forms(row, catalog)
        fields = {"compatibleForms": info_forms,
                  "preferredForm": info_forms[0] if info_forms else None,
                  "visualProfile": selected_profile} if profile_cfg else {}
        beats.append({**shaped, "beatId": _beat_id(shaped),
                      "compatibleKinds": forms, **fields,
                      "decisionRequired": True,
                      "preferredKind": forms[0] if forms else None,
                      "minimumGraphicHoldS":
                          float(MOTION["hold_min_s"]["longform"])})
    return beats


def _early_graphics_floor(end: float) -> int:
    """Match the transcript-bound floor to the structural early-window floor."""
    rules = MOTION["variety"]["local_floors"]
    rule = next((row for row in rules
                 if row.get("label") == "first three minutes"), None)
    if not isinstance(rule, dict):
        return EARLY_GRAPHICS_MAX
    floor = int(rule.get("min_windows_floor", 0))
    every = rule.get("min_windows_floor_every_s")
    if isinstance(every, (int, float)) and every > 0:
        floor = max(floor, math.ceil(end / float(every)))
    return min(EARLY_GRAPHICS_MAX, floor)


def check_intro_graphics(plan: dict, words: list[dict], out_dur: float,
                         rep: Any) -> None:
    """Require every strong early opportunity to resolve on the timeline."""
    target = plan.get("target") or {}
    if target.get("mode") != "longform" \
            or resolve_scope(target) not in ("produced", "full"):
        return
    if not words:
        rep.error("intro graphics contract has no kept transcript words — "
                  "produced/full longform must be transcript-first")
        return
    beats = [beat for beat in semantic_beats(
             words, out_dur, profile_name(target))
             if beat.get("decisionRequired")]
    decisions = decision_map(plan)
    for issue in duplicate_beat_errors(plan):
        rep.error(issue)
    for issue in reuse_errors(plan):
        rep.error(issue)
    for beat in beats:
        decision = decisions.get(beat["beatId"])
        if decision is None:
            rep.error(f"hook graphic beat {beat['beatId']} ({beat['shape']} at "
                      f"{beat['outStart']:.1f}s, {beat['evidence']!r}) has no "
                      "persisted graphicsDecisions row")
            continue
        issue = decision_error(beat, decision, plan)
        if issue:
            rep.error(f"hook graphic beat {beat['beatId']}: {issue}")
    intro_end = min(float(out_dur), INTRO_WINDOW_S)
    issue = density_error(beats, decisions, plan,
                          (intro_end, FIRST_MINUTE_GRAPHICS, "first minute"))
    if issue:
        rep.error(issue)
    if out_dur > INTRO_WINDOW_S:
        early_end = min(out_dur, EARLY_WINDOW_S)
        issue = density_error(
            beats, decisions, plan,
            (early_end, _early_graphics_floor(early_end),
             "first three minutes"))
        if issue:
            rep.error(issue)
