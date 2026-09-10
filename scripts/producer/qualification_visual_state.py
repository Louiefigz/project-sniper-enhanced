#!/usr/bin/env python3
"""Measure and verify source-bound visual state for qualified media."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from ingest_admission_contract import canonical_bytes
from qualification_cadence_approval_store import publish_canonical
from qualification_mezzanine_files import read_canonical_evidence
from transcript_source_authority import SourceObservation, observe_source

POLICY = "sniper-qualified-visual-state-v1"


def _read_object(path: str, label: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} root must be an object")
    return value


def _source(manifest: dict, source_id: str | None) -> dict:
    rows = [row for row in manifest.get("sources") or []
            if isinstance(row, dict)]
    selected = [row for row in rows if row.get("id") == source_id] \
        if source_id else [row for row in rows if row.get("role") == "primary"]
    if len(selected) != 1:
        raise RuntimeError("visual-state source is ambiguous")
    source = selected[0]
    required = ("id", "path", "sourceSha256", "sourceSizeBytes")
    if any(source.get(key) in (None, "") for key in required):
        raise RuntimeError("visual-state source authority is incomplete")
    return source


def _observation(source: SourceObservation) -> dict:
    return {
        "path": source.path,
        "sha256": source.sha256,
        "sizeBytes": source.size_bytes,
        "device": source.device,
        "inode": source.inode,
        "mtimeNs": source.mtime_ns,
        "ctimeNs": source.ctime_ns,
    }


def _identity(source: SourceObservation) -> tuple[int, ...]:
    return (
        source.device, source.inode, source.size_bytes,
        source.mtime_ns, source.ctime_ns,
    )


def _assert_unchanged(source: SourceObservation) -> None:
    current = os.lstat(source.path)
    observed = (
        current.st_dev, current.st_ino, current.st_size,
        current.st_mtime_ns, current.st_ctime_ns,
    )
    if observed != _identity(source):
        raise RuntimeError("visual-state source changed during measurement")


def _implementation_sha() -> str:
    path = Path(__file__).parent / "motion" / "visual_state.py"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_zones(value: object) -> list[dict]:
    if isinstance(value, dict):
        value = value.get("treatmentMap") or value.get("zones") or value
    if not isinstance(value, list):
        raise ValueError(
            "zones JSON must be a list, or carry treatmentMap/zones"
        )
    zones = [
        row for row in value
        if isinstance(row, dict) and "outStart" in row and "outEnd" in row
    ]
    if not zones:
        raise ValueError("no zones with outStart/outEnd found")
    return zones


def _classify_zones(path: str, zones: list[dict]) -> list[dict]:
    from motion.visual_state import classify_zones
    return classify_zones(path, zones)


def build_receipt(manifest_path: str, zones_path: str,
                  source_id: str | None = None) -> dict:
    """Measure zones after one full-byte source observation."""
    manifest = _read_object(manifest_path, "manifest")
    source = _source(manifest, source_id)
    expected = source["sourceSha256"], source["sourceSizeBytes"]
    observed = observe_source(Path(source["path"]), expected)
    try:
        zones_raw = json.loads(Path(zones_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"visual-state zones are unreadable: {exc}") from exc
    zones = _load_zones(zones_raw)
    rows = _classify_zones(observed.path, zones)
    _assert_unchanged(observed)
    body = {
        "schemaVersion": 1,
        "policy": POLICY,
        "source": _observation(observed),
        "zones": zones,
        "zonesSha256": hashlib.sha256(canonical_bytes(zones)).hexdigest(),
        "measurement": {
            "implementationSha256": _implementation_sha(),
            "rows": rows,
            "rowsSha256": hashlib.sha256(canonical_bytes(rows)).hexdigest(),
        },
        "readCost": {
            "measurementFullSourceByteReads": 1,
            "verificationFullSourceByteReadsPerCall": 1,
            "measurementFullSourceBytesRead": observed.size_bytes,
            "sampleFramesDecoded": sum(
                int((row.get("signals") or {}).get("samples", 0))
                for row in rows if isinstance(row, dict)
            ),
        },
    }
    digest = hashlib.sha256(
        b"sniper-qualified-visual-state-v1\0" + canonical_bytes(body)
    ).hexdigest()
    return {**body, "receiptDigest": digest}


def verify_receipt(path: str) -> dict:
    """Rehash the receipt, implementation, measurement, and source bytes."""
    document = read_canonical_evidence(os.path.abspath(path))
    keys = {
        "schemaVersion", "policy", "source", "zones", "zonesSha256",
        "measurement", "readCost", "receiptDigest",
    }
    if set(document) != keys:
        raise RuntimeError("visual-state receipt schema is malformed")
    body = {key: value for key, value in document.items()
            if key != "receiptDigest"}
    measurement, source = document.get("measurement"), document.get("source")
    if not isinstance(measurement, dict) or not isinstance(source, dict):
        raise RuntimeError("visual-state receipt authority is malformed")
    expected = hashlib.sha256(
        b"sniper-qualified-visual-state-v1\0" + canonical_bytes(body)
    ).hexdigest()
    valid = (
        document.get("schemaVersion") == 1
        and document.get("policy") == POLICY
        and document.get("receiptDigest") == expected
        and document.get("zonesSha256")
        == hashlib.sha256(canonical_bytes(document.get("zones"))).hexdigest()
        and measurement.get("rowsSha256")
        == hashlib.sha256(canonical_bytes(measurement.get("rows"))).hexdigest()
        and measurement.get("implementationSha256") == _implementation_sha()
        and (document.get("readCost") or {}).get(
            "measurementFullSourceByteReads") == 1
        and (document.get("readCost") or {}).get(
            "verificationFullSourceByteReadsPerCall") == 1
    )
    if not valid:
        raise RuntimeError("visual-state receipt authority mismatch")
    observed = observe_source(
        Path(str(source.get("path", ""))),
        (source.get("sha256"), source.get("sizeBytes")),
    )
    if _observation(observed) != source:
        raise RuntimeError("visual-state source identity changed")
    return document


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    measure = commands.add_parser("measure")
    measure.add_argument("manifest")
    measure.add_argument("zones")
    measure.add_argument("--output", required=True)
    measure.add_argument("--source-id")
    verify = commands.add_parser("verify")
    verify.add_argument("receipt")
    return parser


def _execute(args: argparse.Namespace) -> dict:
    if args.command == "verify":
        document = verify_receipt(args.receipt)
        path = os.path.abspath(args.receipt)
    else:
        document = build_receipt(args.manifest, args.zones, args.source_id)
        path = os.path.abspath(args.output)
        publish_canonical(Path(path), document)
        document = verify_receipt(path)
    return {
        "ok": True,
        "receiptPath": path,
        "receiptDigest": document["receiptDigest"],
        "sourceSha256": document["source"]["sha256"],
        "rowsSha256": document["measurement"]["rowsSha256"],
        "readCost": document["readCost"],
    }


def main() -> int:
    try:
        result, code = _execute(_parser().parse_args()), 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        result, code = {"ok": False, "error": str(exc)}, 1
    sys.stdout.buffer.write(canonical_bytes(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
