#!/usr/bin/env python3
"""Build or verify a policy-approved cadence approximation receipt."""
from __future__ import annotations

import argparse
import os
import sys

from ingest_admission_contract import canonical_bytes
from qualification_cadence_approval import (
    publish_cadence_approval,
    verify_cadence_approval,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    approve = commands.add_parser("approve")
    approve.add_argument("evidence")
    approve.add_argument("--output", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("approval")
    return parser


def _execute(args: argparse.Namespace) -> dict:
    if args.command == "approve":
        document = publish_cadence_approval(
            os.path.abspath(args.evidence), os.path.abspath(args.output))
        path = os.path.abspath(args.output)
    else:
        path = os.path.abspath(args.approval)
        document = verify_cadence_approval(path)
    return {
        "ok": True,
        "approvalPath": path,
        "approvalDigest": document["approvalDigest"],
        "decision": document["decision"],
        "sourceRate": document["media"]["source"]["rate"],
        "targetRate": document["media"]["normalized"]["video"]["rate"],
        "normalizedMediaPath":
            document["downstreamTimeAuthority"]["mediaPath"],
    }


def main(argv: list[str] | None = None) -> int:
    try:
        result, code = _execute(_parser().parse_args(argv)), 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        result, code = {"ok": False, "error": str(exc)}, 1
    sys.stdout.buffer.write(canonical_bytes(result))
    sys.stdout.buffer.flush()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
