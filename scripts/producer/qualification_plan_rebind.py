#!/usr/bin/env python3
"""Rebind an approved provisional plan to qualified-media transcript authority."""

from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import claims_contract
import operator_intent_contract
import plan_lint
import transcript_cut_contract
from graphics_planner import build_proposal, output_words
from qualification_plan_rebind_inputs import (
    RebindAuthorityPaths,
    RebindError,
    select_source,
    verify_authorities,
    visual_state_authority,
)
from qualification_plan_rebind_publish import (
    RebindPublication,
    publish_bundle,
)
from qualification_plan_rebind_semantics import (
    match_beats as _match_beats,
    rebind_graphics as _rebind_graphics,
)


@dataclass(frozen=True)
class RebindRequest:
    """Filesystem inputs and outputs for one rebind attempt."""

    plan: Path
    proposal: Path
    manifest: Path
    transcripts_dir: Path
    qualification: Path
    cadence_approval: Path
    expected_intent: Path
    visual_state: Path
    output: Path
    proposal_output: Path
    report: Path
    source_id: str | None = None


@dataclass(frozen=True)
class RebindPreparation:
    """Verified candidate authorities and fresh semantic proposal."""

    source: dict
    old_source_id: str
    qualification: dict
    cadence: dict
    expected_intent: dict
    visual_state_receipt: dict
    proposal: dict
    shifts: list[dict]


def _read_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RebindError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise RebindError(f"{label} root must be an object")
    return value


def _source_rows(plan: dict) -> tuple[list[dict], list[dict]]:
    cuts = plan.get("cutTrack")
    decisions = plan.get("cutDecisions")
    removals = decisions.get("removals") if isinstance(decisions, dict) else None
    if not isinstance(cuts, list) or not cuts or not isinstance(removals, list):
        raise RebindError("provisional cut authority is malformed")
    if not all(isinstance(row, dict) for row in cuts + removals):
        raise RebindError("provisional cut authority contains a malformed row")
    return cuts, removals


def _replace_source(plan: dict, source_id: str) -> str:
    cuts, removals = _source_rows(plan)
    source_ids = [row.get("sourceId") for row in cuts + removals]
    if not all(type(value) is str and value for value in source_ids):
        raise RebindError("provisional cut authority has no sourceId")
    cut_ids = {row["sourceId"] for row in cuts}
    removal_ids = {row["sourceId"] for row in removals}
    if len(cut_ids) != 1 or removal_ids - cut_ids:
        raise RebindError("provisional cut authority does not use one source")
    old_id = next(iter(cut_ids))
    for row in cuts + removals:
        row["sourceId"] = source_id
    return old_id


def _stamp_visual_state(plan: dict, state: dict) -> None:
    plan["faceBBoxNorm"] = [float(value) for value in state["faceBBoxNorm"]]
    for zone in plan.get("treatmentMap") or []:
        zone["visualState"] = state["state"]


def _expected_intent(path: Path, manifest_path: Path) -> dict:
    absolute = Path(os.path.abspath(path))
    expected = Path(os.path.abspath(manifest_path)).parent.parent / "project.json"
    if absolute != expected or absolute.is_symlink():
        raise RebindError(
            "stored operator intent must be the fresh project's project.json"
        )
    document = _read_object(path, "stored operator intent")
    value = document.get("resolvedIntent")
    if not isinstance(value, dict):
        raise RebindError("stored operator intent has no resolvedIntent object")
    return value


def _gate_candidate(
    candidate: dict,
    request: RebindRequest,
    manifest: dict,
    expected_intent: dict,
) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(candidate, handle, indent=2)
        handle.write("\n")
        candidate_path = handle.name
    try:
        cut = transcript_cut_contract.check(
            candidate_path, str(request.transcripts_dir), str(request.manifest)
        )
        words = output_words(candidate, str(request.transcripts_dir), manifest)
        lint_report = plan_lint.lint(candidate, manifest, words)
        claims_report = plan_lint.Report()
        claims_contract.check_claims_contract(candidate, words, claims_report)
        return {
            "operatorIntent": operator_intent_contract.evaluate(
                candidate, expected_intent
            ),
            "transcriptCut": cut,
            "planLint": _report(lint_report),
            "claims": _report(claims_report),
        }
    finally:
        os.unlink(candidate_path)


def _report(report: plan_lint.Report) -> dict:
    return {
        "ok": not report.errors,
        "errors": report.errors,
        "warnings": report.warnings,
    }


def _prepare_candidate(
    request: RebindRequest,
    plan: dict,
    previous: dict,
    manifest: dict,
) -> RebindPreparation:
    expected_intent = _expected_intent(
        request.expected_intent, request.manifest
    )
    source = select_source(manifest, request.source_id)
    old_source = _replace_source(plan, str(source["id"]))
    qualification, cadence = verify_authorities(
        plan,
        manifest,
        RebindAuthorityPaths(
            request.manifest,
            request.qualification,
            request.cadence_approval,
        ),
        source,
    )
    visual_receipt, state = visual_state_authority(
        request.visual_state, source
    )
    _stamp_visual_state(plan, state)
    fresh = build_proposal(
        plan,
        str(request.transcripts_dir),
        manifest,
        [state],
        aspect="16:9",
        style="overlay-rich",
    )
    shifts = _rebind_graphics(plan, _match_beats(previous, fresh))
    return RebindPreparation(
        source=source,
        old_source_id=old_source,
        qualification=qualification,
        cadence=cadence,
        expected_intent=expected_intent,
        visual_state_receipt=visual_receipt,
        proposal=fresh,
        shifts=shifts,
    )


def execute(request: RebindRequest) -> dict:
    """Build, gate, and publish one fresh-authority plan last."""
    plan = copy.deepcopy(_read_object(request.plan, "provisional plan"))
    previous = _read_object(request.proposal, "provisional proposal")
    manifest = _read_object(request.manifest, "fresh manifest")
    manifest["_path"] = str(request.manifest.resolve())
    prepared = _prepare_candidate(request, plan, previous, manifest)
    gates = _gate_candidate(
        plan, request, manifest, prepared.expected_intent
    )
    failed = [name for name, result in gates.items() if not result["ok"]]
    if failed:
        raise RebindError(
            "rebound plan failed production gates",
            {"failedGates": failed, "gates": gates},
        )
    result = {
        "ok": True,
        "oldSourceId": prepared.old_source_id,
        "newSourceId": prepared.source["id"],
        "qualificationEvidenceDigest": prepared.qualification["evidenceDigest"],
        "cadenceApprovalDigest": prepared.cadence["approvalDigest"],
        "visualStateReceiptDigest":
            prepared.visual_state_receipt["receiptDigest"],
        "visualStateRowsSha256":
            prepared.visual_state_receipt["measurement"]["rowsSha256"],
        "semanticBeatShifts": prepared.shifts,
        "gates": gates,
    }
    return publish_bundle(
        RebindPublication(
            output=request.output,
            plan=plan,
            proposal_output=request.proposal_output,
            proposal=prepared.proposal,
            report=request.report,
            result=result,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "plan",
        "proposal",
        "manifest",
        "transcripts-dir",
        "qualification",
        "cadence-approval",
        "expected-intent",
        "visual-state",
        "output",
        "proposal-output",
        "report",
    ):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--source-id")
    return parser


def _request(args: argparse.Namespace) -> RebindRequest:
    return RebindRequest(
        plan=Path(args.plan),
        proposal=Path(args.proposal),
        manifest=Path(args.manifest),
        transcripts_dir=Path(args.transcripts_dir),
        qualification=Path(args.qualification),
        cadence_approval=Path(args.cadence_approval),
        expected_intent=Path(args.expected_intent),
        visual_state=Path(args.visual_state),
        output=Path(args.output),
        proposal_output=Path(args.proposal_output),
        report=Path(args.report),
        source_id=args.source_id,
    )


def main() -> int:
    try:
        result, code = execute(_request(_parser().parse_args())), 0
    except (OSError, RebindError, TypeError, ValueError) as exc:
        details = exc.details if isinstance(exc, RebindError) else {}
        result, code = {"ok": False, "error": str(exc), **details}, 1
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
