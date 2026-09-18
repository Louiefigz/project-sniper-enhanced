#!/usr/bin/env python3
"""CLI/data bridge for GUI and native Palmier template planning."""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from graphics.template_contract import entry_errors, template_catalog  # noqa: E402


def _plan(path: str) -> dict:
    handle = sys.stdin if path == "-" else open(path, encoding="utf-8")
    try:
        value = json.load(handle)
    finally:
        if handle is not sys.stdin:
            handle.close()
    if not isinstance(value, dict):
        raise ValueError("plan must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", action="store_true")
    parser.add_argument("--plan", help="validate plan JSON; '-' reads stdin")
    args = parser.parse_args()
    if args.catalog:
        print(json.dumps({"schemaVersion": 1, "templates": template_catalog()},
                         sort_keys=True))
        return 0
    if not args.plan:
        parser.error("choose --catalog or --plan PATH")
    errors = [{"index": index, "kind": entry.get("kind"), "errors": issues}
              for index, entry in enumerate(_plan(args.plan).get("graphicsTrack") or [])
              if (issues := entry_errors(entry))]
    print(json.dumps({"schemaVersion": 1, "ok": not errors, "errors": errors},
                     sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"schemaVersion": 1, "ok": False, "error": str(exc)}))
        raise SystemExit(2)
