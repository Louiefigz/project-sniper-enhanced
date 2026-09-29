#!/usr/bin/env python3
"""Prepare or check one evidence-bound reference style vocabulary."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import bound_json, write_new
from graphics.catalog_discovery import load_catalog
from graphics.reference_style_vocabulary import (
    prepare_vocabulary, read_checked_vocabulary,
)


def _parser() -> argparse.ArgumentParser:
    """Build the small offline vocabulary command surface."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("draft"); prepare.add_argument("output")
    check = commands.add_parser("check")
    check.add_argument("vocabulary")
    return parser


def _execute(args: argparse.Namespace) -> dict:
    """Run one local action without approving creative or render quality."""
    catalog = load_catalog()
    if args.command == "prepare":
        draft = bound_json(Path(args.draft))
        record = prepare_vocabulary(draft, catalog)
        output = Path(args.output)
        write_new(output, record)
        checked = read_checked_vocabulary(output, catalog)
        return {**checked["report"], "path": checked["path"],
                "sha256": checked["sha256"]}
    checked = read_checked_vocabulary(Path(args.vocabulary), catalog)
    return {**checked["report"], "path": checked["path"],
            "sha256": checked["sha256"]}


def main() -> int:
    """Print one bounded JSON result and a meaningful exit status."""
    try:
        result = _execute(_parser().parse_args())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
