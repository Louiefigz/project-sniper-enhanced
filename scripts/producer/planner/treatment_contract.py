"""Closed P4 treatment-operation vocabulary and payload validation."""
from __future__ import annotations

import math
import re

from graphics.scene_contract import validate_scene

_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_VARIABLE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCALAR = (str, int, float, bool)
_TRANSITIONS = {"white-flash", "light-leak", "zoom-pull"}
_GRADES = {"warm", "none"}
_KEYS = {
    "scene.add": {"schemaVersion", "operation", "scene"},
    "scene.setVariable": {
        "schemaVersion", "operation", "sceneId", "elementId", "variable",
        "value", "expectedValue", "expectedSceneVersion",
    },
    "scene.move": {
        "schemaVersion", "operation", "sceneId", "startFrame",
        "endFrameExclusive", "timelineMapHash", "expectedSceneVersion",
    },
    "scene.remove": {
        "schemaVersion", "operation", "sceneId", "expectedSceneVersion",
    },
    "title.setText": {
        "schemaVersion", "operation", "sceneId", "elementId", "variable",
        "text", "expectedText", "expectedSceneVersion",
    },
    "transition.set": {
        "schemaVersion", "operation", "transitionId", "expectedValue", "value",
    },
    "sfx.set": {
        "schemaVersion", "operation", "transitionId", "expectedSfx", "sfx",
    },
    "grade.set": {
        "schemaVersion", "operation", "expectedGrade", "grade",
    },
}


class TreatmentContractError(ValueError):
    """A treatment action is ambiguous, open-ended, or malformed."""


def _stable_id(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) > 96 \
            or not _ID.fullmatch(value):
        raise TreatmentContractError(f"{label} must be a stable kebab-case id")
    return value


def _variable(value: object) -> str:
    if not isinstance(value, str) or len(value) > 96 \
            or not _VARIABLE.fullmatch(value):
        raise TreatmentContractError("variable must be a declared identifier")
    return value


def _version(value: object) -> int:
    if type(value) is not int or value < 1:
        raise TreatmentContractError("expectedSceneVersion must be positive")
    return value


def _frame(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise TreatmentContractError(f"{label} must be a nonnegative frame")
    return value


def _scalar(value: object, label: str) -> object:
    if not isinstance(value, _SCALAR) or isinstance(value, float) \
            and not math.isfinite(value):
        raise TreatmentContractError(f"{label} must be a finite scalar")
    if isinstance(value, str) and len(value) > 4000:
        raise TreatmentContractError(f"{label} is too long")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise TreatmentContractError(f"{label} must be nonblank and <=1000 chars")
    return value


def _sfx(value: object, label: str) -> bool | str:
    if isinstance(value, bool):
        return value
    if not isinstance(value, str) or not value.strip() or len(value) > 96:
        raise TreatmentContractError(f"{label} must be boolean or a pack name")
    return value


def _transition(value: object, label: str) -> dict | None:
    if value is None:
        return None
    keys = {"id", "outFrame", "kind", "sfx"}
    if not isinstance(value, dict) or set(value) != keys:
        raise TreatmentContractError(f"{label} transition has invalid fields")
    _stable_id(value["id"], f"{label}.id")
    _frame(value["outFrame"], f"{label}.outFrame")
    if value["kind"] not in _TRANSITIONS:
        raise TreatmentContractError(f"{label}.kind is unsupported")
    _sfx(value["sfx"], f"{label}.sfx")
    return value


def _scene_action(row: dict, action: str) -> None:
    if action == "scene.add":
        validate_scene(row["scene"])
        return
    _stable_id(row["sceneId"], "sceneId")
    _version(row["expectedSceneVersion"])
    if action in {"scene.setVariable", "title.setText"}:
        _stable_id(row["elementId"], "elementId")
        _variable(row["variable"])
    if action == "scene.setVariable":
        _scalar(row["value"], "value")
        _scalar(row["expectedValue"], "expectedValue")
        return
    if action == "title.setText":
        _text(row["text"], "text")
        if not isinstance(row["expectedText"], str) \
                or len(row["expectedText"]) > 1000:
            raise TreatmentContractError("expectedText is invalid")
        return
    if action == "scene.move":
        start = _frame(row["startFrame"], "startFrame")
        end = _frame(row["endFrameExclusive"], "endFrameExclusive")
        if end <= start:
            raise TreatmentContractError("scene.move range must be nonempty")
        if not isinstance(row["timelineMapHash"], str) \
                or not _SHA256.fullmatch(row["timelineMapHash"]):
            raise TreatmentContractError("timelineMapHash is invalid")


def _other_action(row: dict, action: str) -> None:
    if action == "transition.set":
        ident = _stable_id(row["transitionId"], "transitionId")
        before = _transition(row["expectedValue"], "expectedValue")
        after = _transition(row["value"], "value")
        if after is None or after["id"] != ident \
                or before is not None and before["id"] != ident:
            raise TreatmentContractError("transition target/value IDs differ")
        return
    if action == "sfx.set":
        _stable_id(row["transitionId"], "transitionId")
        _sfx(row["expectedSfx"], "expectedSfx")
        _sfx(row["sfx"], "sfx")
        return
    if action == "grade.set":
        if row["expectedGrade"] not in _GRADES or row["grade"] not in _GRADES:
            raise TreatmentContractError("grade must be warm or none")


def validate_treatment_operation(value: object) -> dict:
    """Validate one exact action; unknown actions and fields fail closed."""
    if not isinstance(value, dict):
        raise TreatmentContractError("treatment operation must be an object")
    action = value.get("operation")
    keys = _KEYS.get(action)
    if keys is None:
        raise TreatmentContractError(f"unsupported treatment operation {action!r}")
    if set(value) != keys:
        missing, extras = sorted(keys - set(value)), sorted(set(value) - keys)
        raise TreatmentContractError(
            f"{action} fields differ (missing={missing}, extras={extras})")
    if value["schemaVersion"] != 1:
        raise TreatmentContractError("treatment schemaVersion must be 1")
    if action.startswith("scene.") or action == "title.setText":
        _scene_action(value, action)
    else:
        _other_action(value, action)
    return value
