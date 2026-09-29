#!/usr/bin/env python3
"""Static resource evidence for catalog discovery; never execution approval.

The checked-in sidecar is built during a catalog refresh. Runtime discovery reads
only this bounded metadata and never opens every HTML source or preview asset.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

SCHEMA_VERSION = 1
RESOURCE_INDEX_NAME = "catalog-resource-index-v1.json"
MAX_RESOURCE_BYTES = 4 * 1024 * 1024
MAX_RESOURCE_ROWS = 4096
_PATTERNS = {
    "canvas": re.compile(r"<canvas\b|getContext\s*\(\s*['\"](?:2d|bitmaprenderer)", re.I),
    "webglGpu": re.compile(
        r"\b(?:WebGL|WebGPU|GPUDevice|TypeGPU|THREE\.|VideoTexture|fragmentShader|vertexShader)\b"
        r"|getContext\s*\(\s*['\"]webgl", re.I),
    "videoTexture": re.compile(r"\bVideoTexture\b|sampler2D[^;\n]{0,120}\bvideo\b", re.I),
}
_MEDIA = re.compile(r"<(video|audio)\b", re.I)
_SLOT = re.compile(r"\b(?:slot|media|video|audio|image)(?:Id|Src|Url)?\b", re.I)
_DEPENDENCY = re.compile(
    r"(?:src|href)\s*=\s*['\"]([^'\"]+)['\"]|url\(\s*['\"]?([^)'\"]+)", re.I)
_EXTERNAL = re.compile(r"^(?:https?:|//|data:|blob:)", re.I)
_REPEAT_SIGNALS = {
    "fixed-dom-id": re.compile(r"\bid\s*=\s*['\"][^'\"]+", re.I),
    "global-id-query": re.compile(r"getElementById\s*\(|querySelector\s*\(\s*['\"]#", re.I),
    "global-window-state": re.compile(r"\bwindow\s*\[[^]]+\]|\bwindow\.[A-Za-z_$]", re.I),
}


def file_sha256(path: str) -> str:
    """Return the exact SHA-256 of one regular file."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dependency_evidence(path: str, html: str, allowed_root: str) -> dict:
    """Bound known local dependency bytes without claiming full closure."""
    root = os.path.dirname(path)
    allowed_root = os.path.realpath(allowed_root)
    refs = sorted({a or b for a, b in _DEPENDENCY.findall(html) if a or b})
    local, missing, external = [], [], []
    for ref in refs:
        clean = ref.split("?", 1)[0].split("#", 1)[0]
        if not clean or clean.startswith("#") or _EXTERNAL.match(clean):
            external.append(ref)
            continue
        candidate = os.path.realpath(os.path.join(root, clean))
        if os.path.commonpath((allowed_root, candidate)) != allowed_root:
            missing.append(ref)
        elif os.path.isfile(candidate) and not os.path.islink(candidate):
            local.append(candidate)
        else:
            missing.append(ref)
    return {"knownLocalBytes": sum(os.path.getsize(item) for item in local),
            "resolvedLocalFiles": len(local), "missingReferences": missing,
            "externalReferences": external, "closure": "static-known-only"}


def classify_source(path: str, dependency_root: str | None = None) -> dict:
    """Classify one source from bounded static signals, all labelled unmeasured."""
    with open(path, encoding="utf-8") as handle:
        html = handle.read()
    classes = {name: bool(pattern.search(html)) for name, pattern in _PATTERNS.items()}
    media = _MEDIA.findall(html)
    repeat = [name for name, pattern in _REPEAT_SIGNALS.items() if pattern.search(html)]
    dependencies = _dependency_evidence(
        path, html, dependency_root or os.path.dirname(path))
    heavy = (classes["webglGpu"] or classes["videoTexture"] or len(media) > 1
             or dependencies["knownLocalBytes"] > 1024 * 1024)
    return {"assessment": "static-unmeasured", "domCss": True, **classes,
            "mediaSlots": {"declaredElements": len(media),
                           "slotSignals": len(_SLOT.findall(html))},
            "dependencySize": dependencies,
            "repeatRisk": {"assessment": "unmeasured",
                           "staticSignals": repeat},
            "guardedProbeRequired": bool(heavy or repeat)}


def build_resource_index(catalog_dir: str, index_path: str, lock_path: str,
                         rows: list[dict]) -> dict:
    """Build a digest-bound sidecar without executing any catalog source."""
    items = {}
    for row in rows:
        folder = "compositions" if row["type"] == "block" else "compositions/components"
        path = os.path.join(catalog_dir, folder, row["name"] + ".html")
        items[row["name"]] = (classify_source(path, catalog_dir) if os.path.isfile(path)
                              else unknown_resource_evidence("source-missing"))
    return {"schemaVersion": SCHEMA_VERSION,
            "snapshot": {"indexSha256": file_sha256(index_path),
                         "lockSha256": file_sha256(lock_path), "items": len(rows)},
            "items": items}


def unknown_resource_evidence(reason: str) -> dict:
    """Explicit absence; unknown facts are never converted to safe defaults."""
    return {"assessment": "unmeasured", "reason": reason, "domCss": None,
            "canvas": None, "webglGpu": None, "videoTexture": None,
            "mediaSlots": {"declaredElements": None, "slotSignals": None},
            "dependencySize": {"knownLocalBytes": None, "resolvedLocalFiles": None,
                               "missingReferences": [], "externalReferences": [],
                               "closure": "unmeasured"},
            "repeatRisk": {"assessment": "unmeasured", "staticSignals": []},
            "guardedProbeRequired": True}


def load_resource_index(path: str, index_path: str,
                        lock_path: str) -> tuple[dict[str, dict], list[str]]:
    """Load a current sidecar or return explicit issues and no trusted rows."""
    if not os.path.isfile(path) or os.path.islink(path):
        return {}, [f"catalog resource index unavailable: {path}"]
    if os.path.getsize(path) > MAX_RESOURCE_BYTES:
        return {}, [f"catalog resource index exceeds the bounded read size: {path}"]
    try:
        with open(path, "rb") as handle:
            content = handle.read(MAX_RESOURCE_BYTES + 1)
        if len(content) > MAX_RESOURCE_BYTES:
            return {}, [f"catalog resource index grew beyond the bounded read size: {path}"]
        data = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, [f"catalog resource index unreadable: {path} — {exc}"]
    issues = _resource_index_issues(data, index_path, lock_path)
    return (dict(data["items"]), []) if not issues else ({}, issues)


def _resource_index_issues(data: object, index_path: str,
                           lock_path: str) -> list[str]:
    """Validate identity and bounded row shape, not the static claims themselves."""
    if not isinstance(data, dict) or data.get("schemaVersion") != SCHEMA_VERSION:
        return ["catalog resource index schema/version is invalid"]
    snapshot, items = data.get("snapshot"), data.get("items")
    if not isinstance(snapshot, dict) or not isinstance(items, dict):
        return ["catalog resource index snapshot/items are invalid"]
    if len(items) > MAX_RESOURCE_ROWS:
        return ["catalog resource index item count exceeds its bound"]
    expected = {"indexSha256": file_sha256(index_path),
                "lockSha256": file_sha256(lock_path)}
    issues = [f"catalog resource index {key} does not match current snapshot"
              for key, value in expected.items() if snapshot.get(key) != value]
    if snapshot.get("items") != len(items):
        issues.append("catalog resource index item count is inconsistent")
    return issues
