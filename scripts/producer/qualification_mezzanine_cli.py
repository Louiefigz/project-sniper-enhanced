#!/usr/bin/env python3
"""Create or verify an isolated over-cap qualification mezzanine."""
from __future__ import annotations

import argparse
import os
import signal
import sys

from headless.qualification_mezzanine_policy import (
    DEFAULT_TIMEOUT_SECONDS,
    PROJECT_FPS,
)
from ingest_admission_contract import canonical_bytes
from qualification_mezzanine import (
    QualificationRequest,
    build_qualification_mezzanine,
    verify_qualification_evidence,
)


def _cancel(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt("qualification conversion cancelled")


def _summary(document: dict, evidence: str) -> dict:
    output = document["output"]
    return {"ok": True, "outputPath": output["path"],
            "outputSha256": output["sha256"],
            "outputSizeBytes": output["sizeBytes"],
            "evidencePath": evidence,
            "evidenceDigest": document["evidenceDigest"],
            "sourceEligibility": document["sourceEligibility"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("source")
    build.add_argument("--output", required=True)
    build.add_argument("--evidence", required=True)
    build.add_argument("--project-fps", type=int, choices=sorted(PROJECT_FPS),
                       default=24)
    build.add_argument("--timeout-seconds", type=int,
                       default=DEFAULT_TIMEOUT_SECONDS)
    verify = commands.add_parser("verify")
    verify.add_argument("evidence")
    return parser


def _execute(args: argparse.Namespace) -> dict:
    if args.command == "verify":
        path = os.path.abspath(args.evidence)
        return _summary(verify_qualification_evidence(path), path)
    request = QualificationRequest(
        os.path.abspath(args.source), os.path.abspath(args.output),
        os.path.abspath(args.evidence), args.timeout_seconds, args.project_fps)
    document = build_qualification_mezzanine(request)
    return _summary(document, request.evidence)


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, _cancel)
    signal.signal(signal.SIGINT, _cancel)
    try:
        result, code = _execute(_parser().parse_args(argv)), 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        result, code = {"ok": False, "error": str(exc)}, 1
    except KeyboardInterrupt:
        result, code = {"ok": False,
                        "error": "qualification conversion cancelled"}, 130
    sys.stdout.buffer.write(canonical_bytes(result))
    sys.stdout.buffer.flush()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
