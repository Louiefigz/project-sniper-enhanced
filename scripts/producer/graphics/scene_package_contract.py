"""Strict package-reference resolution and measured-QC binding for scenes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime

from contracts.schema_validator import (
    SchemaValidationError,
    validate_document,
)
from graphics.scene_bundle import BundleSnapshot, resolve_bundle
from graphics.scene_catalog import catalog_scene_contract
from graphics.scene_contract import (
    SceneContractError,
    canonical_json,
    scene_hash,
    validate_scene,
)
from graphics.scene_lint import validate_scene_bundle

_ZONE = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$")
_MAX_JSON_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class ResolvedScenePackage:
    """One schema-valid scene bound to its exact source generation and QC."""

    package: dict
    scene: dict
    package_hash: str
    source_contract: dict
    bundle: BundleSnapshot | None
    readability_hash: str | None


def _canonical_directory(path: object, label: str) -> str:
    if not isinstance(path, str) or not os.path.isabs(path) \
            or os.path.normpath(path) != path or os.path.realpath(path) != path \
            or os.path.islink(path) or not os.path.isdir(path):
        raise SceneContractError(f"{label} must be a canonical real directory")
    return path


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
        value.st_uid, value.st_size, value.st_mtime_ns, value.st_ctime_ns,
    )


def read_regular_json(path: object, label: str) -> dict:
    """Read one stable, canonical, owned, bounded JSON object without links."""
    if not isinstance(path, str) or not os.path.isabs(path) \
            or os.path.normpath(path) != path or os.path.realpath(path) != path:
        raise SceneContractError(
            f"{label} path must be canonical and absolute")
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise SceneContractError(f"{label} could not be opened safely") from exc
    try:
        before = os.fstat(fd)
        valid = stat.S_ISREG(before.st_mode) and before.st_nlink == 1 \
            and before.st_uid == os.geteuid() \
            and 0 < before.st_size <= _MAX_JSON_BYTES
        if not valid:
            raise SceneContractError(
                f"{label} must be one owned bounded regular file")
        with os.fdopen(fd, encoding="utf-8") as handle:
            fd = -1
            value = json.load(handle)
            after = os.fstat(handle.fileno())
        if _identity(before) != _identity(after) \
                or _identity(after) != _identity(
                    os.stat(path, follow_symlinks=False)):
            raise SceneContractError(f"{label} changed while being read")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SceneContractError(f"{label} is invalid JSON") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(value, dict):
        raise SceneContractError(f"{label} must contain a JSON object")
    return value


def _readability(package: dict, scene: dict) -> str | None:
    value = package["readability"]
    required = value["required"]
    source_hash, receipt = value["sourceSha256"], value["receipt"]
    if (source_hash is None) != (receipt is None) \
            or required and receipt is None:
        raise SceneContractError("scene readability evidence is incomplete")
    if receipt is None:
        return None
    if receipt["sourceSha256"] != source_hash \
            or receipt["sourceFps"] != scene["timing"]["fps"] \
            or receipt["frameRange"] != {
                "startFrame": scene["timing"]["startFrame"],
                "endFrameExclusive": scene["timing"]["endFrameExclusive"]}:
        raise SceneContractError(
            "readability receipt binds different source/timing authority")
    samples = receipt["sampleFrames"]
    start, end = (receipt["frameRange"]["startFrame"],
                  receipt["frameRange"]["endFrameExclusive"])
    if samples != sorted(set(samples)) \
            or any(not start <= frame < end for frame in samples) \
            or receipt["samplePixelCount"] != len(samples) * 64:
        raise SceneContractError("readability samples do not bind the interval")
    x, y, width, height = receipt["textBoxPixels"]
    if width <= 0 or height <= 0 \
            or x + width > scene["canvas"]["width"] \
            or y + height > scene["canvas"]["height"]:
        raise SceneContractError("readability text box leaves the scene canvas")
    if receipt["minimumContrast"] + 1e-9 < receipt["requiredContrast"]:
        raise SceneContractError("readability verdict contradicts its measurement")
    return hashlib.sha256(canonical_json(receipt)).hexdigest()


def _publication(package: dict) -> None:
    value = package["publicationContext"]["evaluatedAt"]
    if not isinstance(value, str) or _ZONE.search(value) is None:
        raise SceneContractError(
            "publication evaluatedAt must be RFC3339 with a timezone")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise SceneContractError(
            "publication evaluatedAt is invalid") from exc
    if parsed.tzinfo is None:
        raise SceneContractError(
            "publication evaluatedAt must include a timezone")


def _project_source(scene: dict, store: str) -> tuple[dict, BundleSnapshot]:
    composition = scene["composition"]
    bundle = resolve_bundle(
        store, composition["bundleId"], composition["bundleHash"])
    validate_scene_bundle(scene, bundle)
    file_set_hash = hashlib.sha256(canonical_json(
        list(bundle.files))).hexdigest()
    return {
        "type": "project", "bundleId": composition["bundleId"],
        "bundleHash": bundle.digest, "bundleFileSetHash": file_set_hash,
        "bundleFiles": list(bundle.files),
    }, bundle


def _catalog_source(scene: dict) -> dict:
    return {"type": "catalog", **catalog_scene_contract(scene)}


def resolve_scene_package(value: object,
                          bundle_store: str | None) -> ResolvedScenePackage:
    """Resolve exact catalog/project authority; CURRENT is never consulted."""
    try:
        package = validate_document("scene-package-v1.schema.json", value)
    except SchemaValidationError as exc:
        raise SceneContractError(f"scene package schema failed: {exc}") from exc
    scene = validate_scene(package["scene"])
    _publication(package)
    if scene["composition"]["type"] == "project":
        if bundle_store is None:
            raise SceneContractError(
                "project scene package requires an explicit bundle store")
        store = _canonical_directory(bundle_store, "scene bundle store")
        source, bundle = _project_source(scene, store)
    else:
        if bundle_store is not None:
            raise SceneContractError(
                "catalog scene package cannot accept a bundle store")
        source, bundle = _catalog_source(scene), None
    readability_hash = _readability(package, scene)
    return ResolvedScenePackage(
        package, scene,
        hashlib.sha256(canonical_json(package)).hexdigest(),
        source, bundle, readability_hash)


def load_scene_package(path: str,
                       bundle_store: str | None) -> ResolvedScenePackage:
    """Read one regular package JSON file and resolve its exact authorities."""
    return resolve_scene_package(
        read_regular_json(path, "scene package"), bundle_store)


def admission_receipt(resolved: ResolvedScenePackage,
                      assets: list[dict]) -> dict:
    """Aggregate schema, source, rights/sandbox, readability, and provenance."""
    value = {
        "schemaVersion": 1, "kind": "scene-package-admission",
        "packageHash": resolved.package_hash,
        "sceneId": resolved.scene["sceneId"],
        "sceneVersion": resolved.scene["version"],
        "sceneHash": scene_hash(resolved.scene),
        "sourceContract": resolved.source_contract,
        "publicationContext": resolved.package["publicationContext"],
        "readability": {
            "required": resolved.package["readability"]["required"],
            "receiptHash": resolved.readability_hash,
        },
        "assetAdmissions": assets,
        "provenance": resolved.scene["provenance"],
        "checks": [
            "python-schema", "scene-contract", "exact-source-generation",
            "asset-rights-bytes-sandbox", "readability-when-required",
        ],
    }
    return {**value, "admissionHash": hashlib.sha256(
        canonical_json(value)).hexdigest()}
