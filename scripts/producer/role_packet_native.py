"""Resolve native Short plans, staged projects and job markers into role packet artifacts."""
from __future__ import annotations

import os
import re
from fractions import Fraction
from pathlib import Path

from context_routes import PROJECT_FILES
from cut_preview_io import digest
from role_packet_files import (REHASH_LIMIT, ArtifactError, artifact, bound_artifact, canonical_directory,
                               canonical_file, declared, read_json)

GENERATED_BINDINGS = ("prebuildReview", "preparedSources", "guidedBinding")
REQUEST_SIBLINGS = ("AGENT-BRIEF.md", "CATALOG-INDEX.json", "DIRECTOR-LIBRARY.json")
PROJECT_FOLDERS = ("compositions", "references")


def plan_hash(plan: dict) -> str:
    """Match nativeShortPrebuildPlanHash: generated bindings are excluded from the digest."""
    return digest({key: value for key, value in plan.items() if key not in GENERATED_BINDINGS})


def seconds(frame: int, rate: Fraction) -> float:
    """Exact frame clock rendered in seconds for human review notes."""
    return round(float(frame / rate), 3)


def require_native_plan(plan: dict, file: Path) -> Fraction:
    """Refuse anything that is not a schema-1 native Short plan; return its frame rate."""
    if plan.get("schemaVersion") != 1 or not isinstance(plan.get("canvas"), dict) \
            or not isinstance(plan.get("strategy"), dict) or not isinstance(plan.get("assets"), list):
        raise ArtifactError(f"{file} is not a native Short plan (schemaVersion 1 with canvas, strategy, assets)")
    return Fraction(plan["canvas"]["frameRate"])


def scene_rows(plan: dict, rate: Fraction) -> list[dict]:
    """Every authored scene with its frame window; plan critics note each one."""
    return [{"index": index, "startFrame": scene["startFrame"], "endFrame": scene["endFrame"],
             "startSeconds": seconds(scene["startFrame"], rate), "endSeconds": seconds(scene["endFrame"], rate),
             "format": scene.get("format"), "viewingNeed": scene.get("viewingNeed")}
            for index, scene in enumerate(plan["strategy"].get("scenes", []))]


def suppression_rows(plan: dict) -> list[dict]:
    """canvas.captionSuppressions (absent on older plans); a malformed field is refused, never skipped."""
    rows, total = plan["canvas"].get("captionSuppressions"), plan["canvas"]["totalFrames"]
    if rows is None:
        return []
    valid = isinstance(rows, list) and all(
        isinstance(row, dict) and isinstance(row.get("reason"), str) and all(
            isinstance(row.get(key), int) and not isinstance(row.get(key), bool) for key in ("startFrame", "endFrame"))
        and 0 <= row["startFrame"] < row["endFrame"] <= total for row in rows)
    if not valid:
        raise ArtifactError("canvas.captionSuppressions must list {startFrame, endFrame, reason} windows inside the program")
    return rows


def caption_suppressions(plan: dict, rate: Fraction) -> list[dict]:
    """Caption-free windows with their reasons and the kept words spoken inside them (C3 review line)."""
    words = [row for row in plan["canvas"].get("occurrences") or [] if isinstance(row, list) and len(row) > 5]
    result = []
    for row in suppression_rows(plan):
        spoken = [word for word in words if word[3] < row["endFrame"] and word[4] > row["startFrame"]]
        result.append({"startFrame": row["startFrame"], "endFrame": row["endFrame"], "reason": row["reason"],
                       "startSeconds": seconds(row["startFrame"], rate), "endSeconds": seconds(row["endFrame"], rate),
                       "spokenOccurrenceIds": [word[0] for word in spoken],
                       "spokenText": " ".join(str(word[5]) for word in spoken)})
    return result


def canvas_summary(plan: dict, rate: Fraction) -> dict:
    """Frame clock and title for the subject header."""
    canvas = plan["canvas"]
    return {"title": canvas.get("title"), "frameRate": canvas["frameRate"], "totalFrames": canvas["totalFrames"],
            "durationSeconds": seconds(canvas["totalFrames"], rate), "captionSuppressions": caption_suppressions(plan, rate)}


def bound_review(plan: dict) -> tuple[list[dict], dict | None, list[str]]:
    """The plan's current prebuild binding, whether it is current, and its recorded author."""
    binding = plan.get("prebuildReview")
    if not binding:
        return [], None, []
    row = bound_artifact("bound-prebuild-review", binding, "Prebuild review record this plan currently binds.")
    record = read_json(row["path"])
    reviewer = record.get("reviewer") if isinstance(record.get("reviewer"), dict) else {}
    summary = {"path": row["path"], "sha256": row["sha256"], "planHash": record.get("planHash"),
               "current": record.get("planHash") == plan_hash(plan),
               "verdict": (record.get("review") or {}).get("verdict"), "reviewerSession": reviewer.get("sessionId")}
    author = reviewer.get("plannerSessionId")
    return [row], summary, [author] if isinstance(author, str) and author.strip() else []


def request_artifacts(plan: dict) -> list[dict]:
    """The frozen request packet and the files its writer publishes beside it."""
    binding = plan.get("requestPacket")
    if not binding:
        return []
    rows = [bound_artifact("request-packet", binding, "Frozen SHORT-REQUEST.json: intent, sources, permissions.")]
    directory = Path(rows[0]["path"]).parent
    for name in REQUEST_SIBLINGS:
        if (directory / name).is_file():
            rows.append(artifact(f"request:{name}", directory / name, "Published with SHORT-REQUEST.json."))
    return rows


def asset_rows(plan: dict) -> tuple[list[dict], list[dict]]:
    """Small bound assets are rehashed; large recordings keep their declared hash."""
    rows, large = [], []
    for index, binding in enumerate(plan.get("assets", [])):
        key, why = f"asset-{index}-{binding.get('role')}", f"Plan asset {binding.get('file')} ({binding.get('role')})."
        if canonical_file(binding["path"]).stat().st_size > REHASH_LIMIT:
            large.append(declared(key, binding, why))
            continue
        rows.append(bound_artifact(key, binding, why))
    for index, binding in enumerate(plan.get("catalogFiles", [])):
        rows.append(bound_artifact(f"catalog-{index}-{binding.get('catalogId')}", binding,
                                   f"Adapted catalog source staged as {binding.get('file')}."))
    return rows, large


def plan_bindings(plan: dict) -> list[dict]:
    """Preparation and visual-plan receipts the plan binds."""
    rows = []
    if isinstance(plan.get("preparedSources"), dict):
        rows.append(bound_artifact("prepared-sources", plan["preparedSources"], "Sealed selected-media receipt."))
    visual = plan.get("visualPlan")
    if isinstance(visual, dict) and isinstance(visual.get("path"), str):
        rows.append(bound_artifact("visual-plan", {"path": visual["path"], "sha256": visual.get("byteHash")},
                                   "VISUAL-PLAN.json the plan binds; its bytes must match visualPlan.byteHash."))
    return rows


def request_value(plan: dict) -> dict | None:
    """The bound request packet's JSON (its hash is verified by request_artifacts), or None when unbound."""
    binding = plan.get("requestPacket")
    if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
        return None
    return read_json(binding["path"])


def reference_route(plan: dict, request: dict | None) -> bool | None:
    """A selected reference in the request or a reference-route source decision; None when either is unknown."""
    sources = plan.get("visualSources")
    decisions = sources.get("decisions") if isinstance(sources, dict) else None
    routes = {row.get("route") for row in decisions if isinstance(row, dict)} if isinstance(decisions, list) else None
    selected = None if request is None else bool(request.get("selectedReference") or request.get("selectedReferences"))
    if (routes and "reference" in routes) or selected:
        return True
    return None if routes is None or selected is None else False


def plan_features(plan: dict) -> dict[str, bool | None]:
    """Which conditional governing sections this plan uses (role_packet_catalog.FEATURES); facts, not judgments."""
    request, canvas = request_value(plan), plan.get("canvas") or {}
    staged = bool(plan.get("catalogFiles")) or plan.get("catalogTitle") is not None or canvas.get("titleCard") is not None
    return {"catalog-staging": staged,
            "reference-route": reference_route(plan, request),
            "related-group": None if request is None else bool(request.get("relatedStyleContext")),
            "source-burned-captions": canvas.get("captionMode") == "source-burned",
            "caption-suppressions": bool(canvas.get("captionSuppressions")),
            "supporting-media": any(isinstance(row, dict) and row.get("role") in ("supporting-video", "image")
                                    for row in plan.get("assets", []))}


def decision_ids(decisions: list) -> set[str]:
    """Catalog ids a visualSources decision names or inspected as the closest alternatives."""
    return {item["id"] for row in decisions if isinstance(row, dict) for key in ("catalog", "inspected")
            for item in row.get(key) or [] if isinstance(item, dict) and isinstance(item.get("id"), str)}


def plan_focus(plan: dict) -> dict[str, dict]:
    """Entries a critic consults in large request indexes, by artifact key.

    The catalog index stays assigned whole (`search`) whenever a custom or reference route must be judged
    against the catalog, or the routes are unknown; the located entries are then starting points.
    """
    canvas = plan.get("canvas") if isinstance(plan.get("canvas"), dict) else {}
    anchors = sorted({copy["anchor"] for holder in (plan.get("catalogTitle"), canvas.get("titleCard"))
                      if isinstance(holder, dict) and isinstance(copy := holder.get("copy"), dict)
                      and isinstance(copy.get("anchor"), str)})
    sources = plan.get("visualSources")
    decisions = sources.get("decisions") if isinstance(sources, dict) else None
    known = isinstance(decisions, list)
    ids = {row["catalogId"] for row in plan.get("catalogFiles", []) if isinstance(row, dict)
           and isinstance(row.get("catalogId"), str)} | (decision_ids(decisions) if known else set())
    search = not known or any(isinstance(row, dict) and row.get("route") in ("custom", "reference") for row in decisions)
    return {"request:CATALOG-INDEX.json": {"collection": "items", "field": "id", "ids": sorted(ids), "search": search},
            "request:DIRECTOR-LIBRARY.json": {"collection": "anchors", "field": "id", "ids": anchors, "search": False}}


def plan_subject(plan_file: str | Path) -> dict:
    """Everything a plan critic reviews, frozen by hash, plus the authored-plan digest."""
    file = canonical_file(plan_file)
    plan = read_json(file)
    rate = require_native_plan(plan, file)
    plan_row = artifact("plan", file, "The exact plan under review; planHash is its authored-field digest.")
    assets, large = asset_rows(plan)
    review_rows, prior, authors = bound_review(plan)
    rows = [plan_row, *request_artifacts(plan), *plan_bindings(plan), *assets, *review_rows,
            *previous_records(file.parent, ("PREBUILD-REVIEW",))]
    subject = {"plan": {"path": str(file), "sha256": plan_row["sha256"], "planHash": plan_hash(plan)},
               **canvas_summary(plan, rate), "scenes": scene_rows(plan, rate), "boundPrebuildReview": prior}
    return {"artifacts": rows, "declaredMedia": large, "authors": authors, "subject": subject, "plan": plan,
            "features": plan_features(plan)}


def project_entries(project: Path) -> list[Path]:
    """Top-level files plus staged compositions and references; assets stay manifest-bound."""
    entries = [path for path in sorted(project.iterdir()) if not path.is_dir()]
    for name in PROJECT_FOLDERS:
        if (project / name).is_dir():
            entries.extend(sorted((project / name).iterdir()))
    linked = [str(path) for path in entries if path.is_symlink() or not path.is_file()]
    if linked:
        raise ArtifactError(f"native project contains linked or special entries: {linked[:4]}")
    return entries


def project_subject(project_dir: str | Path) -> dict:
    """A staged native Short project: its files, current plan digest and bound review."""
    project = canonical_directory(project_dir)
    if not (project / "SHORT-PROJECT.json").is_file() or (project / "LONG-PROJECT.json").exists():
        raise ArtifactError(f"{project} is not a native Short project (exactly SHORT-PROJECT.json required)")
    rows = [artifact(f"project:{path.relative_to(project)}", path, "Staged native project file.")
            for path in project_entries(project)]
    plan = read_json(project / "SHORT-PROJECT.json")
    rate = require_native_plan(plan, project / "SHORT-PROJECT.json")
    review_rows, prior, authors = bound_review(plan)
    subject = {"project": str(project), "planHash": plan_hash(plan), **canvas_summary(plan, rate),
               "scenes": scene_rows(plan, rate), "boundPrebuildReview": prior}
    return {"artifacts": [*rows, *review_rows, *request_artifacts(plan)], "declaredMedia": [],
            "authors": authors, "subject": subject, "plan": plan, "rate": rate, "project": project,
            "features": plan_features(plan)}


MAX_PREVIOUS_RECORDS = 64


def previous_records(directory: Path, prefixes: tuple[str, ...]) -> list[dict]:
    """Published review records beside the subject, in version order; drafts and packets are excluded."""
    pattern = re.compile(rf"({'|'.join(map(re.escape, prefixes))})(?:-v(\d+))?\.json")
    found = [(match.group(1), int(match.group(2) or 0), name) for name in os.listdir(directory)
             if (match := pattern.fullmatch(name))]
    if len(found) > MAX_PREVIOUS_RECORDS:
        raise ArtifactError(f"{directory} holds {len(found)} earlier review records (limit {MAX_PREVIOUS_RECORDS}); "
                            "archive older records outside this directory before resolving a packet")
    return [artifact(f"previous:{name}", directory / name, "Earlier review record in this directory: context "
                     "for what was already found; historical, not current approval.") for _, _, name in sorted(found)]


def job_artifacts(job_dir: str | Path) -> list[dict]:
    """Known brief, handoff and instruction markers in an explicitly selected job directory."""
    root = canonical_directory(job_dir)
    return [artifact(f"job:{name}", root / name, "Job brief/handoff/state marker in the selected directory; "
                     "read it for the accepted requirements.")
            for name in PROJECT_FILES if (root / name).is_file() and not (root / name).is_symlink()]
