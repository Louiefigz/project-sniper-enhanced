#!/usr/bin/env python3
"""Run the pure Palmier-native deterministic gate without MCP mutation."""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from palmier.mcp_client import PalmierError  # noqa: E402
from palmier.native_io import load_plan  # noqa: E402
from palmier.native_gate import validate_native_gate  # noqa: E402
from palmier.native_gate_envelope import load_gate_envelope  # noqa: E402
from palmier.timeline_authority import load_authority  # noqa: E402


def run(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir")
    parser.add_argument("plan_path")
    parser.add_argument("envelope_path")
    args = parser.parse_args(argv)
    out_dir = os.path.realpath(args.out_dir)
    authority = load_authority(out_dir)
    if authority is None:
        raise PalmierError("native gate has no reconciled Palmier authority")
    request, lanes = load_gate_envelope(args.envelope_path)
    validated = validate_native_gate(
        load_plan(args.plan_path), authority, request, lanes)
    return {"ok": True, "status": "native-gate-passed",
            "operationCount": len(validated["operations"]),
            "lanes": validated["lanes"],
            "parentFingerprint": validated["parent"]["fingerprint"]}


def main(argv: list[str] | None = None) -> int:
    try:
        verdict, code = run(argv), 0
    except (PalmierError, OSError, ValueError) as exc:
        verdict, code = {"ok": False, "status": "native-gate-rejected",
                         "error": str(exc)}, 65
    print(json.dumps(verdict, separators=(",", ":")), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
