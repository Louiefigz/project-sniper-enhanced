"""Pure profile dispatch for genesis R1, quality-pass V2, and frozen R0."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .generation_profile import verify_r0_generation_profile
from .generation_schema import (
    GenerationCommitV1,
    GenerationManifestRowV1,
    parse_generation_commit,
)
from .genesis_generation_profile import (
    GENESIS_R1_PROFILE,
    QUALITY_PASS_R0_PROFILE,
    verify_genesis_r1_generation_profile,
)
from .versioned_quality_pass_profile import (
    QUALITY_PASS_R1_PROFILE,
    verify_quality_pass_r1_profile,
)
from .wire_identity import same_wire_value


class VersionedGenerationProfileDispatchError(RuntimeError):
    """A commit cannot be assigned to one exact versioned profile."""


@dataclass(frozen=True)
class VersionedProfileSelectionV2:
    """One explicit card-class/profile selection without legacy inference."""

    profile: str
    approved_card_class: str
    groups: Mapping[str, tuple[GenerationManifestRowV1, ...]]


def _commit(value: object) -> GenerationCommitV1:
    if type(value) is not GenerationCommitV1:
        raise VersionedGenerationProfileDispatchError("dispatch commit is invalid")
    try:
        parsed = parse_generation_commit(value.document_json)
    except RuntimeError as exc:
        raise VersionedGenerationProfileDispatchError(
            "dispatch commit bytes are invalid"
        ) from exc
    if not same_wire_value(value, parsed):
        raise VersionedGenerationProfileDispatchError("dispatch commit is forged")
    return parsed


def _approved_class(commit: GenerationCommitV1) -> str:
    matches = tuple(
        row for row in commit.files if row.path == commit.approved_parent_path
    )
    if len(matches) != 1:
        raise VersionedGenerationProfileDispatchError(
            "approvedParentPath selection is ambiguous"
        )
    return matches[0].artifact_class


def select_versioned_generation_profile(value: object) -> VersionedProfileSelectionV2:
    """Dispatch by null-parent state plus exact approved-card artifact class."""
    commit = _commit(value)
    card_class = _approved_class(commit)
    try:
        if commit.expected_parent is None:
            if card_class != "genesis-approved-card-v2":
                raise VersionedGenerationProfileDispatchError(
                    "null parent requires genesis-approved-card-v2"
                )
            groups = verify_genesis_r1_generation_profile(commit)
            return VersionedProfileSelectionV2(GENESIS_R1_PROFILE, card_class, groups)
        if card_class == "quality-pass-approved-card-v2":
            groups = verify_quality_pass_r1_profile(commit)
            return VersionedProfileSelectionV2(
                QUALITY_PASS_R1_PROFILE, card_class, groups
            )
        if card_class == "approved-parent-v1":
            groups = verify_r0_generation_profile(commit)
            return VersionedProfileSelectionV2(
                QUALITY_PASS_R0_PROFILE, card_class, groups
            )
    except VersionedGenerationProfileDispatchError:
        raise
    except RuntimeError as exc:
        raise VersionedGenerationProfileDispatchError(
            "selected generation profile is invalid"
        ) from exc
    raise VersionedGenerationProfileDispatchError(
        "non-null parent card class is unsupported"
    )
