#!/usr/bin/env python3
"""Locked two-phase CLI for Palmier-canonical native AI candidates."""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from palmier.mcp_client import PalmierClient, PalmierError, emit  # noqa: E402
from palmier.candidate_receipt import recover_quarantined_parent  # noqa: E402
from palmier.native_candidate_lifecycle import discard_candidate  # noqa: E402
from palmier.native_delta import (NativeRequest,                       # noqa: E402
                                  execute_native_candidate)
from palmier.native_io import load_plan                                # noqa: E402
from palmier.native_gate import validate_native_gate  # noqa: E402
from palmier.native_gate_envelope import load_gate_envelope  # noqa: E402
from palmier.sync import load_sidecar  # noqa: E402
from palmier.sync_lock import SyncLock, SyncLockState  # noqa: E402
from palmier.timeline_authority import TimelineConflict  # noqa: E402
from palmier.timeline_guard import reconcile_working_authority  # noqa: E402


@dataclass(frozen=True)
class Command:
    """Validated CLI command."""

    out_dir: str
    action: str
    plan_path: str | None
    gate_path: str | None
    name: str
    progress: bool
    keep_candidate_active: bool


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise PalmierError(f"invalid Palmier native command: {message}")


def _parse(argv: list[str] | None) -> Command:
    parser = _Parser(description=__doc__)
    parser.add_argument("out_dir")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--reconcile", action="store_true")
    action.add_argument("--execute", metavar="PLAN_JSON")
    action.add_argument("--recover-parent", action="store_true")
    action.add_argument("--discard-candidate", action="store_true")
    parser.add_argument("--gate-envelope")
    parser.add_argument("--name", default="Sniper AI candidate")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--keep-candidate-active", action="store_true")
    args = parser.parse_args(argv)
    if not isinstance(args.name, str) or not args.name.strip() \
            or len(args.name) > 120:
        raise PalmierError("Palmier candidate name must be 1-120 characters")
    action_name = "reconcile" if args.reconcile else \
        "recover" if args.recover_parent else \
        "discard" if args.discard_candidate else "execute"
    if action_name == "execute" and not args.gate_envelope:
        raise PalmierError("Palmier native execute requires --gate-envelope")
    if action_name != "execute" and args.gate_envelope:
        raise PalmierError("--gate-envelope is valid only with --execute")
    if action_name != "execute" and args.progress:
        raise PalmierError("--progress is valid only with --execute")
    if action_name != "execute" and args.keep_candidate_active:
        raise PalmierError(
            "--keep-candidate-active is valid only with --execute")
    return Command(os.path.realpath(args.out_dir), action_name,
                   args.execute, os.path.realpath(args.gate_envelope)
                   if args.gate_envelope else None, args.name, args.progress,
                   args.keep_candidate_active)


def _sidecar(out_dir: str) -> dict:
    value = load_sidecar(out_dir)
    if not isinstance(value, dict):
        raise PalmierError("Palmier state is missing for this Sniper project")
    return value


def _plan(command: Command) -> dict | None:
    if command.action != "execute":
        return None
    if command.plan_path is None:
        raise PalmierError("Palmier native execute requires a plan path")
    return load_plan(command.plan_path)


def _waiting(result: object) -> dict:
    reason = getattr(result, "reason", None)
    return {
        "ok": False, "status": "waiting",
        "error": "Another Palmier operation is active.",
        "reason": getattr(reason, "value", None),
        "holderPid": getattr(result, "holder_pid", None),
        "holderOutDir": getattr(result, "holder_out_dir", None),
    }


def _perform(client: PalmierClient, command: Command,
             sidecar: dict, plan: dict | None) -> dict:
    if command.action == "reconcile":
        authority, change = reconcile_working_authority(
            client, command.out_dir, sidecar)
        return {"ok": True, "status": "reconciled", "change": change,
                "authority": authority}
    if command.action == "recover":
        candidate = recover_quarantined_parent(
            client, command.out_dir, sidecar)
        return {"ok": True, "status": "parent-restored",
                "candidate": candidate}
    if command.action == "discard":
        discarded = discard_candidate(client, command.out_dir)
        return {"ok": True, **discarded, "status": "candidate-discarded"}
    if command.gate_path is None or plan is None:
        raise PalmierError("Palmier native execute is missing governed inputs")
    authority, _change = reconcile_working_authority(
        client, command.out_dir, sidecar)
    request_text, lanes = load_gate_envelope(command.gate_path)
    validated = validate_native_gate(plan, authority, request_text, lanes)
    request = NativeRequest(
        sidecar, validated, command.name, command.keep_candidate_active)
    progress = (lambda event: emit(**event)) if command.progress else None
    candidate = execute_native_candidate(
        client, command.out_dir, request, progress)
    return {"ok": True, "status": "candidate-staged",
            "candidate": candidate}


def run(argv: list[str] | None = None) -> tuple[dict, int]:
    """Run one command with a single lock spanning every Palmier call."""
    command = _parse(argv)
    plan = _plan(command)
    lock_key = (plan or {}).get("requestHash") or "palmier-native-reconcile"
    result = SyncLock.acquire(
        command.out_dir, str(lock_key), queue_if_busy=False)
    if result.state != SyncLockState.ACQUIRED or result.lease is None:
        return _waiting(result), 75
    try:
        client = PalmierClient()
        client.handshake()
        previous = signal.signal(signal.SIGTERM, _cancel)
        try:
            return _perform(client, command, _sidecar(command.out_dir), plan), 0
        finally:
            signal.signal(signal.SIGTERM, previous)
    finally:
        result.lease.release()


def _cancel(_signal: int, _frame: object) -> None:
    raise PalmierError("Palmier native edit was cancelled; restoring its preserved parent")


def main(argv: list[str] | None = None) -> int:
    try:
        verdict, code = run(argv)
    except TimelineConflict as exc:
        verdict, code = {"ok": False, "status": "conflict",
                         "error": str(exc)}, 75
    except PalmierError as exc:
        verdict, code = {"ok": False, "status": "rejected",
                         "error": str(exc)}, 65
    except (OSError, ValueError) as exc:
        verdict, code = {"ok": False, "status": "unavailable",
                         "error": str(exc)}, 69
    print(json.dumps(verdict, separators=(",", ":")), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
