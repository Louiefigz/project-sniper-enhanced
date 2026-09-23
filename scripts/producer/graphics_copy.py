#!/usr/bin/env python3
"""graphics_copy — turn brain-written list labels into a timed whiteboard-list.

The planner (graphics_planner_sequences) surfaces candidate BEATS — a window,
per-ordinal timing anchors, and the raw transcript span — with ``needsCopy=True``
and an EMPTY spec. Whether the beat is a real list and what the clean item labels
are is a CONTEXT call ("first person" grammar vs "First, sharpen the pain" step)
that only meaning can make (feedback: no regex for semantics).

That call is made by the BRAIN — the agent running the producer skill — reading
``beat['rawSpan']`` in the skill flow ($0; the producer runs in skills, no live
API, no flags). It writes a short label per REAL step, drops the non-steps, and
calls ``fill_list_spec`` here, which does the DETERMINISTIC part: each label
lands on its ordinal anchor's spoken start (copy from the brain, TIMING from
code). See .claude/skills/producer/SKILL.md.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable

from producer_config import MOTION

TITLE_MAX_WORDS = 5
LABEL_MAX_WORDS = 6
MIN_ITEMS = 2                              # a list needs 2+ real steps


def fill_list_spec(beat: dict, items: list[dict], title: str = "") -> dict | None:
    """Turn the brain's chosen labels into a timed whiteboard-list candidate.

    ``items`` = ordered ``[{"anchorIndex": int, "label": str}]`` — the beat's
    REAL steps (false-positive ordinals dropped by the brain). Each label lands
    on its anchor's spoken start (``atSec``): copy from the brain, timing from
    code. Oversized copy retains the original beat as ``needsCopy`` with a
    structured rewrite request, never a truncated or merge-ready fragment.
    Fewer than MIN_ITEMS valid labels without fit issues returns ``None``;
    only the caller's semantic judgment can discharge a non-list beat.
    A fitting retry retains chosen anchors/title, but does not prove meaning.
    """
    anchors = beat.get("anchors") or []
    if _retry_drops_selection(beat, items, title):
        return {**copy.deepcopy(beat), "spec": {}, "needsCopy": True}
    spec: dict = {"title": _copy_text(title)}
    issues = []
    n = 0
    for index, it in enumerate(items):
        ai = it.get("anchorIndex")
        label = _copy_text(it.get("label", ""))
        if not label or not isinstance(ai, int) or not 0 <= ai < len(anchors):
            continue
        issue = _fit_issue(it.get("label", ""), LABEL_MAX_WORDS,
                           f"items[{index}].label", ai)
        if issue:
            issues.append(issue)
        n += 1
        spec[f"item{n}"] = label
        spec[f"at{n}"] = anchors[ai]["atSec"]
    title_issue = _fit_issue(title, TITLE_MAX_WORDS, "title")
    if title_issue and (n >= MIN_ITEMS or issues):
        issues.insert(0, title_issue)
    if issues:
        return _copy_repair(beat, items, title, issues)
    if n < MIN_ITEMS:
        if beat.get("copyRepair"):
            return {**copy.deepcopy(beat), "spec": {}, "needsCopy": True}
        return None
    out = {k: v for k, v in beat.items()
           if k not in ("anchors", "rawSpan", "needsCopy", "spec", "copyRepair")}
    out["spec"] = spec
    out["confidence"] = "high" if n >= 3 else "medium"
    out["reason"] = (f"{n} sequence steps → whiteboard-list cutaway "
                     "(brain-written copy; atN = spoken land times)")
    out["evidence"] = " → ".join(spec[f"item{k}"] for k in range(1, n + 1))
    return out


def _retry_drops_selection(beat: dict, items: list[dict], title: str) -> bool:
    """Keep every originally chosen valid point, its order and any title."""
    prior = beat.get("copyRepair")
    if not prior:
        return False
    anchors = beat.get("anchors") or []
    expected = _chosen_anchors(prior.get("originalItems", []), anchors)
    return (expected != _chosen_anchors(items, anchors)
            or bool(_copy_text(prior.get("originalTitle", "")))
            and not _copy_text(title))


def _chosen_anchors(items: list[dict], anchors: list[dict]) -> list[int]:
    """Mirror initial valid label selection without interpreting its wording."""
    return [item["anchorIndex"] for item in items
            if _copy_text(item.get("label", ""))
            and isinstance(item.get("anchorIndex"), int)
            and 0 <= item["anchorIndex"] < len(anchors)]


def _fit_issue(text: str, maximum: int, field: str,
               anchor_index: int | None = None) -> dict | None:
    """Describe a mechanical size failure without interpreting or editing copy."""
    count = len(str(text).split())
    if count <= maximum:
        return None
    issue = {"field": field, "originalText": str(text),
             "maxWords": maximum, "actualWords": count}
    if anchor_index is not None:
        issue["anchorIndex"] = anchor_index
    return issue


def _copy_repair(beat: dict, items: list[dict], title: str,
                 issues: list[dict]) -> dict:
    """Detach the complete unresolved obligation and its original timing data."""
    prior = beat.get("copyRepair") or {}
    return {**copy.deepcopy(beat), "spec": {}, "needsCopy": True,
            "copyRepair": {"schemaVersion": 1, "kind": "copy-needs-rewrite",
                           "originalTitle": copy.deepcopy(prior.get("originalTitle", title)),
                           "originalItems": copy.deepcopy(prior.get("originalItems", items)),
                           "issues": copy.deepcopy(issues)}}


def fill_illustration_spec(beat: dict, asset_id: str, pool_ids: Iterable[str] | None,
                           caption: str = "") -> dict | None:
    """Brain's chosen POOL illustration for a concept slot → a brollTrack row.

    ``asset_id`` MUST be a real id in ``pool_ids`` (the manifest ``broll``
    catalog the brain/operator populated) — an unknown or empty id returns
    ``None`` (no invented ids, no fallback; the slot earns nothing, clean head).
    ``caption`` is optional operator context, not load-bearing for the render.
    The result is an ordinary brollTrack row the existing broll_insert engine
    renders full-frame over the footage."""
    aid = str(asset_id or "").strip()
    if not aid or aid not in set(pool_ids or []):
        return None
    out = {k: v for k, v in beat.items()
           if k not in ("needsConcept", "rawSpan", "note", "assetId")}
    out["assetId"] = aid
    out["needsOperator"] = False
    out["confidence"] = "medium"
    if caption:
        out["label"] = _copy_text(caption)
    out["reason"] = (f"concept illustration → pool asset {aid!r} "
                     "(brain-picked; full-frame b-roll)")
    return out


def _word_lands(entry: dict, word_indices: list[int],
                words_out: list[dict], gap: float) -> list[float] | None:
    """Comp-relative land times for the brain's word picks (shared core).

    Returns ``None`` when the picks don't form a valid build — an
    out-of-range index, a land outside the hold, or lands closer than the
    lint floor. No fallback: re-pick the words upstream (the same rule
    ``plan_lint_motion``/``plan_lint_visual`` enforce downstream).
    """
    try:
        out_start = float(entry["outStart"])
        hold = float(entry["outEnd"]) - out_start
    except (KeyError, TypeError, ValueError):
        return None
    if hold <= 0 or not word_indices:
        return None
    lands: list[float] = []
    for idx in word_indices:
        if isinstance(idx, bool) or not isinstance(idx, int) \
                or not 0 <= idx < len(words_out):
            return None
        land = round(float(words_out[idx]["start"]) - out_start, 3)
        if not 0.0 <= land <= hold:
            return None                    # would land off the hold
        if lands and land - lands[-1] < gap:
            return None                    # stacked/non-increasing picks
        lands.append(land)
    return lands


def fill_module_lands(entry: dict, word_indices: list[int],
                      words_out: list[dict]) -> dict | None:
    """Narration-paced module builds: brain picks WHICH words, code times them.

    MODULE_STUDY.md §3 rank 1 / §5 item 4: a card lands its 3-6 modules
    about 0.6-1.4s apart ON spoken words (the ``MOTION["module_lands"]``
    guidance band), never on a fixed stagger. ``word_indices`` are the
    brain's picks into ``words_out`` — the
    KEPT words in OUTPUT time (``graphics_planner.output_words``, i.e. the
    transcript remapped through ``compile_timeline``), so a land survives cut
    edits by arithmetic. Returns a NEW entry whose ``spec.moduleLands`` is the
    comp-relative land list ``[t0, t1, …]`` the comp schedules its builds off,
    or ``None`` on invalid picks (see ``_word_lands``).
    """
    lands = _word_lands(entry, word_indices, words_out,
                        MOTION["module_lands"]["min_spacing_s"])
    if lands is None:
        return None
    return {**entry, "spec": {**(entry.get("spec") or {}), "moduleLands": lands}}


def fill_row_lands(entry: dict, word_indices: list[int],
                   words_out: list[dict]) -> dict | None:
    """Progressive point reveal (LL-011): one land per LIST row, word-locked.

    The operator doctrine: a multi-point list comp (glass-rail rows, numbered
    anything) must land each point exactly when the speaker reaches it —
    never all-at-once. The brain picks one KEPT word per row (indices into
    ``words_out``, one per active row IN ROW ORDER); this converts them to
    comp-relative ``spec.rowLands`` — the same propose/convert seam as
    ``fill_module_lands``. ``plan_lint_visual.check_row_lands`` ERRORs a
    ≥2-item list comp on longform without them. Returns ``None`` on invalid
    picks (see ``_word_lands``); re-pick upstream, no fallback.
    """
    lands = _word_lands(entry, word_indices, words_out,
                        MOTION["row_lands"]["min_spacing_s"])
    if lands is None:
        return None
    return {**entry, "spec": {**(entry.get("spec") or {}), "rowLands": lands}}


def _copy_text(text: str) -> str:
    """Normalize display whitespace without deleting any word or punctuation."""
    return " ".join(str(text).split())
