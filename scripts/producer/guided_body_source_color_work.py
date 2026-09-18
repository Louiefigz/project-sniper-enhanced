"""Private body retention of actual original source and base replay evidence.

Only the two explicit replay phases perform observation/packet work. Repeated
guards retain those actual private readers with original files/sources/clock;
no replacement base/master, native source decoder, timer or old runtime exists.
"""
from __future__ import annotations

from copy import deepcopy
from functools import partial
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from audio.program_master_selection import HeldMasterSelection
from cut_preview_io import digest
from guided_body_source_color_entry import (check_body_source_color_entry, consume_body_source_color_entry,
    capture_body_control_origin, assert_body_control_origin)
from guided_opening_execution import OpeningExecutionClock
from guided_opening_read import _identity
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_read_scope import SourceColorReadScope
from guided_source_color_read_clock import source_color_read_clock_fields

if TYPE_CHECKING:
    from guided_body_work import BodyWork

_WORKS = WeakKeyDictionary()
_ORIGINS = WeakKeyDictionary()
_FIELDS = {"control", "inputs", "clock", "pipeline", "files", "selection", "audio", "workload", "templates", "captions"}
REPLAY_STAGES = ("body-original-source-color-observations", "body-original-base-picture-consumption")


def _origin_fields(work: BodyWork) -> tuple:
    """Original control/input/clock identity wins over a caller's later schema tags."""
    control, invocation = work.control, work.control.invocation
    return (id(control), id(work.inputs), id(work.clock), id(control.value), control.value,
        id(invocation), id(invocation.input_path), str(invocation.input_path), invocation.input_sha256,
        id(work.pipeline), work.pipeline, source_color_read_clock_fields(work.clock))


def _origin_metadata(work: BodyWork, state: tuple) -> None:
    """Retain original constructor input identity through the final callback, without reread."""
    original, origin = state
    if not same_read_metadata(_origin_fields(work), original):
        raise RuntimeError("body original construction control/input/clock changed")
    assert_body_control_origin(origin, work.control, work.clock)


def register_body_work_origin(work: BodyWork) -> None:
    """Authenticate original input/version ONCE, within the existing bound body clock."""
    if work in _ORIGINS:
        raise RuntimeError("body original construction cannot be rebound")
    fields = hold_read_metadata(_fields(work))
    original = hold_read_metadata(_origin_fields(work))
    state = original, capture_body_control_origin(work.control, work.clock)
    _origin_metadata(work, state)
    if not same_read_metadata(_fields(work), fields):
        raise RuntimeError("body original construction work fields changed")
    _ORIGINS[work] = state


def body_source_color_required(control: object, seed: object = None) -> bool:
    """Never route an incomplete or downgraded source2 control through old runtime."""
    return seed is not None or control.value.get("schemaVersion") == 2 or "sourceColorReplay" in control.value \
        or control.documents["openingResult"].get("schemaVersion") == 2


def source_color_body_scope(control: object, inputs: object, clock: object, seed: object) -> SourceColorReadScope:
    """Admit original source2 identity with retained claim DATA, not old runtime IO."""
    controls, transport = consume_body_source_color_entry(seed, control, inputs, clock)
    _identity(control.documents["openingResult"], inputs, controls[1], True)
    scope = SourceColorReadScope(inputs, control.documents["openingResult"], controls, transport)
    check_body_source_color_entry(seed)
    return scope


def _fields(work: BodyWork) -> tuple:
    """Original mutable work fields cannot erase held source2 proof obligations."""
    from guided_body_work import BodyWork
    if type(work) is not BodyWork or set(vars(work)) != _FIELDS:
        raise RuntimeError("source-color body work type or original methods changed")
    return (id(work.control), id(work.inputs), id(work.clock), id(work.pipeline), work.pipeline,
        id(work.files), tuple((id(row), str(row.path), row.sha256, row.identity) for row in work.files))


def _state(work: BodyWork) -> dict | None:
    """Consult original registration before looking at a mutable version discriminator."""
    if work not in _ORIGINS:
        raise RuntimeError("body work needs its actual original construction")
    _origin_metadata(work, _ORIGINS[work])
    state = _WORKS.get(work)
    if state is None:
        if body_source_color_required(work.control):
            raise RuntimeError("source-color body work lacks its original private replay scope")
        return None
    if not same_read_metadata(_fields(work), state["original"]):
        raise RuntimeError("source-color body original work bindings changed")
    if state["preparation"] is not None and not same_read_metadata(_preparation(work), state["preparation"]):
        raise RuntimeError("source-color body original whole-base/master preparation changed")
    return state


def register_body_source_color_work(work: BodyWork, seed: object, scope: SourceColorReadScope) -> None:
    """Hold actual pipeline return BEFORE later dependency or template callbacks."""
    if work in _WORKS or type(scope) is not SourceColorReadScope:
        raise RuntimeError("source-color body work cannot replace its original replay scope")
    _WORKS[work] = {"seed": seed, "scope": scope, "original": hold_read_metadata(_fields(work)),
                    "preparation": None, "replaying": False, "complete": False}
    assert_body_source_color_work(work)


def assert_body_source_color_work(work: BodyWork, complete: bool = False) -> None:
    """Cheap original reader/source guards, never another observation or packet replay."""
    state = _state(work)
    if state is None:
        return
    check_body_source_color_entry(state["seed"])
    SourceColorReadScope.check(state["scope"])
    if complete or state["complete"]:
        if not state["complete"]:
            raise RuntimeError("source-color body original replay groups are incomplete")
        SourceColorReadScope.final_check(state["scope"])
    _state(work)


def append_body_source_color_files(work: BodyWork, added: tuple) -> None:
    """Extend only the actual code-owned file list without rebaselining prior rows."""
    state = _state(work)
    if state is None:
        work.files += added
        return
    assert_body_source_color_work(work)
    work.files += added
    state["original"] = hold_read_metadata(_fields(work))
    assert_body_source_color_work(work)


def _preparation(work: BodyWork) -> tuple:
    """Keep the exact full-program reader's selection and audio return, not substitutes."""
    selected = work.selection
    if type(selected) is not HeldMasterSelection:
        raise RuntimeError("source-color body requires its actual held whole-master selection")
    return (id(selected), id(selected.master), selected.master, id(selected.plan), selected.plan,
        id(selected.context), tuple((name, id(path), str(path)) for name, path in vars(selected.context).items()),
        id(selected.event), selected.event, selected.event_sha256, id(work.audio), work.audio)


def retain_body_source_color_preparation(work: BodyWork) -> None:
    """Bind actual whole-master return immediately, before later metadata callbacks."""
    state = _state(work)
    if state is None:
        return
    if state["preparation"] is not None or work.selection is None or work.audio is None:
        raise RuntimeError("source-color body whole-base/master cannot be rebound or absent")
    state["preparation"] = hold_read_metadata(_preparation(work))
    assert_body_source_color_work(work, True)


def replay_body_source_color(work: BodyWork) -> None:
    """Execute exactly two sibling phases on the SAME clock, outside whole-master phase."""
    state = _state(work)
    if state is None:
        return
    assert_body_source_color_work(work)
    if state["replaying"]:
        raise RuntimeError("source-color body replay cannot run twice or retry a partial failure")
    state["replaying"] = True
    scope = state["scope"]
    actions = (SourceColorReadScope.replay_observations, SourceColorReadScope.replay_consumption)
    for name, action in zip(REPLAY_STAGES, actions):
        assert_body_source_color_work(work)
        count, before = len(work.clock.events), hold_read_metadata(work.clock.events)
        OpeningExecutionClock.phase(work.clock, name, partial(action, scope))
        assert_body_source_color_work(work)
        if len(work.clock.events) != count + 1 or not same_read_metadata(work.clock.events[:count], before):
            raise RuntimeError("source-color body original replay phase history changed")
    SourceColorReadScope.final_check(scope)
    state["complete"] = True
    assert_body_source_color_work(work, True)


def body_source_color_readback(work: BodyWork) -> dict | None:
    """Project only actual complete replay holders; flags grant no new grade/approval."""
    state = _state(work)
    if state is None:
        return None
    assert_body_source_color_work(work, True)
    scope = state["scope"]
    result = {"schemaVersion": 1, "kind": "guided-body-original-source-color-replay",
        "scope": "original-opening-observation-and-base-consumption-not-new-grade-or-approval",
        "sourceColorEvidence": deepcopy(scope.record["sourceColorEvidence"]),
        "observationRecordHash": digest(scope.observations.record), "consumptionRecordHash": digest(scope.consumption.record),
        "sourceColorRecordsReplayed": True, "basePictureConsumptionVerified": True,
        "gamutMeasured": False, "gradeApplied": False, "colorQualified": False, "bodyApproved": False, "deliveryApproved": False}
    assert_body_source_color_work(work, True)
    return result
