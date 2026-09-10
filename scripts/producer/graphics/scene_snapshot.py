"""Canonical sealed render inputs for one project-scoped scene entry."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from graphics.graphics_render import (
    GSAP_CORE,
    MOTION_DIR,
    MOTION_TOKENS_JS,
    TOKENS_CSS,
)
from graphics.scene_bundle import BundleSnapshot
from graphics.scene_contract import SceneContractError
from headless.container_io import SealedInput, verify_snapshot_archive
from headless.safe_source_files import PinnedSourceRoot
from headless.sealed_tar_format import canonical_tar_bytes

_SHARED = {
    "tokens.css": TOKENS_CSS,
    "motion-tokens.js": MOTION_TOKENS_JS,
    "vendor/gsap/gsap.min.js": GSAP_CORE,
    "hyperframes.json": os.path.join(MOTION_DIR, "hyperframes.json"),
    "index.html": os.path.join(MOTION_DIR, "index.html"),
    "package.json": os.path.join(MOTION_DIR, "package.json"),
}
_MAX_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True)
class SceneSnapshotRequest:
    """Exact project-scene inputs crossing the container boundary."""

    bundle: BundleSnapshot
    selected: str
    rendered_html: str
    variables: dict
    asset_bindings: tuple[dict, ...]
    directory: str


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=True, separators=(",", ":"),
            sort_keys=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise SceneContractError("scene snapshot JSON is not canonical") from exc


def _read_shared() -> dict[str, bytes]:
    entries = {}
    for relative, path in _SHARED.items():
        with open(path, "rb") as handle:
            entries[f"motion/{relative}"] = handle.read()
    return entries


def _bundle_entry(
    source: PinnedSourceRoot,
    row: dict,
    selected: str,
    rendered_html: str,
) -> tuple[str, bytes] | None:
    relative = row["path"]
    if relative.endswith(".html") and relative != selected:
        return None
    data = source.read(relative)
    if hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise SceneContractError("scene bundle changed during sealing")
    payload = rendered_html.encode("utf-8") \
        if relative == selected else data
    return f"motion/{relative}", payload


def _bundle_entries(
    bundle: BundleSnapshot,
    source: PinnedSourceRoot,
    selected: str,
    rendered_html: str,
) -> dict[str, bytes]:
    entries = {}
    for row in bundle.files:
        entry = _bundle_entry(source, row, selected, rendered_html)
        if entry is not None:
            entries[entry[0]] = entry[1]
    return entries


def _read_bundle(bundle: BundleSnapshot, selected: str,
                 rendered_html: str) -> dict[str, bytes]:
    with PinnedSourceRoot(bundle.path) as source:
        entries = _bundle_entries(
            bundle, source, selected, rendered_html)
        source.assert_current()
    if f"motion/{selected}" not in entries:
        raise SceneContractError("selected scene entry is absent from bundle")
    return entries


def _manifest(entries: dict[str, bytes]) -> tuple[dict, ...]:
    return tuple({
        "path": path, "sizeBytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    } for path, data in sorted(entries.items()))


def _write_snapshot(directory: str, entries: dict[str, bytes],
                    manifest: tuple[dict, ...]) -> SealedInput:
    entries["request/input-manifest.json"] = _canonical_json(manifest)
    encoded = canonical_tar_bytes(entries)
    if not 0 < len(encoded) <= _MAX_BYTES:
        raise SceneContractError("scene snapshot exceeds the released bound")
    path = os.path.join(directory, "render-input.tar")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL \
        | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o400)
    try:
        os.fchmod(fd, 0o400)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    digest = hashlib.sha256(encoded).hexdigest()
    proof = verify_snapshot_archive(path, digest, manifest)
    return SealedInput(path, digest, manifest, (), proof["sizeBytes"])


def create_scene_snapshot(request: SceneSnapshotRequest) -> SealedInput:
    """Seal exactly one selected composition plus its immutable bundle closure."""
    entries = _read_shared()
    entries.update(_read_bundle(
        request.bundle, request.selected, request.rendered_html))
    entries["request/variables.json"] = _canonical_json(request.variables)
    entries["request/asset-bindings.json"] = _canonical_json(
        list(request.asset_bindings))
    manifest = _manifest(entries)
    snapshot = _write_snapshot(request.directory, entries, manifest)
    return SealedInput(
        snapshot.path, snapshot.sha256, snapshot.manifest,
        request.asset_bindings, snapshot.size_bytes)
