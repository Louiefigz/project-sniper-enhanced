#!/usr/bin/env python3
"""Locked CLI for explicit Palmier-native prepare/audit/approve/promote phases."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from palmier.candidate_receipt import load_candidate  # noqa: E402
from palmier.mcp_client import PalmierClient, PalmierError  # noqa: E402
from palmier.native_qc import (finalize_approval, prepare_qc,  # noqa: E402
                               promote_approved, run_deterministic_qc)
from palmier.native_qc_repair import reject_for_repair  # noqa: E402
from palmier.native_qc_contract import (export_path, qc_path)  # noqa: E402
from palmier.sync_lock import SyncLock, SyncLockState  # noqa: E402
from palmier.timeline_authority import TimelineConflict  # noqa: E402


@dataclass(frozen=True)
class Command:
    out_dir: str
    action: str
    value: str | None


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise PalmierError(f"invalid Palmier native QC command: {message}")


def _parse(argv: list[str] | None) -> Command:
    parser = _Parser(description=__doc__)
    parser.add_argument("out_dir")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--prepare", metavar="CTX_JSON")
    actions.add_argument("--audit", action="store_true")
    actions.add_argument("--finalize-approval", metavar="REVIEWS_JSON")
    actions.add_argument("--reject-for-repair", metavar="REASON_JSON")
    actions.add_argument("--promote", action="store_true")
    args = parser.parse_args(argv)
    action = ("prepare" if args.prepare else "finalize-approval"
              if args.finalize_approval else "reject-for-repair"
              if args.reject_for_repair else "audit" if args.audit else "promote")
    value = args.prepare or args.finalize_approval or args.reject_for_repair
    out_dir = os.path.realpath(args.out_dir)
    if not os.path.isdir(out_dir):
        raise PalmierError("Palmier native QC output directory does not exist")
    if value is not None and (not os.path.isabs(value) or not os.path.isfile(value)):
        raise PalmierError(f"Palmier native QC {action} input must be an existing absolute file")
    return Command(out_dir, action, value)


def _waiting(result: object) -> dict:
    reason = getattr(result, "reason", None)
    return {"ok": False, "status": "waiting", "error": "Another Palmier operation is active.",
            "reason": getattr(reason, "value", None),
            "holderPid": getattr(result, "holder_pid", None),
            "holderOutDir": getattr(result, "holder_out_dir", None)}


def _perform(client: PalmierClient, command: Command) -> dict:
    if command.action == "prepare":
        return prepare_qc(client, command.out_dir, str(command.value))
    if command.action == "audit":
        return run_deterministic_qc(client, command.out_dir)
    if command.action == "finalize-approval":
        return finalize_approval(client, command.out_dir, str(command.value))
    if command.action == "reject-for-repair":
        return reject_for_repair(client, command.out_dir, str(command.value))
    return promote_approved(client, command.out_dir)


def _summary(command: Command, receipt: dict) -> dict:
    candidate, parent = receipt.get("candidate") or {}, receipt.get("parent") or {}
    status = {"prepared": "qc-prepared", "deterministic-passed": "deterministic-passed",
              "qc-approved": "qc-approved", "promoted": "candidate-promoted",
              "qc-rejected": "candidate-rejected"}[receipt["status"]]
    result = {"ok": True, "status": status,
              "candidate": {key: candidate.get(key) for key in ("timelineId", "fingerprint")},
              "parent": {key: parent.get(key) for key in ("timelineId", "fingerprint")},
              "receiptPath": qc_path(command.out_dir)}
    if command.action in ("prepare", "audit", "finalize-approval"):
        result["exportPath"] = export_path(command.out_dir)
    if receipt.get("approvedHead"):
        result["approvedHead"] = receipt["approvedHead"]
    if receipt.get("archivePath"):
        result["archivePath"] = receipt["archivePath"]
    return result


def run(argv: list[str] | None = None) -> tuple[dict, int]:
    command = _parse(argv)
    candidate = load_candidate(command.out_dir) or {}
    key = f"native-qc:{command.action}:{candidate.get('requestHash', 'unknown')}"
    result = SyncLock.acquire(command.out_dir, key, queue_if_busy=False)
    if result.state != SyncLockState.ACQUIRED or result.lease is None:
        return _waiting(result), 75
    try:
        client = PalmierClient()
        client.handshake()
        return _summary(command, _perform(client, command)), 0
    finally:
        result.lease.release()


def main(argv: list[str] | None = None) -> int:
    try:
        verdict, code = run(argv)
    except TimelineConflict as exc:
        verdict, code = {"ok": False, "status": "conflict", "error": str(exc)}, 75
    except PalmierError as exc:
        verdict, code = {"ok": False, "status": "rejected", "error": str(exc)}, 65
    except (OSError, ValueError) as exc:
        verdict, code = {"ok": False, "status": "unavailable", "error": str(exc)}, 69
    print(json.dumps(verdict, separators=(",", ":")), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
