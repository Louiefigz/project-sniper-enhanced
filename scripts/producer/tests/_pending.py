"""Owned expected failures (MASTER-PLAN X38; P0 Step 6.0).

``@pending(owner, reason)`` marks a restored donor test that cannot pass until the named area (P1–P6) lands its
change. It applies ``unittest.expectedFailure``, so the suite stays green while the behaviour is missing and turns
red (an unexpected success) the moment the owner's fix lands, which forces the owner to remove the marker.
Every marker is also listed in the durable registry ``master-plan-2026-09-28/evidence/pending.json``, written by
``p0-records/bin/pending_registry.py`` from a static scan of the tests. A marker still present when the
qualification candidate is cut is a blocker (X38), never a silent expected failure.
"""
from __future__ import annotations

import unittest
from typing import Callable, TypeVar

OWNERS: tuple[str, ...] = ('P1', 'P2', 'P3a', 'P3b', 'P4', 'P5', 'P6')
PENDING: dict[str, tuple[str, str]] = {}
T = TypeVar('T')


def pending(owner: str, reason: str) -> Callable[[T], T]:
    """Mark one test method as an owned expected failure; an unknown owner or empty reason is refused."""
    if owner not in OWNERS or not isinstance(reason, str) or not reason.strip():
        raise ValueError('pending() needs an owner in P1..P6 and a reason')

    def mark(method: T) -> T:
        """Register the method under its qualified name and wrap it as an expected failure."""
        PENDING[f'{method.__module__}.{method.__qualname__}'] = (owner, reason)
        return unittest.expectedFailure(method)
    return mark
