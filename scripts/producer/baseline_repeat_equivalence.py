#!/usr/bin/env python3
"""Preserve cold output and prove warm repeat parity with the pinned oracle."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from baseline_repeat_validation import (
    CALIBRATION_PATH,
    CODEC_FLOOR_CLASS,
    PIXEL_IDENTICAL_CLASS,
)
from baseline_validation_common import document_sha256
from current_render_graph_contract import file_hash, object_hash
from current_render_calibration_source import verify_source_record
from current_render_oracle import CODEC_FLOOR_POLICY, prove

_EVIDENCE_DIR = ".baseline-repeat-evidence"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _safe_output(root: Path, relative: str) -> Path:
    lexical = root / relative
    if lexical.is_symlink() or not lexical.is_file():
        raise RuntimeError("baseline first-run output is not a regular file")
    resolved = lexical.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("baseline first-run output escapes trace cwd") from exc
    return resolved


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def preserve_first_output(root: Path, fixture: dict[str, Any]) -> Path:
    """Atomically move the observed cold final aside before the warm render."""
    source = _safe_output(root, fixture["outputPaths"][0])
    base = root / _EVIDENCE_DIR
    if base.is_symlink():
        raise RuntimeError("baseline repeat-evidence root is a symlink")
    evidence = base / fixture["fixtureId"]
    if evidence.is_symlink():
        raise RuntimeError("baseline fixture evidence directory is a symlink")
    evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    if evidence.resolve(strict=True).parent != base.resolve(strict=True):
        raise RuntimeError("baseline fixture evidence directory escapes trace cwd")
    target = evidence / "first-run-final.mp4"
    os.replace(source, target)
    _sync_directory(evidence)
    _sync_directory(source.parent)
    return target


def _receipt(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("baseline repeat oracle receipt is malformed") from exc
    if not isinstance(value, dict):
        raise RuntimeError("baseline repeat oracle receipt is not an object")
    return value


def _verify_bound_file(path_value: object, digest: object, label: str) -> None:
    if not isinstance(path_value, str) or not isinstance(digest, str):
        raise RuntimeError(f"baseline calibration {label} record is malformed")
    lexical = Path(path_value)
    if lexical.is_symlink() or not lexical.is_file():
        raise RuntimeError(f"baseline calibration {label} file is unavailable")
    if file_hash(lexical.resolve(strict=True)) != digest:
        raise RuntimeError(f"baseline calibration {label} hash is stale")


def _calibration_document() -> dict:
    path = _PROJECT_ROOT / CALIBRATION_PATH
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("baseline codec-floor calibration is unavailable")
    document = _receipt(path)
    unhashed = {key: value for key, value in document.items()
                if key != "receiptHash"}
    observed = document.get("observed") or {}
    if (
        document.get("policy") != CODEC_FLOOR_POLICY
        or document.get("policyHash") != object_hash(CODEC_FLOOR_POLICY)
        or document.get("receiptHash") != object_hash(unhashed)
        or document.get("passed") is not True
        or observed.get("pairCount", 0)
        < CODEC_FLOOR_POLICY["minimumControlPairs"]
    ):
        raise RuntimeError("baseline codec-floor calibration is not qualified")
    sources = document.get("sourceFiles")
    if not isinstance(sources, dict) or not sources:
        raise RuntimeError("baseline calibration source closure is missing")
    for source_path, digest in sources.items():
        _verify_bound_file(source_path, digest, "source")
    verify_source_record(document.get("source"))
    for name in ("ffmpeg", "ffprobe", "oracle", "python"):
        record = (document.get("tools") or {}).get(name) or {}
        _verify_bound_file(record.get("path"), record.get("sha256"), name)
    return document


def calibration_authority() -> dict:
    """Return a fully reverified codec-floor calibration authority."""
    path = _PROJECT_ROOT / CALIBRATION_PATH
    document = _calibration_document()
    return {
        "path": CALIBRATION_PATH,
        "sha256": file_hash(path),
        "documentSha256": document_sha256(document),
        "document": document,
    }


def prove_repeat(
    root: Path,
    fixture: dict[str, Any],
    first: Path,
) -> dict[str, Any]:
    """Compare preserved first-run media with the immediate warm final."""
    warm = _safe_output(root, fixture["outputPaths"][0])
    receipt_path = first.parent / "repeat-oracle-v1.json"
    calibration = calibration_authority()
    error = None
    try:
        receipt = prove(first, warm, receipt_path)
    except RuntimeError as exc:
        error = str(exc)
        if not receipt_path.is_file():
            raise
        receipt = _receipt(receipt_path)
    picture = receipt.get("pictureComparison") or {}
    exact = picture.get("pixelIdentical") is True
    codec = (
        picture.get("pixelIdentical") is False
        and picture.get("codecFloorEquivalent") is True)
    qualified = receipt.get("passed") is True and (exact or codec)
    classification = (PIXEL_IDENTICAL_CLASS if exact else CODEC_FLOOR_CLASS) \
        if qualified else "repeat-equivalence-unqualified"
    if calibration_authority() != calibration:
        raise RuntimeError("baseline codec-floor calibration changed during proof")
    try:
        relative = str(receipt_path.relative_to(root))
    except ValueError as exc:
        raise RuntimeError("baseline repeat receipt escapes trace cwd") from exc
    return {
        "schemaVersion": 1,
        "classification": classification,
        "receiptPath": relative,
        "receiptSha256": file_hash(receipt_path),
        "receipt": receipt,
        "calibrationAuthority": calibration,
        "error": error,
    }
