"""Diff a Studio-edited review project against its generation state.

The manifest's per-entry records hold the GENERATED slot values — including
the exit-on-cut CLAMP, which the plan deliberately does not carry. Diffing
current slot attributes against those records is what separates an operator
edit from the clamp: an untouched clamped slot matches its manifest record
and the plan keeps its unclamped ``outEnd``; a slot that differs was edited,
and the edited timeline values are the operator's intent, written back
verbatim. ``data-variable-values`` diffs run through ``json_canon`` on both
sides so Studio's serialization (quoting, entities, key order, ``30`` vs
``30.0``) never reads as an edit.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from fingerprints import json_canon
from graphics.exit_on_cut import apply_exit_on_cut
from studio.slot_reader import IndexView, SlotElement, read_index
from studio.sync_files import collect_file_findings
from studio.sync_model import (
    Deletion,
    EntryDiff,
    FieldChange,
    StudioSyncError,
    SyncReport,
    t4,
)
from studio.view_manifest import FINGERPRINT_NAME, MANIFEST_NAME

PLAN_BASENAME = "edit_plan.json"


@dataclass(frozen=True)
class SyncState:
    """Everything a diff or apply needs, loaded and binding-checked."""

    studio_dir: str
    manifest: dict
    fingerprint: dict
    plan: dict
    plan_path: str
    view: IndexView


def plan_track_sha(plan: dict) -> str:
    """The plan's effective-graphicsTrack digest, exactly as the generator
    computes it for ``view.fingerprint.json`` (clamp applied first)."""
    effective, _ = apply_exit_on_cut(plan)
    canon = json.dumps(json_canon(effective), sort_keys=True,
                       ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def resolve_plan_path(manifest: dict, override: str | None) -> str:
    """The plan the view was generated from: beside the recorded base."""
    if override:
        return os.path.abspath(override)
    target = manifest.get("media", {}).get("target")
    if not target:
        raise StudioSyncError(
            "manifest records no media.target — pass --plan explicitly")
    return os.path.join(os.path.dirname(target), PLAN_BASENAME)


def _load_json(path: str, what: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise StudioSyncError(f"cannot load {what} at {path}: {exc}") from exc


def _check_binding(state_plan: dict, fingerprint: dict,
                   manifest: dict) -> None:
    """Refuse to sync when the plan drifted since generation."""
    if plan_track_sha(state_plan) != fingerprint.get("graphicsTrackSha256"):
        raise StudioSyncError(
            "edit_plan.json's graphicsTrack no longer matches "
            f"{FINGERPRINT_NAME} — the plan changed after generation; "
            "regenerate the studio project instead of syncing")
    entries = manifest.get("entries") or []
    track = state_plan.get("graphicsTrack") or []
    if len(entries) != len(track):
        raise StudioSyncError(
            f"manifest has {len(entries)} entries but the plan has "
            f"{len(track)} graphicsTrack rows")
    for i, (entry, plan_entry) in enumerate(zip(entries, track)):
        if entry.get("kind") != plan_entry.get("kind") or \
                entry.get("planId") != plan_entry.get("id"):
            raise StudioSyncError(
                f"manifest entry {i} ({entry.get('kind')}/"
                f"{entry.get('planId')}) does not bind to graphicsTrack[{i}]")


def load_state(studio_dir: str, plan_override: str | None = None) -> SyncState:
    """Load + binding-check one studio directory for diff/apply."""
    studio_dir = os.path.abspath(studio_dir)
    manifest = _load_json(os.path.join(studio_dir, MANIFEST_NAME),
                          "generation manifest")
    fingerprint = _load_json(os.path.join(studio_dir, FINGERPRINT_NAME),
                             "view fingerprint")
    plan_path = resolve_plan_path(manifest, plan_override)
    plan = _load_json(plan_path, "edit plan")
    _check_binding(plan, fingerprint, manifest)
    view = read_index(os.path.join(studio_dir, "index.html"))
    return SyncState(studio_dir, manifest, fingerprint, plan, plan_path, view)


def _timing_diff(diff: EntryDiff, entry: dict, slot: SlotElement,
                 report: SyncReport) -> None:
    if slot.start is None or slot.duration is None:
        report.blockers.append(
            f"{slot.slot_id}: data-start/data-duration missing or "
            "non-numeric — malformed host slot")
        return
    generated = (t4(entry["outStart"]), t4(entry["outEnd"]))
    current = (t4(slot.start), t4(slot.start + slot.duration))
    if current != generated:
        diff.timing_old = generated
        diff.timing_new = current


def _canon_equal(left: object, right: object) -> bool:
    """Canon equality that keeps JSON types apart (``True`` is not ``1``).

    The canon values are parsed JSON; Python's ``==`` collapses bool/int/
    float (``True == 1 == 1.0``), which made a bool→number Studio edit
    invisible (BUG-2). Serialized-form comparison is type-exact — the same
    move ``plan_track_sha`` makes with its json.dumps canonicalization.
    """
    return json.dumps(left, sort_keys=True) == json.dumps(right,
                                                          sort_keys=True)


def _values_diff(diff: EntryDiff, plan_entry: dict, slot: SlotElement,
                 report: SyncReport) -> None:
    if slot.values_text is None:
        report.blockers.append(
            f"{slot.slot_id}: data-variable-values attribute missing")
        return
    try:
        current = json_canon(json.loads(slot.values_text))
    except json.JSONDecodeError as exc:
        report.blockers.append(
            f"{slot.slot_id}: data-variable-values is not valid JSON "
            f"({exc}) — cannot read the operator's values")
        return
    if not isinstance(current, dict):
        report.blockers.append(
            f"{slot.slot_id}: data-variable-values is not an object")
        return
    generated = json_canon(plan_entry.get("spec") or {})
    changes = []
    for key in sorted(set(generated) | set(current)):
        # Presence is part of the value: a key nulled or dropped in Studio
        # must surface as FieldChange(old, None), never filter as None==None.
        if (key in generated) == (key in current) and \
                _canon_equal(generated.get(key), current.get(key)):
            continue
        changes.append(FieldChange(key, generated.get(key),
                                   current.get(key)))
    if not changes:
        return
    diff.value_changes = changes
    diff.new_spec = current


def _layout_notes(diff: EntryDiff, entry: dict, slot: SlotElement) -> None:
    if slot.track_index is not None and slot.track_index != entry["track"]:
        diff.layout_notes.append(
            f"track {entry['track']} -> {slot.track_index} (view-only lane "
            "layout — not written to the plan)")
    if slot.z_index is not None and slot.z_index != entry["zIndex"]:
        diff.layout_notes.append(
            f"z-index {entry['zIndex']} -> {slot.z_index} (view-only)")
    if slot.attrs.get("class") != "clip":
        diff.layout_notes.append(
            f"class {slot.attrs.get('class')!r} (view-only)")


def _entry_diff(pair: tuple[int, dict], slot: SlotElement,
                plan_entry: dict, report: SyncReport) -> EntryDiff | None:
    index, entry = pair
    diff = EntryDiff(index=index, slot=entry["slot"],
                     plan_id=entry.get("planId"), kind=entry["kind"])
    if slot.comp_id != entry["instanceId"] or slot.comp_src != entry["file"]:
        report.blockers.append(
            f"{diff.label}: slot retargeted to "
            f"{slot.comp_id!r}/{slot.comp_src!r} — a composition swap "
            "cannot be mapped back to the plan")
        return None
    _timing_diff(diff, entry, slot, report)
    _values_diff(diff, plan_entry, slot, report)
    _layout_notes(diff, entry, slot)
    changed = diff.plan_facing or diff.layout_notes
    return diff if changed else None


def _base_notes(state: SyncState, report: SyncReport) -> None:
    """Base-media element edits are view-only; a swapped src is fatal."""
    video = state.view.media_attrs.get("review-base")
    if video is None:
        report.blockers.append("review-base video element missing")
        return
    if video.get("src") != state.manifest.get("media", {}).get("rel"):
        report.blockers.append(
            f"review-base src changed to {video.get('src')!r} — the base "
            "video was swapped; regenerate instead of syncing")
    root_duration = state.view.root_attrs.get("data-duration")
    if video.get("data-start") not in (None, "0") or (
            root_duration is not None
            and video.get("data-duration") != root_duration):
        report.informational.append(
            "review-base timing edited in Studio — view-only; the base cut "
            "is owned by the render pipeline, not the review project")


def compute_report(state: SyncState) -> SyncReport:
    """The full dry-run report for one loaded studio directory."""
    report = SyncReport()
    slots = {slot.slot_id: slot for slot in state.view.slots}
    for i, entry in enumerate(state.manifest.get("entries") or []):
        slot = slots.pop(entry["slot"], None)
        plan_entry = state.plan["graphicsTrack"][i]
        if slot is None:
            report.deletions.append(Deletion(
                i, entry["slot"], entry.get("planId"), entry["kind"]))
            continue
        diff = _entry_diff((i, entry), slot, plan_entry, report)
        if diff is not None:
            report.entry_diffs.append(diff)
    for slot in slots.values():
        report.additions.append(
            f"slot '{slot.slot_id}' ({slot.comp_id or 'no composition id'}) "
            "is not in the generation manifest — unsupported addition, will "
            "not survive re-render")
    report.additions.extend(
        f"{descr} — unsupported addition, will not survive re-render"
        for descr in state.view.unknown)
    report.blockers.extend(state.view.problems)
    _base_notes(state, report)
    collect_file_findings(state, report)
    return report
