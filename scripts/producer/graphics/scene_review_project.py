"""Closed project authority for graph-wide private scene review fanout."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from graphics.scene_contract import SceneContractError, canonical_json

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_PROJECT_KEYS = {"schemaVersion", "projectId", "base", "scenes"}
_BASE_KEYS = {
    "sha256", "durationFrames", "fps", "width", "height", "sampleRate",
}
_SCENE_KEYS = {
    "sceneId", "packageHash", "sceneVersion",
    "startFrame", "endFrameExclusive",
}


@dataclass(frozen=True)
class SceneProjectRevisionRequest:
    """Authorities needed to prove one changed scene across a full project."""

    previous: dict
    current: dict
    previous_package_hash: str
    current_package_hash: str
    previous_scene: dict
    target_scene: dict
    base_identity: dict
    sample_rate: int


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _positive(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise SceneContractError(f"{label} must be a positive integer")
    return value


def _rate(value: object, label: str) -> dict:
    if not isinstance(value, dict) \
            or set(value) != {"numerator", "denominator"}:
        raise SceneContractError(f"{label} frame rate is invalid")
    return {
        "numerator": _positive(value["numerator"], f"{label} numerator"),
        "denominator": _positive(
            value["denominator"], f"{label} denominator"),
    }


def _base(value: object, label: str) -> dict:
    if not isinstance(value, dict) or set(value) != _BASE_KEYS:
        raise SceneContractError(f"{label} base authority is invalid")
    if not isinstance(value["sha256"], str) \
            or not _DIGEST.fullmatch(value["sha256"]):
        raise SceneContractError(f"{label} base digest is invalid")
    result = {
        "sha256": value["sha256"],
        "durationFrames": _positive(
            value["durationFrames"], f"{label} duration"),
        "fps": _rate(value["fps"], label),
        "width": _positive(value["width"], f"{label} width"),
        "height": _positive(value["height"], f"{label} height"),
        "sampleRate": _positive(
            value["sampleRate"], f"{label} sample rate"),
    }
    return result


def _scene(value: object, duration: int, label: str) -> dict:
    if not isinstance(value, dict) or set(value) != _SCENE_KEYS:
        raise SceneContractError(f"{label} scene row is invalid")
    identity, digest = value["sceneId"], value["packageHash"]
    if not isinstance(identity, str) or not _IDENTITY.fullmatch(identity) \
            or not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise SceneContractError(f"{label} scene identity is invalid")
    start, end = value["startFrame"], value["endFrameExclusive"]
    version = value["sceneVersion"]
    valid = (
        type(start) is int and type(end) is int
        and 0 <= start < end <= duration
        and type(version) is int and version > 0
    )
    if not valid:
        raise SceneContractError(f"{label} scene timing/version is invalid")
    return dict(value)


def _project(value: object, label: str) -> dict:
    if not isinstance(value, dict) or set(value) != _PROJECT_KEYS \
            or value.get("schemaVersion") != 1:
        raise SceneContractError(f"{label} project authority is invalid")
    project_id = value["projectId"]
    if not isinstance(project_id, str) or not _IDENTITY.fullmatch(project_id):
        raise SceneContractError(f"{label} project identity is invalid")
    base = _base(value["base"], label)
    rows = value["scenes"]
    if not isinstance(rows, list) or not rows:
        raise SceneContractError(f"{label} scene set is empty")
    scenes = [
        _scene(row, base["durationFrames"], label)
        for row in rows
    ]
    identities = [row["sceneId"] for row in scenes]
    ordering = [
        (row["startFrame"], row["endFrameExclusive"], row["sceneId"])
        for row in scenes
    ]
    if len(identities) != len(set(identities)) or ordering != sorted(ordering):
        raise SceneContractError(
            f"{label} scenes must be unique and timeline ordered")
    return {
        "schemaVersion": 1, "projectId": project_id,
        "base": base, "scenes": scenes,
    }


def _same_scene_structure(before: dict, after: dict) -> bool:
    keys = _SCENE_KEYS - {"packageHash", "sceneVersion"}
    return all(before[key] == after[key] for key in keys)


def _target_row(project: dict, scene_id: str) -> dict:
    matches = [
        row for row in project["scenes"] if row["sceneId"] == scene_id
    ]
    if len(matches) != 1:
        raise SceneContractError(
            "scene review target is absent or ambiguous in project authority")
    return matches[0]


def _scene_fanout(previous: dict, current: dict) -> tuple[list[str], list[str]]:
    if len(previous["scenes"]) != len(current["scenes"]):
        raise SceneContractError("scene review changed the project scene count")
    dirty, reused = [], []
    for before, after in zip(previous["scenes"], current["scenes"]):
        if not _same_scene_structure(before, after):
            raise SceneContractError(
                "scene review changed unrelated project structure or timing")
        changed = before != after
        (dirty if changed else reused).append(after["sceneId"])
    return dirty, reused


def _target_binding(
    request: SceneProjectRevisionRequest,
    previous_target: dict,
    current_target: dict,
    current_base: dict,
) -> bool:
    scene = request.target_scene
    previous_scene = request.previous_scene
    timing, fps = scene["timing"], scene["timing"]["fps"]
    expected = (
        request.previous_package_hash, request.current_package_hash,
        previous_scene["version"], scene["version"],
        timing["startFrame"], timing["endFrameExclusive"],
        int(fps["numerator"]), int(fps["denominator"]),
        scene["canvas"]["width"], scene["canvas"]["height"],
        request.sample_rate,
    )
    actual = (
        previous_target["packageHash"], current_target["packageHash"],
        previous_target["sceneVersion"], current_target["sceneVersion"],
        current_target["startFrame"], current_target["endFrameExclusive"],
        current_base["fps"]["numerator"], current_base["fps"]["denominator"],
        current_base["width"], current_base["height"],
        current_base["sampleRate"],
    )
    return (
        current_target["sceneVersion"] == previous_target["sceneVersion"] + 1
        and actual == expected
    )


def validate_project_revision(request: SceneProjectRevisionRequest) -> dict:
    """Prove exactly one package revision and return closed project fanout."""
    previous = _project(request.previous, "previous")
    current = _project(request.current, "current")
    scene = request.target_scene
    stable = (
        previous["projectId"] == current["projectId"]
        and previous["base"] == current["base"]
        and current["base"]["sha256"] == request.base_identity.get("sha256")
    )
    if not stable:
        raise SceneContractError(
            "scene review changed project or approved base authority")
    target_id = scene["sceneId"]
    before_target = _target_row(previous, target_id)
    after_target = _target_row(current, target_id)
    dirty, reused = _scene_fanout(previous, current)
    if dirty != [target_id] or not _target_binding(
            request, before_target, after_target, current["base"]):
        raise SceneContractError(
            "project authority does not bind exactly the repaired scene")
    return {
        "projectId": current["projectId"],
        "previousProjectHash": _hash(previous),
        "currentProjectHash": _hash(current),
        "durationFrames": current["base"]["durationFrames"],
        "fps": current["base"]["fps"],
        "sceneCount": len(current["scenes"]),
        "dirtySceneIds": dirty, "reusedSceneIds": reused,
        "dirtySceneCount": len(dirty), "reusedSceneCount": len(reused),
        "baseSha256": current["base"]["sha256"],
    }
