"""Prove the whole saved index before sync; prepare only owned binding deletion."""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import TYPE_CHECKING

from graphics.graphics_render import comp_path
from graphics.template_contract import composition_dimensions
from ingest_probe import probe_media
from studio.comp_transform import parse_source_comp
from studio.index_stream import _semantic_stream, projected_index_stream, require_loaded_slots
from studio.project_writer import ReviewBase, ReviewClip, build_index_html, provenance_bindings
from studio.sync_model import StudioSyncError, SyncReport

if TYPE_CHECKING:
    from studio.sync_diff import SyncState

_RECONSTRUCT_ERRORS = (OSError, ValueError, KeyError, TypeError, RuntimeError,
                       subprocess.CalledProcessError)


@dataclass(frozen=True)
class IndexSync:
    """Original saved bytes and the sole authorized generator-owned replacement."""

    before: bytes
    after: bytes
    needs_split_text: bool


def _baseline_base(state: "SyncState") -> ReviewBase:
    """Reuse the existing staged-base probe for the original generator geometry."""
    media = state.manifest.get("media") or {}
    probe = probe_media(os.path.join(state.studio_dir, media["rel"]))
    width, height = probe.width, probe.height
    if probe.rotation in (90, 270):
        width, height = height, width
    return ReviewBase(width=width, height=height, duration=probe.duration,
                      fps=probe.fps, src_rel=media["rel"],
                      has_audio=probe.audio_present)


def _baseline_clips(state: "SyncState") -> tuple[list[ReviewClip], bool]:
    """Rebuild original host inputs from the bound manifest and plan, not edited DOM."""
    clips, need_split_text = [], False
    for i, entry in enumerate(state.manifest.get("entries") or []):
        kind = str(entry["kind"])
        with open(comp_path(kind), encoding="utf-8") as handle:
            comp_html = handle.read()
        need_split_text = need_split_text or \
            parse_source_comp(kind, comp_html).uses_split_text
        dims = composition_dimensions(comp_html)
        clips.append(ReviewClip(
            slot_id=str(entry["slot"]), instance_id=str(entry["instanceId"]),
            kind=kind, file_rel=str(entry["file"]),
            spec=state.plan["graphicsTrack"][i].get("spec") or {},
            out_start=float(entry["outStart"]),
            out_end=float(entry["outEnd"]),
            authored_out_end=float(entry["authoredOutEnd"]),
            track=int(entry["track"]), z_index=int(entry["zIndex"]),
            width=dims[0], height=dims[1],
            anchor=str(entry.get("anchor", "free-band")), reason="",
            plan_id=entry.get("planId"), non_panel_keys=()))
    return clips, need_split_text


def index_head_dependency(state: "SyncState", reconstructed: bool) -> bool:
    """Retain the originally generated head choice, never infer it from edited HTML."""
    if "indexNeedsSplitText" not in state.manifest:
        return reconstructed
    value = state.manifest["indexNeedsSplitText"]
    if type(value) is not bool:
        raise ValueError("indexNeedsSplitText must be the original boolean")
    return value


def _baseline(state: "SyncState") -> tuple[str, list[ReviewClip], bool]:
    """Reconstruct the prior generator document, including retained head dependencies."""
    clips, need_split_text = _baseline_clips(state)
    needed = index_head_dependency(state, need_split_text)
    baseline = build_index_html(_baseline_base(state), clips,
                                f"{os.path.basename(state.studio_dir)} review", needed)
    return baseline, clips, needed


def _checked_index(state: "SyncState", report: SyncReport) -> IndexSync:
    """Account for exact known host edits, then prepare the original binding update."""
    path = os.path.join(state.studio_dir, "index.html")
    with open(path, "rb") as handle:
        before = handle.read()
    current = before.decode("utf8")
    baseline, clips, needed = _baseline(state)
    original_ids = {clip.slot_id for clip in clips}
    slots = {slot.slot_id: slot for slot in state.view.slots if slot.slot_id in original_ids}
    require_loaded_slots(current, slots)
    deleted = {item.slot for item in report.deletions}
    if projected_index_stream(current, slots, set()) != projected_index_stream(baseline, slots, deleted):
        raise ValueError("index.html has residual edits that cannot be attributed to supported slots "
                         "(script/style/text/comment/structure); "
                         "preserve pending edits and resolve them before syncing")
    after = current
    if deleted:
        old = provenance_bindings(clips)
        if current.count(old) != 1:
            raise ValueError("original generator bindings are not exactly available")
        after = current.replace(old, provenance_bindings(
            [clip for clip in clips if clip.slot_id not in deleted]), 1)
    return IndexSync(before, after.encode("utf8"), needed)


def prepare_index_sync(state: "SyncState", report: SyncReport) -> IndexSync:
    """Fail before writes if the complete original saved index cannot be proved."""
    try:
        return _checked_index(state, report)
    except _RECONSTRUCT_ERRORS as error:
        raise StudioSyncError(str(error)) from error


def check_index_unchanged(studio_dir: str, prepared: IndexSync) -> None:
    """Final prewrite byte check; no late saved edit can be silently overwritten."""
    with open(os.path.join(studio_dir, "index.html"), "rb") as handle:
        if handle.read() != prepared.before:
            raise StudioSyncError("index.html changed during sync; preserve the pending edit")


def write_index_sync(studio_dir: str, prepared: IndexSync) -> None:
    """Publish only the precomputed owned binding substring, preserving other bytes."""
    if prepared.before == prepared.after:
        return
    path = os.path.join(studio_dir, "index.html")
    descriptor, temporary = tempfile.mkstemp(prefix=".studio-sync-", suffix=".tmp", dir=studio_dir)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(prepared.after)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def index_formatting_only(state: "SyncState") -> bool:
    """Retain the old formatting-only query, with complete executable-source checks."""
    try:
        path = os.path.join(state.studio_dir, "index.html")
        with open(path, encoding="utf8", newline="") as handle:
            current = handle.read()
        baseline, _, _ = _baseline(state)
        return _semantic_stream(current) == _semantic_stream(baseline)
    except _RECONSTRUCT_ERRORS:
        return False
