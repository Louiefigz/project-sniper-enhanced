"""Actual exact-owned-name reconciliation regression; no render or broad cleanup.

Only the retained failed V2 smoke's registered name/control digest is selected.
Its original ledger and failed result stay unchanged. A new recovery observation
is evidence of this later cleanup check, never a successful render receipt.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cut_preview_io import file_hash, write_new
from headless.container_policy import _force_remove, _is_absent, reconcile_launch_abort, required_runtime
from headless.resource_ledger import ResourceRequest, registered_containers


def main() -> None:
    """Check the observed-absence protocol against the actual existing daemon."""
    root = Path(sys.argv[1])
    if not str(root).startswith("/private/tmp/sniper-render-build-v2-live-") or root.resolve() != root:
        raise RuntimeError("Explicit retained V2 synthetic attempt required")
    original = json.loads((root / "result.json").read_text())
    if original["passed"] or original["kind"] != "actual-current-v2-single-overlay-smoke":
        raise RuntimeError("Only the previously failed isolated smoke is in scope")
    attempt = root / "authority/attempts/section-marker-v2"
    runtime = required_runtime()
    request = ResourceRequest(str(attempt), attempt.name, runtime.docker, runtime.socket, runtime.image_id, runtime.user_id)
    names = registered_containers(request)
    if len(names) != 1:
        raise RuntimeError("Expected one exact owned recorded resource")
    held = file_hash(attempt / "resource-ledger.json")
    with tempfile.TemporaryDirectory(prefix="sniper-v2-absence-regression-") as config:
        if _is_absent(runtime, config, names[0]) is not True:
            raise RuntimeError("Regression requires the already-absent owned name")
        idempotent_success = _force_remove(runtime, config, names[0])
        started = time.monotonic()
        reconcile_launch_abort(runtime, config, names[0], timeout_seconds=10)
        elapsed = round((time.monotonic() - started) * 1000)
        after = _is_absent(runtime, config, names[0])
    if not after or held != file_hash(attempt / "resource-ledger.json"):
        raise RuntimeError("Absence was unproved or historical ledger changed")
    observation = {"kind": "later-owned-absence-observation-not-render-success", "containerName": names[0],
        "rmAbsentReportedSuccess": idempotent_success, "canonicalAbsenceProvedNow": after,
        "reconcileMs": elapsed, "originalFailurePreserved": True, "deliveryApproved": False}
    write_new(root / "later-absence-regression.json", observation)
    print(json.dumps(observation))


if __name__ == "__main__":
    main()
