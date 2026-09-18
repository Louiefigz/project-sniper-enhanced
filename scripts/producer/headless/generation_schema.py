"""Strict JSON wire types for immutable headless generation authority."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass

from .repair_intent import ParentRefV1, validate_parent_ref

_DIGEST = re.compile(r"[0-9a-f]{64}")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_ROW_KEYS = frozenset("artifactClass path sha256 sizeBytes".split())
_CURRENT_KEYS = frozenset(
    "authorityId commitDigest generationId publicationSeq schemaVersion".split()
)
_COMMIT_KEYS = frozenset(
    "approvedParentPath attemptId authorityId executionPolicyId expectedParent "
    "fallbackPolicyId files generationId qualityPolicyId repairPolicyId "
    "requestDigest schemaVersion unitId".split()
)
_PARENT_KEYS = frozenset(
    "authorityId commitDigest generationId planDigest publicationSeq".split()
)
_RESERVED_PATH_PARTS = frozenset(
    ".publish.mutex .seal-intent.json .seal-intent.pending commit.json current fence "
    "publish-intent.json".split()
)
_RESERVED_CLASSES = frozenset(
    "commit current current-pointer fence fence-state publication "
    "publication-receipt publish-intent publisher-state".split()
)
_COMMIT_DOMAIN = b"sniper-mp4-generation-commit-v1\0"


class GenerationSchemaError(RuntimeError):
    """A CURRENT pointer or immutable generation commit is malformed."""


class _DuplicateKey(ValueError):
    pass


@dataclass(frozen=True)
class CurrentPointerV1:
    """One canonical published-generation pointer."""

    authority_id: str
    publication_seq: int
    generation_id: str
    commit_digest: str
    document_json: bytes


@dataclass(frozen=True)
class GenerationManifestRowV1:
    """One immutable generation-relative artifact binding."""

    artifact_class: str
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class GenerationCommitV1:
    """Closed immutable generation manifest; publication state is external."""

    authority_id: str
    generation_id: str
    attempt_id: str
    unit_id: str
    request_digest: str
    expected_parent: ParentRefV1 | None
    execution_policy_id: str
    repair_policy_id: str
    quality_policy_id: str
    fallback_policy_id: str
    approved_parent_path: str
    files: tuple[GenerationManifestRowV1, ...]
    document_json: bytes
    commit_digest: str


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise GenerationSchemaError("generation JSON cannot be canonicalized") from exc
    return encoded.encode("ascii")


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _document(value: object, label: str) -> tuple[dict, bytes]:
    if type(value) is bytes:
        try:
            decoded = json.loads(
                value, object_pairs_hook=_pairs, parse_constant=_reject_constant
            )
        except _DuplicateKey as exc:
            raise GenerationSchemaError(f"{label} has duplicate JSON keys") from exc
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise GenerationSchemaError(f"{label} is invalid JSON") from exc
        if type(decoded) is not dict or _canonical(decoded) != value:
            raise GenerationSchemaError(f"{label} is not exact canonical JSON")
        return decoded, value
    if type(value) is not dict:
        raise GenerationSchemaError(f"{label} must be an object or canonical bytes")
    return value, _canonical(value)


def _uuid(label: str, value: object) -> str:
    if type(value) is not str:
        raise GenerationSchemaError(f"{label} must be a canonical UUID")
    try:
        parsed = str(uuid.UUID(value))
    except ValueError as exc:
        raise GenerationSchemaError(f"{label} must be a canonical UUID") from exc
    if parsed != value:
        raise GenerationSchemaError(f"{label} must use canonical UUID form")
    return value


def _digest(label: str, value: object) -> str:
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise GenerationSchemaError(f"{label} must be lowercase SHA-256")
    return value


def _identity(label: str, value: object) -> str:
    if type(value) is not str or not _IDENTITY.fullmatch(value):
        raise GenerationSchemaError(f"{label} is invalid")
    return value


def _safe_path(value: object) -> bool:
    if type(value) is not str or not value or "\\" in value:
        return False
    if unicodedata.normalize("NFC", value) != value:
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    if len(encoded) > 4096:
        return False
    parts = value.split("/")
    controls = any(unicodedata.category(char) == "Cc" for char in value)
    valid_parts = all(
        part not in {"", ".", ".."} and len(part.encode("utf-8")) <= 255
        for part in parts
    )
    return not value.startswith("/") and not controls and valid_parts


def _parent(value: object) -> ParentRefV1 | None:
    if value is None:
        return None
    if type(value) is not dict or set(value) != _PARENT_KEYS:
        raise GenerationSchemaError("expected parent is invalid")
    parent = ParentRefV1(
        value.get("authorityId"),
        value.get("publicationSeq"),
        value.get("generationId"),
        value.get("commitDigest"),
        value.get("planDigest"),
    )
    try:
        validate_parent_ref(parent)
    except RuntimeError as exc:
        raise GenerationSchemaError("expected parent is invalid") from exc
    return parent


def _manifest_row(value: object) -> GenerationManifestRowV1:
    valid = (
        type(value) is dict
        and set(value) == _ROW_KEYS
        and _safe_path(value.get("path"))
        and type(value.get("sizeBytes")) is int
        and value["sizeBytes"] >= 0
    )
    if not valid:
        raise GenerationSchemaError("generation manifest row is invalid")
    artifact_class = _identity("artifact class", value["artifactClass"])
    digest = _digest("artifact digest", value["sha256"])
    return GenerationManifestRowV1(
        artifact_class, value["path"], value["sizeBytes"], digest
    )


def _mutable_row(row: GenerationManifestRowV1) -> bool:
    parts = {part.casefold() for part in row.path.split("/")}
    return (
        bool(parts & _RESERVED_PATH_PARTS)
        or row.artifact_class.casefold() in _RESERVED_CLASSES
    )


def _files(value: object, approved_path: str) -> tuple[GenerationManifestRowV1, ...]:
    if type(value) is not list or not value:
        raise GenerationSchemaError("generation manifest must be a nonempty array")
    rows = tuple(_manifest_row(item) for item in value)
    paths = tuple(row.path for row in rows)
    pairs = tuple((row.artifact_class, row.path) for row in rows)
    aliases = tuple(path.casefold() for path in paths)
    valid = (
        len(set(paths)) == len(paths)
        and len(set(pairs)) == len(pairs)
        and len(set(aliases)) == len(aliases)
        and paths.count(approved_path) == 1
        and not any(_mutable_row(row) for row in rows)
    )
    if not valid:
        raise GenerationSchemaError("generation manifest closure is invalid")
    return rows


def parse_current_pointer(value: object) -> CurrentPointerV1:
    """Parse exact CURRENT object/canonical bytes with no fallback behavior."""
    document, raw = _document(value, "CURRENT pointer")
    valid = (
        set(document) == _CURRENT_KEYS
        and type(document.get("schemaVersion")) is int
        and document["schemaVersion"] == 1
        and type(document.get("publicationSeq")) is int
        and document["publicationSeq"] > 0
    )
    if not valid:
        raise GenerationSchemaError("CURRENT pointer envelope is invalid")
    return CurrentPointerV1(
        _identity("authority ID", document["authorityId"]),
        document["publicationSeq"],
        _uuid("generation ID", document["generationId"]),
        _digest("commit digest", document["commitDigest"]),
        raw,
    )


def parse_generation_commit(value: object) -> GenerationCommitV1:
    """Parse exact immutable commit object/canonical bytes; never read legacy state."""
    document, raw = _document(value, "generation commit")
    valid = (
        set(document) == _COMMIT_KEYS
        and type(document.get("schemaVersion")) is int
        and document["schemaVersion"] == 1
        and _safe_path(document.get("approvedParentPath"))
    )
    if not valid:
        raise GenerationSchemaError("generation commit envelope is invalid")
    authority = _identity("authority ID", document["authorityId"])
    parent = _parent(document["expectedParent"])
    if parent is not None and parent.authority_id != authority:
        raise GenerationSchemaError("expected parent authority does not match")
    rows = _files(document["files"], document["approvedParentPath"])
    return GenerationCommitV1(
        authority,
        _uuid("generation ID", document["generationId"]),
        _uuid("attempt ID", document["attemptId"]),
        _uuid("unit ID", document["unitId"]),
        _digest("request digest", document["requestDigest"]),
        parent,
        _digest("execution policy ID", document["executionPolicyId"]),
        _digest("repair policy ID", document["repairPolicyId"]),
        _digest("quality policy ID", document["qualityPolicyId"]),
        _digest("fallback policy ID", document["fallbackPolicyId"]),
        document["approvedParentPath"],
        rows,
        raw,
        hashlib.sha256(_COMMIT_DOMAIN + raw).hexdigest(),
    )


def generation_commit_digest(document_json: bytes) -> str:
    """Digest exact canonical commit bytes in the V1 generation domain."""
    if type(document_json) is not bytes:
        raise GenerationSchemaError("generation commit digest input must be bytes")
    return parse_generation_commit(document_json).commit_digest
