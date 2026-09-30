"""Plan-critic time budgets and mechanical receipts for role packets (P2-11).

``review_budget`` turns ``REVIEW_BUDGETS`` into batch-clock deadlines for one plan-critic packet. ``earlyBy`` is the
checkpoint by which every material issue found so far should have been submitted as an early finding (the
coordinator routes those records then; the absence of early findings is never a pass). ``hardBy`` is the final-record
deadline at which the coordinator interrupts the critic (supervised):
``hardBy = min(resolved + hardSeconds, preparationSeconds - REPAIR_START_MARGIN_SECONDS)`` on P1's counted
``clip_deadlines(record, clip)['preparationSeconds']``, so a repair can still be claimed before the clip's
preparation deadline. ``no-repair-window`` when ``hardBy <= resolved`` (the critic still runs; its verdict is routed);
``unbatched`` outside a batch (no clock, no deadlines). A packet that follows an earlier plan review
(``--prior-reviews``) is a repair. The packet carries its budget terms (``budget_terms``); the absolute deadlines
are computed by the batch authority at the packet's recorded resolution, under the batch lock
(``resolution_budget``, called by ``studio.production.packets.record_packet_resolved``), and recorded on the
``packet-resolved`` event, so every reader takes them from the trail.

``receipt_rows`` binds the pre-render checks that passed on the reviewed plan's exact hash: one early report
(``native-short-early-defect-report`` schema 2, ``no-early-defects-found``) and one build receipt (the built
project's ``PROJECT-MANIFEST.json``: ``native-short-review-project``, structural strategy checks ``passed``). Both
name the same staged project, whose manifest-bound ``SHORT-PROJECT.json`` has the plan's hash (generated bindings
and ``draft`` excluded, as ``nativeShortPrebuildPlanHash`` does). Anything else is refused by name. A receipt says
what passed; it approves nothing and is not a review.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cut_preview_io import read_bytes
from role_packet_catalog import REPAIR_START_MARGIN_SECONDS, RECEIPT_CHECKS, REVIEW_BUDGETS
from role_packet_files import ArtifactError, artifact, canonical_directory, canonical_file, read_json
from role_packet_native import plan_hash
from studio.production.formats import clip_deadlines

EARLY_SCOPE, EARLY_PASS, EARLY_SCHEMA = "native-short-early-defect-report", "no-early-defects-found", 2
BUILD_SCOPE, BUILD_PASS = "native-short-review-project", "passed"
PLAN_FILE, MANIFEST, MAX_PLAN_BYTES = "SHORT-PROJECT.json", "PROJECT-MANIFEST.json", 16 * 1024 * 1024
RECEIPT_WHY = {"early-report": "Passing early report (static preflight, reveal probe) of the built project.",
               "build": "Built project's manifest: the build's structural checks passed for this plan hash."}


@dataclass(frozen=True)
class BudgetRequest:
    """One packet's budget inputs: role, batch record and clip (None outside a batch), resolution time, repair."""

    role: str
    record: dict | None
    clip: str | None
    resolved: float | None
    repair: bool


def review_budget(request: BudgetRequest) -> dict:
    """{kind, status, resolvedElapsed, earlyBy, hardBy} in batch-clock elapsed seconds (None outside a batch)."""
    kind = f"{request.role}-repair" if request.repair else request.role
    if kind not in REVIEW_BUDGETS:
        raise ArtifactError(f"no review budget is defined for {kind}")
    if request.record is None or request.clip is None or request.resolved is None:
        return {"kind": kind, "status": "unbatched", "resolvedElapsed": None, "earlyBy": None, "hardBy": None}
    seconds, resolved = REVIEW_BUDGETS[kind], request.resolved
    preparation = clip_deadlines(request.record, request.record["clips"][request.clip])["preparationSeconds"]
    hard = round(min(resolved + seconds["hardSeconds"], preparation - REPAIR_START_MARGIN_SECONDS), 3)
    early = round(min(resolved + seconds["earlySeconds"], hard), 3)
    return {"kind": kind, "status": "no-repair-window" if hard <= resolved else "bounded", "resolvedElapsed": resolved,
            "earlyBy": early, "hardBy": hard}


def budget_terms(repair: bool) -> dict:
    """The budget terms a plan-critic packet carries; its deadlines are recorded at its resolution (batch only)."""
    kind = "plan-critic-repair" if repair else "plan-critic"
    return {"kind": kind, **REVIEW_BUDGETS[kind], "repairStartMarginSeconds": REPAIR_START_MARGIN_SECONDS,
            "deadlines": "recorded on the packet-resolved event (context.py --role: batchClock.budget; "
                         "--given-check: budget)"}


def resolution_budget(clip: str, terms: dict) -> Callable[[dict, float], dict]:
    """The authority's budget rule for one packet: its deadlines on the locked record at the recorded resolution."""
    repair = terms.get("kind") == "plan-critic-repair"
    return lambda record, resolved: review_budget(BudgetRequest("plan-critic", record, clip, resolved, repair))


def project_plan_hash(project: Path) -> str:
    """The plan hash of a built project's SHORT-PROJECT.json, whose bytes its PROJECT-MANIFEST.json must bind."""
    manifest = read_json(project / MANIFEST)
    rows = [row.get("sha256") for row in manifest.get("files") or []
            if isinstance(row, dict) and row.get("file") == PLAN_FILE]
    raw = read_bytes(project / PLAN_FILE, MAX_PLAN_BYTES)   # one no-follow read: the hashed bytes are the parsed ones
    if manifest.get("scope") != BUILD_SCOPE or rows != [hashlib.sha256(raw).hexdigest()]:
        raise ArtifactError(f"{project} is not a built native Short project whose manifest binds its {PLAN_FILE}")
    return plan_hash(json.loads(raw))


def receipt_row(path: str, wanted: str) -> dict:
    """One receipt, refused unless it passed and its built project has the plan hash ``wanted``."""
    file = canonical_file(path)
    value = read_json(file)
    if value.get("scope") == EARLY_SCOPE:
        kind, status = "early-report", value.get("status")
        if value.get("schemaVersion") != EARLY_SCHEMA:
            raise ArtifactError(f"receipt {file} is early report schema {value.get('schemaVersion')}, not "
                                f"{EARLY_SCHEMA} (with the reveal probe)")
        passed, project = status == EARLY_PASS, value.get("project")
    elif value.get("scope") == BUILD_SCOPE and file.name == MANIFEST:
        kind, status = "build", value.get("structuralStrategyChecks")
        passed, project = status == BUILD_PASS, str(file.parent)
    else:
        raise ArtifactError(f"receipt {file} is neither an early report nor a built project's {MANIFEST}")
    if not passed:
        raise ArtifactError(f"receipt {file} did not pass ({status})")
    if not isinstance(project, str) or not Path(project).is_absolute():
        raise ArtifactError(f"receipt {file} names no absolute project")
    found = project_plan_hash(canonical_directory(project))
    if found != wanted:
        raise ArtifactError(f"receipt {file} is for plan {found}, not {wanted}")
    return {**artifact(f"receipt:{kind}", file, RECEIPT_WHY[kind]), "kind": kind, "status": status,
            "project": str(canonical_directory(project)), "planHash": found}


def receipt_rows(paths: tuple[str, ...], wanted: str) -> list[dict]:
    """Exactly one passing early report and one build receipt, of one built project with the plan hash ``wanted``."""
    rows = [receipt_row(path, wanted) for path in paths]
    kinds = {row["kind"]: row for row in rows}
    if len(rows) != 2 or set(kinds) != {"early-report", "build"}:
        raise ArtifactError("mechanical receipts are exactly one early report and one build receipt "
                            f"({MANIFEST}) of the same built project")
    early, build = kinds["early-report"], kinds["build"]
    if early["project"] != build["project"]:
        raise ArtifactError(f"receipt {early['path']} is for project {early['project']}, not {build['project']}")
    return rows


def review_inputs(role: str, receipts: tuple[str, ...], prior: str | None, plan: dict | None) -> dict:
    """Receipt and prior-review artifacts of one packet request, its receipt rows and whether it is a repair.

    Receipts bind only a plan-critic or clip-owner packet with a plan; a plan-critic packet that names an earlier
    plan review (``--prior-reviews``) is a repair, and that record is frozen as history.
    """
    rows: list[dict] = []
    if receipts:
        if role not in RECEIPT_CHECKS or plan is None:
            raise ArtifactError("--receipt binds a plan's receipts: only for a plan-critic or clip-owner packet with a "
                                "plan (--plan, or an owner's --native-project)")
        rows = receipt_rows(receipts, plan_hash(plan))
    frozen = [{key: row[key] for key in ("key", "path", "sha256", "bytes", "observation", "why")} for row in rows]
    if role == "plan-critic" and prior:
        frozen.append(artifact("prior-plan-review", prior, "The earlier plan review this repair critic follows."))
    summary = [{key: row[key] for key in ("kind", "path", "sha256", "status", "project", "planHash")} for row in rows]
    return {"artifacts": frozen, "receipts": summary if receipts else None,
            "repair": role == "plan-critic" and bool(prior)}
