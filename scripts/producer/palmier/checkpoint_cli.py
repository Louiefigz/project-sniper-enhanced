#!/usr/bin/env python3
"""CLI wrapper for non-authoritative Palmier working checkpoints."""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from palmier.checkpoint import (CheckpointInput, _json, _authority,    # noqa: E402
                                publish_checkpoint)
from ingest_execution_authority import verify_execution_media_authority  # noqa: E402
from palmier.mcp_client import (PalmierClient, PalmierError,           # noqa: E402
                                PalmierWaiting, emit)
from palmier.sync_lock import SyncLock, SyncLockState                  # noqa: E402


def _parse(argv: list[str] | None) -> CheckpointInput:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan_path")
    parser.add_argument("manifest_path")
    parser.add_argument("out_dir")
    parser.add_argument("--stage", choices=("cut", "plan", "revision", "render"),
                        required=True)
    parser.add_argument("--round", type=int, default=0)
    parser.add_argument("--media")
    parser.add_argument("--cache-dir")
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument(
        "--require-source-set-admission", action="store_true",
        help="explicitly require source-set admission (the default)")
    policy.add_argument(
        "--allow-legacy-unadmitted", action="store_true",
        help="non-production migration only: accept a legacy manifest")
    args = parser.parse_args(argv)
    if not args.allow_legacy_unadmitted:
        os.environ["SNIPER_REQUIRE_SOURCE_SET_ADMISSION"] = "1"
    return CheckpointInput(
        os.path.realpath(args.out_dir), os.path.realpath(args.plan_path),
        os.path.realpath(args.manifest_path), args.stage, max(0, args.round),
        os.path.realpath(args.media) if args.media else None,
        os.path.realpath(args.cache_dir) if args.cache_dir else None)


def run(argv: list[str] | None = None) -> int:
    spec = _parse(argv)
    plan = _json(spec.plan_path, "edit plan")
    manifest = _json(spec.manifest_path, "asset manifest")
    verify_execution_media_authority(
        plan, manifest, spec.manifest_path)
    acquired = SyncLock.acquire(
        spec.out_dir, _authority(spec, plan).checkpoint_key,
        queue_if_busy=False)
    if acquired.state != SyncLockState.ACQUIRED or acquired.lease is None:
        emit(status="checkpoint_waiting", reason=str(acquired.reason),
             holderPid=acquired.holder_pid)
        return 0
    try:
        client = PalmierClient(timeout_s=30.0)
        client.handshake()
        emit(**publish_checkpoint(client, spec))
        return 0
    finally:
        acquired.lease.release()


def main() -> int:
    try:
        return run()
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1
    except PalmierWaiting as exc:
        emit(status="checkpoint_waiting", reason=str(exc), required=True)
        return 75
    except (PalmierError, OSError, ValueError) as exc:
        emit(status="checkpoint_error", reason=str(exc), required=True)
        return 1
    except BaseException as exc:
        emit(status="checkpoint_error", reason=f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
