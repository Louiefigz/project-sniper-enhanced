"""Shared source/reference evidence: authored once per production, sealed, and bound by hash into role packets.

Without it every clip author and critic re-derives the same source facts. The production's
coordinator writes them once into a draft; sealing re-reads the admitted manifest, transcripts and
every bound file, validates structure and provenance and publishes an immutable
SHARED-EVIDENCE-vN.json that records its own path. Exclusive creation serializes concurrent seals:
a second seal of the same version fails instead of replacing the first. Given titles and scripts
are not shared evidence (requirement revision `approved-content-production-2026-09-27`): the batch
authority is their only source and change record. Binding and re-checking live in
`role_packet_evidence_record`. The engine never supplies an attribution or verdict.

New drafts are schema version 2 (P2-07). A version 2 draft with speaker intervals is sealed with --batch B.
The engine then observes which approved scripts the intervals must cover, and binds the speaker observations
P2-06 measured for them. Version 1 drafts still seal and version 1 records still verify, exactly as before (ST-2).
--evidence-unresolved lists a v2 draft's intervals that are not established: what the operator is asked to hear.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from role_packet_evidence_record import (ENGINE_LIMITS, KIND, PREFIX, changed_inputs, content_digest, evidence_check,
                                         observed_inputs, sealed_coverage)
from role_packet_evidence_schema import (SCHEMA_VERSION, SCHEMA_VERSIONS, EvidenceError, authored_fields, draft_fields,
                                         draft_keys, field_context)
from role_packet_evidence_speakers import mapped_intervals, speakers_v2
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
    draft = {"schemaVersion": SCHEMA_VERSION, "kind": DRAFT_KIND, "version": paths["version"],
             "record": str(paths["record"]), **observed_inputs(request.manifest, request.bindings), **draft_fields()}
    return {"draft": str(paths["observations"]), "record": str(paths["record"]),
            "sha256": write_json_new(paths["observations"], draft)}


def engine_fields(draft: dict, fields: dict, current: dict, batch: str | None) -> dict:
    """What the engine adds to a record by schema version: nothing for 1; for 2, its observed coverage (P2-07)."""
    if draft["schemaVersion"] == 1:
        if batch is not None:
            raise EvidenceError("--batch applies to version 2 drafts; a version 1 draft records no coverage")
        return {}
    if draft.get("coverage") is not None:
        raise EvidenceError("coverage is observed by the engine at seal from --batch; leave it null in the draft")
    return {"coverage": sealed_coverage(fields, current, batch)}


def seal(draft_file: str, batch: str | None = None) -> dict:
    """Validate an authored draft against fresh observations and publish its immutable record.

    A version 2 draft with speaker intervals needs ``batch``, the deadline batch whose approved scripts its intervals
    must cover (P2-07). A version 1 draft seals exactly as before.
    """
    file = canonical_file(draft_file)
    draft = read_json(file)
    version = draft.get("schemaVersion")
    if type(version) is not int or version not in SCHEMA_VERSIONS or draft.get("kind") != DRAFT_KIND \
            or not isinstance(draft.get("version"), int):
        raise EvidenceError(f"{file} is not a shared-evidence draft")
    record_path = file.parent / f"{PREFIX}-v{draft['version']}.json"
    if draft.get("record") != str(record_path) or set(draft) - draft_keys(version):
        raise EvidenceError(f"the draft must name {record_path} and carry only its template fields "
                            f"(unknown: {sorted(set(draft) - draft_keys(version))})")
    current = observed_inputs(draft["manifest"]["path"], draft.get("bound") or [])
    changes = changed_inputs(draft, current)
    if changes:
        raise EvidenceError(f"stale shared-evidence inputs since the draft was written: {changes[:8]}; write a new draft")
    fields = authored_fields(draft, current)
    record = {"schemaVersion": version, "kind": KIND, "version": draft["version"], "recordPath": str(record_path),
              "sealedAt": datetime.now(timezone.utc).isoformat(),
              "draft": {"path": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()},
              **current, **fields, **engine_fields(draft, fields, current, batch), "engineLimits": list(ENGINE_LIMITS)}
    record["contentSha256"] = content_digest(record)
    return {"record": str(record_path), "sha256": write_json_new(record_path, record),
            "contentSha256": record["contentSha256"], "version": record["version"]}


def unresolved(draft_file: str) -> dict:
    """A version 2 draft's intervals that are not established: the list the operator is asked to listen to (P2-07)."""
    file = canonical_file(draft_file)
    draft = read_json(file)
    if draft.get("schemaVersion") != 2 or draft.get("kind") != DRAFT_KIND:
        raise EvidenceError(f"{file} is not a version 2 shared-evidence draft; only version 2 intervals record certainty")
    current = observed_inputs(draft["manifest"]["path"], draft.get("bound") or [])
    speakers = speakers_v2(draft.get("speakers"), field_context(current))
    rows = [{"interval": index, **row} for index, row in enumerate(mapped_intervals(2, speakers))
            if row["certainty"] != "established"]
    return {"status": "shared-evidence-unresolved", "draft": str(file), "intervals": rows}


def evidence_arguments(parser: argparse.ArgumentParser) -> None:
    """context.py flags: draft once per production, seal it, re-check it, then bind it into role packets.

    Sealing a version 2 draft with speaker intervals also takes context.py's ``--batch B``.
    """
    parser.add_argument("--shared-evidence", help="Sealed SHARED-EVIDENCE-vN.json to bind into this --role packet")
    parser.add_argument("--evidence-draft", metavar="DIR",
                        help="Write a structure-only shared-evidence draft in DIR (with --manifest and --bind)")
    parser.add_argument("--evidence-seal", metavar="DRAFT",
                        help="Validate an authored draft and publish its record (with --batch B when a v2 draft has "
                             "speaker intervals)")
    parser.add_argument("--evidence-check", metavar="RECORD",
                        help="Re-check a sealed record: unedited, at its recorded path, not superseded, inputs unchanged")
    parser.add_argument("--evidence-unresolved", metavar="DRAFT",
                        help="List a v2 draft's speaker intervals whose certainty is not established (to listen to)")
    parser.add_argument("--manifest", help="Admitted asset_manifest.json whose sources the evidence describes")
    parser.add_argument("--bind", action="append", default=[], metavar="KEY=PATH",
                        help="A file the shared evidence binds, e.g. a reference image or a decision record (repeat)")


def run_evidence(args: argparse.Namespace) -> dict:
    """The one evidence operation the arguments name."""
    if args.evidence_check:
        return evidence_check(args.evidence_check)
    if args.evidence_seal:
        return seal(args.evidence_seal, args.batch)
    if args.evidence_unresolved:
        return unresolved(args.evidence_unresolved)
    if not args.manifest:
        raise EvidenceError("--evidence-draft requires --manifest <admitted asset_manifest.json>")
    return write_draft(EvidenceDraftRequest(args.evidence_draft, args.manifest, tuple(args.bind)))


def evidence_main(args: argparse.Namespace) -> int:
    """Draft, seal, re-check or list unresolved intervals; 2 with a bounded error when an input is missing, stale or
    malformed."""
    try:
        result = run_evidence(args)
    except (ArtifactError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "shared-evidence-unavailable", "errorType": type(error).__name__,
                          "error": str(error)[:2048]}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0
