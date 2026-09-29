#!/usr/bin/env python3
"""Fixed, offline source inspection for catalog admission receipts."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path

MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = 16 * 1024 * 1024


def _read_file(path: str, maximum: int, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = None
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 \
                or not 1 <= before.st_size <= maximum:
            raise ValueError(f"{label} must be one bounded single-link file")
        data = bytearray()
        while len(data) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(data)))
            if not chunk:
                raise ValueError(f"{label} changed during its bounded read")
            data.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    identity = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns,
                            row.st_ctime_ns, row.st_nlink)
    if identity(before) != identity(after):
        raise ValueError(f"{label} changed during its bounded read")
    return bytes(data)


def _request(path: str) -> dict:
    try:
        value = json.loads(_read_file(path, MAX_REQUEST_BYTES, "runner request"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("runner request is not valid JSON") from exc
    keys = {"schemaVersion", "kind", "source", "catalogRecordSha256",
            "resourceClass", "resourceEvidence"}
    if not isinstance(value, dict) or set(value) != keys or value["schemaVersion"] != 1:
        raise ValueError("runner request fields are invalid")
    source = value["source"]
    if not isinstance(source, dict) or set(source) != {"path", "sha256"}:
        raise ValueError("runner source pin is invalid")
    if value["kind"] != "source-inspection":
        raise ValueError("runner kind is invalid")
    return value


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dependencies(request: dict) -> tuple[list[str], list[str]]:
    evidence = request["resourceEvidence"]
    dependency = evidence.get("dependencySize") if isinstance(evidence, dict) else None
    missing = dependency.get("missingReferences") if isinstance(dependency, dict) else None
    external = dependency.get("externalReferences") if isinstance(dependency, dict) else None
    missing = missing if isinstance(missing, list) else []
    external = external if isinstance(external, list) else []
    if any(not isinstance(item, str) for item in missing + external):
        raise ValueError("catalog dependency evidence is malformed")
    allowed = {"https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"}
    unsupported = sorted(set(external) - allowed)
    return sorted(set(missing)), unsupported


def _write_exclusive(path: str, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(data):
            offset += os.write(descriptor, data[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _artifact(request: dict, source: bytes,
              missing: list[str], unsupported: list[str]) -> bytes:
    dependency_status = "unresolved" if missing or unsupported else "statically-closed"
    value = {
        "schemaVersion": 1,
        "scope": "catalog-static-source-inspection",
        "sourceSha256": _sha(source),
        "resourceClass": request["resourceClass"],
        "catalogRecordSha256": request["catalogRecordSha256"],
        "staticDependencyStatus": dependency_status,
        "missingReferences": missing,
        "unsupportedExternalReferences": unsupported,
        "approvalClaims": {"runtime": False, "render": False, "quality": False},
    }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def run(request_path: str, artifact_path: str) -> dict:
    """Inspect one exact catalog source without network or runtime claims."""
    request = _request(request_path)
    source = _read_file(request["source"]["path"], MAX_SOURCE_BYTES, "catalog source")
    if _sha(source) != request["source"]["sha256"]:
        raise ValueError("catalog source SHA-256 differs from the request")
    missing, unsupported = _dependencies(request)
    artifact = _artifact(request, source, missing, unsupported)
    _write_exclusive(artifact_path, artifact)
    return {
        "schemaVersion": 1,
        "scope": "catalog-controller-static-source-inspection",
        "kind": request["kind"],
        "sourceSha256": _sha(source),
        "catalogRecordSha256": request["catalogRecordSha256"],
        "resourceClass": request["resourceClass"],
        "artifactSha256": _sha(artifact),
        "artifactBytes": len(artifact),
        "missingDependencies": missing,
        "unsupportedDependencies": unsupported,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write("usage: catalog_receipt_runner.py REQUEST ARTIFACT\n")
        return 2
    try:
        result = run(args[0], args[1])
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"catalog-receipt-runner: {exc}\n")
        return 4
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
