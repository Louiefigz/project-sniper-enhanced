"""Small immutable payloads shared by Desktop element mutation handlers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ElementObservation:
    """One verified Palmier mutation and its before/after readback."""

    state: dict
    pending: dict
    before: dict
    after: dict
    event: dict


@dataclass(frozen=True)
class RecoveryObservation:
    """Facts required to recover one missed PostToolUse receipt."""

    state: dict
    pending: dict
    before: dict
    after: dict
    client: Any
    media_ref: str | None = None
