#!/usr/bin/env python3
"""Explicit CLI boundary for private exact dialogue-program rendering."""
from __future__ import annotations

import argparse
import json
import sys

from audio.dialogue_program_contracts import parse_dialogue_program_request
from audio.dialogue_program_render import render_dialogue_program
from audio.dialogue_stem_contracts import (
    DialogueStemRenderError,
    _regular_snapshot,
)
from current_render_graph_contract import canonical_bytes


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a private exact dialogue-aware program generation")
    parser.add_argument(
        "request", help="absolute closed dialogue-program request JSON")
    return parser


def _document(path: str) -> object:
    canonical = _regular_snapshot(path, "dialogue program request")
    try:
        with open(canonical, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise DialogueStemRenderError(
            "dialogue program request is not valid JSON") from exc


def main(argv: list[str] | None = None) -> int:
    """Parse, execute, and emit one machine-readable success envelope."""
    args = _parser().parse_args(argv)
    try:
        request = parse_dialogue_program_request(_document(args.request))
        receipt = render_dialogue_program(request)
        payload = {
            "ok": True,
            "programGenerationDir": request.program_generation_dir,
            "receipt": receipt,
        }
        sys.stdout.buffer.write(canonical_bytes(payload) + b"\n")
        sys.stdout.buffer.flush()
        return 0
    except (DialogueStemRenderError, RuntimeError, OSError) as exc:
        print(f"dialogue program render failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
