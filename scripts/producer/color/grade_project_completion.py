"""Live-sealed completed grade evidence, not renewed observation or render authority.

Only an actual returned owned observation may be sealed while its original
observation-phase cutoff is still live. Later reads borrow the SAME original
caller context and overall deadline; no clock, guard, source or raw evidence
can be supplied anew. This module has no decoder, JSON reader or claim API.
The enclosing caller still owns the real project/resource/implementation guard.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from color.deadline import require_time
from color.grade_observation_read import BoundGradeObservation
from color.grade_project_owned import (
    GradeProjectOwnedContext, OwnedProjectObservation, _HeldFile,
    _assert_held_files, _assert_observation, _assert_owned_references, _owned_reference_binding, _scalar,
)


def _owned_binding(owned: OwnedProjectObservation) -> tuple:
    """Bind original live wrapper and identities, including the unrenewed caller clock."""
    if type(owned) is not OwnedProjectObservation or type(owned.context) is not GradeProjectOwnedContext:
        raise RuntimeError("completed grade requires the actual owned observation context")
    _assert_owned_references(owned, getattr(owned, "_completion_origin", None))
    return _owned_reference_binding(owned)


@dataclass(frozen=True, init=False)
class CompletedProjectObservation:
    """Completed data only; type identity alone does not authenticate any caller."""

    observation: BoundGradeObservation
    context: GradeProjectOwnedContext
    files: tuple[_HeldFile, ...]
    phase_deadline: float
    executable: bool = field(default=False, init=False)
    grade_applicable: bool = field(default=False, init=False)
    delivery_approved: bool = field(default=False, init=False)
    _owned: OwnedProjectObservation = field(repr=False)
    _observation_binding: tuple = field(repr=False)
    _binding: tuple = field(repr=False)

    def __init__(self) -> None:
        """Do not offer a data/JSON constructor that can bypass live sealing."""
        raise TypeError("completed grade evidence requires live seal_completed_project_observation")

    def assert_current(self) -> None:
        """Read unchanged completed evidence only within the original overall lifetime."""
        original = self._binding
        _unchanged(self, original)
        require_time(self.context.deadline)
        _assert_observation(self.observation, self._observation_binding)
        self.context.check()
        _unchanged(self, original)
        _assert_observation(self.observation, self._observation_binding)
        _assert_held_files(self.files, self.context.deadline)
        require_time(self.context.deadline)
        _unchanged(self, original)
        _assert_observation(self.observation, self._observation_binding)

    @property
    def result_path(self) -> Path:
        """Retain the original immutable publication reference without selecting it."""
        return self.files[-1].path

    @property
    def result_sha256(self) -> str:
        """Expose only the original expected publication hash, never a newly read hash."""
        return self.files[-1].sha256


def _binding(value: CompletedProjectObservation) -> tuple:
    """Bind every exposed field and original owner before and after caller code."""
    return (_owned_binding(value._owned), id(value.observation), id(value.context), id(value.files),
            _scalar(value.phase_deadline), id(value._observation_binding), value._observation_binding,
            _scalar(value.executable), _scalar(value.grade_applicable), _scalar(value.delivery_approved))


def _unchanged(value: CompletedProjectObservation, original: tuple) -> None:
    """A callback cannot replace the seal or make an equal-valued new owner current."""
    if value._binding is not original or _binding(value) != original:
        raise RuntimeError("completed grade original owner, metadata or seal changed")


def _pending(owned: OwnedProjectObservation) -> CompletedProjectObservation:
    """Privately capture the live original references before any sealing callback."""
    value = object.__new__(CompletedProjectObservation)
    values = {"observation": owned.observation, "context": owned.context, "files": owned.files,
              "phase_deadline": owned.deadline, "_owned": owned,
              "_observation_binding": owned._observation_binding,
              "executable": False, "grade_applicable": False, "delivery_approved": False}
    for name, item in values.items():
        object.__setattr__(value, name, item)
    object.__setattr__(value, "_binding", _binding(value))
    return value


def seal_completed_project_observation(owned: OwnedProjectObservation) -> CompletedProjectObservation:
    """Seal only live successful publication; no callback or deadline can be replaced."""
    if type(owned) is not OwnedProjectObservation:
        raise ValueError("completed grade requires the actual returned owned observation")
    completed = _pending(owned)
    original = completed._binding
    owned.assert_current()
    _unchanged(completed, original)
    completed.assert_current()
    require_time(completed.phase_deadline)
    _unchanged(completed, original)
    return completed
