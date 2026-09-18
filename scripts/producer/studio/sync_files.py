"""File-level findings for the Studio sync-back diff (secondary channel).

The primary sync channel is host-slot attributes in ``index.html``; this
module covers everything the manifest tracks by hash: instance composition
files Studio edited directly, sidecars touched outside the sync scope, files
the operator added (which a re-render would drop), and the staged base media.
Per project doctrine, arbitrary DOM/text edits inside an instance comp are
reported for operator/brain review — code finds WHERE, it never reverse-maps
WHAT into the spec.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import TYPE_CHECKING

from fingerprints import json_canon
from graphics.graphics_render import comp_path
from studio import StudioProjectError
from studio.comp_transform import InstancePlan, build_instance, \
    parse_source_comp
from studio.comp_hf_ids import normalize_instances
from studio.comp_dependencies import STYLE_SCOPE
from studio.declaration_sync import declaration_projection, require_paired_declarations
from studio.index_semantics import index_head_dependency, prepare_index_sync
from studio.sync_model import StudioSyncError, SyncReport, t4
from studio.view_manifest import (MANIFEST_NAME, GENERATOR_VERSION, _project_files,
                                  file_sha256, generation_version)

if TYPE_CHECKING:                       # circular at runtime only
    from studio.sync_diff import SyncState

#: Runtime state other tools park inside the project dir (studio_review.py's
#: preview-server record) — never an operator edit, never an addition.
_RUNTIME_FILES = {".studio-server.json"}


def _rebuild_instance(entry: dict, plan_entry: dict) -> str:
    """The byte-exact instance file the generator would write today."""
    kind = str(entry["kind"])
    style_scope = entry.get('styleScope')
    if 'styleScope' in entry and style_scope != STYLE_SCOPE:
        raise StudioProjectError('unknown original composition style scope')
    duration_binding = entry.get('durationBinding')
    if 'durationBinding' in entry and duration_binding != 'mounted-host-v1':
        raise StudioProjectError('unknown original composition duration binding')
    with open(comp_path(kind), encoding="utf-8") as handle:
        comp_html = handle.read()
    duration = t4(float(entry["outEnd"]) - float(entry["outStart"]))
    source = parse_source_comp(kind, comp_html, style_scope == STYLE_SCOPE,
                               duration_binding == 'mounted-host-v1')
    built = build_instance(source, InstancePlan(
        instance_id=str(entry["instanceId"]),
        spec=plan_entry.get("spec") or {}, duration=duration))
    return built.html


def _decls_equal(left: list[dict], right: list[dict]) -> bool:
    """Compare note-only declaration JSON without conflating booleans and numbers."""
    return json.dumps(json_canon(left), sort_keys=True, allow_nan=False) == \
        json.dumps(json_canon(right), sort_keys=True, allow_nan=False)


def rebuild_original_instances(state: SyncState) -> dict[str, str]:
    """Reconstruct one batch with its original version; never normalize edited files."""
    version = generation_version(state.manifest, state.fingerprint)
    original = {entry["file"]: _rebuild_instance(entry, state.plan["graphicsTrack"][index])
                for index, entry in enumerate(state.manifest["entries"])}
    if original and version == GENERATOR_VERSION:
        return normalize_instances(original)
    return original


def _instance_change_note(rel: str, current: str, rebuilt: str) -> str:
    """Describe the same held bytes already checked by declaration sync."""
    cur_body, cur_decl = declaration_projection(current)
    reb_body, reb_decl = declaration_projection(rebuilt)
    if cur_body != reb_body:
        return (f"{rel}: structurally edited in Studio — needs operator/"
                "brain review, not auto-synced")
    if _decls_equal(cur_decl, reb_decl):
        return f"{rel}: formatting-only rewrite (no effective change)"
    return (f"{rel}: declared-variable defaults rewritten by Studio's panel; "
            "only exact matching host-slot values may sync into the plan")


def _instance_findings(state: SyncState, report: SyncReport, pair: tuple[int, dict],
                       baselines: dict[str, str] | None = None) -> None:
    """Keep unmatched defaults pending instead of rebaselining away a user edit."""
    index, entry = pair
    plan_entry = state.plan["graphicsTrack"][index]
    try:
        original = baselines[entry["file"]] if baselines is not None else _rebuild_instance(entry, plan_entry)
        if hashlib.sha256(original.encode("utf8")).hexdigest() != state.manifest["files"][entry["file"]]:
            raise ValueError("original composition baseline cannot be reconstructed exactly; "
                             "preserve pending edits and regenerate only after resolving them")
        with open(os.path.join(state.studio_dir, entry["file"]), encoding="utf8") as handle:
            current = handle.read()
        report.file_notes.append(_instance_change_note(entry["file"], current, original))
        if declaration_projection(current)[0] != declaration_projection(original)[0]:
            raise ValueError("structurally edited composition must remain pending for operator/brain review")
        slot = next(slot for slot in state.view.slots if slot.slot_id == entry["slot"])
        spec = json.loads(slot.values_text) if slot.values_text is not None else None
        if not isinstance(spec, dict):
            raise ValueError("current host-slot values are unavailable")
        require_paired_declarations(original, current, spec)
    except (OSError, ValueError, KeyError, TypeError, StopIteration, StudioProjectError) as error:
        report.blockers.append(f"{entry['file']}: {error}")


def _note_index_change(state: SyncState, report: SyncReport) -> None:
    """A known slot edit cannot conceal any unaccounted saved index content."""
    try:
        prepare_index_sync(state, report)
    except StudioSyncError as error:
        report.blockers.append(str(error))
        return
    if not report.entry_diffs and not report.deletions:
        report.file_notes.append(
            "index.html: formatting-only rewrite (no effective change)")
        return
    report.informational.append("index.html: only the supported slot edits above remain")


def _missing_file(rel: str, deleted_files: set[str], report: SyncReport) -> None:
    """A removed deleted instance is intentional; other tracked absences are broken."""
    if rel in deleted_files:
        report.informational.append(f"{rel}: removed along with its deleted slot")
        return
    report.blockers.append(f"{rel}: tracked file missing — the view is broken; regenerate instead of syncing")


def _tracked_file_notes(state: SyncState, report: SyncReport) -> None:
    """Hash-diff every manifest-tracked file into the right bucket."""
    deleted_files = {state.manifest["entries"][d.index]["file"]
                     for d in report.deletions}
    instance_by_file = {e["file"]: (i, e)
                        for i, e in enumerate(state.manifest["entries"])}
    baselines = None
    for rel, digest in sorted(state.manifest.get("files", {}).items()):
        path = os.path.join(state.studio_dir, rel)
        if not os.path.isfile(path):
            _missing_file(rel, deleted_files, report)
            continue
        if file_sha256(path) == digest:
            continue
        if rel == "index.html":
            _note_index_change(state, report)
        elif rel in instance_by_file:
            baselines = _changed_instance(state, report, instance_by_file[rel], baselines)
        else:
            report.blockers.append(
                f"{rel}: modified outside the supported sync scope — "
                "preserve pending edits for operator/brain review")


def _unexpected_files(state: SyncState, report: SyncReport) -> None:
    """Keep untracked additions outside the baseline so regeneration still refuses."""
    media_rel = state.manifest.get("media", {}).get("rel")
    known = set(state.manifest.get("files", {})) | {MANIFEST_NAME} \
        | _RUNTIME_FILES
    if media_rel:
        known.add(media_rel)
    for rel in _project_files(state.studio_dir):
        if rel not in known:
            report.additions.append(
                f"new file {rel} — unsupported addition, will not survive "
                "re-render and stays untracked (regeneration requires "
                "--force)")


def _media_check(state: SyncState, report: SyncReport) -> None:
    """Retain the existing staged media existence/size check without decoding."""
    media = state.manifest.get("media", {})
    rel = media.get("rel")
    if not rel:
        return
    path = os.path.join(state.studio_dir, rel)
    if not os.path.isfile(path) or \
            os.path.getsize(path) != media.get("bytes"):
        report.blockers.append(
            f"{rel}: staged base media missing or modified — regenerate the "
            "project instead of syncing")


def collect_file_findings(state: SyncState, report: SyncReport) -> None:
    """All hash/staleness findings; call after the slot diff is complete."""
    try:
        generation_version(state.manifest, state.fingerprint)
        index_head_dependency(state, False)
        _tracked_file_notes(state, report)
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        report.blockers.append(str(error))
        return
    _unexpected_files(state, report)
    _media_check(state, report)


def require_supported_files(state: SyncState, report: SyncReport) -> None:
    """Recheck pending residuals after the real gate before any baseline is published."""
    current = SyncReport(entry_diffs=report.entry_diffs, deletions=report.deletions)
    collect_file_findings(state, current)
    if current.blockers:
        raise StudioSyncError("blockers present: " + "; ".join(current.blockers))


def check_sync_files_unchanged(studio_dir: str, original: dict[str, str]) -> None:
    """Compare the original finite tracked bytes after all prepublication dependencies."""
    for relative, digest in original.items():
        if file_sha256(os.path.join(studio_dir, relative)) != digest:
            raise StudioSyncError(f"{relative}: changed during sync; preserve pending edits")


def _changed_instance(state: SyncState, report: SyncReport, pair: tuple[int, dict],
                       baselines: dict[str, str] | None) -> dict[str, str] | None:
    """Normalize at most one baseline batch for a changed v2 view; never v1."""
    if baselines is None:
        baselines = rebuild_original_instances(state)
    _instance_findings(state, report, pair, baselines)
    return baselines
