"""All-used-source metadata preparation, never source observation or job authority.

The enclosing owner supplies actual OpeningInputs from its successful initial
source-hash capture, current saved parent hashes, explicit declarations, and
its unchanged source/tool/project guard and deadline. These Python types alone
prove none of those authorities. No job, decoder, claim, timer or grade starts.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from color.deadline import require_time
from color.grade_contract import SourceBinding, closed, identifier, parse_source_binding
from color.grade_observation_profile import ObservationProfile, V2, admitted_facts, observation_declaration, observation_profile
from color.grade_project_authority import _candidate_count, _selected_source
from cut_preview_io import digest, read_bytes, real_directory
from graphics.render_rate import normalize_render_rate
from guided_opening_inputs import OpeningInputs, hash_value
from headless.admission_receipt import AdmissionReceiptError, validate_admission_receipt
from headless.external_media_verification import (
    SourceVerificationRuntime, VerifiedSnapshotIdentity, assert_verified_snapshots, snapshot_stat_identity,
)
from ingest_admission_contract import MAX_ADMISSION_RECEIPT_BYTES, MAX_SOURCE_SET_BYTES, RECEIPTS_NAME, STORE_NAME
from ingest_execution_authority import _verify_admitted_row
from ingest_media_observation import VerifiedExecutionMedia


@dataclass(frozen=True)
class SourceColorParentRefs:
    """Original owner-supplied saved parent hashes, not arbitrary document paths."""

    producer_dir: Path
    expected: dict


@dataclass(frozen=True)
class SourceColorPreparationContext:
    """Borrow the original source/tool/project guard and absolute caller cutoff."""

    parents: SourceColorParentRefs
    deadline: float
    guard: Callable[[], None]


@dataclass(frozen=True)
class PreparedSourceColorJob:
    """Data-only preparation; source is the SAME actual initial hash-pass identity."""

    source: VerifiedSnapshotIdentity
    profile: ObservationProfile
    binding: SourceBinding
    metadata_json: bytes
    executable: bool = field(default=False, init=False)
    grade_applicable: bool = field(default=False, init=False)
    delivery_approved: bool = field(default=False, init=False)

    def record(self) -> dict:
        """Return a copy of preparation metadata, never a runnable job input."""
        return json.loads(self.metadata_json)


def _json(value: object, maximum: int = MAX_SOURCE_SET_BYTES) -> bytes:
    """Keep numeric types and reject nonfinite/unbounded metadata without normalization."""
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
    if len(raw) > maximum:
        raise RuntimeError("source color preparation metadata exceeds its bound")
    return raw


def _object(pairs: list[tuple[str, object]]) -> dict:
    """Reject duplicate keys in held parent/receipt JSON instead of selecting a value."""
    result = dict(pairs)
    if len(result) != len(pairs):
        raise RuntimeError("source color preparation JSON repeats a key")
    return result


def _snapshots(value: VerifiedExecutionMedia) -> tuple:
    """Bind actual identity objects, including exact integer sizes and stat fields."""
    rows = value.snapshots
    if type(value.entries_json) is not bytes or len(value.entries_json) > MAX_SOURCE_SET_BYTES:
        raise RuntimeError("source color preparation requires original bounded capture bytes")
    if type(rows) is not tuple or not rows or any(type(row) is not VerifiedSnapshotIdentity for row in rows):
        raise RuntimeError("source color preparation requires original source capture")
    if any(type(row.size_bytes) is not int or row.size_bytes <= 0 or type(row.stat_identity) is not tuple
           or len(row.stat_identity) != 9 or any(type(item) is not int for item in row.stat_identity) for row in rows):
        raise RuntimeError("source color preparation captured identity is malformed")
    if len({row.path for row in rows}) != len(rows):
        raise RuntimeError("source color preparation capture repeats a snapshot path")
    return tuple((id(row), row.path, row.sha256, row.size_bytes, row.stat_identity) for row in rows)


class _PreparationRead:
    """Private original-lifetime checks; no completed result escapes partial preparation."""

    def __init__(self, inputs: OpeningInputs, declarations: dict, context: SourceColorPreparationContext) -> None:
        """Hold original argument identities before any callback or file read."""
        if type(inputs) is not OpeningInputs or type(inputs.verified_media) is not VerifiedExecutionMedia:
            raise RuntimeError("source color preparation requires actual opening inputs and capture")
        if type(context) is not SourceColorPreparationContext or type(context.parents) is not SourceColorParentRefs \
                or not callable(context.guard) or type(context.deadline) not in (int, float) or not math.isfinite(context.deadline):
            raise RuntimeError("source color preparation requires the original parent/clock/guard context")
        require_time(context.deadline)
        self.inputs, self.declarations, self.context = inputs, declarations, context
        self.capture, self.deadline, self.callback = inputs.verified_media, context.deadline, context.guard
        self.files: list[tuple[Path, str, int, tuple]] = []
        self.bytes_left = MAX_SOURCE_SET_BYTES
        self.runtime = SourceVerificationRuntime(lambda: require_time(self.deadline))
        self.binding = self.arguments()

    def arguments(self) -> tuple:
        """Never adopt replacement context/capture or equal-valued coerced metadata."""
        context, capture = self.context, self.capture
        return (id(context), id(context.parents), id(context.guard), type(context.deadline), context.deadline,
                context.parents.producer_dir, _json(context.parents.expected), _json(self.declarations),
                id(self.inputs.verified_media), id(capture.entries_json), capture.entries_json,
                id(capture.snapshots), _snapshots(capture), self.inputs.path, self.inputs.sha256,
                _json(self.inputs.value), _json(self.inputs.documents), id(self.runtime), id(self.runtime.remaining))

    def check(self) -> None:
        """Check original guard, input, all source parents/stats, metadata and final time."""
        require_time(self.deadline)
        if self.arguments() != self.binding:
            raise RuntimeError("source color preparation original input/context changed")
        self.callback()
        if self.arguments() != self.binding:
            raise RuntimeError("source color preparation original input/context changed")
        parents = {Path(row.path).parent for row in self.capture.snapshots}
        for parent in parents:
            real_directory(parent)
        assert_verified_snapshots(self.capture.snapshots, self.runtime)
        for parent in parents:
            real_directory(parent)
        for path, _sha, _size, identity in self.files:
            real_directory(path.parent)
            if snapshot_stat_identity(path.lstat()) != identity:
                raise RuntimeError("source color preparation held parent/receipt changed")
        require_time(self.deadline)
        if self.arguments() != self.binding:
            raise RuntimeError("source color preparation original input/context changed")
        require_time(self.deadline)

    def read(self, path: Path, expected: str, maximum: int) -> dict:
        """Hold exact bounded parent/receipt bytes, never hash original media again."""
        require_time(self.deadline)
        hash_value(expected)
        before = snapshot_stat_identity(path.lstat())
        raw = read_bytes(path, min(maximum, self.bytes_left))
        if hashlib.sha256(raw).hexdigest() != expected or snapshot_stat_identity(path.lstat()) != before:
            raise RuntimeError("source color preparation parent/receipt differs from held hash")
        self.bytes_left -= len(raw)
        self.files.append((path, expected, len(raw), before))
        value = json.loads(raw, object_pairs_hook=_object)
        _json(value, maximum)
        if type(value) is not dict:
            raise RuntimeError("source color preparation document is not an object")
        require_time(self.deadline)
        return value

    def finish(self) -> None:
        """Recheck all small original bytes then the same final callback/source lifetime."""
        self.check()
        for path, expected, size, _identity in self.files:
            require_time(self.deadline)
            if hashlib.sha256(read_bytes(path, size)).hexdigest() != expected:
                raise RuntimeError("source color preparation held parent/receipt bytes changed")
        self.check()


def _parents(read: _PreparationRead) -> tuple[dict, dict, dict]:
    """Join current saved parents to actual held opening manifest and unchanged cut."""
    refs = read.context.parents
    expected = closed(refs.expected, {"planSha256", "manifestSha256", "projectSha256"}, "source color parents")
    if not isinstance(refs.producer_dir, Path) or not refs.producer_dir.is_absolute():
        raise RuntimeError("source color preparation producer directory is invalid")
    real_directory(refs.producer_dir)
    paths = (refs.producer_dir / "edit_plan.json", refs.producer_dir / "asset_manifest.json", refs.producer_dir.parent / "project.json")
    saved, manifest, project = (read.read(path, expected[key], 2 * 1024 ** 2) for path, key in
                                zip(paths, ("planSha256", "manifestSha256", "projectSha256")))
    docs = read.inputs.documents
    manifest_ref = read.inputs.value["documents"]["manifest"]
    if manifest_ref["sha256"] != expected["manifestSha256"] or _json(manifest) != _json(docs["manifest"]):
        raise RuntimeError("source color preparation current manifest differs from original opening")
    cut = _json(docs["acceptedPlan"].get("cutTrack"))
    if _json(saved.get("cutTrack")) != cut or _json(docs["candidatePlan"].get("cutTrack")) != cut:
        raise RuntimeError("source color preparation saved/accepted/candidate cut differs")
    return saved, manifest, project


def _used(plan: dict, declarations: dict) -> tuple[str, ...]:
    """Require the complete explicit map; keep unique first-occurrence source order."""
    cuts = plan.get("cutTrack")
    if type(cuts) is not list or not cuts or len(cuts) > 10000 or type(declarations) is not dict:
        raise RuntimeError("source color preparation requires a bounded nonempty cut and declaration map")
    used = tuple(dict.fromkeys(identifier(row.get("sourceId")) for row in cuts if type(row) is dict))
    if any(type(row) is not dict for row in cuts) or not 1 <= len(used) <= 128 or set(declarations) != set(used):
        raise RuntimeError("source color preparation declarations must cover exactly every used source")
    return used


def _profiles(ids: tuple[str, ...], declarations: dict) -> dict[str, ObservationProfile]:
    """Reject unknown/omitted profiles before any source receipt or job work."""
    result = {}
    for source_id in ids:
        row = closed(declarations[source_id], {"profile", "declaration"}, "source color declaration selection")
        result[source_id] = observation_profile(row["profile"])
        _json(row["declaration"], 128 * 1024)
    return result


def _source(read: _PreparationRead, source: dict, entry: dict) -> VerifiedSnapshotIdentity:
    """Require exact admission lane/path/SHA/size and the same original capture object."""
    _verify_admitted_row(source, {"source"}, {entry["originalPath"]: entry}, "source color")
    if type(source.get("sourceSizeBytes")) is not int or type(entry.get("sizeBytes")) is not int \
            or source["sourceSizeBytes"] != entry["sizeBytes"]:
        raise RuntimeError("source color preparation manifest/admission size differs")
    matches = [row for row in read.capture.snapshots if row.path == entry["snapshotPath"]]
    if len(matches) != 1 or (matches[0].sha256, matches[0].size_bytes) != (entry["sha256"], entry["sizeBytes"]):
        raise RuntimeError("source color preparation lacks the exact initial source capture")
    return matches[0]


def _receipt(read: _PreparationRead, entry: dict, source: VerifiedSnapshotIdentity) -> dict:
    """Apply the existing held-entry content-addressed receipt rule, not source-SHA naming."""
    expected = hash_value(entry["admissionReceiptSha256"])
    relative = Path(STORE_NAME) / RECEIPTS_NAME / f"{expected}.json"
    if type(entry["admissionReceiptPath"]) is not str or entry["admissionReceiptPath"] != str(relative):
        raise RuntimeError("source color preparation admission receipt path is not canonical")
    receipt = read.read(read.context.parents.producer_dir / relative, expected, MAX_ADMISSION_RECEIPT_BYTES)
    try:
        validate_admission_receipt(receipt)  # native v4 or historical container v3, same rules as ingest
    except AdmissionReceiptError as exc:
        raise RuntimeError(f"source color preparation admission receipt is unsupported: {exc}") from exc
    snapshot = receipt.get("snapshot")
    if type(snapshot) is not dict or _json(snapshot) != _json({"path": source.path, "sha256": source.sha256, "sizeBytes": source.size_bytes}):
        raise RuntimeError("source color preparation receipt differs from original admitted snapshot")
    if receipt.get("decoded", {}).get("facts", {}).get("sizeBytes") != source.size_bytes:
        raise RuntimeError("source color preparation decoded expectation size differs")
    return receipt


def _prepare(read: _PreparationRead, source_id: str, documents: tuple, profile: ObservationProfile) -> PreparedSourceColorJob:
    """Reuse existing grade expectation/declaration parsers without observing a source."""
    saved, manifest, project, entries = documents
    source, entry = _selected_source({"sourceId": source_id}, saved, manifest, entries)
    identity = _source(read, source, entry)
    receipt = _receipt(read, entry, identity)
    admitted_facts(receipt.get("decoded", {}).get("facts", {}), profile)
    declaration = read.declarations[source_id]["declaration"]
    expected = read.context.parents.expected
    history = {"projectSha256": expected["projectSha256"], "history": project.get("history", [])}
    binding = {"sourceId": source_id, "sourceSha256": identity.sha256,
        "admissionReceiptSha256": entry["admissionReceiptSha256"], "declarationSha256": digest(declaration),
        "projectHistorySha256": digest(history), "fps": normalize_render_rate(source["frameRate"]).token,
        "frameCount": _candidate_count(receipt)}
    parsed = parse_source_binding(binding)
    observation_declaration(declaration, parsed, profile)
    metadata = {"schemaVersion": profile.version, "policy": profile.project_policy,
        "scope": "source-color-job-preparation-not-observation-or-approval", "sourceId": source_id,
        "sourcePath": identity.path, "binding": binding, "declaration": declaration, "expected": expected,
        "admissionExpectation": {"receiptPath": entry["admissionReceiptPath"],
            "receiptSha256": entry["admissionReceiptSha256"], "decoded": receipt["decoded"]},
        "executable": False, "gradeApplicable": False, "deliveryApproved": False}
    if profile is V2:
        metadata["profile"] = profile.token
    return PreparedSourceColorJob(identity, profile, parsed, _json(metadata, 128 * 1024))


def _prepare_source_color_jobs(inputs: OpeningInputs, declarations: dict,
                               context: SourceColorPreparationContext) -> tuple[_PreparationRead, tuple]:
    """Keep the original read available to the internal same-process lifetime holder."""
    read = _PreparationRead(inputs, declarations, context)
    read.check()
    ids = _used(inputs.documents["acceptedPlan"], declarations)
    profiles = _profiles(ids, declarations)
    documents = (*_parents(read), read.capture.entries())
    read.check()
    result = tuple(_prepare(read, source_id, documents, profiles[source_id]) for source_id in ids)
    read.finish()
    return read, result


def prepare_source_color_jobs(inputs: OpeningInputs, declarations: dict,
                              context: SourceColorPreparationContext) -> tuple[PreparedSourceColorJob, ...]:
    """Validate the entire original used-source set before returning data-only preparation."""
    return _prepare_source_color_jobs(inputs, declarations, context)[1]
