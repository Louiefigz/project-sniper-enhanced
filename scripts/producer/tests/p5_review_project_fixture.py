"""Actual 14-minute/50-scene authority for the P5 review cohort."""
from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path

from graphics.scene_package_contract import load_scene_package
from tests.p4_exit_media import file_identity, probe, write_canonical
from tests.scene_fixtures import bind_test_scene_source

_DURATION_FRAMES = 25_200
_SCENE_COUNT = 50
_TARGET_ID = "scene-045"


@dataclass(frozen=True)
class ProjectAuthorities:
    """Create-once paths plus path-free measured project evidence."""

    previous_path: Path
    current_path: Path
    evidence: dict


def _scene_copy(scene: dict, index: int) -> dict:
    value = copy.deepcopy(scene)
    identity = f"scene-{index:03d}"
    start = index * 500
    value["sceneId"] = identity
    value["version"] = 1
    value["timing"].update({
        "startFrame": start,
        "endFrameExclusive": start + 180,
        "timelineMapHash": hashlib.sha256(identity.encode()).hexdigest(),
    })
    value["provenance"]["requestId"] = f"request-{identity}"
    return bind_test_scene_source(value)


def _row(scene: dict, package_hash: str) -> dict:
    timing = scene["timing"]
    return {
        "sceneId": scene["sceneId"], "packageHash": package_hash,
        "sceneVersion": scene["version"],
        "startFrame": timing["startFrame"],
        "endFrameExclusive": timing["endFrameExclusive"],
    }


def _other_rows(context: object, source_scene: dict) -> list[dict]:
    directory = context.root / "project-scene-packages"
    directory.mkdir()
    rows = []
    for index in range(_SCENE_COUNT):
        if f"scene-{index:03d}" == _TARGET_ID:
            continue
        scene = _scene_copy(source_scene, index)
        path = directory / f"scene-{index:03d}.json"
        write_canonical(path, {
            "schemaVersion": 1, "scene": scene,
            "publicationContext": {
                "use": "commercial", "platform": "youtube",
                "evaluatedAt": "2026-07-30T12:00:00Z",
            },
            "assets": [],
            "readability": {
                "required": False, "sourceSha256": None, "receipt": None,
            },
        })
        resolved = load_scene_package(
            str(path.resolve()), str(context.store))
        rows.append(_row(resolved.scene, resolved.package_hash))
    return rows


def _target_rows(context: object) -> tuple[dict, dict]:
    previous = load_scene_package(
        str((context.root / "review-initial-package.json").resolve()),
        str(context.store))
    current = load_scene_package(
        str((context.root / "review-current-package.json").resolve()),
        str(context.store))
    return (
        _row(previous.scene, previous.package_hash),
        _row(current.scene, current.package_hash),
    )


def _base(path: Path) -> tuple[dict, dict]:
    identity, facts = file_identity(path), probe(path)
    authority = {
        "sha256": identity["sha256"],
        "durationFrames": _DURATION_FRAMES,
        "fps": {"numerator": 30, "denominator": 1},
        "width": 1920, "height": 1080, "sampleRate": 48_000,
    }
    expected = {
        "decodedFrames": _DURATION_FRAMES, "frameRate": "30/1",
        "width": 1920, "height": 1080, "pixelFormat": "yuv420p",
        "audio": {"sampleRate": 48_000, "channels": 2},
    }
    if facts != expected:
        raise RuntimeError("LF-14 project base media facts are not exact")
    return authority, facts


def build_project_authorities(
    context: object, previous_scene: dict,
    current_scene: dict, base_path: Path,
) -> ProjectAuthorities:
    """Create 50 validated scene packages and one exact project revision."""
    rows = _other_rows(context, previous_scene)
    previous_target, current_target = _target_rows(context)
    rows.append(previous_target)
    rows.sort(key=lambda row: (
        row["startFrame"], row["endFrameExclusive"], row["sceneId"]))
    base, facts = _base(base_path)
    previous = {
        "schemaVersion": 1, "projectId": "project-p5-lf14",
        "base": base, "scenes": rows,
    }
    current = copy.deepcopy(previous)
    target = next(
        row for row in current["scenes"] if row["sceneId"] == _TARGET_ID)
    target.update(current_target)
    previous_path = context.root / "previous-project-authority.json"
    current_path = context.root / "current-project-authority.json"
    write_canonical(previous_path, previous)
    write_canonical(current_path, current)
    evidence = {
        "durationSeconds": 840,
        "durationFrames": _DURATION_FRAMES,
        "sceneCount": len(rows),
        "validatedPackageCount": len(rows),
        "baseDecode": facts,
        "targetSceneId": current_scene["sceneId"],
    }
    return ProjectAuthorities(previous_path, current_path, evidence)
