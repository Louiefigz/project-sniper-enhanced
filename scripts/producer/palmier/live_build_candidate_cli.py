#!/usr/bin/env python3
"""Locked fork/resume/checkpoint CLI for skilled-agent Palmier live builds."""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from palmier.live_build_candidate import (checkpoint_live_candidate,  # noqa: E402
                                           fork_live_candidate,
                                           resume_live_candidate)
from palmier.mcp_client import PalmierClient, PalmierError  # noqa: E402
from palmier.sync_lock import SyncLock, SyncLockState  # noqa: E402
from palmier.timeline_authority import TimelineConflict  # noqa: E402


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise PalmierError(f"invalid Palmier live-build command: {message}")


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = _Parser(description=__doc__)
    parser.add_argument("out_dir")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--fork", metavar="NAME")
    actions.add_argument("--resume", action="store_true")
    actions.add_argument("--checkpoint", metavar="AUTHORITY_JSON")
    args = parser.parse_args(argv)
    args.out_dir = os.path.realpath(args.out_dir)
    if not os.path.isdir(args.out_dir):
        raise PalmierError("Palmier live-build output directory does not exist")
    if args.fork is not None and (not args.fork.strip() or len(args.fork) > 120):
        raise PalmierError("Palmier live-build candidate name must be 1-120 characters")
    if args.checkpoint is not None:
        args.checkpoint = os.path.realpath(args.checkpoint)
        if not os.path.isfile(args.checkpoint):
            raise PalmierError("Palmier live-build authority file is missing")
    return args


def _summary(candidate: dict) -> dict:
    return {"ok": True, "status": "candidate-ready",
            "candidate": {key: candidate.get(key) for key in
                          ("projectId", "timelineId", "fingerprint",
                           "semanticFingerprint", "status")},
            "base": candidate.get("base")}


def run(argv: list[str] | None = None) -> tuple[dict, int]:
    args = _parse(argv)
    result = SyncLock.acquire(args.out_dir, "skilled-live-build",
                              queue_if_busy=False)
    if result.state != SyncLockState.ACQUIRED or result.lease is None:
        return {"ok": False, "status": "waiting",
                "error": "Another Palmier operation is active."}, 75
    try:
        client = PalmierClient()
        client.handshake()
        if args.fork is not None:
            candidate = fork_live_candidate(client, args.out_dir, args.fork)
        elif args.resume:
            candidate = resume_live_candidate(client, args.out_dir)
        else:
            candidate = checkpoint_live_candidate(
                client, args.out_dir, str(args.checkpoint))
        return _summary(candidate), 0
    finally:
        result.lease.release()


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
