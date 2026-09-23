"""Build-bound overlay source capsules captured before attempt admission."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from typing import Any

from graphics.composition_transform import set_root_duration
from graphics.graphics_render import format_for
from graphics.template_assets import icon_keys
from graphics.template_contract import (
    composition_dimensions, declared_variables, planned_copy, validate_entry)

from .container_io import CompositionInput, SealedInput, create_snapshot
from .safe_source_files import read_stable_owned_file
from .sealed_archive import verify_archive_file

QUALIFIED_KINDS = ("section-marker",)
OVERLAY_SOURCE_KEYS = frozenset({
    "buildDigest", "composition", "compositionHtml",
    "expectedAssetBindings", "expectedCopy", "expectedDimensions",
    "expectedFormat", "expectedKey", "extension", "intent",
    "schemaVersion", "selectionId", "snapshotManifest",
    "snapshotSha256", "sourceCompositionSha256",
})
_DIGEST = re.compile(r"[0-9a-f]{64}")
_KIND = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


@dataclass(frozen=True)
class OverlaySourceCapture:
    """Build-bound source intent captured before attempt admission."""

    pipeline_root: str
    intent: dict[str, Any]
    build_digest: str
    selection_id: str


@dataclass(frozen=True)
class ResolvedOverlaySeal:
    """Freshly verified view of one retained overlay source capsule."""

    entry: dict[str, Any]
    intent: dict[str, Any]
    comp_html: str
    composition: str
    snapshot: SealedInput
    key: str
    fmt: str
    extension: str
    dimensions: tuple[int, int]
    expected_copy: tuple[str, ...]
    duration: float


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                             sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("overlay intent is not canonical JSON") from exc
    return encoded.encode("ascii")


def effective_render_intent(entry: dict[str, Any]) -> dict[str, Any]:
    """Project a mutable plan row onto only the bytes shaping overlay media."""
    if not isinstance(entry, dict):
        raise RuntimeError("overlay entry must be an object")
    kind, spec = entry.get("kind"), entry.get("spec")
    anchor = entry.get("anchor", "free-band")
    presenter = entry.get("presenterFilled", False)
    times = (entry.get("outStart"), entry.get("outEnd"))
    numeric = all(type(value) in {int, float} and math.isfinite(value)
                  for value in times)
    if (kind not in QUALIFIED_KINDS or not _KIND.fullmatch(str(kind))
            or not isinstance(spec, dict) or not isinstance(anchor, str)
            or type(presenter) is not bool or not numeric):
        raise RuntimeError("overlay entry is outside the qualified sealed lane")
    duration = float(times[1]) - float(times[0])
    if duration <= 0:
        raise RuntimeError("overlay duration must be positive")
    frozen_spec = json.loads(_canonical(spec))
    return {"schemaVersion": 1, "kind": kind, "spec": frozen_spec,
            "anchor": anchor, "duration": duration,
            "presenterFilled": presenter}


def entry_from_intent(intent: dict[str, Any]) -> dict[str, Any]:
    """Create the normalized renderer entry represented by an intent."""
    return {"kind": intent["kind"], "spec": intent["spec"],
            "anchor": intent["anchor"],
            "presenterFilled": intent["presenterFilled"],
            "outStart": 0, "outEnd": intent["duration"]}


def render_intents_equal(first: dict, second: dict) -> bool:
    """Compare render intent as exact JSON values, not Python numeric equality."""
    return _canonical(first) == _canonical(second)


def _read_composition(root: str, kind: str) -> str:
    if not os.path.isabs(root) or os.path.realpath(root) != root:
        raise RuntimeError("overlay pipeline root must be canonical")
    path = os.path.join(root, "templates", "motion", "compositions",
                        f"{kind}.html")
    return read_stable_owned_file(path, "overlay composition").decode("utf-8")


def _render_key(snapshot_sha256: str, build_digest: str) -> str:
    material = snapshot_sha256.encode("ascii") + b"\0" + build_digest.encode("ascii")
    return hashlib.sha256(b"sniper-overlay-key-v2\0" + material).hexdigest()


def capture_overlay_source(request: OverlaySourceCapture,
                           directory: str) -> dict:
    """Capture one exact source capsule without attempt-bound identities."""
    intent = effective_render_intent(entry_from_intent(request.intent))
    valid = (render_intents_equal(intent, request.intent)
             and _DIGEST.fullmatch(request.build_digest)
             and _KIND.fullmatch(request.selection_id))
    if not valid:
        raise RuntimeError("overlay source capture identity is invalid")
    validate_entry(entry_from_intent(intent))
    html = _read_composition(request.pipeline_root, intent["kind"])
    entry = entry_from_intent(intent)
    validate_entry(entry, html)
    relative = f"compositions/{intent['kind']}.html"
    composition = CompositionInput(
        relative, html, intent, intent["duration"])
    snapshot = create_snapshot(
        request.pipeline_root, composition, intent["spec"], directory)
    fmt, extension = format_for(intent["kind"], intent["anchor"], intent["spec"])
    return {"schemaVersion": 1, "buildDigest": request.build_digest,
            "selectionId": request.selection_id, "intent": intent,
            "composition": relative, "compositionHtml": html,
            "sourceCompositionSha256": hashlib.sha256(html.encode()).hexdigest(),
            "snapshotSha256": snapshot.sha256,
            "snapshotManifest": list(snapshot.manifest),
            "expectedAssetBindings": list(snapshot.asset_bindings),
            "expectedCopy": planned_copy(entry, html),
            "expectedDimensions": list(composition_dimensions(html)),
            "expectedFormat": fmt, "extension": extension,
            "expectedKey": _render_key(snapshot.sha256, request.build_digest)}


def _asset_rows(value: object) -> tuple[dict, ...]:
    if not isinstance(value, list):
        raise RuntimeError("overlay seal asset bindings are invalid")
    rows = tuple(value)
    for row in rows:
        valid = (isinstance(row, dict)
                 and set(row) == {"field", "path", "selector", "sha256"}
                 and all(isinstance(row[key], str) and row[key]
                         for key in ("field", "path", "selector"))
                 and row["path"].startswith("motion/")
                 and _DIGEST.fullmatch(str(row["sha256"])))
        if not valid:
            raise RuntimeError("overlay seal asset binding row is invalid")
    canonical = tuple(sorted(rows, key=lambda row: (row["field"], row["selector"])))
    unique = len({(row["field"], row["selector"]) for row in rows}) == len(rows)
    if rows != canonical or not unique:
        raise RuntimeError("overlay seal asset bindings are not canonical")
    return rows


def _validate_asset_contract(entry: dict, html: str,
                             assets: tuple[dict, ...]) -> None:
    selectors = icon_keys(declared_variables(html))
    if selectors or assets:
        raise RuntimeError("qualified overlay asset contract is unsupported")


def _manifest_row(manifest: tuple[dict, ...], path: str) -> dict:
    matches = [row for row in manifest if row.get("path") == path]
    if len(matches) != 1:
        raise RuntimeError(f"overlay seal is missing {path}")
    return matches[0]


def _derived(value: dict, directory: str) -> ResolvedOverlaySeal:
    intent = value["intent"]
    if not render_intents_equal(
            effective_render_intent(entry_from_intent(intent)), intent):
        raise RuntimeError("overlay seal intent is invalid")
    entry, html = entry_from_intent(intent), value["compositionHtml"]
    validate_entry(entry, html)
    manifest = tuple(value["snapshotManifest"])
    assets = _asset_rows(value["expectedAssetBindings"])
    _validate_asset_contract(entry, html, assets)
    snapshot_path = os.path.join(directory, "render-input.tar")
    archive = verify_archive_file(
        snapshot_path, value["snapshotSha256"], manifest)
    snapshot = SealedInput(
        snapshot_path, value["snapshotSha256"], manifest, assets,
        archive["sizeBytes"])
    fmt, extension = format_for(intent["kind"], intent["anchor"], intent["spec"])
    expected = (tuple(composition_dimensions(html)), tuple(planned_copy(entry, html)),
                fmt, extension, _render_key(snapshot.sha256, value["buildDigest"]))
    actual = (tuple(value["expectedDimensions"]), tuple(value["expectedCopy"]),
              value["expectedFormat"], value["extension"], value["expectedKey"])
    if actual != expected:
        raise RuntimeError("overlay seal derived expectations are invalid")
    return ResolvedOverlaySeal(entry, intent, html, value["composition"], snapshot,
                               expected[4], fmt, extension, expected[0],
                               expected[1], intent["duration"])


def _validate_snapshot(value: dict, resolved: ResolvedOverlaySeal) -> None:
    manifest = resolved.snapshot.manifest
    intent_row = _manifest_row(manifest, "request/render-intent.json")
    assets_row = _manifest_row(manifest, "request/asset-bindings.json")
    comp_row = _manifest_row(manifest, f"motion/{resolved.composition}")
    expected = (
        hashlib.sha256(_canonical(resolved.intent)).hexdigest(),
        hashlib.sha256(_canonical(value["expectedAssetBindings"])).hexdigest(),
        hashlib.sha256(set_root_duration(
            resolved.comp_html, resolved.duration).encode()).hexdigest(),
    )
    actual = (intent_row["sha256"], assets_row["sha256"], comp_row["sha256"])
    if actual != expected:
        raise RuntimeError("overlay seal snapshot is not bound to its receipt")


def resolve_overlay_source(value: dict, directory: str,
                           selection_id: str,
                           build_digest: str) -> ResolvedOverlaySeal:
    """Revalidate one retained pre-admission overlay source capsule."""
    source_hash = hashlib.sha256(
        str(value.get("compositionHtml", "")).encode()).hexdigest()
    valid = (isinstance(value, dict) and set(value) == OVERLAY_SOURCE_KEYS
             and type(value.get("schemaVersion")) is int
             and value.get("schemaVersion") == 1
             and value.get("buildDigest") == build_digest
             and value.get("selectionId") == selection_id
             and isinstance(value.get("intent"), dict)
             and value.get("composition")
             == f"compositions/{value.get('intent', {}).get('kind')}.html"
             and source_hash == value.get("sourceCompositionSha256"))
    if not valid:
        raise RuntimeError("overlay source seal envelope is invalid")
    resolved = _derived(value, directory)
    _validate_snapshot(value, resolved)
    return resolved
