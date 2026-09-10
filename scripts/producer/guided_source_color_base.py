"""All-used known-BT709 identity evidence for an internal fresh base boundary.

This consumes the SAME completed source batch and its original persistent
owner; it creates no admission, clock, lease, decoder or source conversion.
Only absent or literal-null baselineLook means no new look. Every original
used source must be V1 with known declared history and separate held all-frame
identity metadata. This is not RGB gamut, output pixel parity, a renderer/cache
receipt, creative approval, or permission to activate the presenter registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from color.deadline import require_time
from color.grade_bt709_identity_read import (
    HeldBt709IdentityObservation, _IdentityRead, _unchanged as identity_unchanged, read_bt709_identity_observation,
)
from color.grade_observation_profile import V1
from color.grade_project_owned import _typed_fields
from guided_opening_inputs import OpeningInputs
from guided_source_color_execution import (
    CompletedSourceColorBatch, _binding as batch_binding, _unchanged as batch_unchanged,
)
from guided_source_color_preparation import _used


def _batch(value: CompletedSourceColorBatch) -> tuple:
    """Require the original completed batch, never a reconstructed list of observations."""
    if type(value) is not CompletedSourceColorBatch:
        raise RuntimeError("BT709 base requires the actual completed all-used-source batch")
    batch_unchanged(value, value._origin)
    return batch_binding(value)


def _selection(value: CompletedSourceColorBatch) -> None:
    """Reject unsupported source/intent classes before any supplemental metadata read."""
    preparation = value.preparation
    plan = preparation.inputs.documents["candidatePlan"]
    if type(plan) is not dict or plan.get("baselineLook") is not None:
        raise RuntimeError("BT709 identity base requires absent or literal-null baselineLook; no new look")
    used = _used(plan, preparation._read.declarations)
    jobs = preparation.jobs
    if tuple(row.binding.source_id for row in jobs) != used or len(value.observations) != len(jobs):
        raise RuntimeError("BT709 base does not cover the exact ordered original used sources")
    for job, observed in zip(jobs, value.observations):
        if job.profile is not V1 or observed.context.source is not job.source \
                or _typed_fields(observed.observation.records.source) != _typed_fields(job.binding) \
                or type(observed.context.deadline) is not type(preparation.context.deadline) \
                or observed.context.deadline != preparation.context.deadline:
            raise RuntimeError("BT709 base requires original V1 source bindings and the same overall cutoff")


def _proofs(value: HeldBt709BaseIdentity) -> tuple:
    """Check actual supplemental returns after all batch callbacks without replaying JSON."""
    if type(value.observations) is not tuple or type(value._identity_origins) is not tuple \
            or len(value.observations) != len(value.batch.observations) or len(value._identity_origins) != len(value.observations):
        raise RuntimeError("BT709 base supplemental observation coverage changed")
    result = []
    for identity, completed, original in zip(value.observations, value.batch.observations, value._identity_origins):
        if type(identity) is not HeldBt709IdentityObservation or identity.completed is not completed:
            raise RuntimeError("BT709 base replaced an original supplemental observation")
        identity_unchanged(identity, original)
        _IdentityRead.unchanged(identity._read)
        result.append((id(identity), id(original), original))
    return tuple(result)


def _binding(value: HeldBt709BaseIdentity) -> tuple:
    """Hold the actual batch, original inputs and all small supplemental evidence."""
    return (id(value), id(value.batch), _batch(value.batch), id(value.batch.preparation.inputs),
            id(value.observations), id(value._identity_origins), _proofs(value),
            _typed_fields(value, ("batch", "observations", "_identity_origins", "_origin")))


def _unchanged(value: HeldBt709BaseIdentity, original: tuple) -> None:
    """Reject callbacks that replace source coverage, original lifetime or false flags."""
    if value._origin is not original or _binding(value) != original:
        raise RuntimeError("BT709 base original batch or identity evidence changed")


@dataclass(frozen=True, init=False)
class HeldBt709BaseIdentity:
    """Current all-source identity metadata only, not an executed or approved base."""

    batch: CompletedSourceColorBatch
    observations: tuple[HeldBt709IdentityObservation, ...]
    executable: bool = field(default=False, init=False)
    gamut_measured: bool = field(default=False, init=False)
    base_picture_observed: bool = field(default=False, init=False)
    grade_applicable: bool = field(default=False, init=False)
    delivery_approved: bool = field(default=False, init=False)
    _identity_origins: tuple = field(repr=False)
    _origin: tuple = field(repr=False)

    def __init__(self) -> None:
        """Only the same-process all-source factory can provide an actual held value."""
        raise TypeError("BT709 base identity requires hold_bt709_base_identity")

    @property
    def inputs(self) -> OpeningInputs:
        """Expose the SAME actual original inputs, never a relabeled or copied candidate."""
        return self.batch.preparation.inputs

    def assert_current(self) -> None:
        """Keep original persistent source/file guards, then close every supplemental result."""
        original = self._origin
        _unchanged(self, original)
        CompletedSourceColorBatch.assert_current(self.batch)
        _selection(self.batch)
        _unchanged(self, original)
        require_time(self.batch.preparation.context.deadline)


def _read_identity(completed: object) -> tuple:
    """Retain an actual returned origin immediately, before any later source callback."""
    result = read_bt709_identity_observation(completed)
    return result, result._origin


def hold_bt709_base_identity(batch: CompletedSourceColorBatch) -> HeldBt709BaseIdentity:
    """Read complete original V1 identity evidence once, with no new work allowance."""
    original = _batch(batch)
    _selection(batch)
    CompletedSourceColorBatch.assert_current(batch)
    if _batch(batch) != original:
        raise RuntimeError("BT709 base original batch changed before metadata replay")
    returned = tuple(_read_identity(row) for row in batch.observations)
    if _batch(batch) != original:
        raise RuntimeError("BT709 base original batch changed during metadata replay")
    value = object.__new__(HeldBt709BaseIdentity)
    values = {"batch": batch, "observations": tuple(row[0] for row in returned),
              "_identity_origins": tuple(row[1] for row in returned), "executable": False, "gamut_measured": False,
              "base_picture_observed": False, "grade_applicable": False, "delivery_approved": False}
    for name, item in values.items():
        object.__setattr__(value, name, item)
    object.__setattr__(value, "_origin", _binding(value))
    origin = value._origin
    HeldBt709BaseIdentity.assert_current(value)
    _unchanged(value, origin)
    require_time(batch.preparation.context.deadline)
    return value
