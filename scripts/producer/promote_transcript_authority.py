#!/usr/bin/env python3
"""Rebind a quality transcript between independently admitted identical media."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from ingest_admission_contract import _read_regular
from ingest_execution_authority import execution_media_authority_entries
from resume_ingest_transcription import MAX_MANIFEST_BYTES, _manifest
from transcript_source_authority import (
    bind_result,
    observe_source,
    require_same_source,
    verify_result,
)
from transcript_timing_quality import require_timing_quality

POLICY = "sniper-transcript-authority-promotion-v1"


def _source(manifest: dict, source_id: str) -> dict:
    rows = manifest.get("sources")
    matches = [row for row in rows or []
               if isinstance(row, dict) and row.get("id") == source_id]
    if len(matches) != 1:
        raise RuntimeError(f"manifest must contain exactly one {source_id!r}")
    return matches[0]


def _source_facts(entries: list[dict], row: dict) -> tuple[str, int]:
    matches = [
        entry for entry in entries
        if entry.get("lane") == "source"
        and entry.get("snapshotPath") == row.get("path")
    ]
    if len(matches) != 1:
        raise RuntimeError("manifest source lacks one admitted source-set entry")
    entry = matches[0]
    return entry["sha256"], entry["sizeBytes"]


def _transcript_path(manifest_path: Path, row: dict) -> Path:
    expected = f"{row['id']}.transcript.json"
    if row.get("transcriptPath") != expected:
        raise RuntimeError(
            f"{row['id']} transcriptPath must be canonical before promotion")
    return manifest_path.parent / expected


def _transcript(path: Path) -> tuple[dict, str]:
    payload = _read_regular(
        path, MAX_MANIFEST_BYTES, "transcript promotion candidate")
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("transcript promotion candidate is malformed") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("transcript promotion candidate must be an object")
    return parsed, hashlib.sha256(payload).hexdigest()


def _admitted_source(
    manifest_path: Path,
    source_id: str,
) -> tuple[dict, tuple[str, int], dict]:
    manifest = _manifest(manifest_path)
    entries = execution_media_authority_entries(
        {}, manifest, str(manifest_path))
    if entries is None:
        raise RuntimeError("transcript promotion requires source-set admission")
    row = _source(manifest, source_id)
    return row, _source_facts(entries, row), manifest


def _candidate(
    manifest_path: Path,
    source_id: str,
) -> tuple[dict, tuple[str, int], dict]:
    row, facts, manifest = _admitted_source(manifest_path, source_id)
    transcript_path = _transcript_path(manifest_path, row)
    payload, digest = _transcript(transcript_path)
    error = verify_result(
        payload, {**row, "sourceSizeBytes": facts[1]},
        str(transcript_path))
    if error:
        raise RuntimeError(f"candidate transcript authority failed: {error}")
    quality = require_timing_quality(payload)
    authority = payload["sourceMediaAuthority"]
    evidence = {
        "transcriptSha256": digest,
        "bindingDigest": authority["bindingDigest"],
        "sourceSetDigest": manifest["sourceSetAdmission"]["sourceSetDigest"],
        "quality": quality,
    }
    return payload, facts, evidence


def _promotion(
    candidate: dict,
    facts: tuple[str, int],
    evidence: dict,
    target_manifest: dict,
) -> dict:
    unsigned = {
        key: value for key, value in candidate.items()
        if key != "sourceMediaAuthority"
    }
    if "transcriptPromotionAuthority" in unsigned:
        raise RuntimeError("chained transcript authority promotion is forbidden")
    unsigned["transcriptPromotionAuthority"] = {
        "schemaVersion": 1,
        "policy": POLICY,
        "sourceSha256": facts[0],
        "sourceSizeBytes": facts[1],
        "candidateTranscriptSha256": evidence["transcriptSha256"],
        "candidateBindingDigest": evidence["bindingDigest"],
        "candidateSourceSetDigest": evidence["sourceSetDigest"],
        "targetSourceSetDigest":
            target_manifest["sourceSetAdmission"]["sourceSetDigest"],
        "timingQuality": evidence["quality"],
    }
    return unsigned


def _atomic_publish(path: Path, payload: dict) -> None:
    descriptor, staged = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        try:
            os.unlink(staged)
        except FileNotFoundError:
            pass


def promote(
    target_manifest_path: Path,
    candidate_manifest_path: Path,
    source_id: str,
) -> dict:
    """Verify both authorities and atomically publish one rebound transcript."""
    target_path = Path(os.path.abspath(target_manifest_path))
    candidate_path = Path(os.path.abspath(candidate_manifest_path))
    target_row, target_facts, target_manifest = _admitted_source(
        target_path, source_id)
    candidate, candidate_facts, evidence = _candidate(
        candidate_path, source_id)
    if target_facts != candidate_facts:
        raise RuntimeError(
            "candidate and target admitted media SHA-256/size differ")
    output_path = _transcript_path(target_path, target_row)
    before = observe_source(Path(target_row["path"]), target_facts)
    rebound = bind_result(
        _promotion(candidate, target_facts, evidence, target_manifest), before)
    require_timing_quality(rebound)
    error = verify_result(
        rebound, {**target_row, "sourceSizeBytes": target_facts[1]},
        str(output_path))
    if error:
        raise RuntimeError(f"rebound transcript authority failed: {error}")
    require_same_source(
        before, observe_source(Path(target_row["path"]), target_facts))
    _atomic_publish(output_path, rebound)
    return {
        "status": "done", "policy": POLICY, "sourceId": source_id,
        "transcriptPath": str(output_path),
        "sourceSha256": target_facts[0],
        "sourceSizeBytes": target_facts[1],
        "candidateTranscriptSha256": evidence["transcriptSha256"],
        "publishedTranscriptSha256":
            hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "timingQuality": evidence["quality"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote a transcript across exact admitted media bytes")
    parser.add_argument("target_manifest")
    parser.add_argument("candidate_manifest")
    parser.add_argument("--source-id", default="raw-1")
    args = parser.parse_args()
    try:
        result = promote(
            Path(args.target_manifest), Path(args.candidate_manifest),
            args.source_id)
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), flush=True)
        return 1
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
