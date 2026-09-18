"""Read-only compare-and-swap guard shared by AI starts and mirror sync."""
from __future__ import annotations

from typing import Any

from palmier.candidate_receipt import load_candidate, save_candidate
from palmier.mcp_client import PalmierError
from palmier.mirror import persist_ai_edit_invalidation
from palmier.native_qc_contract import load_qc, save_qc
from palmier.timeline_authority import (
    TimelineConflict, compare_authority, load_authority, read_active,
    record_authority)


def _identity(value: dict) -> dict:
    return {key: value.get(key) for key in
            ("projectId", "timelineId", "fingerprint")}


def _candidate_change(out_dir: str, prior: dict,
                      current: Any) -> tuple[dict, str] | None:
    candidate = load_candidate(out_dir)
    if candidate is None or candidate.get("timelineId") != current.timeline_id:
        return None
    status = candidate.get("status")
    terminal = status in ("promoted", "superseded-manual")
    if terminal and prior.get("timelineId") != candidate.get("timelineId"):
        return None
    if not terminal and candidate.get("base") != _identity(prior):
        raise TimelineConflict(
            "The visible Palmier candidate has stale or unknown parent authority")
    if status in ("staged", "quarantined", "quarantined-recovered"):
        raise TimelineConflict(
            "A failed or incomplete Palmier candidate is visible; restore its "
            "preserved parent, or choose Discard candidate & keep parent, "
            "before asking AI for another change")
    if status == "superseded-manual":
        return None
    if status not in ("edited", "qc-approved", "promoted"):
        raise TimelineConflict("The visible Palmier candidate has an unsupported state")
    if candidate.get("fingerprint") == current.fingerprint:
        phase = "passed QC and awaits deliberate promotion" \
            if status == "qc-approved" else "review-only and still awaits QC"
        raise TimelineConflict(
            f"The visible Palmier candidate is {phase}; "
            "it cannot become the working head merely by being viewed. Run its "
            "QC and use it if approved, or choose Discard candidate & keep parent.")
    persist_ai_edit_invalidation(out_dir)
    saved = record_authority(out_dir, current, "palmier-manual", prior)
    candidate.update({
        "status": "superseded-manual",
        "supersededBy": _identity(saved),
        "qc": {"status": "invalidated-by-manual-edit", "approved": False},
    })
    save_candidate(out_dir, candidate)
    _invalidate_native_qc(out_dir, saved)
    return saved, "candidate-manual"


def _invalidate_native_qc(out_dir: str, saved: dict) -> None:
    """Supersede valid native QC evidence without blocking visible manual truth."""
    try:
        receipt = load_qc(out_dir)
    except PalmierError:
        return
    receipt.update({"status": "superseded-manual",
                    "supersededBy": _identity(saved),
                    "approvalCurrent": False})
    save_qc(out_dir, receipt)


def reconcile_working_authority(client: Any, out_dir: str,
                                sidecar: dict | None) -> tuple[dict, str]:
    """Adopt the visible managed revision as the working head, never a plan.

    This is the entry point for Palmier-native work. Unlike the legacy
    plan-only guard, a manual origin is valid input: the controller will fork
    and edit that exact revision instead of trying to translate it backward.
    """
    project_id = (sidecar or {}).get("projectId")
    if not isinstance(project_id, str) or not project_id:
        raise PalmierError("Palmier state has no canonical project id")
    current = read_active(client, project_id)
    prior = load_authority(out_dir)
    if prior is None:
        candidate = load_candidate(out_dir)
        if candidate and candidate.get("timelineId") == current.timeline_id:
            raise TimelineConflict(
                "A Palmier candidate is visible but its preserved parent authority is missing")
        return record_authority(out_dir, current, "untrusted-bootstrap"), "bootstrap"
    change = compare_authority(prior, current)
    if change == "unchanged":
        return prior, change
    candidate_change = _candidate_change(out_dir, prior, current)
    if candidate_change:
        return candidate_change
    persist_ai_edit_invalidation(out_dir)
    return record_authority(out_dir, current, "palmier-manual", prior), change


def guard_sniper_baseline(client: Any, out_dir: str,
                          sidecar: dict | None) -> dict:
    """Return a verdict, adopting visible manual drift but never overwriting it."""
    saved, change = reconcile_working_authority(client, out_dir, sidecar)
    if change == "bootstrap":
        return _blocked(saved, "No trusted Palmier baseline existed; the visible "
                        "timeline was preserved but cannot be translated to a Sniper plan.")
    if change != "unchanged":
        return _blocked(saved, f"Palmier {change}; that visible revision is now the "
                        "baseline, but the Sniper plan cannot safely replace it.")
    if saved.get("origin") != "sniper-bootstrap":
        return _blocked(saved, "The canonical Palmier baseline contains manual, "
                        "promoted, or unverified work; a native delta is required.")
    coverage = saved.get("readbackCoverage") or {}
    if coverage.get("complete") is not True:
        return _blocked(saved, "Palmier readback is incomplete, so Sniper cannot "
                        "prove it will preserve every caption and timeline property.")
    return {"ok": True, "status": "current", "timelineId": saved["timelineId"],
            "fingerprint": saved["fingerprint"], "authority": "palmier"}


def assert_sniper_baseline(client: Any, out_dir: str,
                           sidecar: dict | None) -> None:
    """Raise before a Sniper mirror can displace the Palmier source of truth."""
    if not sidecar:
        return
    verdict = guard_sniper_baseline(client, out_dir, sidecar)
    if verdict["ok"] is not True:
        raise PalmierError(str(verdict["error"]))


def _blocked(record: dict, message: str) -> dict:
    return {"ok": False, "status": "manual-baseline", "error": message,
            "timelineId": record.get("timelineId"),
            "fingerprint": record.get("fingerprint"), "authority": "palmier"}
