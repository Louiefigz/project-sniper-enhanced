"""Immutable evidence archive for a rejected Palmier-native candidate."""
from __future__ import annotations

import os
import secrets
import shutil
from datetime import datetime, timezone

from fingerprints import file_sha256
from palmier.mcp_client import PalmierError
from palmier.timeline_authority import atomic_write_record


def _inside(out_dir: str, path: str) -> bool:
    try:
        return os.path.commonpath(
            [os.path.realpath(out_dir), os.path.realpath(path)]) \
            == os.path.realpath(out_dir)
    except ValueError:
        return False


def _sources(out_dir: str, qc: dict, reason: dict,
             candidate: dict) -> list[tuple[str, str, str | None]]:
    found: list[tuple[str, str, str | None]] = []
    export = qc.get("export") or {}
    found.append(("candidate-export", export.get("path"), export.get("hash")))
    deterministic = qc.get("deterministic") or {}
    audit_path = deterministic.get("auditPath") or os.path.join(
        out_dir, "palmier.native-audit.json")
    if deterministic.get("auditPath") or os.path.isfile(audit_path):
        found.append(("deterministic-audit", audit_path,
                      deterministic.get("auditHash")))
    authority = qc.get("authority") or {}
    native_input = authority.get("nativeInput") \
        or (candidate.get("nativeAuthority") or {}).get("nativeInput") \
        or {}
    live_input = authority.get("liveInput") \
        or (candidate.get("liveBuildAuthority") or {}).get("liveInput") or {}
    archived_input = native_input or live_input
    label = "native-input" if native_input else "live-input"
    found.append((label, archived_input.get("path"), archived_input.get("hash")))
    for index, row in enumerate(deterministic.get("frames") or []):
        if isinstance(row, dict):
            found.append((f"frame-{index + 1}", row.get("path"), row.get("hash")))
    for index, path in enumerate(reason["reviewArtifacts"]):
        found.append((f"review-{index + 1}", path, None))
    unique, rows = set(), []
    for label, path, digest in found:
        if not isinstance(path, str) or not path:
            continue
        real = os.path.realpath(path)
        if real in unique:
            continue
        if not _inside(out_dir, real) or os.path.islink(path) \
                or not os.path.isfile(real):
            raise PalmierError(f"Palmier rejected-candidate evidence is unsafe: {label}")
        unique.add(real)
        rows.append((label, real, digest if isinstance(digest, str) else None))
    return rows


def _copy(path: str, destination: str, expected: str | None) -> dict:
    before = os.stat(path)
    with open(path, "rb") as source, open(destination, "xb") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
        target.flush()
        os.fsync(target.fileno())
    after = os.stat(path)
    signature = lambda row: (row.st_dev, row.st_ino, row.st_size,
                             row.st_mtime_ns, row.st_ctime_ns)
    if signature(before) != signature(after):
        raise PalmierError("Palmier rejected-candidate evidence changed while archived")
    digest = file_sha256(destination)
    if expected is not None and digest != expected:
        raise PalmierError("Palmier rejected-candidate evidence hash is stale")
    return {"path": destination, "hash": digest, "bytes": os.path.getsize(destination)}


def _archive_name(candidate: dict) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    fingerprint = str(candidate.get("fingerprint") or "unknown")[:12]
    return f"{stamp}-{fingerprint}-{secrets.token_hex(4)}"


def _archive_candidate(out_dir: str, candidate: dict, qc: dict,
                       reason: dict, state: str) -> str:
    root = os.path.join(out_dir, ".sniper-learning", "native-qc-history")
    os.makedirs(root, exist_ok=True)
    name = _archive_name(candidate)
    staging, final = os.path.join(root, f".{name}.tmp"), os.path.join(root, name)
    os.mkdir(staging, 0o700)
    try:
        atomic_write_record(os.path.join(staging, "candidate.json"), candidate)
        atomic_write_record(os.path.join(staging, "qc.json"), qc)
        atomic_write_record(os.path.join(staging, "rejection.json"), reason)
        evidence_dir = os.path.join(staging, "evidence")
        os.mkdir(evidence_dir, 0o700)
        evidence = []
        for index, (label, path, digest) in enumerate(
                _sources(out_dir, qc, reason, candidate)):
            extension = os.path.splitext(path)[1][:16]
            destination = os.path.join(evidence_dir, f"{index + 1:03d}-{label}{extension}")
            enforce = digest if state == "qc-rejected" else None
            copied = _copy(path, destination, enforce)
            evidence.append({"label": label, "sourcePath": path,
                             "expectedHash": digest,
                             "hashMatch": digest is None or copied["hash"] == digest,
                             **copied})
        manifest = {"schemaVersion": 1, "state": state,
                    "candidate": {key: candidate.get(key) for key in
                                  ("projectId", "timelineId", "fingerprint")},
                    "evidence": evidence}
        atomic_write_record(os.path.join(staging, "archive.json"), manifest)
        for entry in os.listdir(evidence_dir):
            os.chmod(os.path.join(evidence_dir, entry), 0o400)
        os.chmod(evidence_dir, 0o500)
        for entry in ("candidate.json", "qc.json", "rejection.json", "archive.json"):
            os.chmod(os.path.join(staging, entry), 0o400)
        os.replace(staging, final)
        return final
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def archive_rejected_candidate(out_dir: str, candidate: dict,
                               qc: dict, reason: dict) -> str:
    """Copy every current evidence byte before any live status is changed."""
    return _archive_candidate(out_dir, candidate, qc, reason, "qc-rejected")


def archive_discarded_candidate(out_dir: str, candidate: dict,
                                qc: dict, reason: dict) -> str:
    """Preserve an explicitly discarded candidate and its available evidence."""
    return _archive_candidate(out_dir, candidate, qc, reason, "discarded")
