"""Legacy-plan projections for typed transition, SFX, and grade actions."""
from __future__ import annotations

import copy

from planner.treatment_contract import TreatmentContractError
from planner.treatment_models import TreatmentEffect, TreatmentState


def _transition_view(row: dict) -> dict:
    keys = ("id", "outFrame", "kind", "sfx")
    if not all(key in row for key in keys):
        raise TreatmentContractError("target transition lacks typed authority")
    return {key: row[key] for key in keys}


def _transition_index(rows: list[dict], ident: str) -> int | None:
    matches = [index for index, row in enumerate(rows)
               if isinstance(row, dict) and row.get("id") == ident]
    if len(matches) > 1:
        raise TreatmentContractError("duplicate transition target")
    return matches[0] if matches else None


def _compat_transition(value: dict, state: TreatmentState) -> dict:
    frame = value["outFrame"]
    if frame >= state.total_frames:
        raise TreatmentContractError("transition frame exceeds project duration")
    seconds = frame * state.fps.denominator / state.fps.numerator
    return {**value, "outTime": seconds}


def _seam_window(state: TreatmentState, frame: int) -> tuple[int, int]:
    radius = (state.fps.numerator + 2 * state.fps.denominator - 1) \
        // (2 * state.fps.denominator)
    return max(0, frame - radius), min(state.total_frames, frame + radius + 1)


def transition_set(state: TreatmentState, operation: dict) -> TreatmentEffect:
    """Add or replace one typed transition and dirty only its seam windows."""
    plan = copy.deepcopy(state.plan)
    rows = list(plan.get("transitions") or [])
    index = _transition_index(rows, operation["transitionId"])
    current = None if index is None else _transition_view(rows[index])
    if current != operation["expectedValue"]:
        raise TreatmentContractError("transition precondition failed")
    value = operation["value"]
    if index is None:
        rows.append(_compat_transition(value, state))
    else:
        rows[index] = _compat_transition(value, state)
    plan["transitions"] = sorted(rows, key=lambda row: row["outFrame"])
    frames = [value["outFrame"]]
    if current is not None:
        frames.append(current["outFrame"])
    dirty = tuple(_seam_window(state, frame) for frame in frames)
    nodes = ["transition-video", "base-video"]
    if value["sfx"] or current and current["sfx"]:
        nodes += ["transition-audio", "master-audio"]
    candidate = TreatmentState(
        plan, state.scenes, state.fps, state.total_frames)
    return TreatmentEffect(candidate, dirty, tuple(nodes), False,
                           operation["transitionId"])


def sfx_set(state: TreatmentState, operation: dict) -> TreatmentEffect:
    """Change only a transition's sound slot and its downstream audio nodes."""
    plan = copy.deepcopy(state.plan)
    rows = list(plan.get("transitions") or [])
    index = _transition_index(rows, operation["transitionId"])
    if index is None or rows[index].get("sfx", False) != operation["expectedSfx"]:
        raise TreatmentContractError("SFX precondition failed")
    rows[index]["sfx"] = operation["sfx"]
    plan["transitions"] = rows
    dirty = (_seam_window(state, rows[index]["outFrame"]),)
    candidate = TreatmentState(
        plan, state.scenes, state.fps, state.total_frames)
    return TreatmentEffect(candidate, dirty, (
        "transition-audio", "master-audio", "final-mux"), True,
        operation["transitionId"])


def grade_set(state: TreatmentState, operation: dict) -> TreatmentEffect:
    """Change the current global grade with an honest full-picture closure."""
    plan = copy.deepcopy(state.plan)
    look = dict(plan.get("baselineLook") or {})
    if look.get("grade", "none") != operation["expectedGrade"]:
        raise TreatmentContractError("grade precondition failed")
    look["grade"] = operation["grade"]
    plan["baselineLook"] = look
    candidate = TreatmentState(
        plan, state.scenes, state.fps, state.total_frames)
    return TreatmentEffect(candidate, ((0, state.total_frames),), (
        "base-video-full", "graphics-composite-full", "final-video"), False,
        "baseline-grade")
