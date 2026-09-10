"""Current admitted source and exact parent-byte capture for timing corrections."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import os
from pathlib import Path
import stat
from typing import Callable

from cut_preview_io import digest, read_bytes, real_directory
from ingest_admission_contract import MAX_ADMISSION_RECEIPT_BYTES
from ingest_execution_authority import execution_media_authority_entries
from transcript_source_authority import SourceObservation, observe_source, verify_result
from transcript_timing_correction_contract import correction_profile, number, parse_json
from transcript_timing_correction_words import correction_rows

POLICY_FILES = (
    "transcript_timing_correction.py", "transcript_timing_correction_contract.py",
    "transcript_timing_correction_words.py", "transcript_timing_correction_authority.py",
    "transcript_timing_correction_text.py",
    "transcript_timing_correction_store.py", "transcript_source_authority.py",
    "transcript_timing_quality.py", "cut_preview_io.py", "cross_runtime_canonical_json.py",
    "ingest_execution_authority.py", "ingest_admission_contract.py",
    "transcript_timing_review_contract.py", "transcript_timing_review_store.py",
)


@dataclass(frozen=True)
class CorrectionInput:
    """Exact existing parents; optional deadline is the caller's monotonic expiry."""

    plan_path: Path
    manifest_path: Path
    transcript_path: Path
    parent_deadline: float | None = None


@dataclass(frozen=True)
class CorrectionCapture:
    """Held bytes and source identity, never request-supplied observed authority."""

    inputs: CorrectionInput
    proposed: dict
    documents: dict[Path, bytes]
    plan: dict
    manifest: dict
    transcript: dict
    source: dict
    source_identity: tuple
    policy_hash: str
    corrections: list[dict]
    observation: SourceObservation | None = None


def _path(value: Path) -> Path:
    """Require an absolute canonical, unlinked parent directory."""
    path = Path(value)
    real_directory(path.parent)
    return path


def source_identity(path: Path) -> tuple:
    """Never accept a link, hardlink or nonregular source as a held observation."""
    _path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size <= 0:
        raise RuntimeError("timing correction source is not one regular no-follow file")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def policy_hash() -> str:
    """Pin correction/delegated helper bytes; this is not a render-pipeline receipt."""
    root = Path(__file__).resolve().parent
    rows = []
    for name in POLICY_FILES:
        path = root / name
        if name == "transcript_timing_quality.py":
            path = root.parent / name
        rows.append({"path": name, "sha256": hashlib.sha256(read_bytes(path)).hexdigest()})
    return digest(rows)


def _parents(inputs: CorrectionInput, proposed: dict) -> tuple[dict, list[dict]]:
    """Capture exact bounded raw parent bytes before parsing their values."""
    paths = (inputs.plan_path, inputs.manifest_path, inputs.transcript_path)
    documents = {_path(path): read_bytes(_path(path)) for path in paths}
    if len(documents) != 3:
        raise RuntimeError("timing correction parent paths must be distinct")
    expected = ("expectedPlanSha256", "expectedManifestSha256", "expectedTranscriptSha256")
    if any(hashlib.sha256(documents[path]).hexdigest() != proposed[key]
           for path, key in zip(paths, expected)):
        raise RuntimeError("timing correction expected parent bytes are stale")
    values = [parse_json(documents[path]) for path in paths]
    if any(type(value) is not dict for value in values):
        raise RuntimeError("timing correction parents must be JSON objects")
    return documents, values


def _source(inputs: CorrectionInput, proposed: dict, values: list[dict]) -> dict:
    """Resolve the unchanged manifest source and its current transcript binding."""
    plan, manifest, transcript = values
    rows = manifest.get("sources")
    if type(rows) is not list or not isinstance(manifest.get("sourceSetAdmission"), dict):
        raise RuntimeError("timing correction requires admitted source-set authority")
    matches = [row for row in rows if isinstance(row, dict) and row.get("id") == proposed["sourceId"]]
    if len(matches) != 1:
        raise RuntimeError("timing correction source does not resolve uniquely")
    source = matches[0]
    relative = source.get("transcriptPath")
    if type(relative) is not str or Path(relative).is_absolute() or ".." in Path(relative).parts \
            or inputs.manifest_path.parent / relative != inputs.transcript_path:
        raise RuntimeError("timing correction transcript is not the manifest's exact current source")
    error = verify_result(transcript, source, str(inputs.transcript_path))
    if error:
        raise RuntimeError(f"timing correction parent source binding failed: {error}")
    duration = number(source.get("duration"), "source duration")
    cuts = plan.get("cutTrack")
    if duration <= 0 or type(cuts) is not list or not any(
            isinstance(row, dict) and row.get("sourceId") == source["id"] for row in cuts):
        raise RuntimeError("timing correction candidate does not use this positive-duration source")
    return {**source, "duration": duration}


def capture(inputs: CorrectionInput, proposed: dict, guard: Callable[[], None]) -> CorrectionCapture:
    """Reject cheap shape/timing failures before actual source-set hashing."""
    guard()
    documents, values = _parents(inputs, proposed)
    source = _source(inputs, proposed, values)
    identity = source_identity(Path(source["path"]))
    corrections = correction_rows(values[2], proposed, source)
    result = CorrectionCapture(inputs, proposed, documents, *values, source, identity,
                               policy_hash(), corrections)
    recheck(result, guard)
    return result


def recheck(value: CorrectionCapture, guard: Callable[[], None]) -> None:
    """Reobserve all exact parents and source identity without a source hash loop."""
    guard()
    for path, raw in value.documents.items():
        if read_bytes(path) != raw:
            raise RuntimeError("timing correction source/transcript/candidate parent changed")
        guard()
    if source_identity(Path(value.source["path"])) != value.source_identity \
            or policy_hash() != value.policy_hash:
        raise RuntimeError("timing correction source or policy changed")
    guard()


def verify_sources(value: CorrectionCapture, guard: Callable[[], None]) -> CorrectionCapture:
    """Use actual admission verification and retain an actual source-byte observation."""
    recheck(value, guard)
    entries = execution_media_authority_entries(value.plan, value.manifest, str(value.inputs.manifest_path))
    if entries is None:
        raise RuntimeError("timing correction lacks current admitted source-set bytes")
    source = value.source
    expected = (source["sourceSha256"], value.transcript["sourceMediaAuthority"]["sourceSizeBytes"])
    matches = [row for row in entries if row["snapshotPath"] == source["path"] and row["lane"] == "source"]
    if len(matches) != 1 or (matches[0]["sha256"], matches[0]["sizeBytes"]) != expected:
        raise RuntimeError("timing correction source diverged from actual admission")
    receipt_path, receipt_bytes = _duration_receipt(value, matches[0], guard)
    value = replace(value, documents={**value.documents, receipt_path: receipt_bytes})
    observed = observe_source(Path(source["path"]), expected, guard)
    recheck(value, guard)
    return replace(value, observation=observed)


def _duration_receipt(value: CorrectionCapture, entry: dict, guard: Callable[[], None]) -> tuple[Path, bytes]:
    """Bind duration to already verified decode facts without rehashing the media."""
    guard()
    path = value.inputs.manifest_path.parent / entry["admissionReceiptPath"]
    raw = read_bytes(path, MAX_ADMISSION_RECEIPT_BYTES)
    if hashlib.sha256(raw).hexdigest() != entry["admissionReceiptSha256"]:
        raise RuntimeError("timing correction selected admission receipt changed")
    receipt = parse_json(raw)
    facts = receipt["decoded"]["facts"]
    duration = number(facts.get("durationSeconds"), "admitted decoded source duration")
    if facts.get("mediaKind") != "timed-media" or duration <= 0 or duration != value.source["duration"]:
        raise RuntimeError("timing correction manifest duration differs from admitted decoded source; unsupported")
    guard()
    return path, raw


def request_for(value: CorrectionCapture) -> dict:
    """Deterministically bind exact candidate/manifest/transcript and proposed changes."""
    parents = {name: {"path": str(path), "sha256": hashlib.sha256(value.documents[path]).hexdigest()}
               for name, path in (("plan", value.inputs.plan_path), ("manifest", value.inputs.manifest_path),
                                  ("transcript", value.inputs.transcript_path))}
    source = value.source
    profile = correction_profile(value.proposed["schemaVersion"])
    binding = {"parents": parents, "policyHash": value.policy_hash,
               "sourceSetAdmission": value.manifest["sourceSetAdmission"],
               "source": {"sourceId": source["id"], "path": source["path"],
                          "sha256": source["sourceSha256"], "duration": source["duration"],
                          "sizeBytes": value.transcript["sourceMediaAuthority"]["sourceSizeBytes"]}}
    body = {"schemaVersion": profile["schemaVersion"], "kind": profile["kindPrefix"] + "-request",
            "policy": profile["policy"], "scope": profile["scope"], "proposal": value.proposed,
            "binding": binding, "corrections": value.corrections}
    return {**body, "requestHash": digest(body)}
