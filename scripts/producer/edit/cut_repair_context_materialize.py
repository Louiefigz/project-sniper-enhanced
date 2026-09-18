#!/usr/bin/env python3
"""Derive P2 analysis context from active revision + sealed evidence."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass

from edit.cut_repair_context_sources import (
    ContextMaterializationError,
    canonical_bytes,
    digest,
    rational_rate,
    require_hash,
    require_keys,
    source_media,
    source_rows,
    stable_file_digest,
    stable_json,
    stable_text,
    target_source,
    transcript,
)
from edit.cut_repair_dialogue_context import materialize_dialogue_context
from edit.cut_repair_existing_leads import existing_audio_lead_ranges
from edit.cut_repair_context_timeline import segments
from edit.exact_timing import PositiveRational, ProjectClock
from fingerprints import plan_content_hash

_EVIDENCE = "cut_repair_acoustic_evidence_v1.json"


@dataclass(frozen=True)
class _LiveInputs:
    head: str
    revision: dict
    plan: dict
    plan_hash: str
    manifest: dict
    manifest_hash: str
    directive: dict


@dataclass(frozen=True)
class _PreparedContext:
    head: str
    revision: dict
    plan: dict
    source: dict
    source_id: str
    manifest_path: str
    compiled: list[dict]
    total_frames: int
    project_rate: tuple[int, int]
    evidence: dict
    dialogue: dict | None


def _active_revision(producer: str) -> tuple[str, dict]:
    root = os.path.join(producer, ".sniper-authority-v1")
    head_path = os.path.join(root, "ACTIVE_HEAD")
    head = require_hash(
        stable_text(head_path, "ACTIVE_HEAD", "ascii").strip(),
        "ACTIVE_HEAD")
    revision_path = os.path.join(
        root, "objects", "revisions", f"{head}.json")
    revision, observed = stable_json(revision_path, "active revision")
    if observed != head or revision.get("schemaVersion") not in (1, 2):
        raise ContextMaterializationError("active revision bytes are invalid")
    if revision.get("workflowState") != "PICTURE_LOCKED" \
            or revision.get("pictureLockHash") is None:
        raise ContextMaterializationError(
            "cut repair route requires a PICTURE_LOCKED active revision")
    return head, revision


def _validate_plan_authority(
        producer: str, revision: dict, plan: dict) -> None:
    if plan_content_hash(plan) != revision.get("planContentHash"):
        raise ContextMaterializationError(
            "live plan does not match revision semantic authority")
    if revision["schemaVersion"] == 1:
        return
    expected = require_hash(
        revision.get("planObjectHash"), "revision plan object hash")
    object_path = os.path.join(
        producer, ".sniper-authority-v1", "objects", "plans",
        f"{expected}.json")
    stored, observed = stable_json(object_path, "revision plan object")
    if observed != expected or canonical_bytes(stored) != canonical_bytes(plan):
        raise ContextMaterializationError(
            "live plan does not match exact revision plan object")


def _validate_parent_media(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise ContextMaterializationError("parent media evidence is malformed")
    path = value.get("path")
    expected = require_hash(value.get("sha256"), "parent media hash")
    if not isinstance(path, str) \
            or stable_file_digest(path, "parent media") != expected:
        raise ContextMaterializationError("parent media evidence is stale")
    return value


def _sealed_evidence(producer: str, bindings: tuple[str, str, str, str]) -> dict:
    head, plan_hash, manifest_hash, source_id = bindings
    path = os.path.join(producer, _EVIDENCE)
    document, _ = stable_json(path, "cut repair acoustic evidence")
    allowed = {
        "schemaVersion", "kind", "parentRevisionHash", "planSha256",
        "manifestSha256", "sourceId", "alignment", "vad", "audition",
        "audioIsolation",
        "silences", "coveredPicture", "replaceableAudio",
        "replaceableAudioEvidenceHash", "dependents", "parentMedia",
        "maxDirtyFrames", "maxAudioOverlapFrames", "authorityHash",
    }
    require_keys(document, allowed, allowed, "cut repair acoustic evidence")
    supplied = require_hash(
        document["authorityHash"], "acoustic authority hash")
    core = {key: value for key, value in document.items()
            if key != "authorityHash"}
    observed = (
        document.get("schemaVersion"),
        document.get("kind"),
        document.get("parentRevisionHash"),
        document.get("planSha256"),
        document.get("manifestSha256"),
        document.get("sourceId"),
        supplied,
    )
    expected = (
        1, "cut-repair-acoustic-evidence", head, plan_hash,
        manifest_hash, source_id, digest(core),
    )
    if observed != expected:
        raise ContextMaterializationError(
            "cut repair acoustic evidence is stale or unsealed")
    document["parentMedia"] = _validate_parent_media(document["parentMedia"])
    return document


def _load_live_inputs(producer: str, manifest_path: str,
                      directive_path: str) -> _LiveInputs:
    head, revision = _active_revision(producer)
    plan, plan_hash = stable_json(
        os.path.join(producer, "edit_plan.json"), "edit plan")
    manifest, manifest_hash = stable_json(manifest_path, "asset manifest")
    directive, _ = stable_json(directive_path, "repair directive")
    _validate_plan_authority(producer, revision, plan)
    if manifest_hash != revision.get("manifestHash"):
        raise ContextMaterializationError(
            "live plan/manifest do not match active revision authority")
    return _LiveInputs(
        head, revision, plan, plan_hash, manifest, manifest_hash, directive)


def _prepare_context(producer: str, inputs: _LiveInputs,
                     manifest_path: str) -> _PreparedContext:
    sources = source_rows(inputs.manifest)
    source_id = target_source(inputs.plan, inputs.directive, sources)
    source = sources[source_id]
    audio = source.get("audio")
    if not isinstance(audio, dict) or not isinstance(
            audio.get("sampleRate"), int):
        raise ContextMaterializationError("target source has no sample clock")
    target = inputs.plan.get("target")
    project_rate = rational_rate(
        target.get("fps") if isinstance(target, dict) else None,
        "project fps")
    compiled, total_frames = segments(inputs.plan, sources, project_rate)
    evidence = _sealed_evidence(
        producer, (inputs.head, inputs.plan_hash,
                   inputs.manifest_hash, source_id))
    dialogue = materialize_dialogue_context(
        inputs.plan, sources, os.path.dirname(manifest_path))
    return _PreparedContext(
        inputs.head, inputs.revision, inputs.plan, source, source_id,
        manifest_path,
        compiled, total_frames, project_rate, evidence, dialogue)


def _existing_leads(value: _PreparedContext) -> list[dict]:
    clock = ProjectClock(
        PositiveRational(*value.project_rate), 48_000)
    ranges = existing_audio_lead_ranges(
        value.plan, {"segments": value.compiled}, clock)
    return [{
        "segmentId": ident,
        "outputSampleRange": sample_range.to_dict(),
    } for ident, sample_range in sorted(ranges.items())]


def _context_core(value: _PreparedContext) -> dict:
    audio = value.source["audio"]
    evidence = value.evidence
    core = {
        "schemaVersion": 1, "kind": "cut-repair-analysis-context",
        "parentRevisionHash": value.head,
        "transcript": transcript(
            value.source, os.path.dirname(value.manifest_path),
            value.source_id, audio["sampleRate"]),
        "segments": value.compiled, "silences": evidence["silences"],
        "coveredPicture": evidence["coveredPicture"],
        "replaceableAudio": evidence["replaceableAudio"],
        "replaceableAudioEvidenceHash":
            evidence["replaceableAudioEvidenceHash"],
        "dependents": evidence["dependents"],
        "clock": {
            "fps": {"numerator": str(value.project_rate[0]),
                    "denominator": str(value.project_rate[1])},
            "sampleRate": 48_000,
        },
        "totalFrames": value.total_frames,
        "parentTimelineMapHash": value.revision["timelineMapHash"],
        "parentPictureLockHash": value.revision["pictureLockHash"],
        "maxDirtyFrames": evidence["maxDirtyFrames"],
        "maxAudioOverlapFrames": evidence["maxAudioOverlapFrames"],
        "evidence": {
            key: evidence[key] for key in (
                "alignment", "vad", "audition", "audioIsolation")},
        "sourceMedia": source_media(value.source, value.source_id),
        "parentMedia": evidence["parentMedia"],
    }
    leads = _existing_leads(value)
    return {
        **core,
        **({"existingAudioLeadSampleRanges": leads} if leads else {}),
        **(value.dialogue or {}),
    }


def _reobserve(producer: str, manifest_path: str,
               inputs: _LiveInputs) -> None:
    head, _ = _active_revision(producer)
    _, plan_hash = stable_json(
        os.path.join(producer, "edit_plan.json"), "edit plan")
    _, manifest_hash = stable_json(manifest_path, "asset manifest")
    if (head, plan_hash, manifest_hash) != (
            inputs.head, inputs.plan_hash, inputs.manifest_hash):
        raise ContextMaterializationError(
            "live repair authority changed during materialization")


def materialize(producer: str, manifest_path: str,
                directive_path: str) -> dict:
    """Build exact analysis context without accepting request-side hashes."""
    if os.path.realpath(producer) != os.path.abspath(producer):
        raise ContextMaterializationError(
            "producer directory path is not canonical")
    producer = os.path.realpath(producer)
    inputs = _load_live_inputs(producer, manifest_path, directive_path)
    core = _context_core(_prepare_context(producer, inputs, manifest_path))
    _reobserve(producer, manifest_path, inputs)
    return {**core, "authorityHash": digest(core)}


def write_context(path: str, document: dict) -> None:
    """Atomically persist one derived controller-owned context."""
    directory = os.path.dirname(path)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".cut-repair-context-", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(document) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("producer_dir")
    parser.add_argument("manifest_path")
    parser.add_argument("directive_path")
    parser.add_argument("output_path")
    args = parser.parse_args()
    try:
        write_context(os.path.abspath(args.output_path), materialize(
            os.path.abspath(args.producer_dir),
            os.path.abspath(args.manifest_path),
            os.path.abspath(args.directive_path)))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
