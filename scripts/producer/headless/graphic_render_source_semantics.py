"""Pure semantic checks for retained graphic source-seal records."""

from __future__ import annotations

import hashlib
import json

from graphics.composition_transform import set_root_duration
from graphics.template_assets import icon_keys
from graphics.template_contract import (
    composition_dimensions,
    declared_variables,
    planned_copy,
    validate_entry,
)

from .artifact_contract import MediaRefV1
from .overlay_source_seal import (
    effective_render_intent,
    entry_from_intent,
    render_intents_equal,
)
from .sealed_archive import validate_manifest


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("ascii")


def _manifest_row(manifest: tuple[dict, ...], path: str) -> dict:
    rows = tuple(row for row in manifest if row.get("path") == path)
    if len(rows) != 1:
        raise RuntimeError(f"graphic source manifest is missing {path}")
    return rows[0]


def _snapshot_semantics(source: dict, intent: dict, html: str) -> None:
    rows = source["snapshotManifest"]
    if type(rows) is not list:
        raise RuntimeError("graphic source snapshot manifest is invalid")
    manifest = tuple(rows)
    validate_manifest(manifest)
    paths = (
        "request/render-intent.json",
        "request/asset-bindings.json",
        f"motion/{source['composition']}",
        "request/variables.json",
    )
    payloads = (
        _canonical(intent),
        _canonical(source["expectedAssetBindings"]),
        set_root_duration(html, intent["duration"]).encode(),
        _canonical(intent["spec"]),
    )
    expected = tuple((hashlib.sha256(raw).hexdigest(), len(raw)) for raw in payloads)
    actual = tuple(
        (
            _manifest_row(manifest, path)["sha256"],
            _manifest_row(manifest, path)["sizeBytes"],
        )
        for path in paths
    )
    if actual != expected:
        raise RuntimeError("graphic source snapshot manifest is stale")


def _media_semantics(source: dict, intent: dict, media: MediaRefV1) -> None:
    facts = media.facts
    duration = intent["duration"]
    tolerance = max(1.0 / 30.0 + 0.005, 0.04)
    actual = (
        source["expectedDimensions"],
        facts.frame_count,
        abs(facts.duration_seconds - duration) <= tolerance,
    )
    expected = ([facts.width, facts.height], round(duration * 30), True)
    if actual != expected:
        raise RuntimeError("graphic source media expectations are stale")


def validate_graphic_source_semantics(
    source: dict, plan_row: dict, media: MediaRefV1
) -> None:
    """Validate source-seal claims that do not require reopening its tar."""
    intent = source["intent"]
    html = source["compositionHtml"]
    if type(intent) is not dict or type(html) is not str:
        raise RuntimeError("graphic source intent or composition is invalid")
    entry = entry_from_intent(intent)
    expected_intent = effective_render_intent(plan_row)
    validate_entry(entry, html)
    variables = declared_variables(html)
    assets = source["expectedAssetBindings"]
    expected = (
        render_intents_equal(intent, expected_intent),
        source["composition"],
        source["sourceCompositionSha256"],
        source["expectedDimensions"],
        source["expectedCopy"],
        assets,
        tuple(icon_keys(variables)),
    )
    actual = (
        True,
        f"compositions/{intent['kind']}.html",
        hashlib.sha256(html.encode()).hexdigest(),
        list(composition_dimensions(html)),
        planned_copy(entry, html),
        [],
        (),
    )
    if expected != actual:
        raise RuntimeError("graphic source composition semantics are stale")
    _snapshot_semantics(source, intent, html)
    _media_semantics(source, intent, media)
