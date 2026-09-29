"""Resolve, publish and render versioned native-Short role packets for owners and critics.

A packet freezes the governing instruction sections that apply to the role and its subject,
the exact current artifacts and their hashes (including optional shared source evidence),
the role's required checks and obligations, the typed submission command and its own size.
Inputs are explicit paths; nothing is selected by recency. The packet never reads media for
the reviewer, supplies a verdict or grants approval.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from context_inventory import codex_root
from role_packet_catalog import (APPROVAL_CHECKS, CATALOG_VERSION, CHECKS, EVIDENCE_CHECKS, FEATURE_CHECKS, INSTRUCTIONS,
                                 LIMITS, OBLIGATIONS, READING, RECORD_PREFIX, ROUTE)
from role_packet_evidence_record import bind_evidence
from role_packet_given import GivenRequest, resolve_given
from role_packet_given_check import record_resolution
from role_packet_files import (ArtifactError, artifact, canonical_directory, new_output, proposed_paths, read_json,
                               json_bytes, staged_work, write_json_new)
from role_packet_media import export_subject, preview_subject
from role_packet_native import job_artifacts, plan_focus, plan_subject, project_subject, request_value
from role_packet_scope import with_reading, with_size
from role_packet_sections import SectionError, instruction_rows
from role_packet_speech import planned_source
from role_packet_submission import critic_submission, observation_draft, owner_steps

CRITIC_INPUT = {"plan-critic": ("plan", plan_subject), "motion-critic": ("preview", preview_subject),
                "final-critic": ("export", export_subject)}
OWNER_INPUTS = (("plan", "plan", plan_subject), ("native_project", "project", project_subject),
                ("preview", "preview", preview_subject), ("export", "export", export_subject))


@dataclass(frozen=True)
class RoleRequest:
    """Explicit inputs for one role packet."""
    role: str
    plan: str | None = None
    native_project: str | None = None
    preview: str | None = None
    export: str | None = None
    project: str | None = None
    author_session: str | None = None
    prior_reviews: str | None = None
    packet_out: str | None = None
    shared_evidence: str | None = None
    batch: str | None = None
    clip: str | None = None


def critic_parts(request: RoleRequest) -> dict:
    """Resolve the one immutable input a critic reviews."""
    name, resolver = CRITIC_INPUT[request.role]
    value = getattr(request, name)
    if not value:
        raise ArtifactError(f"--role {request.role} requires --{name}")
    parts = resolver(value)
    if request.role == "motion-critic":
        authors = {*parts["authors"], *([request.author_session] if request.author_session else [])}
        parts = with_retention(parts, request.prior_reviews, authors)
    return parts


def retainable(review: dict, authors: set[str]) -> bool:
    """Only a passing, typed motion approval with zero material issues from a non-author covers a reused unit.

    A historical row without typed inspection, a pass approving picture only, or a route-canary TEST fixture
    declaration never establishes motion playback.
    """
    verdict = review.get("review") if isinstance(review.get("review"), dict) else {}
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    inspection = review.get("inspection") if isinstance(review.get("inspection"), dict) else {}
    approves = inspection.get("approves") if isinstance(inspection.get("approves"), list) else []
    return (verdict.get("verdict") == "pass" and verdict.get("materialIssues") == []
            and reviewer.get("sessionId") not in authors and "motion" in approves and "fixture" not in inspection)


def with_retention(parts: dict, prior: str | None, authors: set[str]) -> dict:
    """Name the earlier review rows that still bind reused units, or the units left uncovered."""
    subject = parts["subject"]
    reused = set(subject.get("reusedUnits") or [])
    current = {unit["id"]: unit["hash"] for unit in subject["units"]}
    if not prior:
        subject["retention"] = {"reusedUnits": sorted(reused), "record": None, "rows": [], "missingUnits": sorted(reused)}
        return parts
    row = artifact("prior-motion-reviews", prior, "Earlier motion reviews retained verbatim for unchanged units.")
    reviews = [review if isinstance(review, dict) else {} for review in read_json(row["path"]).get("reviews", [])]
    units = [review.get("units") if isinstance(review.get("units"), dict) else {} for review in reviews]
    covered = [{uid for uid, digest in rows.items() if uid in reused and current.get(uid) == digest}
               if retainable(review, authors) else set() for review, rows in zip(reviews, units)]
    keep = [index for index, found in enumerate(covered) if found]
    subject["retention"] = {"reusedUnits": sorted(reused), "record": {"path": row["path"], "sha256": row["sha256"]},
                            "rows": keep, "missingUnits": sorted(reused - set().union(*covered))}
    parts["artifacts"].append(row)
    return parts


def owner_parts(request: RoleRequest) -> dict:
    """Resolve whichever clip artifacts the owner already has."""
    parts = {key: resolver(getattr(request, attr)) for attr, key, resolver in OWNER_INPUTS if getattr(request, attr)}
    if not parts and not request.project:
        raise ArtifactError("--role clip-owner needs --plan, --native-project, --preview, --export or --project")
    return {"artifacts": [row for part in parts.values() for row in part["artifacts"]],
            "declaredMedia": [row for part in parts.values() for row in part["declaredMedia"]],
            "authors": [name for part in parts.values() for name in part["authors"]],
            "subject": {key: part["subject"] for key, part in parts.items()},
            "plan": next((part["plan"] for part in parts.values() if "plan" in part), None)}


def subject_home(subject: dict) -> Path | None:
    """Beside the plan file, else beside the project or export directory (never inside them)."""
    if isinstance(subject.get("plan"), dict) and "path" in subject["plan"]:
        return Path(subject["plan"]["path"]).parent
    if isinstance(subject.get("export"), dict) and "directory" in subject["export"]:
        return Path(subject["export"]["directory"]).parent
    if isinstance(subject.get("project"), str):
        return Path(subject["project"]).parent
    return None


def clip_directory(request: RoleRequest, parts: dict) -> Path:
    """Default home for packets and records."""
    subject = parts["subject"]
    if request.role != "clip-owner":
        return subject_home(subject)
    for key in ("plan", "project", "preview", "export"):
        if key in subject:
            return subject_home(subject[key])
    return canonical_directory(request.project)


def subject_rows(subject: dict) -> list[dict]:
    """A critic subject, or every stage subject in an owner packet."""
    nested = [value for key, value in subject.items() if key in ("plan", "project", "preview", "export")
              and isinstance(value, dict) and "artifacts" not in value and ("scenes" in value or "windows" in value)]
    return [subject, *nested]


def protected_directories(parts: dict) -> list[Path]:
    """Authored project and attempt directories that packets and records must stay out of."""
    found = []
    for row in subject_rows(parts["subject"]):
        project, export, preview = row.get("project"), row.get("export"), row.get("preview")
        found.append(project if isinstance(project, str) else None)
        found.append(export.get("directory") if isinstance(export, dict) else None)
        found.append(str(Path(preview["path"]).parent) if isinstance(preview, dict) and "path" in preview else None)
    return [Path(value) for value in found if isinstance(value, str)]


def packet_paths(request: RoleRequest, parts: dict) -> dict:
    """Unused packet, observation draft and record paths sharing one version, outside all staged work."""
    prefix = RECORD_PREFIX[request.role]
    if request.packet_out:
        packet = new_output(request.packet_out)
        paths = {**proposed_paths(packet.parent, prefix), "packet": packet}
    else:
        paths = proposed_paths(clip_directory(request, parts), prefix)
    home = paths["packet"].parent
    for protected in [*protected_directories(parts), staged_work(home)]:
        if protected is not None and (home == protected or protected in home.parents):
            raise ArtifactError(f"role packets, drafts and review records must stay outside the staged project or "
                                f"attempt {protected}; pass --packet-out in a directory outside it")
    return paths


def scoped_instruction_files(directory: Path) -> list[Path]:
    """Global and ancestor AGENTS.md files that govern the selected directory."""
    candidates = [codex_root() / "AGENTS.md", *(parent / "AGENTS.md" for parent in reversed((directory, *directory.parents)))]
    return [path for path in dict.fromkeys(candidates) if path.is_file()]


def evidence_subject(request: RoleRequest, parts: dict) -> dict:
    """What shared evidence must describe: the plan's source and request manifest, or an owner's project."""
    plan = parts.get("plan")
    if plan is None:
        return {"plan": False, "project": request.project}
    manifest = (request_value(plan) or {}).get("manifest")
    return {"plan": True, "source": planned_source(plan),
            "manifest": manifest.get("sha256") if isinstance(manifest, dict) else None}


def shared_inputs(request: RoleRequest, parts: dict, authors: list[str]) -> tuple[list[dict], dict]:
    """Frozen artifacts with reading classes, the evidence summary and the given title/script facts."""
    evidence = (bind_evidence(request.shared_evidence, evidence_subject(request, parts), authors)
                if request.shared_evidence else {"artifacts": [], "summary": None})
    given = resolve_given(GivenRequest(request.batch, request.clip), parts.get("plan"))
    rows = unique_rows(parts["artifacts"] + job_rows(request) + evidence["artifacts"])
    critic = request.role != "clip-owner" and parts.get("plan") is not None
    return with_reading(rows, plan_focus(parts["plan"]) if critic else None), {**evidence, "given": given}


def role_checks(role: str, given: dict, features: dict | None) -> list[dict]:
    """The role's checks, plus shared-evidence, given title/script and used-feature checks."""
    rows = CHECKS[role] + (EVIDENCE_CHECKS[role] if given["summary"] else ())
    rows += APPROVAL_CHECKS[role] if given["given"]["status"] == "bound" else ()
    rows += tuple(row for feature, by_role in FEATURE_CHECKS.items() if (features or {}).get(feature)
                  for row in by_role.get(role, ()))
    return [{"id": key, "check": text, "source": source} for key, text, source in rows]


def build_packet(request: RoleRequest, parts: dict, repo: Path, paths: dict) -> dict:
    """Assemble the frozen packet body; critics get sections scoped to their subject's features."""
    authors = sorted({*parts["authors"], *([request.author_session] if request.author_session else [])})
    home = clip_directory(request, parts)
    features = None if request.role == "clip-owner" else parts.get("features")
    artifacts, given = shared_inputs(request, parts, authors)
    packet = {"schemaVersion": 1, "kind": "sniper-role-packet", "catalog": CATALOG_VERSION, "role": request.role,
              "route": ROUTE, "resolvedAt": datetime.now(timezone.utc).isoformat(), "repository": str(repo),
              "authorSessionIds": authors, "features": features,
              "instructions": instruction_rows(repo, INSTRUCTIONS[request.role], scoped_instruction_files(home), features),
              "reading": READING, "artifacts": artifacts, "declaredMedia": parts["declaredMedia"],
              "sharedEvidence": given["summary"], "given": given["given"],
              "subject": parts["subject"], "checks": role_checks(request.role, given, features),
              "obligations": {key: {"statement": text, "checks": list(ids)}
                              for key, (text, ids) in OBLIGATIONS[request.role].items()},
              "limits": list(LIMITS)}
    if request.role == "clip-owner":
        packet["submission"] = {"steps": owner_steps(parts["subject"], home, request.author_session)}
    else:
        packet["submission"] = critic_submission(request.role, paths, parts["subject"])
    return packet


def job_rows(request: RoleRequest) -> list[dict]:
    """Job markers from an explicitly selected --project directory."""
    return job_artifacts(request.project) if request.project else []


def unique_rows(rows: list[dict]) -> list[dict]:
    """First observation of each canonical path, in resolution order."""
    seen: set[str] = set()
    return [row for row in rows if not (row["path"] in seen or seen.add(row["path"]))]


def with_evidence_basis(draft: dict, packet: dict) -> dict:
    """With shared evidence bound, each plan scene records whether it was inspected or rests on the evidence alone."""
    if packet["sharedEvidence"] is None or "scenes" not in draft:
        return draft
    return {**draft, "scenes": [{**row, "evidenceBasis": None} for row in draft["scenes"]]}


def resolve_role_packet(request: RoleRequest, repo: Path) -> dict:
    """Resolve and publish one packet (plus a structure-only observations draft for critics)."""
    started = time.monotonic()
    parts = owner_parts(request) if request.role == "clip-owner" else critic_parts(request)
    paths = packet_paths(request, parts)
    packet = with_size(build_packet(request, parts, repo, paths))
    resolved = time.monotonic()
    expected = hashlib.sha256(json_bytes(packet)).hexdigest()
    clock = record_resolution(packet, expected)       # the batch clock, before the packet exists
    sha256 = write_json_new(paths["packet"], packet)
    published = {"packet": str(paths["packet"]), "sha256": sha256, "batchClock": clock}
    if request.role != "clip-owner":
        draft = with_evidence_basis(observation_draft(request.role, sha256, packet["subject"], packet["authorSessionIds"]),
                                    packet)
        write_json_new(paths["observations"], draft)
        published |= {"observations": str(paths["observations"]), "record": str(paths["record"])}
    published["timing"] = {"resolveSeconds": round(resolved - started, 3),
                           "totalSeconds": round(time.monotonic() - started, 3)}
    return {"packet": packet, "published": published}


__all__ = ["RoleRequest", "resolve_role_packet", "ArtifactError", "SectionError"]
