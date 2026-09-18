#!/usr/bin/env python3
"""Audit B checks for first-class caption authority and rendered provenance."""
from __future__ import annotations

import json
import os

from audit.audit_checks import CheckResult, FAIL, PASS
from captions.caption_authority import expected_caption_hashes
from captions.caption_fingerprints import canonical_digest, caption_compiler_hash
from captions.caption_plan_pipeline import PROJECTION_TOOLCHAIN
from captions.caption_shard_authority import validate_bound_shards
from fingerprints import caption_fingerprint, file_sha256


def _load(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _result(status: str, measured: str, detail: str) -> CheckResult:
    return CheckResult("caption_authority", status, measured, detail)


def _files_current(out_dir: str, authority: dict) -> str | None:
    files = authority.get("files")
    if not isinstance(files, dict) or not files:
        return "caption authority has no artifact closure"
    for record in files.values():
        if not isinstance(record, dict) or set(record) != {"name", "sha256"}:
            return "caption artifact record is malformed"
        name, digest = record["name"], record["sha256"]
        if not isinstance(name, str) or os.path.basename(name) != name:
            return "caption artifact file name is unsafe"
        path = os.path.join(out_dir, name)
        if not os.path.isfile(path) or file_sha256(path) != digest:
            return f"caption artifact is missing or stale: {name}"
    return None


def _receipt_hash(authority: dict) -> str:
    payload = {key: value for key, value in authority.items()
               if key != "authorityHash"}
    return canonical_digest("sniper-caption-render-authority-v1", payload)


def _provenance_current(out_dir: str, plan: dict,
                        authority: dict) -> bool:
    proof = _load(os.path.join(out_dir, "final.mp4.assembled.json"))
    if proof is not None:
        return (
            proof.get("captionFingerprint") == caption_fingerprint(plan)
            and proof.get("captionAuthorityHash")
            == authority.get("authorityHash"))
    report = _load(os.path.join(out_dir, "render_report.json"))
    if report is None:
        return False
    if authority.get("burnExpected"):
        return report.get("captionsBurned") is True
    sidecar = report.get("captionsSidecar")
    return isinstance(sidecar, str) \
        and os.path.basename(sidecar) == "captions.srt"


def check_caption_authority(out_dir: str, plan: dict) -> list[CheckResult]:
    """Fail explicit-caption renders on any ghost, stale, or unbound output."""
    try:
        expected = expected_caption_hashes(plan)
    except ValueError as exc:
        return [_result(FAIL, "malformed", str(exc))]
    if expected is None:
        return []
    authority = _load(os.path.join(out_dir, "caption_authority.json"))
    if authority is None:
        return [_result(
            FAIL, "missing", "CaptionTrackV1 rendered without authority")]
    track_hash, ledger_hash = expected
    if authority.get("captionTrackHash") != track_hash \
            or authority.get("correctionLedgerHash") != ledger_hash:
        return [_result(
            FAIL, "stale", "caption authority does not bind the current plan")]
    if authority.get("authorityHash") != _receipt_hash(authority):
        return [_result(
            FAIL, "digest mismatch", "caption authority receipt was modified")]
    stale = _files_current(out_dir, authority)
    if stale:
        return [_result(FAIL, "stale artifact", stale)]
    shard_error = validate_bound_shards(out_dir, authority)
    if shard_error:
        return [_result(FAIL, "stale alpha shards", shard_error)]
    compilation = _load(os.path.join(out_dir, "caption_compilation.json"))
    expected_compilation = (canonical_digest(
        "sniper-caption-compilation-v1", compilation)
        if compilation is not None else None)
    if authority.get("compilationHash") != expected_compilation:
        return [_result(
            FAIL, "stale compilation",
            "caption compilation differs from its render authority")]
    if (compilation or {}).get("compilerHash") != caption_compiler_hash(
            PROJECTION_TOOLCHAIN):
        return [_result(
            FAIL, "stale compiler",
            "caption artifacts were built by a different compiler closure")]
    if not _provenance_current(out_dir, plan, authority):
        return [_result(
            FAIL, "unbound",
            "final provenance does not bind this caption generation")]
    count = len((compilation or {}).get("cues") or [])
    return [_result(
        PASS, f"{count} cues",
        "caption plan, projections, and final provenance share one authority")]
