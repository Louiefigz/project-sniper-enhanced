"""Qualify one real short/long Desktop build in an isolated Palmier project."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "producer"))

from fingerprints import file_sha256  # noqa: E402
from palmier.live_acceptance_cleanup import cleanup_cohort  # noqa: E402
from palmier.live_acceptance_cohort import (  # noqa: E402
    build_cohort, resume_cohort)
from palmier.live_acceptance_fault_evidence import (  # noqa: E402
    combined_receipts, fault_client, response_loss_evidence)
from palmier.live_acceptance_session import (  # noqa: E402
    Evidence, LiveAcceptanceConfig, validate_config)
from palmier.live_acceptance_runtime import (  # noqa: E402
    AcceptanceClient, Deadline, MutationInventory)
from palmier.mcp_client import PalmierError  # noqa: E402
from palmier.process_deadline import use_process_deadline  # noqa: E402
from palmier.sync_lock import SyncLock, SyncLockState  # noqa: E402


@dataclass
class _RunContext:
    config: LiveAcceptanceConfig
    evidence: Evidence
    deadline: Deadline
    inventory: MutationInventory
    client: AcceptanceClient
    previous_connections: list[dict]
    cleanup_connections: list[dict]
    previous_fault_receipts: list[dict]
    cleanup_fault_receipts: list[dict]


def _record_failure(context: _RunContext, exc: BaseException) -> None:
    config, evidence = context.config, context.evidence
    if config.mode == "resume" and "reviews" in str(exc):
        evidence.value.update({"status": "review-mismatch", "error": {
            "type": type(exc).__name__, "message": str(exc)}})
        evidence.save()
    else:
        evidence.fail(exc)


def _checkpointed_handles(
        evidence: Evidence, prior: dict | None,
        project: dict | None) -> tuple[dict | None, dict | None]:
    """Recover cleanup identities saved before a late cohort failure."""
    phases = evidence.value.get("phases") or {}
    if prior is None:
        candidate = phases.get("resumePrior") or phases.get("prior")
        prior = candidate if isinstance(candidate, dict) else None
    if project is None:
        candidate = phases.get("project")
        project = candidate if isinstance(candidate, dict) else None
    return prior, project


def _attempt(
        context: _RunContext
) -> tuple[BaseException | None, dict | None, dict | None]:
    config, evidence, client = (
        context.config, context.evidence, context.client)
    prior, project, failure = None, None, None
    try:
        if config.mode == "resume":
            prior, project = resume_cohort(client, config, evidence)
        else:
            prior, project = build_cohort(client, config, evidence)
    except BaseException as exc:
        failure = exc
        _record_failure(context, exc)
    prior, project = _checkpointed_handles(evidence, prior, project)
    if failure is None:
        try:
            context.deadline.check()
        except BaseException as exc:
            failure = exc
            _record_failure(context, exc)
    evidence.value["cleanupPolicy"] = {
        "trashDisposable": failure is None and config.mode == "resume"}
    return failure, prior, project


def _cleanup(
        context: _RunContext, prior: dict | None,
        project: dict | None) -> list[str]:
    deadline = Deadline(context.config.cleanup_timeout_s)
    client = fault_client(deadline, context.inventory)
    errors: list[str] = []
    with use_process_deadline(deadline):
        try:
            context.client.close(deadline.remaining(), deadline)
        except BaseException as exc:
            errors.append(f"main client close: {exc}")
        if errors:
            policy = context.evidence.value.setdefault("cleanupPolicy", {})
            policy["trashDisposable"] = False
            context.evidence.value.setdefault("cleanup", {})[
                "retainedReason"
            ] = "main MCP client close was not proved"
            context.evidence.save()
        try:
            with client.phase("cleanup-restore"):
                errors.extend(cleanup_cohort(
                    client, context.evidence, prior, project))
            client.bind_proof("cleanup-restore", {
                "kind": "project-restoration-readback",
                "cleanup": context.evidence.value.get("cleanup"),
            })
        except BaseException as exc:
            errors.append(str(exc))
        try:
            client.close(deadline.remaining(), deadline)
        except BaseException as exc:
            errors.append(f"cleanup client close: {exc}")
    context.cleanup_connections.extend(client.connections)
    context.cleanup_fault_receipts.extend(client.response_loss_receipts)
    return errors


def _verify_runtime(
        context: _RunContext, failure: BaseException | None,
        cleanup_errors: list[str]) -> BaseException | None:
    config, inventory = context.config, context.inventory
    try:
        context.client.close()
        journal = os.path.join(
            config.out_dir, ".palmier-desktop-operations.jsonl")
        if os.path.isfile(journal):
            inventory.bind_desktop_journal(journal)
        if failure is None and not cleanup_errors:
            receipts = combined_receipts(
                context.previous_fault_receipts,
                context.client.response_loss_receipts,
                context.cleanup_fault_receipts)
            inventory.assert_response_loss_receipts(receipts)
            required = {
                "project-lifecycle", "bootstrap-authority",
                "candidate-fork", "desktop-journal", "qc-export",
                "cleanup-restore",
            }
            if config.mode == "resume":
                required.add("manual-preservation")
            inventory.assert_complete(
                required, require_response_loss=True)
    except BaseException as exc:
        if failure is None:
            context.evidence.fail(exc)
            return exc
    return failure


def _finish(
        context: _RunContext, failure: BaseException | None,
        cleanup_errors: list[str]) -> dict:
    evidence, inventory = context.evidence, context.inventory
    evidence.value["mutationInventory"] = inventory.snapshot()
    evidence.value["sessionChurn"] = {
        "connections": [
            *context.previous_connections, *context.client.connections,
            *context.cleanup_connections],
        "allMutationSessionsUnique": len({
            row["sessionId"] for row in inventory.rows
        }) == len(inventory.rows),
    }
    receipts = combined_receipts(
        context.previous_fault_receipts,
        context.client.response_loss_receipts,
        context.cleanup_fault_receipts)
    evidence.value["responseLossCohort"] = response_loss_evidence(
        inventory, receipts)
    if failure is None and not cleanup_errors:
        status = "passed" if context.config.mode == "resume" \
            else "review-required"
        evidence.value.update({"status": status, "completedAt": time.time()})
    elif failure is None:
        evidence.value.update({"status": "failed", "error": {
            "type": "CleanupError", "message": "; ".join(cleanup_errors)}})
    evidence.save()
    if failure is not None:
        raise failure
    if cleanup_errors:
        raise PalmierError("; ".join(cleanup_errors))
    return evidence.value


def _run_locked(
        config: LiveAcceptanceConfig, deadline: Deadline,
        acquired: Any, evidence: Evidence) -> dict:
    previous = ((evidence.value.get("mutationInventory") or {})
                .get("rows") or []) if config.mode == "resume" else []
    connections = ((evidence.value.get("sessionChurn") or {})
                   .get("connections") or [])
    prior_faults = ((evidence.value.get("responseLossCohort") or {})
                    .get("receipts") or []) if config.mode == "resume" else []
    inventory = MutationInventory(previous)
    context = _RunContext(
        config, evidence, deadline, inventory,
        fault_client(deadline, inventory), connections, [],
        prior_faults, [])
    evidence.phase("lock", {
        "state": acquired.state.value, "planHash": acquired.plan_hash})
    with use_process_deadline(deadline):
        failure, prior, project = _attempt(context)
    errors = _cleanup(context, prior, project)
    failure = _verify_runtime(context, failure, errors)
    return _finish(context, failure, errors)


def run(config: LiveAcceptanceConfig) -> dict:
    deadline = Deadline(config.timeout_s)
    with use_process_deadline(deadline):
        preflight = validate_config(config)
    acquired = SyncLock.acquire(
        config.out_dir, file_sha256(config.plan_path),
        queue_if_busy=False)
    if acquired.state != SyncLockState.ACQUIRED or acquired.lease is None:
        raise PalmierError(
            "live acceptance could not acquire the global Palmier SyncLock")
    evidence = None
    try:
        evidence = Evidence.resume(config, preflight) \
            if config.mode == "resume" else Evidence(config, preflight)
        return _run_locked(config, deadline, acquired, evidence)
    finally:
        acquired.lease.release()
        if evidence is not None:
            evidence.value["lockRelease"] = {
                "released": True, "releasedAt": time.time()}
            evidence.save()
def _config(args: argparse.Namespace) -> LiveAcceptanceConfig:
    return LiveAcceptanceConfig(
        repo=os.path.abspath(args.repo),
        out_dir=os.path.abspath(args.out_dir),
        plan_path=os.path.abspath(args.plan),
        repair_plan_path=os.path.abspath(args.repair_plan),
        manifest_path=os.path.abspath(args.manifest),
        bootstrap_path=os.path.abspath(args.bootstrap),
        transcripts_dir=os.path.abspath(args.transcripts),
        evidence_path=os.path.abspath(args.evidence),
        format=args.format, fps=args.fps, aspect=args.aspect,
        quality=args.quality, prefix=args.prefix,
        timeout_s=args.timeout, mode=args.mode,
        reviews_path=os.path.abspath(args.reviews)
        if args.reviews else None,
        cleanup_timeout_s=args.cleanup_timeout,
        cadence_approval_path=os.path.abspath(args.cadence_approval)
        if args.cadence_approval else None,
        cadence_approval_digest=args.cadence_approval_digest,
        protected_project_path=os.path.abspath(args.protected_project)
        if args.protected_project else None,
    )
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--repair-plan", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--bootstrap", required=True)
    parser.add_argument("--transcripts", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--format", choices=("short", "long"), required=True)
    parser.add_argument("--fps", type=int, required=True)
    parser.add_argument("--aspect", choices=("9:16", "16:9"), required=True)
    parser.add_argument("--quality", choices=("1080p", "720p"), default="1080p")
    parser.add_argument("--prefix", default="Sniper P5 Connected Qualification")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--cleanup-timeout", type=float, default=120.0)
    parser.add_argument("--mode", choices=("build", "resume"), default="build")
    parser.add_argument("--reviews")
    parser.add_argument("--cadence-approval")
    parser.add_argument("--cadence-approval-digest")
    parser.add_argument("--protected-project")
    return parser
def main() -> int:
    args = _parser().parse_args()
    try:
        value = run(_config(args))
    except BaseException as exc:
        print(json.dumps({"ok": False, "error": str(exc),
                          "evidence": os.path.abspath(args.evidence)}, indent=2))
        return 1
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
