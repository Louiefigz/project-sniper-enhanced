"""Public value types for non-authorizing build closure reobservation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from .build_closure_reobservation_wire import (
    BuildClosureReobservationReportV1,
)
from .build_receipt_binding import BuildReceiptBindingV1

ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class BuildClosureReobservationRequestV1:
    """Static receipt authority and its canonical source release root."""

    binding: BuildReceiptBindingV1
    pipeline_root: str


@dataclass(frozen=True)
class BuildClosureObservationV1:
    """Path-free build identities exposed to the synchronous callback."""

    compositor_build_digest: str
    render_build_digest: str
    source_count: int
    source_set_digest: str
    tool_count: int
    tool_set_digest: str


@dataclass(frozen=True)
class BuildClosureReobservationOutcomeV1(Generic[ResultT]):
    """Callback result plus an explicitly non-authorizing canonical report."""

    observation_result: ResultT
    report: BuildClosureReobservationReportV1
