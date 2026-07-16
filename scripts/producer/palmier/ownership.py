#!/usr/bin/env python3
"""Atomically hand off or reclaim one canonical Palmier mirror sidecar."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from palmier.mcp_client import PalmierError  # noqa: E402
from palmier.mirror import (persist_handoff_to_palmier,  # noqa: E402
                            persist_ai_edit_invalidation,
                            persist_reclaim_for_sniper)
from palmier.sync_lock import DIR_LOCK_NAME, MUTEX_NAME  # noqa: E402


def _sidecar(out_dir: str, require_canonical: bool = True) -> dict:
    path = os.path.join(out_dir, "palmier.sync.json")
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read canonical Palmier state: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError("Palmier state is not a JSON object")
    if not require_canonical:
        return value
    canonical = (value.get("schemaVersion") == 4
                 and value.get("mirrorMode") == "visual-master"
                 and isinstance(value.get("projectId"), str)
                 and isinstance(value.get("latestTimelineId"), str))
    if not canonical:
        raise PalmierError(
            "ownership action requires a verified schemaVersion 4 mirror sidecar")
    return value


def _flock(path: str, nonblocking: bool = False) -> int:
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        operation = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0)
        fcntl.flock(fd, operation)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _acquire(out_dir: str) -> tuple[int, int]:
    """Serialize with SyncLock acquisition, then take its per-dir lease."""
    mutex_fd = _flock(os.path.join(out_dir, MUTEX_NAME))
    try:
        dir_fd = _flock(os.path.join(out_dir, DIR_LOCK_NAME), nonblocking=True)
    except BaseException:
        fcntl.flock(mutex_fd, fcntl.LOCK_UN)
        os.close(mutex_fd)
        raise
    return dir_fd, mutex_fd


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--handoff", action="store_true")
    action.add_argument("--reclaim", action="store_true")
    action.add_argument("--invalidate", action="store_true")
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> dict:
    args = _parse(argv)
    out_dir = os.path.realpath(args.out_dir)
    if not os.path.isdir(out_dir):
        raise PalmierError(f"project output directory does not exist: {out_dir}")
    dir_fd, mutex_fd = _acquire(out_dir)
    try:
        _sidecar(out_dir, require_canonical=not args.invalidate)
        if args.handoff:
            state = persist_handoff_to_palmier(out_dir)
        elif args.reclaim:
            state = persist_reclaim_for_sniper(out_dir)
        else:
            state = persist_ai_edit_invalidation(out_dir)
    finally:
        for fd in (dir_fd, mutex_fd):
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    action = "handoff" if args.handoff else "reclaim" if args.reclaim else "invalidate"
    return {"ok": True, "action": action,
            "ownership": state["ownership"], "freshMirrorRequired": args.reclaim}


def main(argv: list[str] | None = None) -> int:
    """Emit exactly one NDJSON verdict; busy syncs return retryable exit 75."""
    try:
        verdict, code = run(argv), 0
    except BlockingIOError:
        verdict, code = {"ok": False, "status": "waiting",
                         "error": "Palmier sync is active"}, 75
    except BaseException as exc:
        verdict, code = {"ok": False,
                         "error": f"{type(exc).__name__}: {exc}"}, 1
    print(json.dumps(verdict))
    return code


if __name__ == "__main__":
    sys.exit(main())
