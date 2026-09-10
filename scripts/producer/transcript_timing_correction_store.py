"""New-only correction records: durable single-writer fence, immutable commit last."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from typing import Callable

from cut_preview_io import MAX_JSON, digest, read_bytes, real_directory, write_new
from cross_runtime_canonical_json import canonical_compact_json
from transcript_timing_review_store import _new_plan, _sync_directory
from transcript_timing_correction_authority import CorrectionCapture, recheck, request_for
from transcript_timing_correction_contract import closed, correction_profile, parse_json, submission
from transcript_timing_correction_words import corrected_result

PREPARED = {"parent-plan.json", "parent-manifest.json", "parent-transcript.json", "request.json"}
COMMITTED = PREPARED | {"record-claim.json", "decision.json", "corrected-transcript.json", "commit.json"}


def directory(value: CorrectionCapture) -> Path:
    """Derive the private namespace; no caller-controlled output path is accepted."""
    return value.inputs.manifest_path.parent / ".sniper-timing-corrections" / value.proposed["requestId"]


def _bytes(value: dict) -> bytes:
    """Bound the one exact canonical artifact representation."""
    raw = (canonical_compact_json(value) + "\n").encode("utf-8")
    if not 0 < len(raw) <= MAX_JSON:
        raise RuntimeError("timing correction artifact exceeds its bounded size")
    return raw


def _json(path: Path) -> dict:
    """Reject noncanonical or ambiguous stored JSON bytes."""
    raw = read_bytes(path)
    result = parse_json(raw)
    if type(result) is not dict or _bytes(result) != raw:
        raise RuntimeError("timing correction artifact is not exact canonical JSON")
    return result


def _equal(path: Path, expected: dict) -> None:
    """Compare actual file bytes with a separately reconstructed expectation."""
    if read_bytes(path) != _bytes(expected):
        raise RuntimeError(f"timing correction retained {path.name} differs from held authority")


def validate_existing(value: CorrectionCapture) -> tuple[dict, bool]:
    """Reject partial/unknown artifacts before expensive source verification."""
    root = directory(value)
    real_directory(root)
    names = set(os.listdir(root))
    if names not in (PREPARED, COMMITTED):
        raise RuntimeError("timing correction publication is incomplete or fenced; no recovery inferred")
    request = request_for(value)
    _equal(root / "request.json", request)
    for name, path in (("plan", value.inputs.plan_path), ("manifest", value.inputs.manifest_path),
                       ("transcript", value.inputs.transcript_path)):
        if read_bytes(root / f"parent-{name}.json") != value.documents[path]:
            raise RuntimeError("timing correction retained parent bytes differ from exact current inputs")
    return request, names == COMMITTED


def _claim(sent: dict) -> dict:
    """Bind the exact caller submission behind the exclusive record fence."""
    profile = correction_profile(sent["schemaVersion"])
    return {"schemaVersion": profile["schemaVersion"], "kind": profile["kindPrefix"] + "-record-claim",
            "requestHash": sent["requestHash"], "idempotencyKey": sent["idempotencyKey"],
            "submissionHash": digest(sent)}


def _decision(value: object, request: dict) -> dict:
    """Validate the closed explicit-human record and its entire submission."""
    keys = {"schemaVersion", "kind", "policy", "scope", "actor", "requestHash",
            "recordedAt", "submission", "recordHash"}
    row = closed(value, keys, "correction record")
    profile = correction_profile(request["schemaVersion"])
    if type(row["schemaVersion"]) is not int or row["schemaVersion"] != profile["schemaVersion"] \
            or row["kind"] != profile["kindPrefix"] + "-record" or row["policy"] != profile["policy"] \
            or row["scope"] != profile["scope"] or row["actor"] != profile["actor"] \
            or row["requestHash"] != request["requestHash"]:
        raise RuntimeError("timing correction record identity is invalid")
    submission(row["submission"], request)
    timestamp = row["recordedAt"]
    if type(timestamp) is not str or not timestamp.endswith("Z"):
        raise RuntimeError("timing correction recordedAt must be explicit UTC")
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.utcoffset() is None or row["recordHash"] != digest({k: v for k, v in row.items() if k != "recordHash"}):
        raise RuntimeError("timing correction record hash or timestamp is invalid")
    return row


def _commit(request: dict, decision: dict, transcript: dict) -> dict:
    """Bind the exact completed revision without selecting or approving it."""
    profile = correction_profile(request["schemaVersion"])
    body = {"schemaVersion": profile["schemaVersion"], "kind": profile["kindPrefix"] + "-commit",
            "scope": profile["scope"],
            "requestHash": request["requestHash"], "recordHash": decision["recordHash"],
            "recordSha256": hashlib.sha256(_bytes(decision)).hexdigest(),
            "correctedTranscriptSha256": hashlib.sha256(_bytes(transcript)).hexdigest(),
            "sourceBindingDigest": transcript["sourceMediaAuthority"]["bindingDigest"],
            "selected": False, "cutApproved": False, "deliveryApproved": False}
    return {**body, "commitHash": digest(body)}


def _read_current(value: CorrectionCapture) -> tuple[dict, dict | None, dict | None]:
    """Reconstruct the entire committed revision; never accept only a self-hash."""
    request, committed = validate_existing(value)
    if not committed:
        return request, None, None
    if value.observation is None:
        raise RuntimeError("timing correction committed read requires actual current source observation")
    root = directory(value)
    decision = _decision(_json(root / "decision.json"), request)
    _equal(root / "record-claim.json", _claim(decision["submission"]))
    transcript = corrected_result(value.transcript, request, decision, value.observation)
    _equal(root / "corrected-transcript.json", transcript)
    commit = _commit(request, decision, transcript)
    _equal(root / "commit.json", commit)
    revision = {"path": str(root / "corrected-transcript.json"),
                "sha256": commit["correctedTranscriptSha256"],
                "sourceBindingDigest": commit["sourceBindingDigest"],
                "recordPath": str(root / "decision.json"), "recordSha256": commit["recordSha256"],
                "recordHash": decision["recordHash"], "commitHash": commit["commitHash"]}
    return request, decision, revision


def artifact_observation(value: CorrectionCapture) -> dict[Path, bytes]:
    """Hold exact artifact bytes across metadata/source checks, not just their hashes."""
    root = directory(value)
    real_directory(root)
    names = set(os.listdir(root))
    if names not in (PREPARED, COMMITTED):
        raise RuntimeError("timing correction artifacts are incomplete or fenced")
    return {root / name: read_bytes(root / name) for name in sorted(names)}


def recheck_artifacts(value: CorrectionCapture, held: dict[Path, bytes]) -> None:
    """A changed ledger or output invalidates the earlier observation before return."""
    if artifact_observation(value) != held:
        raise RuntimeError("timing correction artifacts changed during committed readback")


def read_held(value: CorrectionCapture) -> tuple[tuple, dict[Path, bytes]]:
    """Return current reconstructed authority with its actual held file observation."""
    held = artifact_observation(value)
    result = _read_current(value)
    recheck_artifacts(value, held)
    return result, held


def read_current(value: CorrectionCapture) -> tuple[dict, dict | None, dict | None]:
    """Read only a complete, stable, reconstructed correction transaction."""
    return read_held(value)[0]


def prepare(value: CorrectionCapture, guard: Callable[[], None]) -> bool:
    """Create exactly one proposal snapshot; races/partial attempts remain fenced."""
    root = directory(value)
    if os.path.lexists(root):
        read_current(value)
        return True
    try:
        root.parent.mkdir(mode=0o700)
    except FileExistsError:
        pass
    real_directory(root.parent)
    recheck(value, guard)
    root.mkdir(mode=0o700)
    for name, path in (("plan", value.inputs.plan_path), ("manifest", value.inputs.manifest_path),
                       ("transcript", value.inputs.transcript_path)):
        guard()
        _new_plan(root / f"parent-{name}.json", value.documents[path])
    guard()
    write_new(root / "request.json", request_for(value))
    _sync_directory(root)
    _sync_directory(root.parent)
    recheck(value, guard)
    read_current(value)
    return False


def _new_decision(sent: dict, request: dict) -> dict:
    """Record only the supplied human attestations with a UTC audit timestamp."""
    profile = correction_profile(request["schemaVersion"])
    body = {"schemaVersion": profile["schemaVersion"], "kind": profile["kindPrefix"] + "-record",
            "policy": profile["policy"], "scope": profile["scope"], "actor": profile["actor"],
            "requestHash": request["requestHash"],
            "recordedAt": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "submission": sent}
    return _decision({**body, "recordHash": digest(body)}, request)


def _publish(value: CorrectionCapture, request: dict, sent: dict, guard: Callable[[], None]) -> None:
    """Write immutable decision/output under the claim and publish commit last."""
    if value.observation is None:
        raise RuntimeError("timing correction record requires actual source verification")
    root = directory(value)
    decision = _new_decision(sent, request)
    transcript = corrected_result(value.transcript, request, decision, value.observation)
    commit = _commit(request, decision, transcript)
    recheck(value, guard)
    _equal(root / "record-claim.json", _claim(sent))
    write_new(root / "decision.json", decision)
    guard()
    write_new(root / "corrected-transcript.json", transcript)
    _sync_directory(root)
    recheck(value, guard)
    _equal(root / "decision.json", decision)
    _equal(root / "corrected-transcript.json", transcript)
    _equal(root / "record-claim.json", _claim(sent))
    guard()
    write_new(root / "commit.json", commit)
    _sync_directory(root)
    recheck(value, guard)
    read_current(value)
    guard()


def record(value: CorrectionCapture, submitted: object, guard: Callable[[], None]) -> bool:
    """Exclusive creation is the CAS; only this writer may record its own failure."""
    request, prior, _revision = read_current(value)
    sent = submission(submitted, request)
    if prior is not None:
        if prior["submission"] != sent:
            raise RuntimeError("timing correction single-record/idempotency conflict")
        return True
    recheck(value, guard)
    root = directory(value)
    write_new(root / "record-claim.json", _claim(sent))  # No overwrite or lease-expiry retry.
    try:
        _sync_directory(root)
        _publish(value, request, sent, guard)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, IndexError) as exc:
        version = value.proposed["schemaVersion"]
        kind = "timing-correction-failed" if version == 1 else "source-word-text-correction-failed"
        write_new(root / "failure.json", {"schemaVersion": version, "kind": kind,
                  "error": str(exc)[:1000], "requestHash": request["requestHash"], "selected": False})
        _sync_directory(root)
        raise
    return False
