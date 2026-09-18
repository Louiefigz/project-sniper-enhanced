"""Static and contract lint for project-scoped HyperFrames scene bundles."""
from __future__ import annotations

import os
import posixpath
import re

from graphics.scene_bundle import BundleSnapshot
from graphics.scene_bundle_manifest import (
    resolved_variable_values,
    validate_bundle_manifest,
    validate_variable_values,
)
from graphics.scene_contract import SceneContractError, validate_scene
from graphics.template_contract import composition_dimensions, declared_variables
from headless.safe_source_files import PinnedSourceRoot

_DENIED = (
    (re.compile(r"https?://|(?<!:)//[A-Za-z0-9]"), "remote URL"),
    (re.compile(r"\b(fetch|XMLHttpRequest|WebSocket|EventSource)\b"),
     "network API"),
    (re.compile(r"\b(eval|Function)\s*\(|\bimport\s*\("), "dynamic evaluation"),
    (re.compile(r"\b(require|process\.env|Deno\.env)\b"), "host/runtime access"),
    (re.compile(r"\b(localStorage|sessionStorage|indexedDB)\b"), "ambient storage"),
    (re.compile(r"\b(Date\.now|performance\.now|Math\.random)\s*\("),
     "nondeterministic clock/randomness"),
    (re.compile(r"\b(setInterval|Worker|SharedWorker|WebAssembly)\b"),
     "unbounded worker/runtime"),
    (re.compile(r"\brepeat\s*:\s*-1\b|\bwhile\s*\(\s*true\s*\)"),
     "infinite animation"),
)
_REQUIRED_SOURCE = (
    (re.compile(r'<script src="/vendor/gsap/gsap\.min\.js"></script>'),
     "pinned local GSAP"),
    (re.compile(r"gsap\.timeline\s*\(\s*\{\s*paused\s*:\s*true"),
     "paused GSAP timeline"),
    (re.compile(r"window\.__timelines\s*\["), "HyperFrames timeline registration"),
    (re.compile(r"window\.__sniperAnimationMap\s*="), "animation map"),
    (re.compile(r"root\.dataset\.duration"), "root duration authority"),
)
_PARTICLES = re.compile(r"\b(particle|sparkle|ember|flame|fire)\w*\b", re.I)
_SAFE_SHARED = {
    "/tokens.css", "/motion-tokens.js", "/vendor/gsap/gsap.min.js",
}
_ASSET_EXTENSIONS = {
    ".svg", ".png", ".jpg", ".jpeg", ".webp", ".woff", ".woff2",
    ".ttf", ".otf",
}
_RESOURCE = re.compile(r"""(?:src|href)\s*=\s*["']([^"']+)["']""")


def _fps_tuple(scene: dict) -> tuple[int, int]:
    value = scene["timing"]["fps"]
    return int(value["numerator"]), int(value["denominator"])


def _canvas_tuple(scene: dict) -> tuple[int, int]:
    value = scene["canvas"]
    return value["width"], value["height"]


def _supported(scene: dict, manifest: dict) -> list[str]:
    canvases = {(row["width"], row["height"])
                for row in manifest["supportedCanvases"]}
    rates = {(int(row["numerator"]), int(row["denominator"]))
             for row in manifest["supportedFps"]}
    errors = []
    if _canvas_tuple(scene) not in canvases:
        errors.append("scene canvas is outside the bundle support matrix")
    if _fps_tuple(scene) not in rates:
        errors.append("scene FPS is outside the bundle support matrix")
    return errors


def _entry_mapping(scene: dict, manifest: dict) -> list[str]:
    composition = scene["composition"]
    errors = []
    if composition["entry"] != manifest["fullEntry"]:
        errors.append("scene full entry does not match bundle.fullEntry")
    expected = manifest["unitEntries"]
    actual = {row["unitId"]: row["entry"] for row in scene["renderUnits"]}
    if actual != expected:
        errors.append("scene render-unit entries do not match bundle.unitEntries")
    return errors


def _variable_catalog_errors(html: str, manifest: dict, label: str,
                             expected_ids: set[str]) -> list[str]:
    try:
        declared = declared_variables(html)
    except (ValueError, TypeError) as exc:
        return [f"{label}: invalid variable catalog: {exc}"]
    expected = {row["id"]: row["type"] for row in manifest["variables"]
                if row["id"] in expected_ids}
    actual = {ident: row.get("type") for ident, row in declared.items()}
    if actual != expected:
        return [f"{label}: HTML variables do not match bundle manifest"]
    return []


def _resource_error(
    resource: str, bundle_files: set[str], label: str, entry_relative: str,
) -> str | None:
    if resource in _SAFE_SHARED:
        return None
    if resource.startswith("/"):
        resolved = resource.removeprefix("/")
        return (None if resolved in bundle_files
                else f"{label}: unsafe resource {resource!r}")
    if ".." in resource.split("/"):
        return f"{label}: unsafe resource {resource!r}"
    resolved = posixpath.normpath(posixpath.join(
        posixpath.dirname(entry_relative), resource))
    if resolved not in bundle_files:
        return f"{label}: missing bundle resource {resource!r}"
    return None


def _resource_errors(html: str, bundle_files: set[str], label: str,
                     entry_relative: str) -> list[str]:
    errors = []
    for resource in _RESOURCE.findall(html):
        error = _resource_error(resource, bundle_files, label, entry_relative)
        if error:
            errors.append(error)
    return errors


def _source_errors(html: str, label: str) -> list[str]:
    errors = []
    for pattern, reason in _DENIED:
        if pattern.search(html):
            errors.append(f"{label}: forbidden {reason}")
    for pattern, requirement in _REQUIRED_SOURCE:
        if pattern.search(html) is None:
            errors.append(f"{label}: missing {requirement}")
    if "data-duration=" not in html:
        errors.append(f"{label}: root data-duration is required")
    if _PARTICLES.search(html) and (
            "seededRandom" not in html or "vars.seed" not in html):
        errors.append(f"{label}: particles require vars.seed + seededRandom")
    return errors


def _entry_errors(snapshot: BundleSnapshot, relative: str, scene: dict,
                  expected_variables: set[str]) -> list[str]:
    label = f"bundle entry {relative}"
    with PinnedSourceRoot(snapshot.path) as source:
        try:
            raw = source.read(relative)
        except (OSError, RuntimeError) as exc:
            return [f"{label}: unreadable: {exc}"]
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{label}: HTML must be UTF-8"]
    errors = _source_errors(html, label)
    errors.extend(_resource_errors(
        html, {row["path"] for row in snapshot.files}, label, relative))
    errors.extend(_variable_catalog_errors(
        html, snapshot.manifest, label, expected_variables))
    try:
        dimensions = composition_dimensions(html)
    except ValueError as exc:
        errors.append(f"{label}: {exc}")
    else:
        if dimensions != _canvas_tuple(scene):
            errors.append(f"{label}: canvas {dimensions} != scene canvas")
    return errors


def _element_values(scene: dict) -> list[tuple[str, str, object]]:
    return [
        (element["elementId"], key, value)
        for element in scene["elements"]
        for key, value in element["values"].items()
    ]


def _variable_ownership_errors(scene: dict, manifest: dict) -> list[str]:
    owners: dict[str, set[str]] = {}
    values: dict[str, object] = {}
    for element_id, key, value in _element_values(scene):
        owners.setdefault(key, set()).add(element_id)
        if key in values and values[key] != value:
            return [f"shared scene variable {key} has conflicting values"]
        values[key] = value
    declared = {row["id"]: set(row["elementIds"])
                for row in manifest["variables"]}
    if owners != declared:
        return ["bundle variable ownership does not match scene elements"]
    try:
        resolved = resolved_variable_values(
            scene["composition"]["variables"], manifest)
    except SceneContractError as exc:
        return [str(exc)]
    if resolved != values:
        return ["scene composition variables do not match element values"]
    return []


def _variables_for(manifest: dict, element_ids: set[str]) -> set[str]:
    return {row["id"] for row in manifest["variables"]
            if element_ids.intersection(row["elementIds"])}


def _script_closure_errors(
    source: PinnedSourceRoot, row: dict,
) -> list[str]:
    if not row["path"].endswith(".js"):
        return []
    label = f"bundle script {row['path']}"
    try:
        text = source.read(row["path"]).decode("utf-8")
    except (RuntimeError, UnicodeDecodeError) as exc:
        return [f"{label}: unreadable: {exc}"]
    errors = [
        f"{label}: forbidden {reason}"
        for pattern, reason in _DENIED if pattern.search(text)
    ]
    if _PARTICLES.search(text) and (
            "seededRandom" not in text or "vars.seed" not in text):
        errors.append(f"{label}: particles require deterministic seed")
    return errors


def _closure_errors(snapshot: BundleSnapshot) -> list[str]:
    errors = []
    with PinnedSourceRoot(snapshot.path) as source:
        for row in snapshot.files:
            errors.extend(_script_closure_errors(source, row))
        source.assert_current()
    return errors


def _asset_binding_errors(scene: dict, snapshot: BundleSnapshot) -> list[str]:
    errors = []
    files = snapshot.files
    for dependency in scene["dependencies"]:
        if dependency["kind"] != "asset":
            continue
        matches = [row for row in files
                   if row["sha256"] == dependency["sha256"]
                   and os.path.splitext(row["path"])[1].lower()
                   in _ASSET_EXTENSIONS]
        if len(matches) != 1:
            errors.append(
                f"scene asset {dependency['id']} must bind exactly one "
                "immutable bundle media member")
    return errors


def scene_bundle_errors(scene_value: object,
                        snapshot: BundleSnapshot) -> list[str]:
    """Return every static/runtime-closure mismatch for a project scene."""
    try:
        scene = validate_scene(scene_value)
        manifest = validate_bundle_manifest(snapshot.manifest)
    except SceneContractError as exc:
        return [str(exc)]
    composition = scene["composition"]
    if composition["type"] != "project":
        return ["scene bundle lint requires composition.type=project"]
    errors = []
    if composition["bundleId"] != manifest["bundleId"] \
            or composition["bundleHash"] != snapshot.digest:
        errors.append("scene does not bind this exact bundle generation")
    errors.extend(_supported(scene, manifest))
    errors.extend(_entry_mapping(scene, manifest))
    try:
        validate_variable_values(composition["variables"], manifest)
    except SceneContractError as exc:
        errors.append(str(exc))
    errors.extend(_variable_ownership_errors(scene, manifest))
    scene_assets = {row["id"] for row in scene["dependencies"]
                    if row["kind"] == "asset"}
    if scene_assets != set(manifest["assetIds"]):
        errors.append("scene asset dependencies do not match bundle.assetIds")
    errors.extend(_asset_binding_errors(scene, snapshot))
    errors.extend(_closure_errors(snapshot))
    all_elements = {row["elementId"] for row in scene["elements"]}
    errors.extend(_entry_errors(
        snapshot, manifest["fullEntry"], scene,
        _variables_for(manifest, all_elements)))
    for unit in scene["renderUnits"]:
        relative = manifest["unitEntries"][unit["unitId"]]
        errors.extend(_entry_errors(
            snapshot, relative, scene,
            _variables_for(manifest, set(unit["elementIds"]))))
    return errors


def validate_scene_bundle(scene: object, snapshot: BundleSnapshot) -> dict:
    """Raise unless the scene and exact bundle form a closed render input."""
    errors = scene_bundle_errors(scene, snapshot)
    if errors:
        raise SceneContractError("; ".join(errors))
    return validate_scene(scene)
