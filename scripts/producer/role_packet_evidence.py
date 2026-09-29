"""Shared source/reference evidence: authored once per production, sealed, and bound by hash into role packets.

Without it every clip author and critic re-derives the same source facts. The production's
coordinator writes them once into a draft; sealing re-reads the admitted manifest, transcripts and
every bound file, validates structure and provenance and publishes an immutable
SHARED-EVIDENCE-vN.json that records its own path. Exclusive creation serializes concurrent seals:
a second seal of the same version fails instead of replacing the first. Given titles and scripts
are not shared evidence (requirement revision `approved-content-production-2026-09-27`): the batch
authority is their only source and change record. Binding and re-checking live in
`role_packet_evidence_record`. The engine never supplies an observation, attribution or verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from role_packet_evidence_record import (ENGINE_LIMITS, KIND, PREFIX, changed_inputs, content_digest, evidence_check,
                                         observed_inputs)
from role_packet_evidence_schema import DRAFT_KEYS, EvidenceError, authored_fields, draft_fields
from role_packet_files import (ArtifactError, canonical_directory, canonical_file, proposed_paths, read_json,
                               staged_work, write_json_new)

DRAFT_KIND = "sniper-shared-source-evidence-draft"


@dataclass(frozen=True)
class EvidenceDraftRequest:
    """Explicit inputs for a new shared-evidence draft."""
    directory: str
    manifest: str
    bindings: tuple[str, ...] = ()


def write_draft(request: EvidenceDraftRequest) -> dict:
    """Publish a structure-only draft beside the next unused record version; nothing is authored here."""
    directory = canonical_directory(request.directory)
    if staged_work(directory):
        raise EvidenceError(f"shared evidence must stay outside the staged project or attempt {staged_work(directory)}")
    paths = proposed_paths(directory, PREFIX)
    draft = {"schemaVersion": 1, "kind": DRAFT_KIND, "version": paths["version"], "record": str(paths["record"]),
             **observed_inputs(request.manifest, request.bindings), **draft_fields()}
    return {"draft": str(paths["observations"]), "record": str(paths["record"]),
            "sha256": write_json_new(paths["observations"], draft)}


def seal(draft_file: str) -> dict:
    """Validate an authored draft against fresh observations and publish its immutable record."""
    file = canonical_file(draft_file)
    draft = read_json(file)
    if draft.get("schemaVersion") != 1 or draft.get("kind") != DRAFT_KIND or not isinstance(draft.get("version"), int):
        raise EvidenceError(f"{file} is not a shared-evidence draft")
    record_path = file.parent / f"{PREFIX}-v{draft['version']}.json"
    if draft.get("record") != str(record_path) or set(draft) - DRAFT_KEYS:
        raise EvidenceError(f"the draft must name {record_path} and carry only its template fields "
                            f"(unknown: {sorted(set(draft) - DRAFT_KEYS)})")
    current = observed_inputs(draft["manifest"]["path"], draft.get("bound") or [])
    changes = changed_inputs(draft, current)
    if changes:
        raise EvidenceError(f"stale shared-evidence inputs since the draft was written: {changes[:8]}; write a new draft")
    record = {"schemaVersion": 1, "kind": KIND, "version": draft["version"], "recordPath": str(record_path),
              "sealedAt": datetime.now(timezone.utc).isoformat(),
              "draft": {"path": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()},
              **current, **authored_fields(draft, current), "engineLimits": list(ENGINE_LIMITS)}
    record["contentSha256"] = content_digest(record)
    return {"record": str(record_path), "sha256": write_json_new(record_path, record),
            "contentSha256": record["contentSha256"], "version": record["version"]}


def evidence_arguments(parser: argparse.ArgumentParser) -> None:
    """context.py flags: draft once per production, seal it, re-check it, then bind it into role packets."""
    parser.add_argument("--shared-evidence", help="Sealed SHARED-EVIDENCE-vN.json to bind into this --role packet")
    parser.add_argument("--evidence-draft", metavar="DIR",
                        help="Write a structure-only shared-evidence draft in DIR (with --manifest and --bind)")
    parser.add_argument("--evidence-seal", metavar="DRAFT", help="Validate an authored draft and publish its record")
    parser.add_argument("--evidence-check", metavar="RECORD",
                        help="Re-check a sealed record: unedited, at its recorded path, not superseded, inputs unchanged")
    parser.add_argument("--manifest", help="Admitted asset_manifest.json whose sources the evidence describes")
    parser.add_argument("--bind", action="append", default=[], metavar="KEY=PATH",
                        help="A file the shared evidence binds, e.g. a reference image or a decision record (repeat)")


def run_evidence(args: argparse.Namespace) -> dict:
    """The one evidence operation the arguments name."""
    if args.evidence_check:
        return evidence_check(args.evidence_check)
    if args.evidence_seal:
        return seal(args.evidence_seal)
    if not args.manifest:
        raise EvidenceError("--evidence-draft requires --manifest <admitted asset_manifest.json>")
    return write_draft(EvidenceDraftRequest(args.evidence_draft, args.manifest, tuple(args.bind)))


def evidence_main(args: argparse.Namespace) -> int:
    """Draft, seal or re-check shared evidence; 2 with a bounded error when an input is missing, stale or malformed."""
    try:
        result = run_evidence(args)
    except (ArtifactError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "shared-evidence-unavailable", "errorType": type(error).__name__,
                          "error": str(error)[:2048]}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0
