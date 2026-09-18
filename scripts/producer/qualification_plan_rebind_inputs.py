"""Qualified source and visual-state inputs for deterministic plan rebinding."""

from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from pathlib import Path

from ingest_admission_contract import canonical_bytes
from ingest_execution_authority import verify_execution_media_authority
from qualification_cadence_approval import verify_cadence_approval
from qualification_mezzanine import verify_qualification_evidence
from qualification_visual_state import verify_receipt as verify_visual_state

_POLICY = "sniper-overcap-qualification-mezzanine-v1"


class RebindError(RuntimeError):
    """A deterministic rebind could not be proved."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


@dataclass(frozen=True)
class RebindAuthorityPaths:
    """Exact retained files consumed by authority verification."""

    manifest: Path
    qualification: Path
    cadence: Path


def select_source(manifest: dict, requested: str | None) -> dict:
    """Select one explicit or uniquely primary transcript-bearing source."""
    rows = [row for row in manifest.get("sources") or [] if isinstance(row, dict)]
    selected = (
        [row for row in rows if row.get("id") == requested]
        if requested
        else [row for row in rows if row.get("role") == "primary"]
    )
    if not requested and not selected and len(rows) == 1:
        selected = rows
    if len(selected) != 1:
        raise RebindError(
            "manifest source is ambiguous; pass --source-id explicitly",
            {"availableSourceIds": [row.get("id") for row in rows]},
        )
    source = selected[0]
    if (
        type(source.get("id")) is not str
        or not source["id"]
        or type(source.get("transcriptPath")) is not str
        or not source["transcriptPath"]
    ):
        raise RebindError("selected source has no id or transcriptPath")
    return source


def _finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _rate_value(value: object) -> float | None:
    if type(value) is not str or value.count("/") != 1:
        return None
    numerator, denominator = value.split("/")
    if not numerator.isdigit() or not denominator.isdigit():
        return None
    if int(numerator) <= 0 or int(denominator) <= 0:
        return None
    return int(numerator) / int(denominator)


def qualification_errors(evidence: dict, source: dict) -> list[str]:
    """Return exact qualification-to-admitted-source binding errors."""
    output = evidence.get("output") or {}
    stream = output.get("streamFacts") or {}
    target = evidence.get("target") or {}
    unsigned = {
        key: value for key, value in evidence.items() if key != "evidenceDigest"
    }
    expected_digest = hashlib.sha256(
        b"sniper-overcap-qualification-mezzanine-v1\0" + canonical_bytes(unsigned)
    ).hexdigest()
    errors = _identity_errors(evidence, source, output, expected_digest)
    expected_rate = target.get("rate")
    expected_fps = _rate_value(expected_rate)
    source_fps = source.get("fps")
    if (
        expected_fps is None
        or not _finite_number(source_fps)
        or abs(float(source_fps) - expected_fps) > 1e-6
        or source.get("frameRate") != expected_rate
    ):
        errors.append("manifest cadence differs from qualified output")
    expected_duration = stream.get("durationSeconds")
    if (
        not _finite_number(expected_duration)
        or not _finite_number(source.get("duration"))
        or abs(float(source["duration"]) - float(expected_duration)) > 0.05
    ):
        errors.append("manifest duration differs from qualified output")
    resolution = [target.get("width"), target.get("height")]
    if source.get("resolution") != resolution:
        errors.append("manifest resolution differs from qualified output")
    return errors


def _identity_errors(
    evidence: dict, source: dict, output: dict, expected_digest: str
) -> list[str]:
    errors = []
    if evidence.get("policy") != _POLICY:
        errors.append("qualification policy is not the governed mezzanine policy")
    if evidence.get("evidenceDigest") != expected_digest:
        errors.append("qualification evidence digest is invalid")
    if output.get("sha256") != source.get("sourceSha256"):
        errors.append("manifest source SHA-256 differs from qualified output")
    manifest_size = source.get("sourceSizeBytes")
    if (
        isinstance(manifest_size, bool)
        or not isinstance(manifest_size, int)
        or manifest_size <= 0
        or output.get("sizeBytes") != manifest_size
    ):
        errors.append("manifest source size differs from qualified output")
    return errors


def verify_authorities(
    plan: dict,
    manifest: dict,
    paths: RebindAuthorityPaths,
    source: dict,
) -> tuple[dict, dict]:
    """Reverify exact qualification, cadence, and admitted source authorities."""
    qualification_abs = os.path.abspath(paths.qualification)
    cadence_abs = os.path.abspath(paths.cadence)
    qualification = verify_qualification_evidence(qualification_abs)
    errors = qualification_errors(qualification, source)
    if errors:
        raise RebindError(
            "fresh source is not the qualified output", {"errors": errors}
        )
    admitted = verify_execution_media_authority(
        plan, manifest, os.path.abspath(paths.manifest)
    )
    if admitted is not True:
        raise RebindError("fresh manifest lacks admitted source-set authority")
    cadence = verify_cadence_approval(cadence_abs)
    _bind_cadence(cadence, qualification, qualification_abs, source)
    return qualification, cadence


def _bind_cadence(
    cadence: dict,
    qualification: dict,
    qualification_path: str,
    source: dict,
) -> None:
    authority = cadence.get("qualification") or {}
    normalized = (cadence.get("media") or {}).get("normalized") or {}
    downstream = cadence.get("downstreamTimeAuthority") or {}
    expected_sha = qualification["output"]["sha256"]
    valid = (
        authority.get("evidencePath") == qualification_path
        and authority.get("evidenceDigest") == qualification.get("evidenceDigest")
        and normalized.get("sha256") == expected_sha
        and normalized.get("sizeBytes") == qualification["output"]["sizeBytes"]
        and downstream.get("mediaSha256") == expected_sha
        and downstream.get("transcriptAndCutsMustBindThisAsset") is True
        and downstream.get("rawSourceIsNotEditTimeAuthority") is True
        and source.get("sourceSha256") == expected_sha
    )
    if not valid:
        raise RebindError(
            "cadence approval does not bind the requested qualified source"
        )


def visual_state_authority(
    path: Path,
    source: dict | None = None,
) -> tuple[dict, dict]:
    """Verify and load the one source-bound global C0679 measurement."""
    try:
        receipt = verify_visual_state(str(path))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise RebindError(f"visual-state evidence is unreadable: {exc}") from exc
    if source is not None:
        _bind_visual_source(receipt, source)
    value = (receipt.get("measurement") or {}).get("rows")
    if not isinstance(value, list) or len(value) != 1:
        raise RebindError("visual-state evidence must contain one global source row")
    row = value[0]
    if not isinstance(row, dict):
        raise RebindError("global visual-state row must be an object")
    bbox = row.get("faceBBoxNorm")
    if (
        row.get("state") not in ("talking-head", "screen-share", "mixed")
        or not isinstance(bbox, list)
        or len(bbox) != 4
        or not all(_finite_number(value) for value in bbox)
        or not _valid_bbox([float(value) for value in bbox])
        or not _finite_number(row.get("outStart"))
        or abs(float(row["outStart"])) > 1e-9
        or not _finite_number(row.get("outEnd"))
        or float(row["outEnd"]) <= 0
        or (
            source is not None
            and (
                not _finite_number(source.get("duration"))
                or abs(float(row["outEnd"]) - float(source["duration"])) > 0.05
            )
        )
    ):
        raise RebindError("global visual-state row has no valid state/faceBBoxNorm")
    return receipt, row


def global_visual_state(path: Path, source: dict | None = None) -> dict:
    """Return the verified global visual-state row."""
    return visual_state_authority(path, source)[1]


def _bind_visual_source(receipt: dict, source: dict) -> None:
    authority = receipt.get("source") or {}
    valid = (
        authority.get("path") == os.path.abspath(str(source.get("path", "")))
        and authority.get("sha256") == source.get("sourceSha256")
        and authority.get("sizeBytes") == source.get("sourceSizeBytes")
    )
    if not valid:
        raise RebindError(
            "visual-state receipt does not bind the selected admitted source"
        )


def _valid_bbox(bbox: list[float]) -> bool:
    x, y, width, height = bbox
    return (
        0 <= x < 1
        and 0 <= y < 1
        and 0 < width <= 1
        and 0 < height <= 1
        and x + width <= 1
        and y + height <= 1
    )
