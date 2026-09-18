"""Gate Studio edits before writes; preserve pending bytes and owned provenance."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone

from fingerprints import json_canon
from fingerprint_io import write_json_atomic
from graphics.exit_on_cut import apply_exit_on_cut
from graphics.graphics_render import comp_path
from graphics.template_contract import validate_entry
from plan_lint import lint
from studio.comp_transform import parse_source_comp, seed_declarations
from studio.index_semantics import prepare_index_sync, check_index_unchanged, write_index_sync
from studio.project_writer import readback_window
from studio.slot_reader import SlotElement
from studio.sync_diff import SyncState
from studio.sync_files import check_sync_files_unchanged, require_supported_files
from studio.sync_model import (
    StudioSyncError,
    StudioSyncGateFailure,
    SyncReport,
    t4,
)
from studio.view_manifest import (
    FINGERPRINT_NAME,
    MANIFEST_NAME,
    build_fingerprint,
    generation_fields,
    file_sha256,
    write_json,
)

HISTORY_DIR = "plan-history"
HISTORY_KEEP = 20
PREEXISTING_NOTE = "predates this edit — not caused by it"
#: Mechanical index tag in lint messages (index remap only, no semantics).
_TRACK_TAG_RE = re.compile(r"graphicsTrack\[(\d+)\]")


def build_new_plan(state: SyncState, report: SyncReport) -> dict:
    """The plan with every operator edit folded in (nothing written yet)."""
    plan = copy.deepcopy(state.plan)
    track = plan["graphicsTrack"]
    for diff in report.entry_diffs:
        entry = track[diff.index]
        if diff.timing_new is not None:
            entry["outStart"] = json_canon(diff.timing_new[0])
            entry["outEnd"] = json_canon(diff.timing_new[1])
        if diff.new_spec is not None:
            entry["spec"] = diff.new_spec
    for deletion in sorted(report.deletions, key=lambda d: d.index,
                           reverse=True):
        del track[deletion.index]
    if report.plan_changes:
        plan["planVersion"] = int(plan.get("planVersion") or 0) + 1
    return plan


def _lint_words(new_plan: dict, manifest: dict,
                manifest_path: str) -> list[dict]:
    """KEPT output-time words, resolved the way the plan_lint CLI does."""
    from graphics_planner import output_words   # local: heavy import
    return output_words(new_plan, os.path.dirname(manifest_path), manifest)


def _contract_failures(new_plan: dict, report: SyncReport) -> list[str]:
    """Changed-entry template-contract violations — always blocking."""
    failures: list[str] = []
    for diff in report.entry_diffs:
        if not diff.plan_facing:
            continue
        try:
            validate_entry(new_plan["graphicsTrack"][_new_index(
                report, diff.index)])
        except ValueError as exc:
            failures.append(f"{diff.label}: {exc}")
    return failures


def gate_verdict(state: SyncState, report: SyncReport, new_plan: dict,
                 manifest_path: str) -> tuple[list[str], list[str]]:
    """Return (blocking, preexisting): changed-entry contracts always block;
    lint blocks only candidate errors absent from the remapped baseline.
    """
    blocking = _contract_failures(new_plan, report)
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        manifest.setdefault("_path", os.path.abspath(manifest_path))
        words = _lint_words(new_plan, manifest, manifest_path)
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        blocking.append(f"lint inputs unavailable: {exc}")
        return blocking, []
    baseline = lint(state.plan, manifest, words).errors
    candidate = lint(new_plan, manifest, words).errors
    track_len = len(state.plan.get("graphicsTrack") or [])
    known = set(_remapped_baseline(report, baseline, track_len))
    blocking.extend(e for e in candidate if e not in known)
    return blocking, [e for e in candidate if e in known]


def _remapped_baseline(report: SyncReport, errors: list[str],
                       track_len: int) -> list[str]:
    """Remap surviving graphicsTrack[N] and whole-track counts after deletion.
    Drop errors naming deleted entries; newly introduced errors still block.
    """
    if not report.deletions:
        return errors
    deleted = {d.index for d in report.deletions}
    count_re = re.compile(rf"\b{track_len} graphicsTrack entr")
    new_count = f"{track_len - len(report.deletions)} graphicsTrack entr"
    remapped = []
    for error in errors:
        if any(int(m) in deleted for m in _TRACK_TAG_RE.findall(error)):
            continue
        error = _TRACK_TAG_RE.sub(
            lambda m: f"graphicsTrack[{_new_index(report, int(m.group(1)))}]",
            error)
        remapped.append(count_re.sub(new_count, error))
    return remapped


def _new_index(report: SyncReport, old_index: int) -> int:
    """Map a manifest entry index onto the deletion-compacted plan track."""
    return old_index - sum(1 for d in report.deletions
                           if d.index < old_index)


def snapshot_plan(plan_path: str, plan: dict) -> str:
    """Copy the current plan into ``plan-history/`` (newest 20 kept)."""
    history = os.path.join(os.path.dirname(plan_path), HISTORY_DIR)
    os.makedirs(history, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    version = int(plan.get("planVersion") or 0)
    dest = os.path.join(history, f"{version}-{stamp}.json")
    shutil.copyfile(plan_path, dest)
    kept = sorted((os.path.join(history, name)
                   for name in os.listdir(history)
                   if name.endswith(".json")),
                  key=os.path.getmtime, reverse=True)
    for stale in kept[HISTORY_KEEP:]:
        os.remove(stale)
    return dest


def _write_plan(plan_path: str, new_plan: dict) -> None:
    """Atomic replace, formatted like the repo's other plan writers."""
    write_json_atomic(plan_path, new_plan, indent=1)


def _non_panel_keys(kind: str, spec: dict) -> list[str]:
    """Return spec keys absent from the original composition's panel contract."""
    try:
        path = comp_path(kind)
    except ValueError as exc:
        raise StudioSyncError(str(exc)) from exc
    with open(path, encoding="utf-8") as handle:
        source = parse_source_comp(kind, handle.read())
    _, non_panel = seed_declarations(source.variables, spec)
    return list(non_panel)


def _rebaselined_entry(entry: dict, slot: SlotElement, plan_entry: dict,
                       spec_changed: bool) -> dict:
    """One manifest entry re-recorded from the current slot + new plan."""
    out = dict(entry)
    out["outStart"] = json_canon(t4(slot.start))
    out["outEnd"] = json_canon(t4(slot.start + slot.duration))
    out["authoredOutEnd"] = json_canon(plan_entry["outEnd"])
    # Clamp detection compares projections, not raw plan floats: an
    # untouched >4-decimal window projects to exactly the slot read-back.
    out["exitClamped"] = t4(slot.start + slot.duration) != \
        readback_window(float(plan_entry["outStart"]),
                        float(plan_entry["outEnd"]))[1]
    if slot.track_index is not None:
        out["track"] = slot.track_index
    if slot.z_index is not None:
        out["zIndex"] = slot.z_index
    if spec_changed:
        out["nonPanelKeys"] = _non_panel_keys(
            entry["kind"], plan_entry.get("spec") or {})
    return out


def _rebaselined_entries(state: SyncState, report: SyncReport,
                         new_plan: dict) -> list[dict]:
    """Rebind surviving original entries to the saved slots and new plan."""
    slots = {slot.slot_id: slot for slot in state.view.slots}
    deleted = {d.index for d in report.deletions}
    spec_changed = {d.index for d in report.entry_diffs
                    if d.new_spec is not None}
    entries = []
    for i, entry in enumerate(state.manifest.get("entries") or []):
        if i in deleted:
            continue
        plan_entry = new_plan["graphicsTrack"][_new_index(report, i)]
        entries.append(_rebaselined_entry(
            entry, slots[entry["slot"]], plan_entry, i in spec_changed))
    return entries


def _rebaselined_files(state: SyncState, report: SyncReport) -> dict:
    """Every still-present tracked file rehashed to its on-disk state."""
    deleted_files = {state.manifest["entries"][d.index]["file"]
                     for d in report.deletions}
    files = {}
    for rel in state.manifest.get("files", {}):
        path = os.path.join(state.studio_dir, rel)
        if rel in deleted_files and not os.path.isfile(path):
            continue
        files[rel] = file_sha256(path)
    return files


def _require_target(state: SyncState) -> str:
    """The recorded base video, verified present (fingerprint rebind input)."""
    target = state.manifest.get("media", {}).get("target")
    if not target or not os.path.isfile(target):
        raise StudioSyncError(
            f"base video {target} is gone — cannot re-bind the view "
            "fingerprint to the updated plan")
    return target


def _check_writable(state: SyncState, plan_changes: bool) -> None:
    """Refuse before the first write when an output directory is read-only."""
    dirs = [state.studio_dir]
    if plan_changes:
        dirs.append(os.path.dirname(state.plan_path))
    for path in dirs:
        if not os.access(path, os.W_OK):
            raise StudioSyncError(f"{path} is not writable — cannot apply")


def _rewrite_fingerprint(state: SyncState, new_plan: dict,
                         files: dict) -> None:
    """Preserve the original generator identity when rebinding the plan."""
    effective, _ = apply_exit_on_cut(new_plan)
    target = _require_target(state)
    path = os.path.join(state.studio_dir, FINGERPRINT_NAME)
    write_json(path, build_fingerprint(effective, target, state.manifest["generator"]))
    files[FINGERPRINT_NAME] = file_sha256(path)


def apply_sync(state: SyncState, report: SyncReport,
               manifest_path: str) -> dict:
    """Gate and precompute all edits before publishing the plan and saved baseline."""
    if report.blockers:
        raise StudioSyncError("blockers present: " + "; ".join(report.blockers))
    original_files = _rebaselined_files(state, report)
    new_plan = build_new_plan(state, report)
    blocking, preexisting = gate_verdict(state, report, new_plan,
                                         manifest_path)
    if blocking:
        raise StudioSyncGateFailure(blocking, preexisting)
    require_supported_files(state, report)
    prepared = prepare_index_sync(state, report)
    entries = _rebaselined_entries(state, report, new_plan)
    files = dict(original_files)
    files["index.html"] = hashlib.sha256(prepared.after).hexdigest()
    _check_writable(state, report.plan_changes)
    if report.plan_changes:
        _require_target(state)
    check_index_unchanged(state.studio_dir, prepared)
    check_sync_files_unchanged(state.studio_dir, original_files)
    backup = None
    if report.plan_changes:
        backup = snapshot_plan(state.plan_path, state.plan)
        _write_plan(state.plan_path, new_plan)
        _rewrite_fingerprint(state, new_plan, files)
    write_index_sync(state.studio_dir, prepared)
    write_json(os.path.join(state.studio_dir, MANIFEST_NAME), {
        **generation_fields(state.manifest["generator"]),
        "files": files, "media": state.manifest.get("media"),
        "entries": entries,
        "indexNeedsSplitText": prepared.needs_split_text,
        "exitClampedCount": sum(1 for e in entries if e["exitClamped"])})
    return {"status": "applied", "planPath": state.plan_path,
            "planVersion": new_plan.get("planVersion"),
            "backup": backup,
            "entriesUpdated": sum(1 for d in report.entry_diffs
                                  if d.plan_facing),
            "entriesDeleted": len(report.deletions),
            "unsupportedAdditions": list(report.additions),
            "fileNotes": list(report.file_notes),
            "preexistingGateFailures": preexisting,
            "preexistingNote": PREEXISTING_NOTE if preexisting else ""}
