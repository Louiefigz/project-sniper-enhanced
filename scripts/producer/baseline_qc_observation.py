#!/usr/bin/env python3
"""Bind one baseline media observation to its complete Audit B authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fingerprints import plan_content_hash


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_document(value: dict) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _regular(path: Path, root: Path, label: str) -> Path:
    lexical = root / path.name
    if lexical.is_symlink() or not lexical.is_file():
        raise RuntimeError(f"baseline {label} is not a regular file")
    resolved = lexical.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"baseline {label} escapes the render directory") from exc
    return resolved


def _document(path: Path, root: Path, label: str) -> tuple[Path, dict]:
    resolved = _regular(path, root, label)
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"baseline {label} is malformed") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"baseline {label} is not an object")
    return resolved, value


def _check_audit(report: dict, final: Path) -> None:
    try:
        reported_final = Path(report["final"]).resolve(strict=True)
    except (KeyError, OSError, TypeError) as exc:
        raise RuntimeError("baseline Audit B final path is malformed") from exc
    checks = report.get("checks")
    counts = report.get("counts")
    if reported_final != final or not isinstance(checks, list):
        raise RuntimeError("baseline Audit B does not identify the observed final")
    observed = {
        status: sum(
            isinstance(row, dict) and row.get("status") == status
            for row in checks
        )
        for status in ("pass", "warn", "fail")
    }
    if (
        not checks
        or counts != observed
        or report.get("exitCode") != 0
        or report.get("overall") not in {"pass", "warn"}
        or observed["fail"] != 0
    ):
        raise RuntimeError("baseline Audit B result is incomplete or failing")


def _check_assembled(record: dict, final_sha256: str, plan: dict) -> None:
    if (
        record.get("authorityHash") != final_sha256
        or record.get("planHash") != plan_content_hash(plan)
    ):
        raise RuntimeError(
            "baseline assembled authority does not bind final and plan")


def observe_qc(final_path: Path, final_sha256: str) -> dict:
    """Return complete QC/provenance facts bound to ``final_path``."""
    final = final_path.resolve(strict=True)
    root = final.parent
    audit_path, audit = _document(
        root / "audit_report.json", root, "Audit B report")
    sidecar_path, sidecar = _document(
        root / f"{final.name}.assembled.json", root, "assembled authority")
    plan_path, plan = _document(
        root / "edit_plan.json", root, "render plan")
    timeline_path, timeline = _document(
        root / "timeline_map.json", root, "timeline map")
    _check_audit(audit, final)
    _check_assembled(sidecar, final_sha256, plan)
    duration = timeline.get("outputDuration")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise RuntimeError("baseline timeline map has no positive duration")
    return {
        "finalSha256": final_sha256,
        "auditReport": {
            "sha256": _sha256_file(audit_path),
            "documentSha256": _sha256_document(audit),
            "document": audit,
        },
        "assembledAuthority": {
            "sha256": _sha256_file(sidecar_path),
            "recordSha256": _sha256_document(sidecar),
            "record": sidecar,
        },
        "renderPlan": {
            "sha256": _sha256_file(plan_path),
            "contentHash": plan_content_hash(plan),
        },
        "timelineMap": {
            "sha256": _sha256_file(timeline_path),
            "outputDuration": duration,
        },
    }
