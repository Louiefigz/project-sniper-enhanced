"""Exact body activation-bound Docker cleanup after the owned process stops.

The foreground owner must first prove the actual outer group stopped. Known
Docker resources can be reconciled while nested local ownership remains
unresolved, but that cannot qualify selection or clear the durable claim.
This helper neither restarts work nor requires healthy historical source media;
Docker absence never changes a retained failed attempt into successful video.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

from guided_body_claim import (body_registration_intent, body_resource_request,
                               read_body_resource_claim)
from guided_body_contract import BodyInvocation
from guided_opening_execution import OpeningExecutionClock
from headless.claimed_resource_cleanup import reconcile_claimed_resource


def cleanup(invocation: BodyInvocation, root: Path, timeout: float) -> dict:
    """Use protected termination time only; never permit late rendering success."""
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise RuntimeError("body cleanup requires a positive protected budget at most300 seconds")
    started = time.monotonic()
    clock = OpeningExecutionClock(started + timeout)
    claim = clock.phase("body-cleanup-control", lambda: read_body_resource_claim(invocation, root))
    rows = []
    for order in claim.value["selectedGraphicOrders"]:
        request, intent = body_resource_request(claim, order), body_registration_intent(claim, order)
        rows.append(clock.phase(f"reconcile-graphic-{order}",
            lambda: reconcile_claimed_resource(request, intent, order)))
    clock.phase("body-cleanup-control-after", lambda: read_body_resource_claim(invocation, root))
    return {"schemaVersion": 1, "kind": "guided-body-cleanup-result",
        "activationPath": str(invocation.activation_path), "activationSha256": invocation.activation_sha256,
        "inputSha256": invocation.input_sha256, "outputRoot": str(root),
        "executionId": claim.value["executionId"], "cleanupVerified": True, "graphics": rows,
        "elapsedMs": round((time.monotonic() - started) * 1000), "stages": clock.events,
        "budgetScope": "separate-protected-cleanup-not-render-allowance",
        "processGroupStopped": "requires-owned-controller-observation", "bodyApproved": False, "deliveryApproved": False}


def main() -> int:
    """Fixed local cleanup command; emit UNKNOWN and nonzero on any missing proof."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--execution-activation", type=Path, required=True)
    parser.add_argument("--execution-activation-sha256", required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    args = parser.parse_args()
    invocation = BodyInvocation(args.input, args.input_sha256, args.execution_activation, args.execution_activation_sha256)
    try:
        result = cleanup(invocation, args.output, args.timeout_seconds)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "unknown", "cleanupVerified": False, "error": str(error)}), flush=True)
        return 1
    print(json.dumps(result, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
