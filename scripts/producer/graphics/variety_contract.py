#!/usr/bin/env python3
"""Fail-closed structural-variety contract for graphic windows (LL-016)."""
from __future__ import annotations

import math
from typing import Any

from edit_scope import lane_required, resolve_scope
from graphics.intro_semantic_binding import validated_bound_ids
from producer_config import MOTION


def _out_start(row: dict) -> float:
    value = row.get("outStart")
    return float(value) if isinstance(value, (int, float)) \
        and not isinstance(value, bool) else 0.0


def _out_end(row: dict) -> float:
    value = row.get("outEnd")
    return float(value) if isinstance(value, (int, float)) \
        and not isinstance(value, bool) else _out_start(row)


def _chain_exempt(left: dict, right: dict) -> bool:
    """A statement replacement chain deliberately reuses one chassis."""
    return any(str((row.get("spec") or {}).get("statements") or "").strip()
               for row in (left, right))


def _anatomy(row: dict) -> str:
    """Executable information form when typed, else the legacy renderer kind."""
    information_form = row.get("informationForm")
    if isinstance(information_form, str) and information_form:
        return information_form
    return str(row.get("kind", ""))


def _anatomy_label(cards: list[tuple[int, dict]]) -> str:
    """Keep legacy diagnostics stable outside typed visual profiles."""
    return "forms" if any(row.get("informationForm") for _index, row in cards) \
        else "kinds"


def strict_scope(plan: dict, mode: str, scopes: tuple[str, ...]) -> bool:
    """Whether this is fail-closed produced/full longform work."""
    if mode != "longform":
        return False
    try:
        return resolve_scope(plan.get("target")) in scopes
    except ValueError:
        return False


def _cards(plan: dict, cfg: dict, bound_only: bool = False) -> list[tuple[int, dict]]:
    layers = cfg["layer_kinds"]
    bound = validated_bound_ids(plan) if bound_only else None
    return sorted(((index, row) for index, row in
                   enumerate(plan.get("graphicsTrack") or [])
                   if str(row.get("kind", "")) not in layers
                   and (bound is None or row.get("id") in bound)),
                  key=lambda pair: _out_start(pair[1]))


def _report_repeats(cards: list[tuple[int, dict]], rep: Any,
                    strict: bool) -> None:
    for (left_i, left), (right_i, right) in zip(cards, cards[1:]):
        anatomy = _anatomy(right)
        if anatomy != _anatomy(left) or _chain_exempt(left, right):
            continue
        label = "information form" if right.get("informationForm") else "kind"
        message = (
            f"graphicsTrack[{left_i}]→[{right_i}]: consecutive graphic windows "
            f"({_out_start(left):g}s → {_out_start(right):g}s) both use {label} "
            f"{anatomy!r} — vary the anatomy without violating the beat's semantic "
            "form mapping (LL-016/LESSON-030, MODULE_CARDS §2)")
        rep.error(message) if strict else rep.warn(message)


def _whole_plan_floor(cards: list[tuple[int, dict]], cfg: dict,
                      rep: Any) -> None:
    if len(cards) < int(cfg["min_windows"]):
        return
    distinct = {_anatomy(row) for _index, row in cards}
    label = _anatomy_label(cards)
    ratio = float(cfg["min_distinct_ratio"])
    floor = math.ceil(ratio * len(cards))
    if len(distinct) >= floor:
        return
    rep.error(
        f"{len(cards)} graphic windows use only {len(distinct)} distinct "
        f"{label} (< floor {floor} = ceil({ratio:g} × {len(cards)})) — drain "
        "compatible forms before repeating one; the reference uses 20 forms "
        "across 23 windows (LL-016/LESSON-030, MODULE_CARDS §2)")


def _duration(cards: list[tuple[int, dict]], out_dur: float | None) -> float:
    if isinstance(out_dur, (int, float)) and not isinstance(out_dur, bool):
        return max(0.0, float(out_dur))
    return max((_out_end(row) for _index, row in cards), default=0.0)


def _local_floor(cards: list[tuple[int, dict]], duration: float,
                 rule: dict, rep: Any) -> None:
    end = min(duration, float(rule["window_s"]))
    rows = [(index, row) for index, row in cards
            if _out_start(row) < end and _out_end(row) > 0.0]
    window_floor = _scaled_floor(rule, "min_windows_floor", end)
    if duration < float(rule.get("min_output_s", 0.0)) \
            and len(rows) < window_floor:
        return
    distinct = {_anatomy(row) for _index, row in rows}
    label = _anatomy_label(rows)
    distinct_floor = _scaled_floor(rule, "min_distinct_floor", end)
    ratio = float(rule["min_distinct_ratio"])
    floor = max(distinct_floor, math.ceil(ratio * len(rows)))
    if len(rows) >= window_floor and len(distinct) >= floor:
        return
    rep.error(
        f"{rule['label']} [0,{end:g}s] has {len(rows)} info-bearing graphic "
        f"windows / {len(distinct)} {label}; needs at least {window_floor} "
        f"windows and {floor} distinct forms (ratio component ceil({ratio:g} "
        f"× {len(rows)})) — map real transcript beats to another compatible "
        "form from "
        "MOTION['card_form_map']; palette changes do not count as anatomy "
        "(LL-016/LESSON-030)")


def _scaled_floor(rule: dict, key: str, end: float) -> int:
    """Fixed floor optionally grown by the elapsed-window cadence."""
    floor = int(rule.get(key, 0))
    every = rule.get(key + "_every_s")
    if isinstance(every, (int, float)) and every > 0:
        floor = max(floor, math.ceil(end / float(every)))
    return floor


def check_variety(plan: dict, mode: str, rep: Any,
                  out_dur: float | None = None) -> None:
    """Enforce adjacent, local-retention, and whole-plan variety floors."""
    cfg = MOTION["variety"]
    strict = strict_scope(plan, mode, cfg["scopes"])
    try:
        strict = strict and lane_required(plan.get("target"), "graphics")
    except ValueError:
        strict = False
    cards = _cards(plan, cfg)
    _report_repeats(cards, rep, strict)
    if not strict:
        return
    duration = _duration(cards, out_dur)
    bound_cards = _cards(plan, cfg, bound_only=True)
    for rule in cfg["local_floors"]:
        _local_floor(bound_cards, duration, rule, rep)
    _whole_plan_floor(cards, cfg, rep)
