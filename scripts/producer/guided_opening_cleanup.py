"""Exact claim-bound Docker reconciliation after the owned opening process stops.

The server must first prove its process group is stopped and hold this claim.
This helper performs no render, source decode, provider call or recursive scan.
Missing ledgers after an armed marker are UNKNOWN, not an empty success.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

from guided_opening_claim import HeldOpeningClaim, read_execution_claim, registration_intent, resource_request
from guided_opening_execution import OpeningExecutionClock
from headless.claimed_resource_cleanup import reconcile_claimed_resource
from guided_source_color_cleanup_execution import SourceColorCleanupRequest, cleanup_source_color


def reconcile_order(claim: HeldOpeningClaim, order: int) -> dict:
    """Recover only one server-derived candidate-order attempt and exact owned names."""
    return reconcile_claimed_resource(resource_request(claim, order), registration_intent(claim, order), order)


def cleanup(paths: tuple[Path, Path], refs: tuple[str, Path, str], timeout: float,
            source_color: SourceColorCleanupRequest | None = None) -> dict:
    """Use a distinct protected cleanup allowance, not renewed render work time."""
    if source_color is not None:
        return cleanup_source_color(paths, refs, (time.monotonic(), timeout), source_color)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise RuntimeError("opening cleanup requires a positive protected budget at most300 seconds")
    clock, started = OpeningExecutionClock(time.monotonic() + timeout), time.monotonic()
    claim = clock.phase("cleanup-claim-and-controls", lambda: read_execution_claim(paths, refs))
    rows = [clock.phase(f"reconcile-graphic-{order}", lambda order=order: reconcile_order(claim, order))
            for order in claim.value["selectedGraphicOrders"]]
    clock.phase("cleanup-controls-after", lambda: read_execution_claim(paths, refs))
    return {"schemaVersion": 1, "kind": "guided-opening-cleanup-result", "claimPath": str(claim.path),
        "claimSha256": claim.sha256, "inputSha256": refs[0], "outputRoot": str(paths[1]),
        "executionId": claim.value["executionId"], "cleanupVerified": True, "graphics": rows,
        "elapsedMs": round((time.monotonic() - started) * 1000), "stages": clock.events,
        "budgetScope": "separate-protected-cleanup-not-render-allowance",
        "processGroupStopped": "requires-owned-server-observation", "openingApproved": False}


def main() -> int:
    """Return actual cleanup evidence or UNKNOWN; never start another render."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--execution-claim", type=Path, required=True)
    parser.add_argument("--execution-claim-sha256", required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--source-color-reservation", type=Path)
    parser.add_argument("--source-color-reservation-sha256")
    parser.add_argument("--source-color-request-sha256")
    args = parser.parse_args()
    colors = (args.source_color_reservation, args.source_color_reservation_sha256, args.source_color_request_sha256)
    if any(value is not None for value in colors) and any(value is None for value in colors):
        parser.error("source color cleanup requires all three explicit reservation/request flags")
    selected = SourceColorCleanupRequest(*colors) if colors[0] is not None else None
    try:
        result = cleanup((args.input, args.output), (args.input_sha256, args.execution_claim,
                         args.execution_claim_sha256), args.timeout_seconds, selected)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "unknown", "cleanupVerified": False, "error": str(error)}), flush=True)
        return 1
    print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
