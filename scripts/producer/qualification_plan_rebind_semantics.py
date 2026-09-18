"""One-to-one semantic graphic rebinding for qualified transcript authority."""

from __future__ import annotations

import re
from typing import Any

from qualification_plan_rebind_inputs import RebindError

_TOKEN = re.compile(r"[a-z0-9]+")


def _semantic_key(beat: dict) -> tuple[str, str, tuple[str, ...]]:
    evidence = tuple(_TOKEN.findall(str(beat.get("evidence", "")).lower()))
    return str(beat.get("shape")), str(beat.get("trigger")), evidence


def _unique_beats(rows: Any, label: str) -> dict[tuple, dict]:
    if not isinstance(rows, list) or not rows:
        raise RebindError(f"{label} has no introSemanticBeats")
    indexed: dict[tuple, dict] = {}
    beat_ids: set[str] = set()
    for beat in rows:
        beat_id = beat.get("beatId") if isinstance(beat, dict) else None
        if type(beat_id) is not str or not beat_id or beat_id in beat_ids:
            raise RebindError(f"{label} contains a malformed semantic beat")
        key = _semantic_key(beat)
        if not key[2] or key in indexed:
            raise RebindError(f"{label} semantic signatures are ambiguous")
        beat_ids.add(beat_id)
        indexed[key] = beat
    return indexed


def _display_key(key: tuple) -> dict:
    return {"shape": key[0], "trigger": key[1], "evidence": " ".join(key[2])}


def match_beats(previous: dict, fresh: dict) -> dict[str, dict]:
    """Match exact semantic signatures without accepting reorders."""
    old = _unique_beats(previous.get("introSemanticBeats"), "previous proposal")
    new = _unique_beats(fresh.get("introSemanticBeats"), "fresh proposal")
    missing = [key for key in old if key not in new]
    added = [key for key in new if key not in old]
    if missing or added:
        raise RebindError(
            "fresh semantic beat set changed",
            {
                "missing": [_display_key(key) for key in missing],
                "added": [_display_key(key) for key in added],
            },
        )
    if list(old) != list(new):
        raise RebindError("fresh semantic beat order changed")
    return {
        old[key]["beatId"]: {"previous": old[key], "fresh": new[key]} for key in old
    }


def _graphics_authority(plan: dict) -> tuple[list[dict], dict[str, dict]]:
    decisions, graphics = (
        plan.get("graphicsDecisions"),
        plan.get("graphicsTrack"),
    )
    if not isinstance(decisions, list) or not isinstance(graphics, list):
        raise RebindError("semantic graphic authority is malformed")
    if not all(isinstance(row, dict) for row in decisions + graphics):
        raise RebindError("semantic graphic authority contains a malformed row")
    graphic_ids = [row.get("id") for row in graphics]
    if (
        not all(type(value) is str and value for value in graphic_ids)
        or len(set(graphic_ids)) != len(graphic_ids)
    ):
        raise RebindError("graphicsTrack ids are missing or ambiguous")
    return decisions, {row["id"]: row for row in graphics}


def rebind_graphics(plan: dict, matches: dict[str, dict]) -> list[dict]:
    """Shift exactly one bound graphic for every matched semantic beat."""
    decisions, by_id = _graphics_authority(plan)
    seen_beats: set[str] = set()
    seen_graphics: set[str] = set()
    shifts = []
    for decision in decisions:
        old_id, graphic_id = decision.get("beatId"), decision.get("graphicId")
        match = matches.get(old_id)
        graphic = by_id.get(graphic_id)
        complete = (
            type(old_id) is str
            and type(graphic_id) is str
            and decision.get("decision") == "graphic"
            and old_id not in seen_beats
            and graphic_id not in seen_graphics
            and match is not None
            and graphic is not None
            and graphic.get("semanticBeatId") == old_id
        )
        if not complete:
            raise RebindError(f"semantic graphic binding is incomplete for {old_id}")
        seen_beats.add(old_id)
        seen_graphics.add(graphic_id)
        fresh, previous = match["fresh"], match["previous"]
        delta = float(fresh["outStart"]) - float(previous["outStart"])
        duration = float(graphic["outEnd"]) - float(graphic["outStart"])
        start = round(float(graphic["outStart"]) + delta, 6)
        graphic["outStart"], graphic["outEnd"] = start, round(start + duration, 6)
        graphic["semanticBeatId"] = fresh["beatId"]
        decision["beatId"] = fresh["beatId"]
        shifts.append(
            {
                "graphicId": graphic["id"],
                "oldBeatId": old_id,
                "newBeatId": fresh["beatId"],
                "deltaSeconds": round(delta, 6),
            }
        )
    semantic = {
        row["id"] for row in by_id.values() if row.get("semanticBeatId") is not None
    }
    if seen_beats != set(matches) or seen_graphics != semantic:
        raise RebindError("not every semantic beat has exactly one graphic decision")
    return shifts
