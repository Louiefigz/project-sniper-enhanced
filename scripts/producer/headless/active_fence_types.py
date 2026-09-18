"""Closed data types for the non-authorizing active-fence primitive."""

from __future__ import annotations

from dataclasses import dataclass, field


class ActiveFenceError(RuntimeError):
    """The active-fence authority is absent, corrupt, or unsafe."""


class ActiveFenceConflictError(ActiveFenceError):
    """A reservation conflicts with the currently active attempt."""


@dataclass(frozen=True)
class ActiveFenceStateV1:
    """Canonical mutable fence state materialized at ``FENCE``."""

    authority_id: str
    fence_revision: int
    fence_token: str
    active_attempt_id: str | None
    document_json: bytes = field(repr=False)


@dataclass(frozen=True)
class ActiveFenceTransitionV1:
    """One validated frame in the authoritative transition journal."""

    event: str
    attempt_id: str | None
    state: ActiveFenceStateV1
    sequence: int
    prior_event_digest: str
    event_digest: str
    frame_json: bytes = field(repr=False)


@dataclass(frozen=True)
class ActiveFenceJournalScanV1:
    """Validated journal prefix plus an optional uncommitted final fragment."""

    transitions: tuple[ActiveFenceTransitionV1, ...]
    valid_bytes: int
    torn_bytes: int


@dataclass(frozen=True)
class ActiveFenceOperationResultV1:
    """Reservation outcome that grants no execution or publication authority."""

    operation: str
    state: ActiveFenceStateV1
    created: bool
    replayed: bool
    execution_authorized: bool = field(default=False, init=False)
    publication_authorized: bool = field(default=False, init=False)
    release_authorized: bool = field(default=False, init=False)
    current_advanced: bool = field(default=False, init=False)
    work_launched: bool = field(default=False, init=False)
