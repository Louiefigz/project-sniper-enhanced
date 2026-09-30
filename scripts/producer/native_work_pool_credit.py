"""Which pool waits earn Short credit: only waits for occupied, eligible slots (C5).

native_work_pool.decide groups every waitable reason by its source (ReasonGroups) and calls
classify, which only annotates decision.context. It never adds, removes or reorders a reason, so
no admission decision depends on it; native_queue_accounting reads capacityOnly through the
refusal (native_work_pool_fence.refusal copies the context into capacity_evidence).

The rule, stated by the operator: "credit only waits for occupied, eligible slots; queue-order
and quarantine waits are not credited". A wait is credited only when the capacity this request
is eligible for is occupied by live work:
- live (not quarantined) occupancy of its lane is at capacity (liveFull);
- a live exclusive or outside-profile member holds the pool (a mix wait, P1 M1); or
- live old-code exclusive work runs (the legacy reason).
Given that, the slot, FIFO ('queued behind N') and memory reasons are the same wait seen three
ways and are credited with it. Without it none of them is: a FIFO-only wait (queue order while
live slots are free, for example behind an older request that waits for disk, or while the pool
drains for a queued exclusive Long), a quarantine-only wait (slots whose cleanup is unverified)
and a memory wait while live slots are free. A disk reason and the qualification-session reason
are never credited, and neither is a terminal or unsupported refusal or any class but 'heavy'.

Context keys: liveOccupied, liveFull, occupants (at most MAX_OCCUPANTS sorted nonces: the live
members consuming the needed capacity plus the live mix blockers), occupantsTruncated, waitClass
('capacity' when credited, 'other' for any other wait, None when nothing waits) and capacityOnly.
"""
from __future__ import annotations

from dataclasses import dataclass

MAX_OCCUPANTS = 8


@dataclass(frozen=True)
class ReasonGroups:
    """One decision's waitable reasons, grouped by the source that added them.

    Attributes:
        slot: The slot reason ('all N <class> slot(s) are occupied').
        memory: The aggregate memory budget reason.
        mix: Waits beside a live exclusive or outside-profile member (P1 M1).
        fifo: The queue-order reason ('queued behind N earlier request(s)').
        legacy: Live old-code exclusive heavy work.
        other: Reasons never credited: disk headroom and the qualification session.
        blockers: Nonces of the live members behind the mix reasons.
    """

    slot: tuple[str, ...] = ()
    memory: tuple[str, ...] = ()
    mix: tuple[str, ...] = ()
    fifo: tuple[str, ...] = ()
    legacy: tuple[str, ...] = ()
    other: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()


def _credited(decision: object, full: bool, groups: ReasonGroups) -> bool:
    """A heavy wait on live occupied capacity, with no uncredited reason and no refusal."""
    occupied_by_live_work = full or bool(groups.mix) or bool(groups.legacy)
    return (decision.lane == 'heavy' and bool(decision.reasons) and occupied_by_live_work
            and not groups.other and not decision.terminal and not decision.unsupported)


def classify(decision: object, rows: list[dict], groups: ReasonGroups) -> None:
    """Record the live occupancy behind one decision and whether its wait is credited.

    Args:
        decision: The native_work_pool.Decision; its reasons, terminal and unsupported lists are
            final and its context holds 'capacity' (native_work_pool._slot_reasons).
        rows: The charged member rows that consume the capacity this request needs
            (native_work_pool._occupancy): each has 'nonce' and 'quarantined'.
        groups: The decision's waitable reasons by source.
    """
    live = [row['nonce'] for row in rows if not row['quarantined']]
    full = len(live) >= decision.context['capacity']
    occupants = sorted({*live, *groups.blockers})
    credited = _credited(decision, full, groups)
    decision.context.update(liveOccupied=len(live), liveFull=full, occupants=occupants[:MAX_OCCUPANTS],
                            occupantsTruncated=len(occupants) > MAX_OCCUPANTS, capacityOnly=credited,
                            waitClass='capacity' if credited else 'other' if decision.reasons else None)
