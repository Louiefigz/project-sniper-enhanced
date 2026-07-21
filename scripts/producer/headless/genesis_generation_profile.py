"""Disjoint genesis R1 profile selected solely by a null expected parent."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .generation_profile import (
    R0_ARTIFACT_CLASS_BYTE_CAPS,
    R0_GENERATION_ARTIFACT_CLASS_COUNTS,
    R0_MAX_AGGREGATE_BYTES,
    R0_MAX_PATH_DEPTH,
    verify_r0_generation_profile,
)
from .generation_schema import (
    GenerationCommitV1,
    GenerationManifestRowV1,
    parse_generation_commit,
)
from .wire_identity import same_wire_value

GENESIS_R1_PROFILE = "deterministic-mp4-genesis-r1-v2"
QUALITY_PASS_R0_PROFILE = "deterministic-mp4-r0-v1"
_REMOVED_R0_CLASSES = frozenset(
    {
        "approved-parent-v1",
        "generation-verification-v1",
        "execution-policy-v1",
        "assembly-receipt-v1",
    }
)
_GENESIS_CLASSES = (
    "genesis-approved-card-v2",
    "generation-verification-v2",
    "initialization-execution-policy-v2",
    "initialization-origin-receipt-v1",
    "headless-operation-v1",
    "initialization-snapshot-authority-v1",
)
_GENESIS_POLICY_CLASSES = (
    "repair-policy-v1",
    "quality-policy-v1",
    "fallback-policy-v1",
)
GENESIS_R1_SEMANTIC_DOCUMENT_MAX_BYTES = 1024 * 1024

GENESIS_R1_GENERATION_ARTIFACT_CLASS_COUNTS: Mapping[str, int] = MappingProxyType(
    {
        **{
            name: count
            for name, count in R0_GENERATION_ARTIFACT_CLASS_COUNTS.items()
            if name not in _REMOVED_R0_CLASSES
        },
        **{name: 1 for name in _GENESIS_CLASSES},
    }
)
GENESIS_R1_MANIFEST_ROWS = sum(GENESIS_R1_GENERATION_ARTIFACT_CLASS_COUNTS.values())
GENESIS_R1_ARTIFACT_CLASS_BYTE_CAPS: Mapping[str, int] = MappingProxyType(
    {
        **{
            name: R0_ARTIFACT_CLASS_BYTE_CAPS[name]
            for name in GENESIS_R1_GENERATION_ARTIFACT_CLASS_COUNTS
            if name in R0_ARTIFACT_CLASS_BYTE_CAPS
        },
        **{
            name: GENESIS_R1_SEMANTIC_DOCUMENT_MAX_BYTES
            for name in _GENESIS_CLASSES + _GENESIS_POLICY_CLASSES
        },
    }
)


class GenesisGenerationProfileError(RuntimeError):
    """A commit does not match the selected disjoint generation profile."""


@dataclass(frozen=True)
class GenerationProfileSelectionV2:
    """One explicit profile selection with immutable artifact groups."""

    profile: str
    expected_parent_is_null: bool
    groups: Mapping[str, tuple[GenerationManifestRowV1, ...]]


def _validated_commit(value: object) -> GenerationCommitV1:
    if type(value) is not GenerationCommitV1 or type(value.files) is not tuple:
        raise GenesisGenerationProfileError("generation profile commit type is invalid")
    try:
        parsed = parse_generation_commit(value.document_json)
    except RuntimeError as exc:
        raise GenesisGenerationProfileError(
            "generation profile commit is invalid"
        ) from exc
    if not same_wire_value(value, parsed):
        raise GenesisGenerationProfileError("generation profile commit is forged")
    return parsed


def _approved_card(commit: GenerationCommitV1) -> None:
    matches = tuple(
        row for row in commit.files if row.path == commit.approved_parent_path
    )
    if len(matches) != 1:
        raise GenesisGenerationProfileError(
            "genesis approvedParentPath must select exactly one row"
        )
    if matches[0].artifact_class != "genesis-approved-card-v2":
        raise GenesisGenerationProfileError(
            "genesis approvedParentPath must select genesis-approved-card-v2"
        )


def _bounds(commit: GenerationCommitV1) -> None:
    if len(commit.files) != GENESIS_R1_MANIFEST_ROWS:
        raise GenesisGenerationProfileError(
            f"genesis R1 requires exactly {GENESIS_R1_MANIFEST_ROWS} manifest rows"
        )
    paths = tuple(row.path for row in commit.files)
    if paths != tuple(sorted(paths)):
        raise GenesisGenerationProfileError("genesis R1 rows must be path ordered")
    aggregate = 0
    for row in commit.files:
        if row.size_bytes <= 0:
            raise GenesisGenerationProfileError("genesis R1 artifacts must be nonempty")
        if len(row.path.split("/")) > R0_MAX_PATH_DEPTH:
            raise GenesisGenerationProfileError("genesis R1 artifact path is too deep")
        cap = GENESIS_R1_ARTIFACT_CLASS_BYTE_CAPS[row.artifact_class]
        if row.size_bytes > cap:
            raise GenesisGenerationProfileError("genesis R1 class byte cap exceeded")
        aggregate += row.size_bytes
    if aggregate > R0_MAX_AGGREGATE_BYTES:
        raise GenesisGenerationProfileError("genesis R1 aggregate byte cap exceeded")


def _grouped(
    commit: GenerationCommitV1,
) -> Mapping[str, tuple[GenerationManifestRowV1, ...]]:
    groups: dict[str, list[GenerationManifestRowV1]] = {
        name: [] for name in GENESIS_R1_GENERATION_ARTIFACT_CLASS_COUNTS
    }
    for row in commit.files:
        if row.artifact_class not in groups:
            raise GenesisGenerationProfileError(
                f"genesis R1 unknown artifact class: {row.artifact_class}"
            )
        groups[row.artifact_class].append(row)
    mismatches = tuple(
        name
        for name, expected in GENESIS_R1_GENERATION_ARTIFACT_CLASS_COUNTS.items()
        if len(groups[name]) != expected
    )
    if mismatches:
        raise GenesisGenerationProfileError(
            f"genesis R1 class cardinality mismatch: {', '.join(mismatches)}"
        )
    return MappingProxyType({name: tuple(rows) for name, rows in groups.items()})


def verify_genesis_r1_generation_profile(
    commit: object,
) -> Mapping[str, tuple[GenerationManifestRowV1, ...]]:
    """Verify only the null-parent genesis R1 class multiset."""
    commit = _validated_commit(commit)
    if commit.expected_parent is not None:
        raise GenesisGenerationProfileError("genesis R1 requires expectedParent null")
    if any(type(row) is not GenerationManifestRowV1 for row in commit.files):
        raise GenesisGenerationProfileError("genesis R1 row type is invalid")
    groups = _grouped(commit)
    _bounds(commit)
    _approved_card(commit)
    return groups


def select_disjoint_generation_profile(commit: object) -> GenerationProfileSelectionV2:
    """Select genesis R1 iff expectedParent is null, otherwise select frozen R0."""
    commit = _validated_commit(commit)
    if commit.expected_parent is None:
        groups = verify_genesis_r1_generation_profile(commit)
        return GenerationProfileSelectionV2(GENESIS_R1_PROFILE, True, groups)
    try:
        groups = verify_r0_generation_profile(commit)
    except RuntimeError as exc:
        raise GenesisGenerationProfileError(
            "quality-pass R0 profile is invalid"
        ) from exc
    return GenerationProfileSelectionV2(QUALITY_PASS_R0_PROFILE, False, groups)
