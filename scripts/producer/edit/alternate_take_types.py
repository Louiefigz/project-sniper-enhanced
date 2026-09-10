"""Shared value types for governed alternate-take selection."""
from __future__ import annotations

from dataclasses import dataclass

from edit.cut_repair_candidate_qc_types import CandidateQcContractError
from edit.target_resolver import WordRef


class AlternateTakeAuthorityError(CandidateQcContractError):
    """Alternate-take choice is absent, ambiguous, stale, or substituted."""


@dataclass(frozen=True)
class CandidateSetInput:
    """Exact inputs from which the controller derives available takes."""

    context: dict
    operation: dict
    transcript_path: str
    retake_id: int


@dataclass(frozen=True)
class ScanAuthorityInput:
    """Bindings required to run the released retake detector."""

    context: dict
    source_id: str
    sample_rate: int
    timing_hash: str
    transcript_path: str
    retake_id: int


@dataclass(frozen=True)
class RetakeScanAuthority:
    """Stable transcript/report result used to mint the candidate set."""

    refs: list[WordRef]
    layout: list[tuple[int, int]]
    earlier_indexes: list[int]
    later_indexes: list[int]
    transcript_hash: str
    detector_closure: dict
    detector_closure_hash: str
    report_hash: str
    policy_hash: str
    retake_id: int
