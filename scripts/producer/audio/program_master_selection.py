"""Captured full-program execution selection for private audio excerpts.

Only an owned invocation holding the actual returned ProgramMaster may capture
a selection. Readers require its independently held event SHA; mutable final
pointers, directory scans, and a caller's self-computed receipt are not authority.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from audio.program_master_bus import ProgramMaster, verify_program_master
from audio.program_master_cache import load_program_master
from audio.render_audio_cache import load_source_bus
from cut_preview_io import bound_json, digest, file_hash, read_bytes, real_directory, write_new
from render_effect_discovery import local_python_import_closure

_KIND = "ordinary-full-program-master-selection"
_KEYS = {"schemaVersion", "kind", "scope", "planPath", "planSha256", "manifestPath",
    "manifestSha256", "artifactRoot", "basePath", "baseSha256", "sourceBusReceiptHash",
    "programMasterReceiptPath", "programMasterReceiptHash", "audioProgramInputHash",
    "selectionImplementation"}


@dataclass(frozen=True)
class SelectionContext:
    """Exact owned files associated with the just-completed full-program render."""

    plan_path: Path
    manifest_path: Path
    artifact_root: Path
    base_path: Path
    event_path: Path


@dataclass(frozen=True)
class HeldMasterSelection:
    """Reopened source/master plus the separately held immutable completion fact."""

    master: ProgramMaster
    plan: dict
    context: SelectionContext
    event: dict
    event_sha256: str


def selection_implementation() -> list[dict]:
    """Bind executable selection checks, not only a schema version string."""
    paths = local_python_import_closure([Path(__file__)])
    return [{"path": str(path), "sha256": file_hash(path)} for path in sorted(set(paths))]


def _document(path: Path) -> tuple[dict, str]:
    """Parse the exact regular-file bytes that supplied a document hash."""
    import json
    raw = read_bytes(path)
    value = json.loads(raw.decode("utf-8"))
    if type(value) is not dict:
        raise RuntimeError("program selection document must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def _context(event: dict, event_path: Path) -> SelectionContext:
    """Require canonical paths; directory location cannot select a receipt itself."""
    fields = ("planPath", "manifestPath", "artifactRoot", "basePath")
    if any(type(event.get(key)) is not str for key in fields):
        raise RuntimeError("program selection paths are malformed")
    receipt = event.get("programMasterReceiptPath")
    if type(receipt) is not str or event_path.name != "selection-event.json" \
            or event_path.parent != Path(receipt).parent:
        raise RuntimeError("program selection event is outside its actual master generation")
    result = SelectionContext(*(Path(event[key]) for key in fields), event_path)
    real_directory(result.artifact_root)
    for path in (result.plan_path, result.manifest_path, result.base_path, event_path):
        real_directory(path.parent)
    return result


def _load(event: dict, context: SelectionContext) -> tuple[ProgramMaster, dict]:
    """Use existing strong source/master cache readers with held receipt identities."""
    plan = bound_json(context.plan_path, event["planSha256"])
    manifest = bound_json(context.manifest_path, event["manifestSha256"])
    manifest["_path"] = str(context.manifest_path)
    if file_hash(context.base_path) != event["baseSha256"]:
        raise RuntimeError("program selection base bytes changed")
    bus = load_source_bus(plan, manifest, (str(context.artifact_root), str(context.base_path)),
                          event["sourceBusReceiptHash"])
    master = load_program_master(bus, plan,
        (event["programMasterReceiptPath"], event["programMasterReceiptHash"]))
    if master.receipt["audioProgramInputHash"] != event["audioProgramInputHash"]:
        raise RuntimeError("program selection global audio inputs changed")
    return master, plan


def read_master_selection(event_path: Path, expected_sha256: str) -> HeldMasterSelection:
    """Reopen only a completion fact already held by the actual server invocation."""
    if type(expected_sha256) is not str or len(expected_sha256) != 64:
        raise RuntimeError("program selection needs a separately held event SHA")
    event = bound_json(event_path, expected_sha256)
    if set(event) != _KEYS or type(event["schemaVersion"]) is not int or event["schemaVersion"] != 1 \
            or event["kind"] != _KIND or event["scope"] != "full-program-audio-not-delivery-approval" \
            or event["selectionImplementation"] != selection_implementation():
        raise RuntimeError("program selection role or implementation changed")
    context = _context(event, event_path)
    master, plan = _load(event, context)
    if file_hash(event_path) != expected_sha256:
        raise RuntimeError("program selection event changed during validation")
    return HeldMasterSelection(master, plan, context, event, expected_sha256)


def capture_master_selection(master: ProgramMaster, plan: dict, context: SelectionContext) -> HeldMasterSelection:
    """Capture an actual returned full master, never build one from a final pointer."""
    if type(master) is not ProgramMaster:
        raise RuntimeError("program selection requires an actual full-program master result")
    current, plan_sha = _document(context.plan_path)
    _, manifest_sha = _document(context.manifest_path)
    if digest(current) != digest(plan):
        raise RuntimeError("program selection plan differs from the completed invocation")
    verify_program_master(master, plan)
    event = {"schemaVersion": 1, "kind": _KIND, "scope": "full-program-audio-not-delivery-approval",
        "planPath": str(context.plan_path), "planSha256": plan_sha,
        "manifestPath": str(context.manifest_path), "manifestSha256": manifest_sha,
        "artifactRoot": str(context.artifact_root), "basePath": str(context.base_path),
        "baseSha256": file_hash(context.base_path), "sourceBusReceiptHash": master.source_bus.receipt["receiptHash"],
        "programMasterReceiptPath": str(Path(master.directory) / "master-receipt.json"),
        "programMasterReceiptHash": master.receipt["receiptHash"],
        "audioProgramInputHash": master.receipt["audioProgramInputHash"],
        "selectionImplementation": selection_implementation()}
    _load(event, _context(event, context.event_path))
    write_new(context.event_path, event)
    os.chmod(context.event_path, 0o400)
    return read_master_selection(context.event_path, file_hash(context.event_path))


def revalidate_master_selection(selection: HeldMasterSelection) -> None:
    """Keep all global dependencies current even for an unchanged opening range."""
    current = read_master_selection(selection.context.event_path, selection.event_sha256)
    if current.event != selection.event or current.master.receipt != selection.master.receipt:
        raise RuntimeError("program selection changed before excerpt publication")
