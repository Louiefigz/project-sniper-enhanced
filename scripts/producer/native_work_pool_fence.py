"""Compatibility fence between pool clients of different generations.

Every ticket and member record this client writes carries poolClient
(native_work_pool_lease.POOL_CLIENT). Older pooled clients (the base 4a15560 pool and
anything else without the marker) read only a member's class, scalar memory reservation
and one root-filesystem disk reservation, keyed by device. They cannot see that a member
must run alone (exclusive mode), that it was admitted under a schema-2 profile whose mix
they would break, that it reserves disk on another filesystem (E2 expansion,
native_work_pool_expand.off_root_fence), or that its disk comes from an APFS container
whose other volumes they charge separately (native_work_pool_disk.fence_reasons). A member whose
guarantee depends on such state holds a fence: one live ticket per pool class, marked
'fence', with sequence 0 (native_work_pool_lease.FENCE_SEQUENCE). An older client counts
it as an earlier request of its own class (its _fifo_reasons compares sequences), so no
older client is admitted while any fence is held. New clients read the fenced state
directly and skip fence tickets, and a fenced request skips older clients' request tickets
in its own queue order (native_work_pool_mix.fifo_reasons): those requests wait behind its
fence anyway, and counting them would deadlock (the new request waiting for an older one
that waits for the new request's fence). The pre-pool exclusive mutex (heavy.lock) stays
excluded by every member's shared heavy.lock.

Trade-off, stated plainly: new fenced work keeps overlapping while older clients wait. An
older request queued behind fences is admitted only once no fence is held; if new fenced
work keeps arriving it waits until its own capacity wait expires and fails with its own
error. Retire older installs before running clocked batches on the same host.

Only older clients that read a valid schema-1 host record run qualified and can join
another member; without one they are exclusive and wait for an idle pool, so no fence is
taken (native_work_qualification.Committed.legacy_qualified). A request that needs a fence
takes it on its first transaction and keeps it while it waits. The fence is removed by
complete(), released by close() or withdraw(). When a fenced supervisor dies its locks are
released, but every fenced member's record charges the whole memory budget (reservationBytes;
fence_member raises it before fencing at expansion), so older clients stay out, refused as
quarantined, until native_work_recovery.py recovers it. While any fenced member of this client
exists, live or quarantined, older clients do not start. Whether a member is fenced is
decided at its admission (and, for off-root disk, at that expansion).
"""
from __future__ import annotations

import json
import os

import native_work_pool_policy as policy
import native_work_pool_state as state
import native_work_qualification as qualification
from headless.durable_files import write_all
from native_work_lease import NativeWorkBusy
from native_work_pool_state import NativeWorkQuarantined, NativeWorkQueued
from native_work_pool_lease import POOL_CLIENT, Ticket, publish_ticket
from native_work_pool_policy import POOL_CLASSES, PoolMode


class NativeWorkUnsupportedMix(NativeWorkBusy):
    """The request cannot share the host with the pool work present; waiting is not offered."""


def is_current(record: object) -> bool:
    """Written by this client generation (older clients write no marker)."""
    return isinstance(record, dict) and record.get('poolClient') == POOL_CLIENT


def is_fence(record: object) -> bool:
    """A fence ticket, not a request."""
    return isinstance(record, dict) and isinstance(record.get('fence'), dict)


def request_tickets(view: state.PoolView) -> list[dict]:
    """Live request tickets; fence tickets are not requests."""
    return [ticket for ticket in view.tickets if not is_fence(ticket['record'])]


def reasons_for(mode: PoolMode, requested: tuple[str, ...]) -> list[str]:
    """Why a member with this mode needs a fence: exclusive, schema-2 mix, or caller reasons."""
    reasons = ['an exclusive member runs alone'] if mode.exclusive else []
    record = mode.record or {}
    if mode.name == 'qualified' and not record.get('legacy'):
        reasons.append(f"schema-2 profile {record.get('profile')} admits only the mix it exercised")
    return reasons + list(requested)


def _fields(owner: dict, lane: str, reasons: list[str]) -> dict:
    """A fence ticket's record: the owner's paths, one pool class and the reasons."""
    return {'class': lane, 'project': owner['project'], 'root': owner.get('root'), 'receipt': owner.get('receipt'),
            'workload': None, 'fence': {'reasons': list(reasons), 'owner': owner.get('nonce')}}


def take(namespace: state.Namespace, view: state.PoolView, owner: dict, reasons: list[str]) -> list[Ticket]:
    """Publish and lock one fence ticket per pool class inside the current ledger transaction.

    All or none: if a later ticket fails to publish, those already published are closed and
    removed before the error propagates, so no stray fence stays held until the process exits.
    """
    tickets: list[Ticket] = []
    try:
        for lane in POOL_CLASSES:
            tickets.append(publish_ticket(namespace, view, _fields(owner, lane, reasons)))
    except BaseException:
        _discard(namespace, tickets)
        raise
    return tickets


def _discard(namespace: state.Namespace, tickets: list[Ticket]) -> None:
    """Close and remove fence tickets published by a failed take (the caller holds the ledger)."""
    for ticket in tickets:
        ticket.withdraw()
        try:
            os.unlink(ticket.name, dir_fd=namespace.pool_fd)
        except FileNotFoundError:
            continue


def fence_member(namespace: state.Namespace, view: state.PoolView, lease: object, reasons: list[str]) -> None:
    """Fence a running member before it reserves state older clients cannot see (E2 expansion).

    The member's recorded charge is raised to the whole memory budget first (durably), so an
    older client stays out even if this supervisor dies and its fence tickets lapse. An older
    request already queued stays queued behind the new fence; nothing is refused here.

    Args:
        namespace: The open ledger namespace (the caller holds the ledger lock).
        view: This transaction's observation.
        lease: The caller's own live PoolLease.
        reasons: What the member is about to hold that older clients cannot account.
    """
    if lease.fence:
        return
    host = policy.host_identity()
    if not qualification.committed(host).legacy_qualified:
        return
    lease.adopt_charge(policy.aggregate_bytes(host['memsizeBytes']))
    lease.fence = take(namespace, view, lease.record, reasons)


def rewrite_ticket(ticket: Ticket, record: dict) -> None:
    """Rewrite a held ticket in place, so its lock stays on the same inode (the caller holds the ledger)."""
    os.ftruncate(ticket.fd, 0)
    os.lseek(ticket.fd, 0, os.SEEK_SET)
    write_all(ticket.fd, (json.dumps(record, sort_keys=True) + '\n').encode())
    os.fsync(ticket.fd)


def refresh_ticket(namespace: state.Namespace, ticket: Ticket, workload: dict) -> None:
    """Rewrite a held request ticket's workload in place (its engine became known later)."""
    record = state.read_json(namespace.pool_fd, ticket.name)
    if not isinstance(record, dict) or record.get('workload') == workload:
        return
    rewrite_ticket(ticket, dict(record, workload=workload))


def refusal(lane: str, decision: object) -> NativeWorkBusy:
    """Keep legacy wording: only 'already active' refusals are worth waiting for."""
    if decision.unsupported:
        return NativeWorkUnsupportedMix(
            f'Native {lane} work cannot join the pool work present: ' + '; '.join(decision.unsupported)
            + '; no qualification profile covers this mix, so no SLA is promised: run it on an idle pool '
            'or qualify a profile that covers it')
    if decision.terminal:
        return NativeWorkQuarantined(f'Native {lane} cleanup is unverified or capacity is quarantined: '
                                     + '; '.join(decision.terminal)
                                     + '; inspect and recover with native_work_recovery.py <nonce>')
    error = NativeWorkQueued(f'Native {lane} work is already active: ' + '; '.join(decision.reasons))
    error.capacity_only = decision.context.get('capacityOnly', False)
    error.capacity_evidence = dict(decision.context)
    return error
