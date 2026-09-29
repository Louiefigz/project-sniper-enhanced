#!/usr/bin/env python3
"""Bounded local CLI for validating, allocating, and hashing VISUAL-PLAN.json."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from planner.visual_plan_allocator import allocate_visual_plan  # noqa: E402
from planner.visual_plan_contract import (  # noqa: E402
    invalidation_inputs,
    validate_visual_plan,
)
from planner.visual_plan_catalog_authority import (  # noqa: E402
    materialize_catalog_authority,
)
from planner.visual_plan_receipts import authority_pin  # noqa: E402

MAX_PLAN_BYTES = 4 * 1024 * 1024


def _read_plan(raw_path: str) -> tuple[Path, object]:
    path = Path(raw_path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("visual-plan input must be one regular file")
    size = path.stat().st_size
    if size < 2 or size > MAX_PLAN_BYTES:
        raise ValueError("visual-plan input exceeds the bounded read size")
    try:
        return path.resolve(), json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("visual-plan input is not readable JSON") from exc


def _emit(value: object) -> None:
    sys.stdout.write(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False) + "\n")


def _operation_result(command: str, path: Path, plan: object,
                      receipt_authority: dict | None = None) -> object:
    if command == "allocate":
        return allocate_visual_plan(plan, receipt_authority)
    if command not in {"fingerprints", "binding"}:
        validated = validate_visual_plan(plan, receipt_authority)
        return {"valid": True, **invalidation_inputs(validated, receipt_authority)}
    identity = invalidation_inputs(plan, receipt_authority)
    if command == "binding":
        binding = {"schemaVersion": 1, "path": str(path),
                   "byteHash": hashlib.sha256(path.read_bytes()).hexdigest(),
                   **identity}
        if receipt_authority is not None:
            binding["catalogReceiptAuthority"] = receipt_authority
        return binding
    return identity


def main(argv: list[str] | None = None) -> int:
    """Run one planning-only visual-plan operation."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("validate", "allocate", "fingerprints", "binding",
                            "catalog-authority"))
    parser.add_argument("plan")
    parser.add_argument("--receipt-authority")
    args = parser.parse_args(argv)
    try:
        if args.command == "catalog-authority":
            _emit(materialize_catalog_authority(args.plan))
            return 0
        path, plan = _read_plan(args.plan)
        receipt_authority = (authority_pin(args.receipt_authority)
                             if args.receipt_authority else None)
        _emit(_operation_result(args.command, path, plan, receipt_authority))
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"visual-plan: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
