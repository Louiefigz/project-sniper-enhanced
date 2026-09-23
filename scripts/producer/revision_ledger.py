"""Immutable revision and QC observations; no review is inherited by new bytes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fingerprint_io import file_sha256, write_json_atomic


def _digest(value: object) -> str:
    """Bind an exact observation independently of legacy short fingerprints."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _persist(final: str, payload: dict) -> dict:
    """Keep each distinct observation under its content identity, without a winner pointer."""
    record = {"schemaVersion": 1, "kind": "revision-review-observation",
              "outputPath": os.path.abspath(final), "reviewCarryForward": False,
              "fullReviewRequired": True, **payload}
    record["receiptHash"] = _digest(record)
    directory = Path(final + ".review-ledger")
    directory.mkdir(exist_ok=True)
    write_json_atomic(str(directory / f"{record['receiptHash']}.json"), record, 2)
    return record


def record_render(final: str, plan: dict, provenance: dict) -> dict:
    """New output gets a pending full-review entry, even if its base was reused."""
    return _persist(final, {"event": "render-completed", "reviewStatus": "pending",
                           "outputSha256": provenance["authorityHash"],
                           "planSha256": _digest(plan), "provenance": provenance})


def record_audit(final: str, expected_sha256: str, report: dict) -> dict:
    """Bind an actual deterministic audit to unchanged media and sampled frame bytes."""
    if file_sha256(final) != expected_sha256:
        raise RuntimeError("review ledger refused an audit of changed output bytes")
    frames = report.get("frames", [])
    observations = []
    for frame in frames:
        path = frame.get("path")
        if path and os.path.isfile(path):
            observations.append({"path": os.path.abspath(path), "sha256": file_sha256(path),
                                 "timestamp": frame.get("timestamp"), "label": frame.get("label")})
    return _persist(final, {"event": "deterministic-audit", "outputSha256": expected_sha256,
                           "reviewStatus": "editorial-review-required",
                           "report": report, "sampledFrames": observations})


def current_observations(final: str) -> list[dict]:
    """Read only valid records for these bytes; never turn a prior audit into approval."""
    sha = file_sha256(final)
    directory = Path(final + ".review-ledger")
    records = []
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text())
        body = {key: value for key, value in record.items() if key != "receiptHash"}
        if record.get("receiptHash") != _digest(body):
            raise RuntimeError("review ledger observation digest mismatch")
        if record.get("outputSha256") == sha and record.get("outputPath") == os.path.abspath(final):
            records.append(record)
    return records
