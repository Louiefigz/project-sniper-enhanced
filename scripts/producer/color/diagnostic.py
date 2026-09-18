"""Private source-color screening; no draft, grade, final or approval writes.

CLI: diagnostic.py PRODUCER_DIR CONTEXT_JSON PLAN_SHA256 MANIFEST_SHA256
CONTEXT_JSON is an array of the private source-context rows in color/model.py.
Missing context is explicit unknown. Existing admitted source-set authority is
required. The only outputs are new immutable .sniper-color-diagnostics UUID jobs.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from color.authority import observe, toolchain
from color.deadline import require_time, wall_budget
from color.model import DiagnosticRequest, POLICY, validate_request
from color.proposal import group_proposal
from color.sample_plan import build_sample_plan
from cut_preview_io import digest, read_bytes, real_directory, write_new
from headless.color_diagnostic_policy import run_isolated


def _attempt(producer: Path) -> Path:
    """Create new private evidence only; never recycle or overwrite an attempt."""
    real_directory(producer)
    store = producer / ".sniper-color-diagnostics"
    store.mkdir(mode=0o700, exist_ok=True)
    real_directory(store)
    info = store.lstat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeError("color diagnostic store must be private to this user")
    attempt = store / str(uuid.uuid4())
    attempt.mkdir(mode=0o700, exist_ok=False)
    return attempt


def _sealed(path: Path, value: dict) -> None:
    """Publish a new read-only artifact; hashes are integrity, not approval."""
    write_new(path, {**value, "artifactHash": digest(value)})
    os.chmod(path, 0o400, follow_symlinks=False)


def _request_document(request: DiagnosticRequest, attempt: Path) -> dict:
    """Freeze the requested parents and operator context, without approval."""
    return {"schemaVersion": 1, "policy": POLICY, "diagnosticId": attempt.name,
            "producerDir": str(request.producer_dir), "planHash": request.plan_hash,
            "manifestHash": request.manifest_hash, "contexts": request.contexts,
            "sampleBudget": request.sample_budget, "timeoutSeconds": request.timeout_seconds,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "deliveryApproved": False, "writesGrade": False}


def _source_request(source: dict, sampling: dict, timeout: int) -> dict:
    """Select only this admitted source's planned sample identities."""
    samples = [sample for group in sampling["groups"] if group["sourceId"] == source["sourceId"]
               for sample in group["samples"]]
    return {"sourceSha256": source["sha256"], "samples": samples,
            "timeoutSeconds": timeout}


def _worker_results(observed: dict, sampling: dict,
                    execution: tuple[Callable[[str, dict], dict], float, list[dict]]) -> list[dict]:
    """Run sequential bounded source jobs; retain any completed evidence on failure."""
    runner, deadline, results = execution
    for source in observed["sources"]:
        remaining = int(deadline - time.monotonic())
        if remaining < 30:
            raise RuntimeError("color attempt has insufficient remaining bounded decode time")
        request = _source_request(source, sampling, min(120, remaining))
        started = time.monotonic()
        try:
            envelope = runner(source["path"], request)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            results.append({"sourceId": source["sourceId"], "status": "failed",
                            "error": str(exc), "cleanupVerified": getattr(exc, "cleanup_verified", False),
                            "elapsedMs": round((time.monotonic() - started) * 1000)})
            raise
        results.append({"sourceId": source["sourceId"], "envelope": envelope})
        worker = envelope.get("worker") or {}
        expected_ids = {row["id"] for row in request["samples"]}
        actual_ids = [row.get("id") for row in worker.get("samples") or []]
        if worker.get("sourceSha256") != source["sha256"] or worker.get("schemaVersion") != 1:
            raise RuntimeError("color worker source identity is inconsistent")
        if worker.get("status") == "failed":
            raise RuntimeError(f"color worker failed: {worker.get('error', 'unknown failure')}")
        if worker.get("status") not in {"complete", "partial"} \
                or set(actual_ids) != expected_ids or len(actual_ids) != len(expected_ids):
            raise RuntimeError("color worker sample closure is incomplete")
    return results


def _completed(observed: dict, sampling: dict, workers: list[dict]) -> dict:
    """Project observations into explicit unreviewed proposals and caveats."""
    indexed = {row["sourceId"]: row["envelope"] for row in workers}
    groups = [group_proposal(group, indexed[group["sourceId"]]) for group in sampling["groups"]]
    partial = any(any(row["status"] != "sampled" for row in group["observations"]) for group in groups)
    return {"state": "partial" if partial else "complete", "bindings": observed["bindings"],
            "sources": observed["sources"], "sampling": sampling, "groups": groups,
            "inputsRevalidated": True,
            "caveats": ["Private diagnostic, not an approved grade or a quality pass.",
                        "Sampling is not exhaustive; retained but unsampled intervals are listed.",
                        "Only primary retained footage is measured; b-roll, proxies, overlays and final color are not qualified.",
                        "No Log/HDR transform, white-balance correction, canonical draft save or render was performed."]}


def run_diagnostic(request: DiagnosticRequest,
                   runner: Callable[[str, dict], dict] | None = None) -> dict:
    """Execute screening and preserve failed timing, never modifying authority."""
    validate_request(request)
    request = replace(request, contexts=json.loads(json.dumps(request.contexts, allow_nan=False)))
    attempt = _attempt(request.producer_dir)
    invocation = _request_document(request, attempt)
    _sealed(attempt / "request.json", invocation)
    started, workers, implementation = time.monotonic(), [], None
    deadline = started + request.timeout_seconds
    try:
        with wall_budget(deadline):
            observed = observe(request)
            implementation = toolchain()
            sources = [row["manifestRow"] for row in observed["sources"]]
            sampling = build_sample_plan(observed["plan"], sources, request.contexts, request.sample_budget)
        _worker_results(observed, sampling, (runner or run_isolated, deadline, workers))
        with wall_budget(deadline):
            if observe(request) != observed or toolchain() != implementation:
                raise RuntimeError("color diagnostic parents, source history or implementation changed during sampling")
            result = _completed(observed, sampling, workers)
            require_time(deadline)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        result = {"state": "failed", "error": str(exc), "groups": [],
                  "inputsRevalidated": False}
    result.update(schemaVersion=1, policy=POLICY, diagnosticId=attempt.name,
                  requestHash=digest(invocation), implementation=implementation,
                  workers=workers, elapsedMs=round((time.monotonic() - started) * 1000),
                  startedAt=invocation["createdAt"], queueMs=0, queuePolicy="synchronous-no-job-queue",
                  reviewState="unreviewed", deliveryApproved=False, qualityQualified=False,
                  writesGrade=False, artifactDir=str(attempt))
    _sealed(attempt / "result.json", result)
    return result


def main() -> None:
    """Expose private explicit diagnostic invocation, not an editor action API."""
    if len(sys.argv) != 5:
        raise SystemExit("Usage: diagnostic.py PRODUCER_DIR CONTEXT_JSON PLAN_SHA256 MANIFEST_SHA256")
    contexts = json.loads(read_bytes(Path(sys.argv[2]).resolve(), 64 * 1024).decode("utf8"))
    request = DiagnosticRequest(Path(sys.argv[1]).resolve(), sys.argv[3], sys.argv[4], contexts)
    result = run_diagnostic(request)
    print(json.dumps(result, allow_nan=False))
    raise SystemExit(1 if result["state"] == "failed" else 0)


if __name__ == "__main__":
    main()
