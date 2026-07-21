"""Disjoint non-genesis profile for card, assembly, and verification V2."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from .generation_profile import (
    R0_ARTIFACT_CLASS_BYTE_CAPS,
    R0_GENERATION_ARTIFACT_CLASS_COUNTS,
    R0_MAX_AGGREGATE_BYTES,
    R0_MAX_PATH_DEPTH,
)
from .generation_schema import (
    GenerationCommitV1,
    GenerationManifestRowV1,
    parse_generation_commit,
)
from .wire_identity import same_wire_value

QUALITY_PASS_R1_PROFILE = "deterministic-mp4-quality-pass-r1-v2"
_REPLACED = frozenset(
    {
        "approved-parent-v1",
        "assembly-receipt-v1",
        "generation-verification-v1",
    }
)
_V2_CLASSES = (
    "quality-pass-approved-card-v2",
    "assembly-receipt-v2",
    "quality-pass-generation-verification-v2",
)
QUALITY_PASS_R1_CLASS_COUNTS: Mapping[str, int] = MappingProxyType(
    {
        **{
            name: count
            for name, count in R0_GENERATION_ARTIFACT_CLASS_COUNTS.items()
            if name not in _REPLACED
        },
        **{name: 1 for name in _V2_CLASSES},
    }
)
QUALITY_PASS_R1_MANIFEST_ROWS = sum(QUALITY_PASS_R1_CLASS_COUNTS.values())
QUALITY_PASS_R1_BYTE_CAPS: Mapping[str, int] = MappingProxyType(
    {
        **{
            name: R0_ARTIFACT_CLASS_BYTE_CAPS[name]
            for name in QUALITY_PASS_R1_CLASS_COUNTS
            if name in R0_ARTIFACT_CLASS_BYTE_CAPS
        },
        **{name: 16 * 1024 * 1024 for name in _V2_CLASSES},
    }
)


class QualityPassGenerationProfileV2Error(RuntimeError):
    """A commit does not match the closed quality-pass profile V2."""


def _commit(value: object) -> GenerationCommitV1:
    if type(value) is not GenerationCommitV1:
        raise QualityPassGenerationProfileV2Error("quality-pass commit type is invalid")
    try:
        parsed = parse_generation_commit(value.document_json)
    except RuntimeError as exc:
        raise QualityPassGenerationProfileV2Error(
            "quality-pass commit bytes are invalid"
        ) from exc
    if not same_wire_value(value, parsed):
        raise QualityPassGenerationProfileV2Error("quality-pass commit is forged")
    return parsed


def _groups(
    commit: GenerationCommitV1,
) -> Mapping[str, tuple[GenerationManifestRowV1, ...]]:
    grouped: dict[str, list[GenerationManifestRowV1]] = {
        name: [] for name in QUALITY_PASS_R1_CLASS_COUNTS
    }
    for row in commit.files:
        if row.artifact_class not in grouped:
            raise QualityPassGenerationProfileV2Error(
                f"quality-pass V2 unknown class: {row.artifact_class}"
            )
        grouped[row.artifact_class].append(row)
    mismatches = tuple(
        name
        for name, expected in QUALITY_PASS_R1_CLASS_COUNTS.items()
        if len(grouped[name]) != expected
    )
    if mismatches:
        raise QualityPassGenerationProfileV2Error(
            f"quality-pass V2 class cardinality mismatch: {', '.join(mismatches)}"
        )
    return MappingProxyType({name: tuple(rows) for name, rows in grouped.items()})


def _bounds(commit: GenerationCommitV1) -> None:
    if len(commit.files) != QUALITY_PASS_R1_MANIFEST_ROWS:
        raise QualityPassGenerationProfileV2Error(
            f"quality-pass V2 requires {QUALITY_PASS_R1_MANIFEST_ROWS} rows"
        )
    paths = tuple(row.path for row in commit.files)
    if paths != tuple(sorted(paths)):
        raise QualityPassGenerationProfileV2Error(
            "quality-pass V2 rows must be path ordered"
        )
    aggregate = 0
    for row in commit.files:
        if row.size_bytes <= 0 or len(row.path.split("/")) > R0_MAX_PATH_DEPTH:
            raise QualityPassGenerationProfileV2Error(
                "quality-pass V2 artifact bounds are invalid"
            )
        if row.size_bytes > QUALITY_PASS_R1_BYTE_CAPS[row.artifact_class]:
            raise QualityPassGenerationProfileV2Error(
                "quality-pass V2 class byte cap exceeded"
            )
        aggregate += row.size_bytes
    if aggregate > R0_MAX_AGGREGATE_BYTES:
        raise QualityPassGenerationProfileV2Error(
            "quality-pass V2 aggregate byte cap exceeded"
        )


def verify_quality_pass_r1_profile(
    value: object,
) -> Mapping[str, tuple[GenerationManifestRowV1, ...]]:
    """Verify the exact non-null-parent V2 card/assembly class multiset."""
    commit = _commit(value)
    if commit.expected_parent is None:
        raise QualityPassGenerationProfileV2Error(
            "quality-pass V2 requires a non-null expected parent"
        )
    groups = _groups(commit)
    _bounds(commit)
    matches = tuple(
        row for row in commit.files if row.path == commit.approved_parent_path
    )
    valid = len(matches) == 1 and matches[0].artifact_class == (
        "quality-pass-approved-card-v2"
    )
    if not valid:
        raise QualityPassGenerationProfileV2Error(
            "quality-pass approvedParentPath does not select card V2"
        )
    return groups
