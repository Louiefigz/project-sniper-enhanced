#!/usr/bin/env python3
"""CLI for the Claude Code Desktop → Palmier staged authority."""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from palmier.desktop_authority import (advance, approve, begin, load_pointer,
                                       reconcile, run_qc)  # noqa: E402
from palmier.desktop_lease import renew  # noqa: E402
from palmier.desktop_state import DesktopStageInput  # noqa: E402
from palmier.mcp_client import PalmierClient  # noqa: E402


def _client() -> PalmierClient:
    client = PalmierClient()
    client.handshake()
    return client


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.getcwd())
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("begin")
    start.add_argument("out_dir"); start.add_argument("plan")
    start.add_argument("manifest"); start.add_argument("--stage", default="cut")
    start.add_argument("--hours", type=float, default=3.0)
    start.add_argument("--transcripts-dir")
    next_stage = sub.add_parser("advance")
    next_stage.add_argument("plan"); next_stage.add_argument("manifest")
    next_stage.add_argument("--stage", required=True)
    next_stage.add_argument("--transcripts-dir")
    next_stage.add_argument("--revision-set")
    sub.add_parser("status")
    renewal = sub.add_parser("renew")
    renewal.add_argument("--hours", type=float, default=3.0)
    reconcile_parser = sub.add_parser("reconcile")
    reconcile_parser.add_argument("--media-ref")
    sub.add_parser("qc")
    finish = sub.add_parser("approve"); finish.add_argument("reviews")
    return parser


def main() -> int:
    args = _parser().parse_args()
    repo = os.path.abspath(args.repo)
    if args.command == "status":
        _path, result = load_pointer(repo)
    elif args.command == "begin":
        inputs = DesktopStageInput(
            repo, args.out_dir, args.plan, args.manifest, args.stage,
            args.transcripts_dir)
        result = begin(_client(), inputs, args.hours)
    elif args.command == "advance":
        inputs = DesktopStageInput(
            repo, "", args.plan, args.manifest, args.stage,
            args.transcripts_dir, args.revision_set)
        result = advance(_client(), inputs)
    elif args.command == "renew":
        result = renew(_client(), repo, args.hours)
    elif args.command == "reconcile":
        result = reconcile(_client(), repo, args.media_ref)
    elif args.command == "qc":
        result = run_qc(_client(), repo)
    else:
        result = approve(_client(), repo, args.reviews)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
