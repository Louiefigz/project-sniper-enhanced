"""Same-process prepared source lifetime, never a serialized execution capability.

This retains the actual successful preparation read and its original caller
guard. It does not repeat admission, hash original media, acquire a resource,
start a clock or launch a decoder. The enclosing caller must supply the real
persistent project/source/tool guard, not a temporary color-resource claim.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from color.deadline import require_time
from color.grade_contract import SourceBinding
from color.grade_observation_profile import ObservationProfile
from color.grade_project_owned import _typed_fields
from guided_opening_inputs import OpeningInputs
from guided_source_color_preparation import (
    PreparedSourceColorJob, SourceColorPreparationContext, _PreparationRead, _prepare_source_color_jobs,
)
from headless.external_media_verification import VerifiedSnapshotIdentity


def _job_binding(row: PreparedSourceColorJob) -> tuple:
    """Retain the original identity and exact typed metadata of each prepared row."""
    if type(row) is not PreparedSourceColorJob or type(row.source) is not VerifiedSnapshotIdentity \
            or type(row.profile) is not ObservationProfile or type(row.binding) is not SourceBinding \
            or type(row.metadata_json) is not bytes:
        raise RuntimeError("held source color preparation row changed")
    return (id(row), id(row.source), _typed_fields(row.source), id(row.profile), _typed_fields(row.profile),
            id(row.binding), _typed_fields(row.binding), row.metadata_json,
            _typed_fields(row, ("source", "profile", "binding", "metadata_json")))


def _binding(value: HeldSourceColorPreparation) -> tuple:
    """Bind actual private read references before any further caller callback."""
    read = value._read
    if type(read) is not _PreparationRead or type(value.jobs) is not tuple \
            or type(value.context) is not SourceColorPreparationContext or read.context is not value.context:
        raise RuntimeError("held source color preparation original lifetime changed")
    return (id(value), id(read), id(value.context), id(value.jobs), tuple(_job_binding(row) for row in value.jobs),
            id(read.inputs), id(read.declarations), id(read.context), id(read.capture),
            type(read.deadline), read.deadline, id(read.callback), id(read.binding), id(read.runtime),
            id(read.files), tuple(read.files),
            _typed_fields(value, ("jobs", "context", "_read", "_origin")))


def _unchanged(value: HeldSourceColorPreparation, original: tuple) -> None:
    """A clone or callback cannot renew a preparation's original source/clock lifetime."""
    if value._origin is not original or _binding(value) != original:
        raise RuntimeError("held source color preparation original references or metadata changed")


@dataclass(frozen=True, init=False)
class HeldSourceColorPreparation:
    """Retain actual prepared source data only while the original caller remains live."""

    jobs: tuple[PreparedSourceColorJob, ...]
    context: SourceColorPreparationContext
    executable: bool = field(default=False, init=False)
    grade_applicable: bool = field(default=False, init=False)
    delivery_approved: bool = field(default=False, init=False)
    _read: _PreparationRead = field(repr=False)
    _origin: tuple = field(repr=False)

    def __init__(self) -> None:
        """Do not accept prepared JSON or caller-supplied replacement source authority."""
        raise TypeError("held source color preparation requires hold_source_color_preparation")

    def assert_current(self) -> None:
        """Check original metadata/guard/source stats without re-reading source bytes."""
        original = self._origin
        _unchanged(self, original)
        self._read.check()
        _unchanged(self, original)
        require_time(self._read.deadline)

    @property
    def inputs(self) -> OpeningInputs:
        """Expose the SAME held opening input for exact immutable preclaim joins."""
        return self._read.inputs


def hold_source_color_preparation(inputs: OpeningInputs, declarations: dict,
                                  context: SourceColorPreparationContext) -> HeldSourceColorPreparation:
    """Retain one completed original all-source read; no job or partial result escapes."""
    read, rows = _prepare_source_color_jobs(inputs, declarations, context)
    value = object.__new__(HeldSourceColorPreparation)
    fields = {"jobs": rows, "context": context, "_read": read,
              "executable": False, "grade_applicable": False, "delivery_approved": False}
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    object.__setattr__(value, "_origin", _binding(value))
    value.assert_current()
    return value
