#!/usr/bin/env python3
"""Cross-project template reuse gate for transcript-bound graphic decisions."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from typing import Any

from cross_runtime_canonical_json import canonical_compact_json
from edit_scope import lane_required, resolve_scope
from graphics.form_allocation import (assess_kind_reuse,
                                      assess_profile_form_reuse)
from graphics.intro_semantic_contract import semantic_beats
from graphics.style_profiles import profile_name
from graphics.template_contract import template_catalog

_SHA = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"a", "an", "and", "are", "as", "at", "be", "but", "by", "for",
         "from", "i", "in", "is", "it", "of", "on", "or", "that", "the",
         "this", "to", "was", "we", "with", "you", "your"}
MIN_REUSE_REASON = 30


def _stable_hash(value: Any) -> str:
    raw = canonical_compact_json(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _usage_counts(projects: list[dict]) -> dict[str, dict]:
    counts: dict[str, dict] = {}
    for project in projects:
        for kind, uses in (project.get("uses") or {}).items():
            prior = counts.setdefault(kind, {"uses": 0, "projects": 0,
                                             "lastUsedAt": project["approvedAt"]})
            prior["uses"] += uses
            prior["projects"] += 1
            prior["lastUsedAt"] = max(prior["lastUsedAt"],
                                      project["approvedAt"])
    return dict(sorted(counts.items()))


def _project_window_errors(projects: list[object], known: dict) -> list[str]:
    errors, project_ids = [], set()
    for index, project in enumerate(projects):
        if not isinstance(project, dict):
            errors.append(f"template usage projects[{index}] must be an object")
            continue
        project_id, approved_at = project.get("projectId"), project.get("approvedAt")
        plan_hash, uses = project.get("planHash"), project.get("uses")
        if not isinstance(project_id, str) or not project_id or project_id in project_ids:
            errors.append(f"template usage projects[{index}].projectId is invalid or duplicated")
        else:
            project_ids.add(project_id)
        if not isinstance(approved_at, str) or not approved_at:
            errors.append(f"template usage projects[{index}].approvedAt is invalid")
        if not isinstance(plan_hash, str) or not _SHA.fullmatch(plan_hash):
            errors.append(f"template usage projects[{index}].planHash is invalid")
        if not isinstance(uses, dict) or any(
                kind not in known or not isinstance(count, int)
                or isinstance(count, bool) or count < 1
                for kind, count in (uses.items() if isinstance(uses, dict) else [])):
            errors.append(f"template usage projects[{index}].uses is invalid")
    return errors


def _snapshot_errors(snapshot: object, mode: str,
                     expected_digest: str | None = None) -> list[str]:
    if not isinstance(snapshot, dict):
        return ["template usage history must be an object"]
    found = snapshot.get("digest")
    core = {key: value for key, value in snapshot.items() if key != "digest"}
    errors = []
    if snapshot.get("schemaVersion") != 1 \
            or snapshot.get("kind") != "producer-template-usage-history":
        errors.append("template usage history schema/kind is invalid")
    if snapshot.get("mode") != mode:
        errors.append("template usage history mode does not match this plan")
    if not isinstance(found, str) or not _SHA.fullmatch(found) \
            or found != _stable_hash(core):
        errors.append("template usage history digest is invalid")
    if expected_digest is not None and found != expected_digest:
        errors.append("template usage history does not match controller-bound digest")
    projects = snapshot.get("projects")
    if not isinstance(projects, list) or snapshot.get("projectCount") != len(projects):
        errors.append("template usage project window is malformed")
        return errors
    window = snapshot.get("windowProjects")
    if not isinstance(window, int) or isinstance(window, bool) \
            or window < 1 or len(projects) > window:
        errors.append("template usage windowProjects is malformed")
    project_errors = _project_window_errors(projects, template_catalog())
    errors.extend(project_errors)
    if project_errors:
        return errors
    expected = _usage_counts(projects)
    if snapshot.get("counts") != expected:
        errors.append("template usage counts do not match approved project rows")
    policy = snapshot.get("policy") or {}
    minimum, share = policy.get("minProjects"), policy.get("minProjectShare")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1 \
            or not isinstance(share, (int, float)) or isinstance(share, bool) \
            or share <= 0 or share > 1:
        errors.append("template usage overuse policy is malformed")
        return errors
    overused = sorted(kind for kind, item in expected.items()
                      if item["projects"] >= minimum
                      and item["projects"] / max(1, len(projects)) >= share)
    if snapshot.get("overusedKinds") != overused:
        errors.append("template usage overusedKinds does not match its policy")
    return errors


def _content_tokens(value: object) -> set[str]:
    return {token for token in _TOKEN.findall(str(value).lower())
            if token not in _STOP and (len(token) >= 3 or token.isdigit())}


def _reuse_error(decision: dict, beat: dict, snapshot: dict) -> str | None:
    chosen = str(decision.get("kind") or "")
    counts = snapshot.get("counts") or {}
    overused = set(snapshot.get("overusedKinds") or [])
    if chosen not in overused:
        return None
    chosen_projects = (counts.get(chosen) or {}).get("projects", 0)
    alternatives = [kind for kind in beat["compatibleKinds"] if kind != chosen
                    and kind not in overused
                    and (counts.get(kind) or {}).get("projects", 0) < chosen_projects]
    if not alternatives:
        return None
    considered = decision.get("alternativesConsidered") or []
    if not any(kind in alternatives for kind in considered):
        return (f"overused {chosen!r} ({chosen_projects} recent projects) has "
                f"underused compatible alternatives {alternatives}; consider one explicitly")
    reason = str(decision.get("reuseReason") or "").strip()
    evidence = _content_tokens(beat.get("evidence"))
    overlap = evidence & _content_tokens(reason)
    required = min(2, len(evidence))
    if len(reason) < MIN_REUSE_REASON or len(overlap) < required:
        return (f"reusing overused {chosen!r} needs a {MIN_REUSE_REASON}+ character "
                "reuseReason quoting transcript-specific evidence and explaining why "
                f"underused forms {alternatives} fit worse")
    return None


def _allocation_error(assessment: dict) -> str | None:
    if not assessment["avoidableReuse"]:
        return None
    witness = json.dumps(assessment["replacementWitnesses"],
                         sort_keys=True, separators=(",", ":"))
    profiled = "selectedDistinctForms" in assessment
    label = "information form" if profiled else "graphic kind"
    selected = assessment["selectedDistinctForms" if profiled
                          else "selectedDistinctKinds"]
    maximum = assessment["maximumFeasibleDistinctForms" if profiled
                         else "maximumFeasibleDistinctKinds"]
    return (f"{label} reuse is avoidable: selected {selected} distinct "
            f"{'forms' if profiled else 'kinds'} but {maximum} are globally "
            "feasible for these transcript beats; compatible replacement "
            f"witness={witness}")


def check(plan: dict, words: list[dict], snapshot: object,
          expected_digest: str | None = None) -> dict:
    target = plan.get("target") or {}
    errors = _snapshot_errors(snapshot, str(target.get("mode") or ""),
                              expected_digest)
    if errors or target.get("mode") != "longform" \
            or resolve_scope(target) not in ("produced", "full") \
            or not lane_required(target, "graphics"):
        # Out-of-scope modes (shorts) still bind the VALIDATED history digest:
        # the approval writer requires metrics.snapshotDigest to equal its
        # controller-bound authority, and _snapshot_errors already checked it.
        metrics = {} if errors else {"snapshotDigest": snapshot.get("digest")}
        return {"scope": "template_usage", "ok": not errors,
                "errors": errors, "warnings": [], "metrics": metrics}
    out_dur = max((float(word.get("end", 0)) for word in words), default=0.0)
    selected_profile = profile_name(target)
    beats = {beat["beatId"]: beat for beat in semantic_beats(
        words, out_dur, selected_profile)}
    checked = 0
    for index, decision in enumerate(plan.get("graphicsDecisions") or []):
        if not isinstance(decision, dict) or decision.get("decision") != "graphic":
            continue
        beat = beats.get(str(decision.get("beatId") or ""))
        if beat is None:
            continue
        issue = _reuse_error(decision, beat, snapshot)
        if issue:
            errors.append(f"graphicsDecisions[{index}]: {issue}")
        elif decision.get("kind") in snapshot.get("overusedKinds", []):
            checked += 1
    allocation = (assess_profile_form_reuse(
        list(beats.values()), plan.get("graphicsDecisions") or [],
        selected_profile) if selected_profile else assess_kind_reuse(
            list(beats.values()), plan.get("graphicsDecisions") or []))
    allocation_issue = _allocation_error(allocation)
    if allocation_issue:
        errors.append(allocation_issue)
    return {"scope": "template_usage", "ok": not errors,
            "errors": errors, "warnings": [],
            "metrics": {"snapshotDigest": snapshot.get("digest"),
                        "overusedKinds": snapshot.get("overusedKinds"),
                        "checkedReuses": checked,
                        **allocation}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan"); parser.add_argument("transcripts_dir")
    parser.add_argument("manifest"); parser.add_argument("usage_history")
    parser.add_argument("--expected-digest", required=True)
    args = parser.parse_args()
    from graphics_planner import output_words
    try:
        plan = json.load(open(args.plan)); manifest = json.load(open(args.manifest))
        snapshot = json.load(open(args.usage_history))
        verdict = check(plan, output_words(plan, args.transcripts_dir, manifest),
                        snapshot, args.expected_digest)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        verdict = {"scope": "template_usage", "ok": False,
                   "errors": [str(exc)], "warnings": [], "metrics": {}}
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
