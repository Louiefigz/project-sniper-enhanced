"""The 'studio' pool class: a finished Short's Studio view opens while other Shorts render (C1).

A Studio server is one small Node process that renders nothing. Its startup
(studio/managed_preview_launch.launch) is admitted under the same ledger lock, tickets, memory
budget and disk accounting as every member, but in its own capacity:
- STUDIO_SLOTS slots counted over Studio members only. A quarantined Studio member (an attempted,
  unverified startup) keeps its slot; once every slot is quarantined the open is refused by name
  until native_work_recovery.py <nonce> recovers one. A render slot is never taken or quarantined.
- Memory against the aggregate budget with every member charged; disk admission in its own space.
- The legacy-exclusive and qualification-session reasons, both waitable.
- FIFO among Studio tickets only; a Studio ticket is never ahead of a render request
  (native_work_pool_mix.fifo_reasons).
It is never exclusive, never a mix problem, never fenced and never credited (capacityOnly False).
Render requests in qualified mode never count Studio members as occupancy
(native_work_pool._occupancy counts their own class); an exclusive request needs an idle pool, so it
still waits the seconds a startup takes. The Studio figures are provisional
(native_work_pool_policy.STUDIO_*) and outside policy_identity().
Rollout (X107 M1): the base 4a15560 pool client reads a Studio member, an unknown class, as
quarantined even while it is live, so its own admission is refused as quarantined for the seconds a
Studio start runs (fail closed: nothing over-commits; test_native_work_pool_liveness pins it). The
72de76f3-generation client charges it maximally and waits. Neither can recover a quarantined Studio
member (this engine's native_work_recovery.py can). Do not upgrade while old-engine batches run.
"""
from __future__ import annotations

import native_work_pool as pool
import native_work_pool_credit as credit
import native_work_pool_mix as mix
import native_work_pool_state as state
from native_work_pool_policy import STUDIO_CLASS, STUDIO_DISK_BYTES, STUDIO_RESERVATION_BYTES, STUDIO_SLOTS, PoolMode

MODE = 'studio'


def mode() -> PoolMode:
    """The capacity rule of every Studio request: STUDIO_SLOTS slots of its own class, never exclusive."""
    return PoolMode(MODE, {STUDIO_CLASS: STUDIO_SLOTS})


def decide(view: state.PoolView, request: pool.PoolRequest, host: dict) -> pool.Decision:
    """Apply Studio slots, aggregate memory, shared disk and Studio queue order to one Studio request.

    Args:
        view: This ledger transaction's observation.
        request: A request of class STUDIO_CLASS holding its ticket.
        host: This host's identity (memsizeBytes).

    Returns:
        The decision; the member reserves and is charged STUDIO_RESERVATION_BYTES of memory.
    """
    physical = host['memsizeBytes']
    rows = pool._member_charges(view, physical)
    studio = mode()
    size = request.disk_bytes if request.disk_bytes is not None else STUDIO_DISK_BYTES
    decision = pool.Decision(studio, STUDIO_RESERVATION_BYTES, size, 0, charge=STUDIO_RESERVATION_BYTES,
                             lane=STUDIO_CLASS)
    groups = pool._reason_groups(view, request, decision, (mix.session_of(view, host), rows, physical))
    fifo = mix.fifo_reasons(view, request, studio, (None, None, False))  # Studio tickets only
    decision.reasons += fifo
    credit.classify(decision, pool._occupancy(rows, studio, STUDIO_CLASS),
                    credit.ReasonGroups(fifo=tuple(fifo), **groups))
    decision.context['ticket'] = request.sequence
    return decision
