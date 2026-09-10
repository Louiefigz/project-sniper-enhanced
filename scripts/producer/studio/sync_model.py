"""Shared shapes for the Studio sync-back lane (``studio_sync``).

``studio_sync`` diffs a Studio-edited review project against its generation
manifest and maps operator edits back into ``edit_plan.json``. These
dataclasses are the contract between ``slot_reader`` (parse),
``sync_diff``/``sync_files`` (compare), ``sync_apply`` (write) and the
``studio_sync`` CLI (report).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field


class StudioSyncError(RuntimeError):
    """The studio directory cannot be diffed or synced back to its plan."""


class StudioSyncGateFailure(StudioSyncError):
    """A gate rejected the updated plan (new failures only, baseline-diffed).

    ``failures`` are the blocking findings the operator's edit introduced —
    changed-entry template-contract violations plus plan_lint errors absent
    from the pre-apply baseline. ``preexisting`` are baseline lint errors the
    edit did not cause; they never block, only report.
    """

    def __init__(self, failures: list[str],
                 preexisting: list[str] | None = None) -> None:
        super().__init__("; ".join(failures))
        self.failures = failures
        self.preexisting = list(preexisting or [])


#: ``project_writer.sec()`` writes slot timing with <=4 decimals; every timing
#: comparison and write-back normalizes to the same precision.
ROUND_DECIMALS = 4


def t4(value: float) -> float:
    """Timing normalized to the slot attributes' 4-decimal precision."""
    return round(float(value), ROUND_DECIMALS)


@dataclass(frozen=True)
class FieldChange:
    """One ``data-variable-values`` key the operator changed in Studio."""

    key: str
    old: object
    new: object


@dataclass
class EntryDiff:
    """Operator-visible changes on one manifest-tracked slot."""

    index: int
    slot: str
    plan_id: str | None
    kind: str
    timing_old: tuple[float, float] | None = None
    timing_new: tuple[float, float] | None = None
    value_changes: list[FieldChange] = field(default_factory=list)
    new_spec: dict | None = None
    layout_notes: list[str] = field(default_factory=list)

    @property
    def plan_facing(self) -> bool:
        """Whether this diff writes anything into the plan on ``--apply``."""
        return self.timing_new is not None or self.new_spec is not None

    @property
    def label(self) -> str:
        """The entry's report identity: its plan id when bound, else slot."""
        return self.plan_id or self.slot


@dataclass(frozen=True)
class Deletion:
    """A manifest-tracked slot the operator removed in Studio."""

    index: int
    slot: str
    plan_id: str | None
    kind: str

    @property
    def label(self) -> str:
        return self.plan_id or self.slot


@dataclass
class SyncReport:
    """Everything one dry run found, bucketed by how apply treats it."""

    entry_diffs: list[EntryDiff] = field(default_factory=list)
    deletions: list[Deletion] = field(default_factory=list)
    #: Unsupported additions (new elements / files) — reported prominently,
    #: never written into the plan, never fatal on their own.
    additions: list[str] = field(default_factory=list)
    #: File-level findings (instance comps, sidecars) — warnings, not fatal.
    file_notes: list[str] = field(default_factory=list)
    informational: list[str] = field(default_factory=list)
    #: Conditions that refuse ``--apply`` outright.
    blockers: list[str] = field(default_factory=list)

    @property
    def plan_changes(self) -> bool:
        """Whether apply would modify ``edit_plan.json`` at all."""
        return bool(self.deletions
                    or any(d.plan_facing for d in self.entry_diffs))

    @property
    def clean(self) -> bool:
        """Nothing to report: the view still matches its generation state."""
        return not (self.entry_diffs or self.deletions or self.additions
                    or self.file_notes or self.blockers)

    def to_json(self) -> dict:
        """JSON-safe view of the report for ``--json`` output."""
        return {
            "clean": self.clean,
            "planChanges": self.plan_changes,
            "entries": [dataclasses.asdict(d) for d in self.entry_diffs],
            "deletions": [dataclasses.asdict(d) for d in self.deletions],
            "unsupportedAdditions": list(self.additions),
            "fileNotes": list(self.file_notes),
            "informational": list(self.informational),
            "blockers": list(self.blockers),
        }
