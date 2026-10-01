"""The budget event trail's bound, its terminal reserve and its settling classes (split from ``native_budget_store``
at P1-RP5, X217 M1; the store re-exports every name here).

New work stops ``TERMINAL_RESERVE_BYTES`` below ``MAX_EVENT_BYTES``, at 15 MiB. Past that point only settling lines
(``terminal``) are written, so a full trail can refuse new work but never keep a batch open, strand a cancellation
or lose a task outcome. ``tests/test_trail_reserve_budget`` holds the reserve to that: its classes are
``TERMINAL_EVENTS`` plus the abandoning ``observed`` line, every class must have a worst case past the stop, and
their sum must fit the reserve.

The worst cases count transitions. Past the stop no claim, launch, owner row, task or clip can begin (each begins
with a line that is not a settling line, which the trail refuses), so every settling line settles something that
existed at the stop, a bounded number of times. A transition whose record replace fails leaves the record unchanged,
with its line and a ``commit-failed`` line on the trail. The reserve holds one such failure for each automatic
writer that never repeats a written line: a checkpoint (X190 n6) and an abandoned launch (X217 m3). It does not hold
an operator's or a process's repeated attempts under a persistent replace failure; the authority is then unwritable
and refuses new work anyway (``BudgetAuthorityError``).
"""
from __future__ import annotations

# New work stops TERMINAL_RESERVE_BYTES below the bound, so every settling line fits inside it. Counted at every
# writer of every terminal class (X217 M1), the worst case past the stop is ~10.6 MiB (test_trail_reserve_budget),
# so the reserve was raised from 4 to 12 MiB and the bound from 19 to 27 MiB with it: new work keeps its 15 MiB.
MAX_EVENT_BYTES = 27 * 1024 ** 2
TERMINAL_RESERVE_BYTES = 12 * 1024 ** 2
# A commit-failed line's error: at most this many characters of the failure's ASCII escape (``error_text``).
ERROR_TEXT_CHARS = 96
# Outcomes, closing, draining, hand-offs and task settlement are bounded by the record's own
# row bounds (each task acknowledges, ends and settles a bounded number of times, and a new
# claim is not a settling event), so they are always written: a full trail can refuse new
# work but never keep a batch open, strand a cancellation or lose a task outcome.
# ``commit-unsynced`` is not one (X217 M1): its commit stands with or without its line (``approvals.trail_events``
# drops only an event followed by ``commit-failed``), so past the stop it is not written.
TERMINAL_EVENTS = frozenset({'batch-closed', 'batch-draining', 'launch-completed', 'clip-handed-off',
                             'batch-archived', 'commit-failed', 'task-attached',
                             'task-released', 'task-completed', 'task-failed', 'task-cancel-requested',
                             'task-cancelled', 'task-abandoned', 'task-superseded', 'task-resource-settled',
                             # A task's settling event (task-*, tasks-reconciled) carries capacitySettled (X189 F2):
                             # one entry per Short whose owner rows it removed, <= MAX_WORKERS (64) 16-hex owner
                             # digests (~1.3 KB); a task's owners serve its own Short and settle once, so <=
                             # BOUNDS['tasks'] (256) entries per batch (queue_audit.settlement_entry). An owner's
                             # end (capacity-settled) names owners by digest too (queue_authority._settled_line).
                             'tasks-reconciled', 'capacity-settled',
                             # Bound (X183 m5): <= MAX_CHECKPOINTS (32) per Short x BOUNDS['clips'] (32) events,
                             # each written only within queue_authority.CHECKPOINT_EVENT_BYTES (512 B) as canonical()
                             # encodes it: 512 KiB of TERMINAL_RESERVE_BYTES (queue_authority._checkpoint_due).
                             'capacity-checkpoint',
                             # X184 MAJOR: the operator's one stall decision, at most one per Short (decide refuses
                             # a second), so <= BOUNDS['clips'] rows; a close may need it (X19), so it always writes.
                             'capacity-stall-decided'})
# Commits that write the record without a trail line: a same-state heartbeat, and an observation that marked nothing
# at a full trail (X189 F1: native_budget_status.commit_observation).
RECORD_ONLY = frozenset({'capacity-heartbeat', 'observed-record-only'})
# Commits that the settlement room never refuses: settlements, and read-only observations (status and
# wait advance the clock and mark provably dead launches abandoned, which the room already covers).
ROOM_EXEMPT = TERMINAL_EVENTS | RECORD_ONLY | {'observed', 'capacity-observed'}


def terminal(value: dict) -> bool:
    """A settling line, always written: a ``TERMINAL_EVENTS`` member, or an observation that marked dead launches
    abandoned (G9, X190 F1): a launch outcome, at most one per attempt (BOUNDS['attempts'] per Short, X217 m3)."""
    return value.get('event') in TERMINAL_EVENTS or (value.get('event') == 'observed' and bool(value.get('abandoned')))


def error_text(error: BaseException) -> str:
    """A failure's text for its ``commit-failed`` line: escaped to printable ASCII and cut to ``ERROR_TEXT_CHARS``,
    so the line is bounded whatever the error says (X217 M1)."""
    return str(error).encode('unicode_escape').decode('ascii')[:ERROR_TEXT_CHARS]
