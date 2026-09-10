#!/usr/bin/env python3
"""Prove real Palmier paging for one native caption group above 200 rows."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "producer"))

from palmier.desktop_native_captions import (  # noqa: E402
    native_caption_settings)
from palmier.live_caption_probe_input import (  # noqa: E402
    ProbeConfig, source_authority, validate_probe_config)
from palmier.live_acceptance_runtime import (  # noqa: E402
    AcceptanceClient, Deadline, MutationInventory)
from palmier.live_acceptance_project_safety import (  # noqa: E402
    checkpoint_protected_project, fingerprint_protected_project,
    recover_disposable_project, require_active_project,
    require_same_protected_project, require_surface)
from palmier.live_acceptance_fault_evidence import (  # noqa: E402
    combined_receipts, fault_client, response_loss_evidence)
from palmier.live_acceptance_session import (  # noqa: E402
    capture_prior, created_project, restore_project, trash_disposable)
from palmier.live_caption_pagination import (  # noqa: E402
    await_capped_caption_readback)
from palmier.mcp_client import PalmierError  # noqa: E402
from palmier.process_deadline import use_process_deadline  # noqa: E402
from palmier.sync_lock import SyncLock, SyncLockState  # noqa: E402
from palmier.timeline_authority import atomic_write_record  # noqa: E402

class ProbeEvidence:
    """Atomic evidence checkpoints used to recover after any late failure."""

    def __init__(self, config: ProbeConfig, source: dict):
        self.path = config.evidence
        self.value = {
            "schemaVersion": 1,
            "kind": "p5-connected-native-caption-pagination",
            "status": "running", "startedAt": time.time(),
            "config": config.__dict__, "sourceBefore": source, "phases": {},
        }
        self.save()

    def save(self) -> None:
        atomic_write_record(self.path, self.value)

    def phase(self, name: str, value: object) -> None:
        self.value["phases"][name] = value
        self.save()


@dataclass(frozen=True)
class CleanupInput:
    """Runtime identities needed for independent-budget restoration."""

    inventory: MutationInventory
    evidence: ProbeEvidence
    main: AcceptanceClient
    prior: dict | None
    project: dict | None
    receipts: list[dict]
    trash_disposable: bool


@dataclass(frozen=True)
class ProbeOutcome:
    """All facts needed to close one probe without dropping evidence."""

    evidence: ProbeEvidence
    inventory: MutationInventory
    receipts: list[dict]
    failure: BaseException | None
    errors: list[str]


def _build(
        client: AcceptanceClient, config: ProbeConfig,
        evidence: ProbeEvidence, frames: int) -> tuple[dict, dict]:
    prior = capture_prior(client)
    paths = set(prior["knownProjectPaths"])
    evidence.phase("prior", prior)
    protected = checkpoint_protected_project(
        client, config.protected_project_path,
        prior["surface"], "project-lifecycle")
    if protected is not None:
        evidence.phase("protectedBefore", protected)
    name = f"{config.prefix} {int(time.time())}"
    evidence.phase("projectIntent", {"name": name})
    with client.phase("project-lifecycle"):
        client.call_json("new_project", {
            "name": name, "fps": config.fps,
            "aspectRatio": config.aspect, "quality": config.quality,
    })
    project = created_project(client, name, paths)
    evidence.phase("project", project)
    client.bind_proof("project-lifecycle", {
        "kind": "caption-probe-project-readback",
        "projectId": project["id"], "path": project["path"],
    })
    settings = native_caption_settings({
        "target": {"mode": "longform", "aspect": config.aspect},
        "captions": {"style": "karaoke", "maxWords": 1},
    })
    with client.phase("bootstrap-authority"):
        require_active_project(client, project["id"])
        imported = client.call_json("import_media", {
            "source": {"path": config.source},
            "name": "Sniper capped-caption source",
        })
        media_ref = imported.get("mediaRef")
        if not isinstance(media_ref, str):
            raise PalmierError("caption pagination import returned no mediaRef")
        client.wait_media(media_ref)
        require_active_project(client, project["id"])
        client.call_json("add_clips", {"entries": [{
            "mediaRef": media_ref, "startFrame": 0, "endFrame": frames,
        }]})
        require_active_project(client, project["id"])
        client.call_json("add_captions", settings)
    proof = await_capped_caption_readback(client, client.deadline)
    client.bind_proof("bootstrap-authority", proof)
    evidence.phase("pagination", proof)
    return prior, project


def _cleanup(config: ProbeConfig, request: CleanupInput) -> list[str]:
    inventory, evidence, main = request.inventory, request.evidence, request.main
    prior, project = request.prior, request.project
    deadline = Deadline(config.cleanup_timeout_s)
    client = fault_client(deadline, inventory)
    errors = []
    with use_process_deadline(deadline):
        try:
            main.close(deadline.remaining(), deadline)
        except BaseException as exc:
            errors.append(f"main client close: {exc}")
        try:
            if project is None:
                project = recover_disposable_project(
                    client, evidence.value["phases"]["projectIntent"]["name"])
            restored = prior or evidence.value["phases"].get("prior")
            with client.phase("cleanup-restore"):
                proof = restore_project(
                    client, restored or {"project": None}, project)
                protected = None
                if isinstance(config.protected_project_path, str):
                    protected = fingerprint_protected_project(
                        client, config.protected_project_path,
                        restored["surface"])
                    require_same_protected_project(
                        evidence.value["phases"]["protectedBefore"],
                        protected)
            client.bind_proof("cleanup-restore", {
                "kind": "caption-probe-restoration-readback", **proof,
                "protectedProject": protected})
            trashed = False
            retained = None
            if request.trash_disposable and not errors:
                trashed = trash_disposable(project, config.prefix)
            elif isinstance(project, dict):
                retained = project.get("path")
            final_open = require_surface(client, restored["surface"])
            evidence.phase("cleanup", {
                **proof, "protectedProject": protected,
                "trashed": trashed, "retainedForRecovery": retained,
                "finalOpenState": final_open,
            })
        except BaseException as exc:
            errors.append(str(exc))
        try:
            client.close(deadline.remaining(), deadline)
        except BaseException as exc:
            errors.append(f"cleanup client close: {exc}")
    request.receipts.extend(client.response_loss_receipts)
    return errors


def _finish_probe(outcome: ProbeOutcome) -> None:
    evidence, inventory = outcome.evidence, outcome.inventory
    completion_error: BaseException | None = None
    if outcome.failure is None and not outcome.errors:
        try:
            inventory.assert_response_loss_receipts(outcome.receipts)
            inventory.assert_complete({
                "project-lifecycle", "bootstrap-authority", "cleanup-restore",
            }, require_response_loss=True)
        except BaseException as exc:
            completion_error = exc
            evidence.value["error"] = {
                "type": type(exc).__name__, "message": str(exc),
            }
        else:
            evidence.value.update({
                "status": "passed", "completedAt": time.time(),
            })
    if outcome.failure is not None or outcome.errors or completion_error:
        evidence.value.update({
            "status": "failed", "cleanupErrors": outcome.errors,
        })
    evidence.value.update({
        "mutationInventory": inventory.snapshot(),
        "responseLossCohort": response_loss_evidence(
            inventory, outcome.receipts),
    })
    evidence.save()
    if completion_error is not None:
        raise completion_error


def _execute(
        config: ProbeConfig, source: dict, frames: int,
        deadline: Deadline) -> dict:
    evidence = ProbeEvidence(config, source)
    inventory = MutationInventory()
    client = fault_client(deadline, inventory)
    prior = project = None
    failure: BaseException | None = None
    try:
        with use_process_deadline(deadline):
            prior, project = _build(
                client, config, evidence, frames)
            source_after = source_authority(config.source, deadline)
            if source_after != source:
                raise PalmierError(
                    "caption pagination source changed during the live probe")
            evidence.value["sourceAfter"] = source_after
    except BaseException as exc:
        failure = exc
        evidence.value["error"] = {
            "type": type(exc).__name__, "message": str(exc),
        }
    cleanup_receipts: list[dict] = []
    errors = _cleanup(config, CleanupInput(
        inventory, evidence, client, prior, project, cleanup_receipts,
        failure is None))
    receipts = combined_receipts(
        client.response_loss_receipts, cleanup_receipts)
    _finish_probe(ProbeOutcome(
        evidence, inventory, receipts, failure, errors))
    if failure is not None:
        raise failure
    if errors:
        raise PalmierError("; ".join(errors))
    return evidence.value
def run(config: ProbeConfig) -> dict:
    deadline = Deadline(config.timeout_s)
    with use_process_deadline(deadline):
        source, frames = validate_probe_config(config, deadline)
        lock_dir = os.path.dirname(os.path.abspath(config.evidence))
        acquired = SyncLock.acquire(
            lock_dir, source["sha256"], queue_if_busy=False)
        if acquired.state != SyncLockState.ACQUIRED \
                or acquired.lease is None:
            raise PalmierError(
                "caption pagination could not acquire Palmier lock")
        try:
            return _execute(config, source, frames, deadline)
        finally:
            acquired.lease.release()
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--prefix", default="Sniper P5 Caption Paging")
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--aspect", choices=("16:9", "9:16"), default="16:9")
    parser.add_argument("--quality", choices=("720p", "1080p"), default="1080p")
    parser.add_argument("--max-seconds", type=float, default=180)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--cleanup-timeout", type=float, default=120)
    parser.add_argument("--protected-project")
    return parser
def main() -> int:
    args = _parser().parse_args()
    config = ProbeConfig(
        os.path.abspath(args.source), os.path.abspath(args.evidence),
        args.prefix, args.fps, args.aspect, args.quality,
        args.max_seconds, args.timeout, args.cleanup_timeout,
        os.path.abspath(args.protected_project)
        if args.protected_project else None)
    try:
        result = run(config)
    except BaseException as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
