"""Content-addressed rendering for proved project-scoped scene bundles."""
from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from graphics.animation_map import (
    animation_map_digest,
    filmstrip_frames,
    parse_animation_map,
    validate_animation_map,
)
from graphics.asset_proof import AssetProofRequest, prove_rendered_asset
from graphics.graphics_render import PIPELINE_ROOT
from graphics.render_cache import CacheRequest, materialize
from graphics.render_tools import live_tools_identity
from graphics.scene_bundle import BundleSnapshot
from graphics.scene_bundle_manifest import resolved_variable_values
from graphics.scene_contract import (
    SceneContractError,
    canonical_json,
    validate_scene,
)
from graphics.scene_executor import (
    SceneExecution, assert_scene_container_version, assert_scene_runtime_identity, execute_scene,
    scene_runtime_identity,
)
from graphics.scene_lint import validate_scene_bundle
from graphics.render_rate import normalize_render_rate
from graphics.template_contract import declared_variables
from headless.container_renderer import cache_identity as container_cache_identity
from headless.runtime_receipt import bind_runtime_receipt
from headless.safe_source_files import PinnedSourceRoot


@dataclass(frozen=True)
class SceneRenderRequest:
    """All authority needed to render one scene or independently proved unit."""

    scene: dict
    bundle: BundleSnapshot
    cache_dir: str
    unit_id: str | None = None


@dataclass(frozen=True)
class _PreparedScene:
    """Resolved immutable inputs shared by render and proof callbacks."""

    unit: dict | None
    relative: str
    html: str
    events: list[dict]
    key: str
    fmt: str
    extension: str
    runtime_identity: bytes | None


def _unit(scene: dict, unit_id: str | None) -> dict | None:
    if unit_id is None:
        return None
    matches = [row for row in scene["renderUnits"] if row["unitId"] == unit_id]
    if len(matches) != 1:
        raise SceneContractError(f"render unit {unit_id!r} did not resolve once")
    return matches[0]


def _entry(scene: dict, bundle: BundleSnapshot,
           unit: dict | None) -> str:
    return (bundle.manifest["fullEntry"] if unit is None
            else bundle.manifest["unitEntries"][unit["unitId"]])


def _format(scene: dict, unit: dict | None) -> tuple[str, str]:
    if unit is not None or scene["renderMode"] != "takeover-opaque":
        return "mov", "mov"
    return "mp4", "mp4"


def _duration(scene: dict) -> tuple[int, float, float, str]:
    timing = scene["timing"]
    frame_count = timing["endFrameExclusive"] - timing["startFrame"]
    rate = normalize_render_rate(timing["fps"])
    return frame_count, frame_count / rate.numeric, rate.numeric, rate.token


def _entry_html(bundle: BundleSnapshot, relative: str) -> str:
    with PinnedSourceRoot(bundle.path) as source:
        raw = source.read(relative)
        source.assert_current()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SceneContractError("scene entry is not UTF-8") from exc


def _asset_bindings(scene: dict) -> tuple[dict, ...]:
    return tuple({
        "field": row["kind"], "selector": row["id"], "sha256": row["sha256"],
    } for row in scene["dependencies"])


def _local_timing(scene: dict) -> dict:
    timing = scene["timing"]
    return {
        "durationFrames": (
            timing["endFrameExclusive"] - timing["startFrame"]),
        "fps": timing["fps"],
    }


def _media_identity(scene: dict, bundle: BundleSnapshot,
                    unit: dict | None) -> dict:
    element_ids = ({row["elementId"] for row in scene["elements"]}
                   if unit is None else set(unit["elementIds"]))
    variables = resolved_variable_values(
        scene["composition"]["variables"], bundle.manifest)
    owned = {row["id"] for row in bundle.manifest["variables"]
             if element_ids.intersection(row["elementIds"])}
    return {
        "sceneId": scene["sceneId"], "timing": _local_timing(scene),
        "canvas": scene["canvas"], "renderMode": scene["renderMode"],
        "bundleHash": bundle.digest, "entry": _entry(scene, bundle, unit),
        "unit": unit, "variables": {
            key: variables[key] for key in sorted(owned)},
        "elements": [row for row in scene["elements"]
                     if row["elementId"] in element_ids],
        "dependencies": scene["dependencies"],
    }


def _key(scene: dict, bundle: BundleSnapshot, unit: dict | None,
         events: list[dict]) -> tuple[str, bytes | None]:
    """Bind local installed runtime bytes without changing sealed cache shape."""
    sealed = bool(os.environ.get("SNIPER_RENDER_IMAGE_ID"))
    if sealed:
        assert_scene_container_version(bundle)
    runtime_identity = None if sealed else scene_runtime_identity(bundle)
    tool_identity = (container_cache_identity(PIPELINE_ROOT)
                     if sealed
                     else live_tools_identity())
    payload = {
        "sceneIdentity": _media_identity(scene, bundle, unit),
        "bundleHash": bundle.digest,
        "unitId": None if unit is None else unit["unitId"],
        "animationMapHash": animation_map_digest(scene, events),
        "toolIdentity": tool_identity.hex(),
        **({"liveRuntimeIdentity": runtime_identity.hex()}
           if runtime_identity is not None else {}),
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest(), runtime_identity


def _proof_request(path: str, scene: dict,
                   prepared: _PreparedScene) -> AssetProofRequest:
    frames, duration, fps, token = _duration(scene)
    del token
    del frames
    composition = scene["composition"]
    entry = {
        "kind": f"project-{scene['sceneId']}", "spec": composition["variables"],
        "anchor": ("own-screen" if scene["renderMode"] == "takeover-opaque"
                   else "free-band"),
    }
    canvas = scene["canvas"]
    return AssetProofRequest(
        path, entry, prepared.fmt, (canvas["width"], canvas["height"]),
        duration, prepared.key, expected_fps=fps, comp_html=prepared.html,
        require_terminal_clear=False,
        sealed_asset_inputs=_asset_bindings(scene))


def _render_candidate(request: SceneRenderRequest, prepared: _PreparedScene,
                      output: str) -> None:
    """Carry the cache-selected live runtime into the actual executor."""
    _, duration, fps, token = _duration(request.scene)
    del fps
    resolved = resolved_variable_values(
        request.scene["composition"]["variables"], request.bundle.manifest)
    declared = set(declared_variables(prepared.html))
    variables = {key: value for key, value in resolved.items()
                 if key in declared}
    execute_scene(SceneExecution(
        request.bundle, prepared.relative, prepared.html, prepared.fmt,
        variables, output, token, duration, request.cache_dir,
        _asset_bindings(request.scene), prepared.runtime_identity))


def _prove(path: str, scene: dict, prepared: _PreparedScene) -> dict:
    proof = prove_rendered_asset(_proof_request(path, scene, prepared))
    return (bind_runtime_receipt(path, proof)
            if os.environ.get("SNIPER_RENDER_IMAGE_ID") else proof)


def _prepare(scene: dict, bundle: BundleSnapshot,
             unit: dict | None) -> _PreparedScene:
    """Resolve scene metadata and runtime identity before entering the cache."""
    relative = _entry(scene, bundle, unit)
    html = _entry_html(bundle, relative)
    events = validate_animation_map(scene, parse_animation_map(html))
    key, runtime_identity = _key(scene, bundle, unit, events)
    fmt, extension = _format(scene, unit)
    return _PreparedScene(unit, relative, html, events, key, fmt, extension,
                          runtime_identity)


def render_scene(request: SceneRenderRequest) -> dict:
    """Render and prove one full scene or independently addressable unit."""
    scene = validate_scene(request.scene)
    validate_scene_bundle(scene, request.bundle)
    unit = _unit(scene, request.unit_id)
    prepared = _prepare(scene, request.bundle, unit)
    os.makedirs(request.cache_dir, mode=0o700, exist_ok=True)
    cache_request = CacheRequest(
        request.cache_dir, prepared.key, prepared.extension)
    output, cached, proof = materialize(
        cache_request,
        lambda path: _render_candidate(request, prepared, path),
        lambda path: _prove(path, scene, prepared))
    assert_scene_runtime_identity(request.bundle, prepared.runtime_identity)
    if prepared.runtime_identity is None:
        assert_scene_container_version(request.bundle)
    return {
        "schemaVersion": 1, "sceneId": scene["sceneId"],
        "sceneVersion": scene["version"],
        "unitId": None if unit is None else unit["unitId"],
        "path": output, "cached": cached, "renderKey": prepared.key,
        "proof": proof,
        "animationMapHash": animation_map_digest(scene, prepared.events),
        "filmstripFrames": list(filmstrip_frames(scene, prepared.events)),
    }


def render_scene_units(scene: dict, bundle: BundleSnapshot, cache_dir: str,
                       workers: int = 2) -> list[dict]:
    """Render in z-order, keeping serial work on the caller's deadline thread."""
    valid = validate_scene(scene)
    if type(workers) is not int or not 1 <= workers <= 4:
        raise SceneContractError("scene render workers must be within 1..4")
    unit_ids = [row["unitId"] for row in sorted(
        valid["renderUnits"], key=lambda row: row["zIndex"])]
    if workers == 1:
        return [render_scene(SceneRenderRequest(valid, bundle, cache_dir, unit_id))
                for unit_id in unit_ids]
    with ThreadPoolExecutor(max_workers=min(workers, len(unit_ids))) as pool:
        results = list(pool.map(
            lambda unit_id: render_scene(
                SceneRenderRequest(valid, bundle, cache_dir, unit_id)),
            unit_ids))
    return results
