"""Production admission, rendering, and Palmier projection for ScenePackageV1."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from graphics.scene_catalog import render_catalog_scene
from graphics.scene_bundle import capture_bundle
from graphics.scene_contract import SceneContractError, canonical_json
from graphics.scene_package_assets import admit_package_assets
from graphics.scene_package_contract import (
    ResolvedScenePackage,
    admission_receipt,
)
from graphics.scene_render import (
    SceneRenderRequest,
    render_scene,
    render_scene_units,
)
from palmier.scene_binding_reader import read_scene_bindings
from palmier.scene_bindings import SceneBindingInput, build_scene_bindings


@dataclass(frozen=True)
class ScenePackageRenderRequest:
    """All explicit mutable locations and bounded concurrency for one render."""

    resolved: ResolvedScenePackage
    cache_dir: str
    snapshot_store: str | None = None
    workers: int = 2


def _canonical_directory(path: object, label: str) -> str:
    valid = isinstance(path, str) and os.path.isabs(path) \
        and os.path.normpath(path) == path and os.path.realpath(path) == path
    if not valid or os.path.islink(path) or not os.path.isdir(path):
        raise SceneContractError(f"{label} must be a canonical real directory")
    return path


def admit_scene_package(resolved: ResolvedScenePackage,
                        snapshot_store: str | None) -> dict:
    """Run every non-render admission and return one canonical receipt."""
    assets = admit_package_assets(resolved, snapshot_store)
    return admission_receipt(resolved, assets)


def _project_receipts(request: ScenePackageRenderRequest) -> list[dict]:
    bundle = request.resolved.bundle
    if bundle is None:
        raise SceneContractError("project scene package lacks its exact bundle")
    fresh = capture_bundle(bundle.path)
    if fresh.digest != bundle.digest or fresh.files != bundle.files:
        raise SceneContractError(
            "project bundle changed after package resolution")
    scene = request.resolved.scene
    modes = {row["palmierGranularity"] for row in scene["renderUnits"]}
    if modes == {"scene"}:
        receipts = [render_scene(SceneRenderRequest(
            scene, fresh, request.cache_dir))]
    elif modes == {"unit"}:
        receipts = render_scene_units(
            scene, fresh, request.cache_dir, request.workers)
    else:
        raise SceneContractError(
            "mixed Palmier scene granularity is unsupported")
    after = capture_bundle(bundle.path)
    if after.digest != fresh.digest or after.files != fresh.files:
        raise SceneContractError("project bundle changed during render")
    return receipts


def _render_receipts(request: ScenePackageRenderRequest) -> list[dict]:
    scene = request.resolved.scene
    if scene["composition"]["type"] == "project":
        return _project_receipts(request)
    modes = {row["palmierGranularity"] for row in scene["renderUnits"]}
    if modes != {"scene"}:
        raise SceneContractError(
            "catalog rendering supports full-scene Palmier granularity only")
    return [render_catalog_scene(scene, request.cache_dir)]


def _palmier_readback(scene: dict, receipts: list[dict]) -> dict:
    bindings = build_scene_bindings(
        SceneBindingInput(scene, tuple(receipts)))
    frozen = json.loads(canonical_json(bindings))
    return read_scene_bindings(frozen, scene)


def _assert_source_receipts(resolved: ResolvedScenePackage,
                            receipts: list[dict]) -> None:
    if resolved.scene["composition"]["type"] != "catalog":
        return
    expected = resolved.source_contract
    if len(receipts) != 1 or any(
            receipts[0].get(key) != expected[key]
            for key in ("catalogSourceHash", "motionContractHash")):
        raise SceneContractError(
            "catalog render receipt differs from admitted source contract")


def render_scene_package(request: ScenePackageRenderRequest) -> dict:
    """Admit, render, prove, project, and read back one exact scene package."""
    if type(request.workers) is not int or not 1 <= request.workers <= 4:
        raise SceneContractError("scene package workers must be within 1..4")
    _canonical_directory(request.cache_dir, "scene render cache")
    admission = admit_scene_package(
        request.resolved, request.snapshot_store)
    receipts = _render_receipts(request)
    _assert_source_receipts(request.resolved, receipts)
    bindings = _palmier_readback(request.resolved.scene, receipts)
    value = {
        "schemaVersion": 1, "kind": "scene-package-render",
        "packageHash": request.resolved.package_hash,
        "sceneId": request.resolved.scene["sceneId"],
        "sceneVersion": request.resolved.scene["version"],
        "admission": admission, "renderReceipts": receipts,
        "palmierBindings": bindings,
        "checks": [
            "package-admission", "proved-render-media",
            "palmier-projection", "palmier-readback",
        ],
    }
    return {**value, "receiptHash": hashlib.sha256(
        canonical_json(value)).hexdigest()}
