#!/usr/bin/env python3
"""CLI shell for the closed ``cut.restoreSpeech`` analysis route."""
from __future__ import annotations

import argparse
import json
import os

from edit.cut_repair_route import RouteContractError, run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("producer_dir")
    parser.add_argument("directive_path")
    parser.add_argument("context_path", nargs="?")
    args = parser.parse_args()
    try:
        print(json.dumps(run(
            os.path.abspath(args.producer_dir),
            os.path.abspath(args.directive_path),
            (os.path.abspath(args.context_path)
             if args.context_path else None)),
            ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, RouteContractError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
