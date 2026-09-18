"""Typed result for one selected-CURRENT ancestry resolution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .approved_parent_schema import ApprovedParentDescriptorV1
from .generation_schema import CurrentPointerV1, GenerationCommitV1
from .repair_intent import ParentRefV1

SELECTED_CURRENT_ANCESTRY_SCOPE = "selected-current-ancestry-only"


@dataclass(frozen=True)
class HistoricalGenerationRecordV1:
    """One generation proved on the ancestry selected by the pinned CURRENT."""

    ref: ParentRefV1
    commit: GenerationCommitV1
    descriptor: ApprovedParentDescriptorV1


@dataclass(frozen=True)
class HistoricalGenerationMaterializationV1:
    """Private target copy plus the complete selected ancestry to genesis.

    The proof scope intentionally excludes global fork uniqueness. Orphaned
    generation directories have no authenticated publication sequence because
    the V1 schema has no append-only publication ledger.
    """

    proof_scope: str
    anchor_current: CurrentPointerV1
    target: HistoricalGenerationRecordV1
    lineage: tuple[HistoricalGenerationRecordV1, ...]
    materialized: Mapping[str, str]
    materialized_snapshots: Mapping[str, tuple[int, ...]]
