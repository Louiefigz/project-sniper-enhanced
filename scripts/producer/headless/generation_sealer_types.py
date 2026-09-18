"""Closed types and resource policy for non-publishing generation sealing."""

from __future__ import annotations

from dataclasses import dataclass

from .generation_schema import GenerationCommitV1

MAX_COMMIT_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_ROWS = 4_096
MAX_PATH_DEPTH = 32
MAX_FILE_BYTES = 16 * 1024 * 1024 * 1024
MAX_GENERATION_BYTES = 64 * 1024 * 1024 * 1024
MAX_JSON_DEPTH = 8
MAX_JSON_STRUCTURAL_TOKENS = 65_536
PENDING_INTENT_NAME = ".seal-intent.json"
PENDING_INTENT_TEMP_NAME = ".seal-intent.pending"


class GenerationSealError(RuntimeError):
    """A staging tree cannot be installed as one immutable generation."""


def validate_json_resource_shape(raw: bytes) -> None:
    """Bound JSON structure before allocating the standard decoder tree."""
    depth = structural = 0
    in_string = escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == ord("\\"):
                escaped = True
            elif byte == ord('"'):
                in_string = False
            continue
        if byte == ord('"'):
            in_string = True
            continue
        if byte in (ord("["), ord("{")):
            depth += 1
            structural += 1
        elif byte in (ord("]"), ord("}")):
            depth -= 1
            structural += 1
        elif byte in (ord(","), ord(":")):
            structural += 1
        if depth < 0 or depth > MAX_JSON_DEPTH:
            raise GenerationSealError(
                "generation commit exceeds parser limits"
            )
        if structural > MAX_JSON_STRUCTURAL_TOKENS:
            raise GenerationSealError(
                "generation commit exceeds parser limits"
            )
    if in_string or depth != 0:
        raise GenerationSealError("generation commit JSON shape is invalid")


@dataclass(frozen=True)
class GenerationSealRequestV1:
    """Canonical authority, staging root, and exact generation commit bytes."""

    authority_root: str
    staging_root: str
    commit_json: bytes


@dataclass(frozen=True)
class GenerationSealResultV1:
    """Administrative result; this does not publish or authorize execution."""

    generation_id: str
    commit_digest: str
    replayed: bool


def validate_resource_policy(commit: GenerationCommitV1) -> None:
    """Reject manifests that can exceed the bounded sealer work envelope."""
    rows = commit.files
    valid_count = 0 < len(rows) <= MAX_MANIFEST_ROWS
    valid_depth = all(
        len(row.path.split("/")) <= MAX_PATH_DEPTH for row in rows
    )
    valid_sizes = all(row.size_bytes <= MAX_FILE_BYTES for row in rows)
    if not valid_count or not valid_depth or not valid_sizes:
        raise GenerationSealError("generation manifest exceeds sealer limits")
    if sum(row.size_bytes for row in rows) > MAX_GENERATION_BYTES:
        raise GenerationSealError("generation payload exceeds sealer limits")
