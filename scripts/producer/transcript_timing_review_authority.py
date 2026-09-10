"""Current admitted bytes and exact cut/anomaly parents for timing reviews."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Callable

from cut_preview_io import digest, read_bytes, real_directory
from ingest_execution_authority import execution_media_authority_entries
from transcript_cut_evidence import SourceEvidence, _load_words
from transcript_source_authority import verify_result
from transcript_timing_review_contract import MAX_ANOMALIES, POLICY

POLICY_FILES = (
    "transcript_cut_quality.py", "transcript_cut_evidence.py",
    "transcript_timing_review_contract.py", "transcript_timing_review_authority.py",
    "transcript_timing_review_store.py", "transcript_timing_review.py",
    "cross_runtime_canonical_json.py",
)


@dataclass(frozen=True)
class ReviewInput:
    """Existing cut-gate inputs; paths/bytes are reobserved, not caller authority."""

    plan_path: str
    manifest_path: str
    transcripts_dir: str
    plan: dict
    manifest: dict
    sources: dict[str, SourceEvidence]


@dataclass(frozen=True)
class ReviewCapture:
    """Held metadata and inode observations around one actual admission hash pass."""

    inputs: ReviewInput
    binding: dict
    anomalies: list[dict]
    plan_bytes: bytes
    documents: dict[Path, bytes]
    source_identities: dict[Path, tuple]


def cut_projection(plan: dict) -> dict:
    """Retain exact cut/intent fields while permitting later visual authoring."""
    target = plan.get("target")
    if type(target) is dict:
        target = {key: value for key, value in target.items()
                  if key not in {"graphicsStyle", "graphicsStyleRationale"}}
    return {"target": target, "cutTrack": plan.get("cutTrack"), "cutDecisions": plan.get("cutDecisions")}


def _path(value: str) -> Path:
    result = Path(os.path.abspath(value))
    real_directory(result.parent)
    return result


def _identity(path: Path) -> tuple:
    row = path.lstat()
    if not stat.S_ISREG(row.st_mode) or row.st_nlink != 1 or row.st_size <= 0:
        raise RuntimeError("timing review source must be one regular no-follow file")
    return (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns)


def _policy_hash() -> str:
    root = Path(__file__).resolve().parent
    return digest([{ "path": name, "sha256": hashlib.sha256(
        read_bytes(root / name)).hexdigest()} for name in POLICY_FILES])


def _source_rows(inputs: ReviewInput, documents: dict[Path, bytes]) -> list[dict]:
    rows = []
    for source_id, evidence in sorted(inputs.sources.items()):
        matches = [row for row in inputs.manifest.get("sources", []) if row.get("id") == source_id]
        if len(matches) != 1:
            raise RuntimeError("timing review source id does not resolve uniquely")
        source, path = matches[0], _path(evidence.transcript_path)
        raw = read_bytes(path)
        payload = json.loads(raw.decode("utf-8"))
        problem = verify_result(payload, source, str(path))
        errors: list[str] = []
        words = _load_words(payload, "timing review", errors)
        if problem or errors or words != evidence.words:
            raise RuntimeError(f"timing review transcript authority changed: {problem or errors}")
        documents[path] = raw
        rows.append({"sourceId": source_id, "path": str(_path(source["path"])),
                     "sha256": source["sourceSha256"],
                     "sizeBytes": payload["sourceMediaAuthority"]["sourceSizeBytes"],
                     "transcriptPath": str(path), "transcriptSha256": hashlib.sha256(raw).hexdigest(),
                     "transcriptBindingDigest": payload["sourceMediaAuthority"]["bindingDigest"]})
    return rows


def _windows(word: dict, boundary: float, source: SourceEvidence) -> list[dict]:
    """Never truncate a suspect word or merge distant contexts into a long audition."""
    word_range = (max(0.0, word["start"] - 1), min(source.duration, word["end"] + 1))
    edge_range = (max(0.0, boundary - 2), min(source.duration, boundary + 2))
    ranges = [("word-context", word_range), ("cut-boundary-context", edge_range)]
    if word_range[1] >= edge_range[0] and edge_range[1] >= word_range[0]:
        ranges = [("word-and-boundary-context", (min(word_range[0], edge_range[0]),
                                                  max(word_range[1], edge_range[1])))]
    result = []
    for kind, (start, end) in ranges:
        row = {"kind": kind, "sourceId": source.source_id, "start": start, "end": end}
        result.append({**row, "windowHash": digest(row)})
    return result


def _anomaly(finding: dict, inputs: ReviewInput) -> dict:
    source = inputs.sources[finding["sourceId"]]
    index = finding["sourceWordIndex"]
    word = source.words[index]
    if not 0 <= word["start"] < word["end"] <= source.duration:
        raise RuntimeError("timing review cannot truncate an out-of-source suspect word")
    cut = inputs.plan["cutTrack"][finding["cutIndex"]]
    windows = _windows(word, cut["start"], source)
    body = {"finding": finding, "sourceWord": word, "sourceWindows": windows}
    return {**body, "anomalyHash": digest(body)}


def capture(inputs: ReviewInput, findings: list[dict], guard: Callable[[], None]) -> ReviewCapture:
    """Capture small parents; source bytes are freshly hashed only when needed."""
    guard()
    if not 1 <= len(findings) <= MAX_ANOMALIES:
        raise RuntimeError("timing review supports 1–128 exact anomalies per cut")
    plan_path, manifest_path = _path(inputs.plan_path), _path(inputs.manifest_path)
    documents = {path: read_bytes(path) for path in (plan_path, manifest_path)}
    if digest(json.loads(documents[plan_path])) != digest(inputs.plan) \
            or digest(json.loads(documents[manifest_path])) != digest(inputs.manifest):
        raise RuntimeError("timing review cut/manifest changed during capture")
    admission = inputs.manifest.get("sourceSetAdmission")
    if type(admission) is not dict:
        raise RuntimeError("timing review requires actual admitted source-set authority")
    rows = _source_rows(inputs, documents)
    identities = {_path(row["path"]): _identity(_path(row["path"])) for row in rows}
    binding = {"manifestPath": str(manifest_path), "policyHash": _policy_hash(),
               "manifestSha256": hashlib.sha256(documents[manifest_path]).hexdigest(),
               "cutDigest": digest(cut_projection(inputs.plan)), "sourceSetAdmission": admission,
               "sources": rows}
    anomalies = [_anomaly(row, inputs) for row in findings]
    if len({row["anomalyHash"] for row in anomalies}) != len(anomalies):
        raise RuntimeError("timing review anomaly identities are not unique")
    guard()
    return ReviewCapture(inputs, binding, anomalies, documents[plan_path], documents, identities)


def recheck(value: ReviewCapture, guard: Callable[[], None]) -> None:
    """Detect parent/inode/policy drift without rehashing the same large media twice."""
    guard()
    for path, raw in value.documents.items():
        if read_bytes(path) != raw:
            raise RuntimeError("timing review source transcript/candidate/manifest bytes changed")
    for path, identity in value.source_identities.items():
        if _identity(path) != identity:
            raise RuntimeError("timing review admitted source changed during observation")
    if _policy_hash() != value.binding["policyHash"]:
        raise RuntimeError("timing review policy source changed during observation")
    guard()


def verify_sources(value: ReviewCapture, guard: Callable[[], None]) -> None:
    """Use the existing admission verifier once, holding source identity around it."""
    recheck(value, guard)
    entries = execution_media_authority_entries(
        value.inputs.plan, value.inputs.manifest, value.inputs.manifest_path)
    if entries is None:
        raise RuntimeError("timing review requires actual source-set admission")
    held = {row["snapshotPath"]: (row["sha256"], row["sizeBytes"]) for row in entries}
    for row in value.binding["sources"]:
        if held.get(row["path"]) != (row["sha256"], row["sizeBytes"]):
            raise RuntimeError("timing review source diverged from its admitted snapshot")
    recheck(value, guard)


def request_for(value: ReviewCapture, original_plan: bytes) -> dict:
    """Bind original reviewed bytes and rederived current cut/anomaly facts."""
    if digest(cut_projection(json.loads(original_plan))) != digest(cut_projection(value.inputs.plan)):
        raise RuntimeError("timing review original plan no longer binds the exact current cut")
    body = {"schemaVersion": 1, "kind": "source-timing-review-request", "policy": POLICY,
            "binding": value.binding, "originalPlanSha256": hashlib.sha256(original_plan).hexdigest(),
            "anomalies": value.anomalies}
    return {**body, "requestHash": digest(body)}
