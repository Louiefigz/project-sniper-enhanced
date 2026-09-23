"""Inert TEST source seam for storage/ledger units, never render admission.

Only artifact capture and source resolution are substituted. Real envelope,
private-file, tar, request binding and durable ledger checks remain in use.
Real current-policy rejection is tested separately without this context.
"""
from __future__ import annotations

import contextlib
import hashlib
from pathlib import Path
from unittest import mock

from _graphic_render_receipt_fixture import _composition_html
from graphics.composition_transform import set_root_duration
from graphics.graphics_render import format_for
from graphics.template_contract import composition_dimensions, planned_copy
from headless.container_io import SealedInput
from headless.graphic_render_source_semantics import (
    _snapshot_semantics, _validate_retained_entry,
)
from headless.overlay_source_seal import (
    ResolvedOverlaySeal, _canonical, _render_key, entry_from_intent,
)
from headless.sealed_archive import verify_archive_file
from headless.sealed_tar_format import canonical_tar_bytes


def capture_test_metadata(request: object, directory: str) -> dict:
    """Write a non-executable synthetic archive under the TEST temporary root."""
    html, intent = _composition_html(), request.intent
    composition = "compositions/section-marker.html"
    entries = {
        f"motion/{composition}": set_root_duration(html, intent["duration"]).encode(),
        "motion/hyperframes.json": b"{}", "motion/package.json": b"{}",
        "motion/index.html": b"<!-- TEST inert historical metadata -->",
        "request/asset-bindings.json": b"[]",
        "request/variables.json": _canonical(intent["spec"]),
        "request/render-intent.json": _canonical(intent),
    }
    rows = [{"path": name, "sha256": hashlib.sha256(raw).hexdigest(),
             "sizeBytes": len(raw)} for name, raw in sorted(entries.items())]
    entries["request/input-manifest.json"] = _canonical(rows)
    raw = canonical_tar_bytes(entries)
    target = Path(directory) / "render-input.tar"
    target.write_bytes(raw)
    target.chmod(0o400)
    digest = hashlib.sha256(raw).hexdigest()
    fmt, extension = format_for(intent["kind"], intent["anchor"], intent["spec"])
    return {"schemaVersion": 1, "buildDigest": request.build_digest,
            "selectionId": request.selection_id, "intent": intent,
            "composition": composition, "compositionHtml": html,
            "sourceCompositionSha256": hashlib.sha256(html.encode()).hexdigest(),
            "snapshotSha256": digest, "snapshotManifest": rows,
            "expectedAssetBindings": [], "expectedFormat": fmt, "extension": extension,
            "expectedCopy": planned_copy(entry_from_intent(intent), html),
            "expectedDimensions": list(composition_dimensions(html)),
            "expectedKey": _render_key(digest, request.build_digest)}


def resolve_test_metadata(value: dict, directory: str, selection: str,
                          build_digest: str) -> ResolvedOverlaySeal:
    """Supply static DTOs only; do not call this seam from a rendering test."""
    if (value["selectionId"], value["buildDigest"]) != (selection, build_digest):
        raise RuntimeError("TEST source identity mismatch")
    intent, html = value["intent"], value["compositionHtml"]
    entry = entry_from_intent(intent)
    _validate_retained_entry(entry, html)
    _snapshot_semantics(value, intent, html)
    fmt, extension = format_for(intent["kind"], intent["anchor"], intent["spec"])
    derived = (list(composition_dimensions(html)), planned_copy(entry, html),
               fmt, extension, _render_key(value["snapshotSha256"], build_digest))
    retained = (value["expectedDimensions"], value["expectedCopy"],
                value["expectedFormat"], value["extension"], value["expectedKey"])
    if retained != derived:
        raise RuntimeError("TEST source derived expectations are invalid")
    path = str(Path(directory) / "render-input.tar")
    rows = tuple(value["snapshotManifest"])
    proof = verify_archive_file(path, value["snapshotSha256"], rows)
    snapshot = SealedInput(path, value["snapshotSha256"], rows, (), proof["sizeBytes"])
    return ResolvedOverlaySeal(
        entry, intent, html, value["composition"], snapshot,
        value["expectedKey"], fmt, extension, tuple(value["expectedDimensions"]),
        tuple(value["expectedCopy"]), intent["duration"])


@contextlib.contextmanager
def inert_artifact_sources():
    """Isolate source policy from storage units without patching validation."""
    with mock.patch("headless.render_admission_artifact.capture_overlay_source",
                    side_effect=capture_test_metadata), mock.patch(
                        "headless.render_admission_artifact_reader.resolve_overlay_source",
                        side_effect=resolve_test_metadata):
        yield


def store_test_artifact(request: object):
    """Exercise private storage mechanics only; deliberately not public admission."""
    from dataclasses import replace
    from headless import render_admission_artifact as storage
    from headless.durable_files import locked_private_dir
    from headless.request_artifact import canonical_request_document
    frozen = canonical_request_document(request.request)[0]
    closed = replace(request, request=frozen)
    with locked_private_dir(closed.authority_root, storage.RENDER_ARTIFACT_LOCK) as root:
        storage.ensure_authority_record(root, closed.authority_id)
        digest = storage._store_under_lock(root, closed)
    locator = storage.RenderArtifactLocator(digest)
    storage.load_render_admission_artifact(closed.authority_root, locator)
    return locator
