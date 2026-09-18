#!/usr/bin/env python3
"""One-to-one transcript-beat bindings for produced intro graphics."""
from __future__ import annotations

from edit_scope import lane_required, resolve_lanes, resolve_scope
from graphics.style_profiles import form_contract

MIN_REASON_CHARS = 20
MIN_SELECTION_REASON_CHARS = 20


def _decision_rows(plan: dict) -> list[dict]:
    rows = plan.get("graphicsDecisions")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _counts(rows: list[dict], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(field)
        if isinstance(value, str) and value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def decision_map(plan: dict) -> dict[str, dict]:
    """Return only unambiguous beat receipts; duplicate rows bind nothing."""
    rows = _decision_rows(plan)
    counts = _counts(rows, "beatId")
    return {str(row["beatId"]): row for row in rows
            if isinstance(row.get("beatId"), str)
            and counts.get(str(row["beatId"])) == 1}


def duplicate_beat_errors(plan: dict) -> list[str]:
    counts = _counts(_decision_rows(plan), "beatId")
    return [f"graphicsDecisions beatId {beat_id!r} appears {count} times; "
            "every transcript beat requires exactly one decision row"
            for beat_id, count in sorted(counts.items()) if count > 1]


def covers(entries: list[dict], beat: dict) -> bool:
    at = float(beat["outStart"])
    return any(float(row.get("outStart", 1e18)) <= at
               <= float(row.get("outEnd", row.get("outStart", 1e18)))
               for row in entries)


def _graphic_by_id(plan: dict, graphic_id: str) -> dict | None:
    matches = [row for row in plan.get("graphicsTrack") or []
               if row.get("id") == graphic_id]
    return matches[0] if len(matches) == 1 else None


def validated_bound_ids(plan: dict) -> set[str]:
    """Structurally unique beat→decision→graphic bindings for local floors."""
    rows = _decision_rows(plan)
    beat_counts = _counts(rows, "beatId")
    graphic_counts = _counts(rows, "graphicId")
    bound: set[str] = set()
    for row in rows:
        beat_id, graphic_id = row.get("beatId"), row.get("graphicId")
        if row.get("decision") != "graphic" \
                or not isinstance(beat_id, str) \
                or not isinstance(graphic_id, str) \
                or beat_counts.get(beat_id) != 1 \
                or graphic_counts.get(graphic_id) != 1:
            continue
        entry = _graphic_by_id(plan, graphic_id)
        form_ok = not row.get("informationForm") or \
            entry.get("informationForm") == row.get("informationForm")
        if entry is not None and entry.get("semanticBeatId") == beat_id \
                and entry.get("kind") == row.get("kind") and form_ok:
            bound.add(graphic_id)
    return bound


def _asset_error(beat: dict, entry: dict) -> str | None:
    expected = beat.get("resolvedAssets") or []
    kind, spec = entry.get("kind"), entry.get("spec") or {}
    if kind == "logo-card":
        actual = [spec.get("iconFile")] if spec.get("iconFile") else []
    elif kind == "icon-badge-wide":
        actual = [spec.get(f"icon{index}") for index in range(1, 4)
                  if spec.get(f"icon{index}")]
    else:
        return None
    if actual == expected:
        return None
    return (f"{kind} assets {actual} do not exactly match transcript-resolved "
            f"selectors {expected}")


def _hold_error(beat: dict, entry: dict) -> str | None:
    minimum = float(beat.get("minimumGraphicHoldS") or 0.0)
    hold = float(entry.get("outEnd", 0.0)) - float(entry.get("outStart", 0.0))
    if minimum <= 0.0 or hold + 1e-6 >= minimum:
        return None
    return (f"bound graphic hold {hold:.2f}s is shorter than semantic beat "
            f"minimumGraphicHoldS {minimum:.2f}s; extend the window within "
            "output bounds")


def _selection_error(beat: dict, decision: dict) -> str | None:
    kind = str(decision.get("kind") or "")
    if kind not in beat["compatibleKinds"]:
        return f"kind {kind!r} is outside compatible forms {beat['compatibleKinds']}"
    compatible_forms = beat.get("compatibleForms") or []
    if compatible_forms:
        information_form = str(decision.get("informationForm") or "")
        if information_form not in compatible_forms:
            return (f"informationForm {information_form!r} is outside compatible "
                    f"profile forms {compatible_forms}")
        contract = form_contract(beat.get("visualProfile"), information_form)
        if not contract or contract.get("kind") != kind:
            expected = contract.get("kind") if contract else None
            return (f"informationForm {information_form!r} requires renderer kind "
                    f"{expected!r}, not {kind!r}")
    alternatives_key = "alternativeFormsConsidered" if compatible_forms \
        else "alternativesConsidered"
    alternatives = decision.get(alternatives_key)
    if not isinstance(alternatives, list) \
            or any(not isinstance(item, str) for item in alternatives):
        return f"graphic decision needs string-list {alternatives_key}"
    unique = list(dict.fromkeys(alternatives))
    selected = str(decision.get("informationForm") or "") \
        if compatible_forms else kind
    compatible = compatible_forms or beat["compatibleKinds"]
    if selected in unique or any(item not in compatible for item in unique):
        return f"{alternatives_key} must contain other compatible anatomies"
    needed = min(2, max(0, len(compatible) - 1))
    if len(unique) < needed:
        return (f"graphic decision considered {len(unique)} alternative(s) in "
                f"{alternatives_key}; needs {needed}")
    selection = str(decision.get("selectionReason") or "").strip()
    if len(selection) < MIN_SELECTION_REASON_CHARS:
        return ("graphic decision needs a transcript-specific selectionReason "
                f"of {MIN_SELECTION_REASON_CHARS}+ characters")
    return None


def _resolution_error(beat: dict, action: str, target: dict) -> str | None:
    """Enforce transcript-bound opportunities for produced/full longform."""
    if not beat.get("decisionRequired") \
            or target.get("mode") != "longform" \
            or resolve_scope(target) not in ("produced", "full"):
        return None
    if action == "omit":
        return ("decisionRequired beat must resolve to a graphic or matching "
                "b-roll; omit cannot discharge it")
    if action == "broll" and resolve_lanes(target).get("broll") == "off":
        return ("b-roll lane is off; decisionRequired beat must resolve to a "
                "graphic")
    return None


def decision_error(beat: dict, decision: dict, plan: dict) -> str | None:
    action = decision.get("decision")
    reason = str(decision.get("reason") or "").strip()
    if action not in ("graphic", "broll", "omit"):
        return "decision must be 'graphic', 'broll', or 'omit'"
    if len(reason) < MIN_REASON_CHARS:
        return f"{action} decision needs a {MIN_REASON_CHARS}+ character reason"
    if beat.get("shape") == "credibility" \
            and lane_required(plan.get("target") or {}, "credibility") \
            and action != "graphic":
        return "automatic credibility requires a bound credibility graphic"
    issue = _resolution_error(beat, action, plan.get("target") or {})
    if issue:
        return issue
    if action == "broll" and not covers(plan.get("brollTrack") or [], beat):
        return "broll decision has no matching b-roll window"
    if action != "graphic":
        return None
    issue = _selection_error(beat, decision)
    if issue:
        return issue
    graphic_id = decision.get("graphicId")
    if not isinstance(graphic_id, str) or not graphic_id:
        return "graphic decision needs controller-bound graphicId"
    entry = _graphic_by_id(plan, graphic_id)
    if entry is None:
        return f"graphicId {graphic_id!r} does not resolve uniquely"
    if entry.get("semanticBeatId") != beat["beatId"]:
        return "bound graphic semanticBeatId does not match this beatId"
    if entry.get("kind") != decision.get("kind"):
        return (f"bound graphic kind {entry.get('kind')!r} does not match "
                f"{decision.get('kind')!r}")
    if decision.get("informationForm") and \
            entry.get("informationForm") != decision.get("informationForm"):
        return (f"bound graphic informationForm "
                f"{entry.get('informationForm')!r} does not match "
                f"{decision.get('informationForm')!r}")
    if not covers([entry], beat):
        return (f"bound graphic {graphic_id!r} is not on screen at the exact "
                f"semantic beat {beat['outStart']:.3f}s")
    issue = _hold_error(beat, entry)
    if issue:
        return issue
    return _asset_error(beat, entry)


def _realized(beat: dict, decisions: dict[str, dict], plan: dict) -> bool:
    decision = decisions.get(beat["beatId"]) or {}
    graphic_id = decision.get("graphicId")
    if decision.get("decision") != "graphic" or not isinstance(graphic_id, str):
        return False
    references = [row for row in decisions.values()
                  if row.get("decision") == "graphic"
                  and row.get("graphicId") == graphic_id]
    entry = _graphic_by_id(plan, graphic_id)
    form_ok = not decision.get("informationForm") or \
        entry is not None and entry.get("informationForm") == \
        decision.get("informationForm")
    return len(references) == 1 and entry is not None and form_ok \
        and entry.get("semanticBeatId") == beat["beatId"] \
        and entry.get("kind") == decision.get("kind") and covers([entry], beat)


def density_error(beats: list[dict], decisions: dict[str, dict], plan: dict,
                  requirement: tuple[float, int, str]) -> str | None:
    end, cap, label = requirement
    scoped = [beat for beat in beats if beat["outStart"] < end]
    if len(scoped) < cap:
        return (f"{label} exposes only {len(scoped)} strong transcript beats; "
                f"insufficient transcript beats for the absolute {cap}-graphic "
                "floor. Add deterministic transcript-bound visual obligations "
                "or stop with this explicit insufficiency; never lower the floor")
    required = cap
    graphic = sum(1 for beat in scoped if _realized(beat, decisions, plan))
    if graphic >= required:
        return None
    return (f"{label} has {len(scoped)} strong semantic beats but only {graphic} "
            f"uniquely bound graphic decisions (needs {required}); choose compatible "
            "forms for real transcript beats, never filler templates")


def reuse_errors(plan: dict) -> list[str]:
    claimed: dict[str, str] = {}
    errors = []
    for decision in _decision_rows(plan):
        beat_id = str(decision.get("beatId") or "<missing>")
        graphic_id = decision.get("graphicId")
        if decision.get("decision") != "graphic" or not isinstance(graphic_id, str):
            continue
        if graphic_id in claimed:
            errors.append(f"graphicId {graphic_id!r} is reused by semantic beats "
                          f"{claimed[graphic_id]} and {beat_id}; one graphic may "
                          "discharge exactly one beat")
        else:
            claimed[graphic_id] = beat_id
    return errors
