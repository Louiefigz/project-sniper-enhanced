"""A plan critic's early findings on the batch clock (P2-11): ``review-early-findings`` events, closed by its final.

A plan critic submits each material issue as soon as it has it (``native-review.ts submit-prebuild-early``), so the
coordinator can route a repair while one can still help. The authority records one small event per early record:
the packet's SHA-256, the SHA-256 and count of its material issues and the record's index, at the batch-clock time
the record states. The event carries no verdict and admits nothing. Built on the event helpers of
``studio.production.packets`` (extracted from it for its line budget).

Admission (each condition refused by name; an identical replay is a no-op):

- the batch is ``active`` or ``draining`` and holds the clip; the packet is a plan critic's, and the batch recorded
  its resolution for this clip and role;
- the stated time lies between that resolution and the batch clock now, and no approval change of the clip is
  recorded after it (as for ``review-submitted``);
- indexes 1-3, each once, in order;
- **no final review of the packet is recorded yet**: once a ``review-submitted`` event names the packet
  (``packetSha256``, P2-11's plan fields), its early findings are closed, so every early code is one the final had
  to account for (M-090/M-091 route on this).

Like ``packet-resolved`` and ``review-submitted`` the event is not a settling event: the trail's reserve refuses it,
so it never takes the room settling events keep. At most three per packet.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from studio.native_budget_binding import advance_clock
from studio.native_budget_store import BatchSession, BudgetAuthorityError, locked_batch
from studio.production.packets import (
    PLAN_CRITIC, REVIEW_EVENT, ResolvedPacket, _append, _finite, _open_record, _read, _resolution, _sha256, _trail,
)

EARLY_EVENT = 'review-early-findings'
MAX_EARLY_FINDINGS, MAX_EARLY_ISSUES = 3, 16


@dataclass(frozen=True)
class EarlyFindings:
    """One early-findings record of a plan-critic packet: its issues' SHA-256 and count, index and batch-clock time."""

    packet: ResolvedPacket
    issues_sha256: str
    issues: int
    index: int
    elapsed: float


def early_rows(events: list[dict], packet_sha256: str) -> list[dict]:
    """The recorded early-findings events of one packet, in trail order."""
    return [row for row in events if row.get('event') == EARLY_EVENT and row.get('packetSha256') == packet_sha256]


def _closed(events: list[dict], packet: ResolvedPacket) -> str | None:
    """Why the packet's early findings are closed (its final review is recorded), or None."""
    finals = [row for row in events if row.get('event') == REVIEW_EVENT and row.get('packetSha256') == packet.sha256]
    if not finals:
        return None
    return (f'the final plan review of packet {packet.sha256[:12]} was recorded at {finals[0].get("elapsed")} s; '
            'its early findings are closed (put further issues in a new review)')


def _early_problem(record: dict, events: list[dict], early: EarlyFindings, now: float) -> str | None:
    """Why this early record cannot be recorded, or None."""
    packet, recorded = early.packet, len(early_rows(events, early.packet.sha256))
    resolved = _resolution(events, packet.batch, packet.sha256)
    if (resolved['clipId'], resolved['role']) != (packet.clip, packet.role):
        return f'batch {packet.batch} recorded packet {packet.sha256[:12]} for another clip or role'
    if not float(resolved['elapsed']) <= early.elapsed <= now:
        return (f'the stated time {early.elapsed} s is not between the packet resolution ({resolved["elapsed"]} s) '
                f'and the batch clock now ({now} s)')
    rows = record['clips'][packet.clip]['approvals']
    if rows and rows[-1]['elapsed'] > early.elapsed:
        return (f'the approved title or script of clip {packet.clip} changed at {round(rows[-1]["elapsed"], 3)} s, '
                f'after this early record states {early.elapsed} s; re-resolve the role packet')
    if early.index != recorded + 1:
        return (f'early record {early.index} of packet {packet.sha256[:12]} follows {recorded} recorded early '
                f'record(s); at most {MAX_EARLY_FINDINGS}, each index once and in order')
    return _closed(events, packet)


def _early_event(early: EarlyFindings) -> dict:
    """The event of one well-formed early record, or a refusal."""
    packet, counted = early.packet, type(early.issues) is int and 1 <= early.issues <= MAX_EARLY_ISSUES
    if packet.role != PLAN_CRITIC or not counted or type(early.index) is not int \
            or not 1 <= early.index <= MAX_EARLY_FINDINGS or not _finite(early.elapsed):
        raise BudgetAuthorityError(f'an early-findings record belongs to a plan-critic packet: 1-{MAX_EARLY_ISSUES} '
                                   f'issues, index 1-{MAX_EARLY_FINDINGS} and a finite batch-clock time')
    return {'event': EARLY_EVENT, 'clipId': packet.clip, 'role': packet.role, 'index': early.index,
            'packetSha256': _sha256(packet.sha256, 'a resolved packet'), 'issues': early.issues,
            'issuesSha256': _sha256(early.issues_sha256, 'the early material issues'), 'elapsed': float(early.elapsed)}


def _replayed(events: list[dict], event: dict) -> bool:
    """True for an identical replay of a recorded early record."""
    return [row for row in early_rows(events, event['packetSha256']) if row['index'] == event['index']] == [event]


def _record(session: BatchSession, early: EarlyFindings, event: dict) -> dict:
    """Inside the batch lock: the recorded event, an identical replay, or a refusal."""
    record = _open_record(session, early.packet, ('active', 'draining'))
    events = _trail(session, early.packet.batch)
    if _replayed(events, event):
        return event
    problem = _early_problem(record, events, early, round(advance_clock(record), 3))
    if problem:
        raise BudgetAuthorityError(f'Early findings not recorded: {problem}')
    return _append(session, event)


def record_early_findings(root: Path, early: EarlyFindings) -> dict:
    """Append one review-early-findings event for a plan-critic packet on an active or draining batch."""
    event = _early_event(early)
    with locked_batch(root, early.packet.batch) as session:
        return _record(session, early, event)


def early_findings(root: Path, batch_id: str, packet_sha256: str) -> list[dict]:
    """[{index, issuesSha256, issues, elapsed}] recorded for one packet (any batch status, read only)."""
    wanted = _sha256(packet_sha256, 'a resolved packet')
    return [{key: row[key] for key in ('index', 'issuesSha256', 'issues', 'elapsed')}
            for row in early_rows(_read(root, batch_id)[1], wanted)]
