#!/usr/bin/env python3
"""Verify, activate, or inspect one QC-gated current-render graph candidate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from current_render_graph_build import DEFAULT_CACHE, GraphBuildInputs
from current_render_graph_candidate import (
    activate_candidate,
    active_binds,
    candidate_is_active,
    rollback_candidate,
    verify_candidate,
)
from current_render_graph_contract import object_hash
from current_render_graph_store import load_active


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("verify", "activate", "candidate-active",
                           "rollback", "active"))
    parser.add_argument("--producer-dir", required=True, type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--final", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--base", type=Path)
    return parser


def _run(args: argparse.Namespace) -> dict[str, object]:
    producer = args.producer_dir.resolve(strict=True)
    final = args.final.absolute()
    if args.action == "verify":
        graph_hash = verify_candidate(
            producer, args.candidate.absolute(), args.expected_sha256)
        return {"ok": True, "graphHash": graph_hash, "status": "verified"}
    if args.action == "activate":
        graph_hash = activate_candidate(
            producer, args.candidate.absolute(), final, args.expected_sha256)
        return {"ok": True, "graphHash": graph_hash, "status": "active"}
    if args.action == "candidate-active":
        active = candidate_is_active(
            producer, args.candidate.absolute(), final, args.expected_sha256)
        generation = load_active(producer) if active else None
        graph_hash = object_hash(generation[0]) if generation else None
        return {
            "ok": active, "graphHash": graph_hash,
            "status": "candidate-active",
        }
    if args.action == "rollback":
        graph_hash = rollback_candidate(
            producer, args.candidate.absolute(), final, args.expected_sha256)
        return {"ok": True, "graphHash": graph_hash, "status": "rolled-back"}
    required = (args.plan, args.manifest, args.base)
    if any(path is None for path in required):
        raise RuntimeError("active inspection requires plan, manifest, and base")
    inputs = GraphBuildInputs(
        producer, args.plan.resolve(strict=True),
        args.manifest.resolve(strict=True), args.base.absolute(), final,
        DEFAULT_CACHE)
    return {"ok": active_binds(inputs, args.expected_sha256),
            "status": "active-inspection"}


def main() -> int:
    try:
        result = _run(_parser().parse_args())
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 2
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
