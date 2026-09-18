"""Pinned selected-CURRENT reader with exact versioned profile dispatch."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass

from .generation_reader import GenerationReadError, ResolvedGenerationV1, _resolve
from .generation_schema import (
    CurrentPointerV1,
    GenerationCommitV1,
    GenerationSchemaError,
    parse_current_pointer,
    parse_generation_commit,
)
from .genesis_generation_profile import GENESIS_R1_PROFILE
from .versioned_generation_profile_dispatch import (
    VersionedProfileSelectionV2,
    select_versioned_generation_profile,
)
from .wire_identity import same_wire_value


class VersionedGenerationReadError(RuntimeError):
    """Selected CURRENT is not one exact, continuous supported generation."""


@dataclass(frozen=True)
class VersionedResolvedGenerationV2:
    """Pinned generation tagged with its exact approved-card/profile identity."""

    profile: str
    approved_card_class: str
    generation: ResolvedGenerationV1


def _validate_publication_edge(
    current: CurrentPointerV1,
    commit: GenerationCommitV1,
    selection: VersionedProfileSelectionV2,
) -> None:
    parent = commit.expected_parent
    if selection.profile == GENESIS_R1_PROFILE:
        if current.publication_seq != 1 or parent is not None:
            raise VersionedGenerationReadError(
                "genesis R1 CURRENT must be publication sequence one"
            )
        return
    valid = (
        parent is not None
        and parent.authority_id == current.authority_id
        and current.publication_seq == parent.publication_seq + 1
        and parent.generation_id != current.generation_id
    )
    if not valid:
        raise VersionedGenerationReadError(
            "quality-pass CURRENT has an invalid immediate parent edge"
        )


def _validate_selected(
    current: CurrentPointerV1, commit: GenerationCommitV1
) -> VersionedProfileSelectionV2:
    try:
        selection = select_versioned_generation_profile(commit)
    except RuntimeError as exc:
        raise VersionedGenerationReadError(
            "selected CURRENT profile is unsupported or mismatched"
        ) from exc
    _validate_publication_edge(current, commit, selection)
    return selection


def _reparse_selected(
    value: object,
) -> tuple[VersionedResolvedGenerationV2, CurrentPointerV1, GenerationCommitV1]:
    if type(value) is not VersionedResolvedGenerationV2:
        raise VersionedGenerationReadError("versioned selection type is invalid")
    if type(value.generation) is not ResolvedGenerationV1:
        raise VersionedGenerationReadError("resolved generation type is invalid")
    if type(value.generation.current) is not CurrentPointerV1:
        raise VersionedGenerationReadError("selected CURRENT type is invalid")
    if type(value.generation.commit) is not GenerationCommitV1:
        raise VersionedGenerationReadError("selected commit type is invalid")
    try:
        current = parse_current_pointer(value.generation.current.document_json)
        commit = parse_generation_commit(value.generation.commit.document_json)
    except GenerationSchemaError as exc:
        raise VersionedGenerationReadError(
            "selected generation wire bytes are invalid"
        ) from exc
    if not same_wire_value(value.generation.current, current):
        raise VersionedGenerationReadError("selected CURRENT construction is forged")
    if not same_wire_value(value.generation.commit, commit):
        raise VersionedGenerationReadError("selected commit construction is forged")
    return value, current, commit


def validate_versioned_resolved_generation(
    value: object,
) -> VersionedProfileSelectionV2:
    """Reparse and bind one exact tagged selection without trusting construction."""
    selected, current, commit = _reparse_selected(value)
    observed = (commit.authority_id, commit.generation_id, commit.commit_digest)
    expected = (current.authority_id, current.generation_id, current.commit_digest)
    if observed != expected:
        raise VersionedGenerationReadError("selected CURRENT does not bind commit")
    selection = _validate_selected(current, commit)
    tags = (selected.profile, selected.approved_card_class)
    expected_tags = (selection.profile, selection.approved_card_class)
    if not same_wire_value(tags, expected_tags):
        raise VersionedGenerationReadError("selected version/profile tag is stale")
    return selection


@contextlib.contextmanager
def read_versioned_current_generation(
    authority_root: str, materialization_root: str
) -> Iterator[VersionedResolvedGenerationV2]:
    """Materialize one selected R0/R1 generation after pre-walk dispatch."""
    try:
        generation = _resolve(authority_root, materialization_root, _validate_selected)
        selection = _validate_selected(generation.current, generation.commit)
    except VersionedGenerationReadError:
        raise
    except (OSError, GenerationReadError, GenerationSchemaError) as exc:
        raise VersionedGenerationReadError(
            "cannot resolve versioned selected CURRENT"
        ) from exc
    selected = VersionedResolvedGenerationV2(
        selection.profile, selection.approved_card_class, generation
    )
    validate_versioned_resolved_generation(selected)
    yield selected
