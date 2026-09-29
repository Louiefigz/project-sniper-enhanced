#!/usr/bin/env python3
"""Command wrapper for controller-owned catalog receipt issuance."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from planner.catalog_receipt_issuer import issue_catalog_receipts  # noqa: E402
from planner.catalog_receipt_pipeline import (  # noqa: E402
    catalog_receipt_pipeline_sha256,
)
from planner.visual_plan_receipts import MAX_RECEIPT_BYTES, read_exact  # noqa: E402


def _read_plan(path: str) -> dict:
    return json.loads(read_exact(os.path.realpath(path), "visual plan",
                                 MAX_RECEIPT_BYTES).decode("utf-8"))


def _write(path: Path, value: object) -> None:
    data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan")
    parser.add_argument("output_plan")
    parser.add_argument("authority_parent")
    args = parser.parse_args(argv)
    try:
        pipeline_sha256 = catalog_receipt_pipeline_sha256()
        result = issue_catalog_receipts(
            _read_plan(args.plan), args.authority_parent)
        output = Path(args.output_plan).resolve()
        _write(output, result.plan)
        sys.stdout.write(json.dumps({"plan": str(output), "authority": result.authority,
                                    "pipelineAuthoritySha256": pipeline_sha256},
                                    sort_keys=True, separators=(",", ":")) + "\n")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"catalog-receipt-issuer: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
