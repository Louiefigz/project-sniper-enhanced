"""Exact caller phase cutoffs for preclaimed source observation.

The original launch owner is never rebuilt or given a fresh lifetime. This
small context carries a narrower absolute caller phase through scheduling and
setup delays; its type and private binding are not project/resource authority.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from color.deadline import require_time
from headless.grade_launch_intent import OwnedGradeLaunch


@dataclass(frozen=True)
class OwnedGradePhase:
    """Carry the SAME launch owner plus the caller's already-running phase end."""

    owner: OwnedGradeLaunch
    deadline: float
    _original: tuple = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Capture original owner and numeric types before any callback or IO."""
        if type(self.owner) is not OwnedGradeLaunch or self.owner.binding() != self.owner._original \
                or type(self.deadline) not in (int, float) or not math.isfinite(self.deadline) \
                or self.deadline > self.owner.deadline:
            raise ValueError("owned grade phase must retain its original owner and narrower cutoff")
        object.__setattr__(self, "_original", self.binding())

    def binding(self) -> tuple:
        """Bind identity and exact scalar types without invoking the owner's callback."""
        if type(self.owner) is not OwnedGradeLaunch:
            raise RuntimeError("owned grade phase original owner changed")
        return (id(self.owner), id(self.owner._original), self.owner.binding(), type(self.deadline), self.deadline)

    def check(self) -> None:
        """Keep the caller's original phase and owner unchanged; never renew either."""
        original = self._original
        if self.binding() != original or self.owner.binding() != self.owner._original:
            raise RuntimeError("owned grade phase original binding changed")
        require_time(self.deadline)
        if self._original is not original or self.binding() != original:
            raise RuntimeError("owned grade phase original binding changed")


def select_grade_phase(value: OwnedGradeLaunch | OwnedGradePhase, entry: float,
                       maximum: int) -> tuple[OwnedGradePhase, float]:
    """Preserve explicit caller phase and cap from entry for historical owned calls."""
    if type(value) is OwnedGradeLaunch:
        phase = OwnedGradePhase(value, min(value.deadline, entry + maximum))
    elif type(value) is OwnedGradePhase:
        phase = value
    else:
        raise ValueError("owned grade launch requires its actual original context")
    phase.check()
    return phase, min(phase.deadline, entry + maximum)
