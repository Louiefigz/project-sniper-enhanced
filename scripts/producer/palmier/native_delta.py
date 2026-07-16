"""Non-destructive Palmier-native candidate execution from a validated plan."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from palmier.candidate_receipt import save_candidate
from palmier.mcp_client import PalmierClient, PalmierError
from palmier.native_candidate_lifecycle import assert_candidate_slot_available
from palmier.native_progress import NativeProgress, Progress
from palmier.native_plan import (MAY_ADD, MAY_REMOVE, remap_plan_ids,
                                 validate_native_plan)
from palmier.quality_hash import stable_hash
from palmier.timeline_authority import (TimelineSnapshot, fork_candidate,
                                        compare_authority, read_active,
                                        record_candidate)
from palmier.timeline_guard import reconcile_working_authority

_REFERENCE_KEYS = {"clipId", "trackId", "timelineId", "captionGroupId",
                   "linkGroupId"}
_STRUCTURAL_LISTS = {"tracks", "clips", "audio", "linkedClips",
                     "captionGroups"}
@dataclass(frozen=True)
class NativeRequest:
    """Controller-owned inputs for one immutable native edit transaction."""

    sidecar: dict
    plan: object
    name: str = "Sniper AI candidate"
    keep_candidate_active: bool = False
@dataclass(frozen=True)
class _CandidateContext:
    project_id: str
    timeline_id: str
    plan: dict
@dataclass
class _Transaction:
    client: Any
    out_dir: str
    authority: dict
    forked: dict | None = None
    receipts: list[dict] = field(default_factory=list)
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _identity_map(before: object, after: object, parent: str | None = None,
                  found: dict[str, str] | None = None) -> dict[str, str]:
    found = {} if found is None else found
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            raise PalmierError("Palmier candidate copy changed structural list length")
        for left, right in zip(before, after, strict=True):
            _identity_map(left, right, parent, found)
        return found
    if not isinstance(before, dict) or not isinstance(after, dict):
        return found
    for key in before.keys() & after.keys():
        left, right = before[key], after[key]
        structural_id = key == "id" and parent in _STRUCTURAL_LISTS
        if (key in _REFERENCE_KEYS or structural_id) \
                and isinstance(left, str) and isinstance(right, str):
            if left in found and found[left] != right:
                raise PalmierError("Palmier candidate copy has ambiguous regenerated ids")
            found[left] = right
            continue
        _identity_map(left, right, key, found)
    return found


def _active_candidate(client: Any, project_id: str,
                      timeline_id: str) -> TimelineSnapshot:
    current = read_active(client, project_id)
    if current.timeline_id != timeline_id:
        raise PalmierError("Palmier candidate is no longer the active timeline")
    return current


def _removed(delta: object) -> set[str]:
    if not isinstance(delta, dict):
        return set()
    value = delta.get("removedClipIds") or []
    return {item for item in value if isinstance(item, str)}


def _structural_ids(value: object, parent: str | None = None,
                    found: set[str] | None = None) -> set[str]:
    found = set() if found is None else found
    if isinstance(value, list):
        for item in value:
            _structural_ids(item, parent, found)
        return found
    if not isinstance(value, dict):
        return found
    for key, item in value.items():
        if key == "id" and parent in _STRUCTURAL_LISTS and isinstance(item, str):
            found.add(f"{parent}:{item}")
        elif key in _REFERENCE_KEYS and parent == "captionGroups" \
                and isinstance(item, str):
            found.add(f"{parent}:{item}")
        _structural_ids(item, key, found)
    return found


def _candidate_authority(record: dict) -> dict:
    return {key: record[key] for key in (
        "projectId", "timelineId", "fingerprint", "timeline")}
def _candidate_plan(validated: dict, identities: dict[str, str],
                    forked: dict) -> dict:
    remapped = remap_plan_ids(validated, identities)
    remapped["parent"] = {key: forked[key] for key in
                          ("projectId", "timelineId", "fingerprint")}
    return validate_native_plan(remapped, _candidate_authority(forked))


def _operation_at_head(context: _CandidateContext,
                       current: TimelineSnapshot, index: int) -> dict:
    plan = {**context.plan,
            "parent": {"projectId": current.project_id,
                       "timelineId": current.timeline_id,
                       "fingerprint": current.fingerprint},
            "operations": [context.plan["operations"][index]]}
    authority = {"projectId": current.project_id,
                 "timelineId": current.timeline_id,
                 "fingerprint": current.fingerprint,
                 "timeline": current.timeline}
    return validate_native_plan(plan, authority)["operations"][0]


def _apply_operation(client: Any, context: _CandidateContext,
                     index: int) -> tuple[dict, TimelineSnapshot]:
    before = _active_candidate(client, context.project_id, context.timeline_id)
    operation = _operation_at_head(context, before, index)
    result = client.call_json(operation["tool"], operation["args"])
    after = _active_candidate(client, context.project_id, context.timeline_id)
    before_ids, after_ids = (_structural_ids(before.timeline),
                             _structural_ids(after.timeline))
    removed, added = before_ids - after_ids, after_ids - before_ids
    declared = _removed(result)
    if removed and operation["tool"] not in MAY_REMOVE:
        raise PalmierError(
            f"Palmier {operation['tool']} removed structure unexpectedly; "
            "the canonical parent remains unchanged")
    if added and operation["tool"] not in MAY_ADD:
        raise PalmierError(
            f"Palmier {operation['tool']} added structure unexpectedly; "
            "the canonical parent remains unchanged")
    if declared and operation["tool"] not in MAY_REMOVE:
        raise PalmierError(
            f"Palmier {operation['tool']} reported removed clips unexpectedly; "
            "the canonical parent remains unchanged")
    if after.fingerprint == before.fingerprint:
        raise PalmierError(
            f"Palmier {operation['tool']} completed without an observable change")
    receipt = {
        "index": index + 1, "tool": operation["tool"],
        "reason": operation["reason"], "delta": result,
        "beforeFingerprint": before.fingerprint,
        "afterFingerprint": after.fingerprint,
        "observedRemovedStructuralIds": sorted(removed),
        "observedAddedStructuralIds": sorted(added),
    }
    return receipt, after


def _restore_parent(transaction: _Transaction) -> str | None:
    authority = transaction.authority
    try:
        visible = read_active(transaction.client, authority["projectId"])
        if compare_authority(authority, visible) == "unchanged":
            return None
        candidate_id = (transaction.forked or {}).get("timelineId")
        if candidate_id and visible.timeline_id != candidate_id:
            raise PalmierError(
                "Palmier switched away from both the parent and AI candidate; "
                "the visible manual timeline was preserved")
        transaction.client.call_json(
            "set_active_timeline", {"timelineId": authority["timelineId"]})
        restored = read_active(transaction.client, authority["projectId"])
        change = compare_authority(authority, restored)
        if change != "unchanged":
            raise PalmierError(f"restored parent readback is {change}")
    except BaseException as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _visible_candidate(transaction: _Transaction) -> tuple[TimelineSnapshot | None, str | None]:
    authority = transaction.authority
    try:
        visible = read_active(transaction.client, authority["projectId"])
    except BaseException as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return (visible, None) if compare_authority(authority, visible) != "unchanged" else (None, None)


def _quarantine(transaction: _Transaction, failure: BaseException) -> None:
    visible, read_error = _visible_candidate(transaction)
    record, write_error = transaction.forked, None
    failure_row = {"type": type(failure).__name__, "message": str(failure),
                   "at": _now(), "candidateReadError": read_error}
    try:
        if visible:
            record = record_candidate(
                transaction.out_dir, visible, transaction.authority)
        if record:
            record.update({"status": "quarantined", "failure": failure_row,
                           "operations": transaction.receipts,
                           "qc": {"status": "blocked", "approved": False}})
            save_candidate(transaction.out_dir, record)
    except BaseException as exc:
        write_error = f"{type(exc).__name__}: {exc}"
    restore_error = _restore_parent(transaction)
    if record:
        record["parentRestoration"] = {
            "status": "failed" if restore_error else "restored",
            "error": restore_error, "at": _now(),
        }
        try:
            save_candidate(transaction.out_dir, record)
        except BaseException as exc:
            write_error = write_error or f"{type(exc).__name__}: {exc}"
    if restore_error or write_error:
        detail = "; ".join(item for item in (restore_error, write_error) if item)
        raise PalmierError(
            f"{failure}; candidate recovery was incomplete: {detail}") from failure


def _complete_candidate(transaction: _Transaction, staged: dict,
                        keep_candidate_active: bool) -> dict:
    try:
        transaction.forked = save_candidate(transaction.out_dir, staged)
        if keep_candidate_active:
            visible = _active_candidate(
                transaction.client, staged["projectId"], staged["timelineId"])
            if compare_authority(staged, visible) != "unchanged":
                raise PalmierError("visible candidate changed before QC could start")
            staged["parentRestoration"] = {
                "status": "deferred-until-qc", "error": None, "at": _now()}
            return save_candidate(transaction.out_dir, staged)
        restore_error = _restore_parent(transaction)
        if restore_error:
            raise PalmierError(
                f"candidate finished but parent restoration failed: {restore_error}")
        staged["parentRestoration"] = {
            "status": "restored", "error": None, "at": _now()}
        return save_candidate(transaction.out_dir, staged)
    except BaseException as exc:
        _quarantine(transaction, exc)
        raise


def execute_native_candidate(client: PalmierClient, out_dir: str,
                             request: NativeRequest,
                             progress: Progress | None = None) -> dict:
    """Reconcile manual truth, fork it, apply a bounded delta, and stage proof."""
    authority, change = reconcile_working_authority(
        client, out_dir, request.sidecar)
    assert_candidate_slot_available(out_dir)
    validated = validate_native_plan(request.plan, authority)
    transaction = _Transaction(client, out_dir, authority)
    updates = NativeProgress(progress)
    try:
        forked = fork_candidate(client, out_dir, authority, request.name)
        transaction.forked = forked
        updates.candidate_active(forked)
        identities = _identity_map(authority["timeline"], forked["timeline"])
        candidate_plan = _candidate_plan(validated, identities, forked)
        context = _CandidateContext(
            authority["projectId"], forked["timelineId"], candidate_plan)
        for index, _operation in enumerate(candidate_plan["operations"]):
            receipt, _found = _apply_operation(client, context, index)
            transaction.receipts.append(receipt)
            updates.operation_applied(receipt, len(candidate_plan["operations"]))
        found = _active_candidate(client, authority["projectId"],
                                  forked["timelineId"])
        if found.fingerprint == forked["fingerprint"]:
            raise PalmierError("Palmier native plan completed without changing the candidate")
        staged = record_candidate(out_dir, found, authority)
        staged.update({"status": "edited", "workingHeadChange": change,
                       "operations": transaction.receipts,
                       "requestHash": candidate_plan.get("requestHash"),
                       "lanes": candidate_plan.get("lanes"),
                       "nativePlanHash": stable_hash(validated),
                       "qc": {"status": "pending", "approved": False}})
    except BaseException as exc:
        _quarantine(transaction, exc)
        raise
    result = _complete_candidate(
        transaction, staged, request.keep_candidate_active)
    if request.keep_candidate_active:
        updates.candidate_visible(result)
    else:
        updates.parent_restored(authority, result)
    return result
