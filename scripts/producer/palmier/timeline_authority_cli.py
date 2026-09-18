#!/usr/bin/env python3
"""Read-only Palmier authority guard used before a Sniper AI edit starts."""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from palmier.mcp_client import PalmierClient, PalmierError  # noqa: E402
from palmier.sync import load_sidecar                       # noqa: E402
from palmier.sync_lock import SyncLock, SyncLockState       # noqa: E402
from palmier.timeline_authority import TimelineConflict     # noqa: E402
from palmier.timeline_guard import guard_sniper_baseline     # noqa: E402


def guard(client: PalmierClient, out_dir: str) -> dict:
    """Capture manual drift, then refuse plan-only AI work that would erase it."""
    return guard_sniper_baseline(client, out_dir, load_sidecar(out_dir))


def run(argv: list[str] | None = None) -> tuple[dict, int]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir")
    args = parser.parse_args(argv)
    out_dir = os.path.realpath(args.out_dir)
    result = SyncLock.acquire(
        out_dir, "timeline-authority-guard", queue_if_busy=False)
    if result.state != SyncLockState.ACQUIRED or result.lease is None:
        return ({"ok": False, "status": "waiting",
                 "error": "Another Palmier operation is active."}, 75)
    try:
        client = PalmierClient()
        client.handshake()
        verdict = guard(client, out_dir)
        return verdict, 0 if verdict["ok"] else 65
    finally:
        result.lease.release()


def main(argv: list[str] | None = None) -> int:
    try:
        verdict, code = run(argv)
    except (OSError, ValueError, PalmierError, TimelineConflict) as exc:
        verdict, code = {"ok": False, "status": "unavailable",
                         "error": str(exc)}, 69
    print(json.dumps(verdict))
    return code


if __name__ == "__main__":
    sys.exit(main())
