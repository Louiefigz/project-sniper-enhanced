#!/usr/bin/env python3
"""Deterministic command used only to prove the baseline trace harness."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def main() -> int:
    """Emit synthetic stage/cache evidence and a deterministic plan artifact."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    output = Path(fixture["outputPaths"][0])
    label = os.environ["SNIPER_BASELINE_RUN_LABEL"]
    state = "cold" if label == "first-run" else "warm"
    clauses = [
        {"clauseId": f"clause-{index:04d}", "status": "retained"}
        for index in range(1, 21)
    ]
    artifact = {
        "fixtureId": fixture["fixtureId"],
        "durationFrames": fixture["durationFrames"],
        "clauses": clauses,
    }
    output.write_text(
        json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(json.dumps({
        "event": "baseline_cache_state",
        "state": state,
    }, sort_keys=True))
    print(json.dumps({
        "event": "baseline_stage",
        "stage": "plan-only-shadow",
        "wallMs": 0,
        "cache": state,
        "retries": 0,
        "workers": 1,
        "outputSha256": digest,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
