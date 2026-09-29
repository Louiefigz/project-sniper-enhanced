"""Review timing on the batch's own clock: when a batch-bound packet was resolved and when its record was submitted.

A critic's typed record claims normal-speed playback and listening; those claims must fit between the
packet's resolution and the submission. A packet's ``resolvedAt`` is written by its author and a file's
times can be moved (on APFS setting an earlier mtime also moves birthtime), so for a packet naming a
batch clip ``context.py --role`` records one small ``packet-resolved`` event in that batch's trail:
the packet's SHA-256, role and clip at the batch-clock elapsed seconds. The typed submission then records
one ``review-submitted`` event: the record's canonical SHA-256, role, clip and the batch-clock elapsed
seconds the record states as its submission (``submission.timing.submittedElapsed``). Every gate reader
and ``check-final`` require both: the record's timing must equal what the trail holds for its packet and
its own bytes, so a record edited after submission, or built by hand, finds no event of its own.

Admission of each event (both refused at the reserve, so they never eat the room settling events keep,
and bounded by ``EVENT_BYTES``):

- ``packet-resolved`` only while the batch is ``active``: a new review packet is new work, and a
  draining batch admits no new work (``NATIVE_SHORTS_DEADLINE_BATCH.md``).
- ``review-submitted`` while the batch is ``active`` or ``draining``: it closes a review whose packet was
  admitted while the batch was active, the way draining lets admitted work settle; refused once closed.
  The stated submission time must lie between the packet's recorded resolution and the batch clock now,
  and no approval change of the clip may be recorded after it (a review that read an approval the
  operator has since changed is refused, never recorded as current). An identical replay is a no-op.

Reading the trail back takes the batch lock and also works for a closed or archived batch (read-only
verification of an existing record). What this still cannot prove: that anyone watched or listened, or that a
submission was not deliberately delayed. It only bounds how early a record can claim to have finished,
and anyone able to run these commands can append an event (the trail is unkeyed).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from headless.durable_files import DurableFileError, read_private_file
from studio.native_budget_binding import advance_clock
from studio.native_budget_store import (
    EVENTS, MAX_EVENT_BYTES, BudgetAuthorityError, BatchSession, archived_directory, batch_directory, canonical,
    locked_batch, require_clip_id,
)
from studio.production.approvals import trail_events

PACKET_EVENT, REVIEW_EVENT = 'packet-resolved', 'review-submitted'
EVENT_BYTES = 512
ROLES = ('clip-owner', 'plan-critic', 'motion-critic', 'final-critic')
CRITICS = ROLES[1:]


@dataclass(frozen=True)
class ResolvedPacket:
    """One batch-bound role packet: the batch clip it names, its role and the SHA-256 of its exact bytes."""

    batch: str
    clip: str
    role: str
    sha256: str


@dataclass(frozen=True)
class SubmittedReview:
    """One typed record at submission: the packet it answers, its canonical SHA-256 and its stated batch-clock time."""

    packet: ResolvedPacket
    record_sha256: str
    elapsed: float


def _sha256(value: object, what: str) -> str:
    """A lowercase SHA-256 hex digest, or a refusal."""
    if type(value) is not str or len(value) != 64 or any(char not in '0123456789abcdef' for char in value):
        raise BudgetAuthorityError(f'{what} is named by its lowercase SHA-256')
    return value


def _trail(session: BatchSession, batch_id: str) -> list[dict]:
    """The committed events of the locked batch's trail."""
    try:
        raw = read_private_file(session.dir_fd, EVENTS, 2 * MAX_EVENT_BYTES)
    except (OSError, DurableFileError) as error:
        raise BudgetAuthorityError(f'Budget event trail for {batch_id} is unreadable: {error}') from error
    return trail_events(raw)


def _read(root: Path, batch_id: str) -> tuple[float, list[dict]]:
    """The batch clock now and the committed trail of a live or archived batch, read under its lock."""
    directory = batch_directory(root, batch_id)
    directory = directory if directory.is_dir() else archived_directory(root, batch_id)
    with locked_batch(root, batch_id, directory=directory) as session:
        record = session.read()
        return round(advance_clock(record), 3), _trail(session, batch_id)


def _open_record(session: BatchSession, packet: ResolvedPacket, statuses: tuple[str, ...]) -> dict:
    """The locked record, refused unless the batch is in one of ``statuses`` and holds the packet's clip."""
    if packet.role not in ROLES:
        raise BudgetAuthorityError(f'unknown packet role {packet.role!r}')
    record = session.read()
    if record['status'] not in statuses:
        work = 'no new review packet is admitted' if statuses == ('active',) else 'no review submission is recorded'
        raise BudgetAuthorityError(f'Batch {packet.batch} is {record["status"]}; {work}')
    if require_clip_id(packet.clip) not in record['clips']:
        raise BudgetAuthorityError(f'Clip {packet.clip} is not part of batch {packet.batch}')
    return record


def _append(session: BatchSession, event: dict) -> dict:
    """Write one bounded, non-settling event (refused once the trail reaches its reserve)."""
    if len(canonical(event)) > EVENT_BYTES:
        raise BudgetAuthorityError(f'a {event["event"]} event exceeds its size bound')
    session.event(event)
    return event


def record_packet_resolved(root: Path, packet: ResolvedPacket) -> dict:
    """Append one packet-resolved event on the batch clock of an active batch; returns the event."""
    sha256 = _sha256(packet.sha256, 'a resolved packet')
    with locked_batch(root, packet.batch) as session:
        record = _open_record(session, packet, ('active',))
        return _append(session, {'event': PACKET_EVENT, 'clipId': packet.clip, 'role': packet.role,
                                 'packetSha256': sha256, 'elapsed': round(advance_clock(record), 3)})


def _resolution(events: list[dict], batch_id: str, packet_sha256: str) -> dict:
    """The first recorded resolution of a packet, or a refusal."""
    rows = [row for row in events if row.get('event') == PACKET_EVENT and row.get('packetSha256') == packet_sha256]
    if not rows:
        raise BudgetAuthorityError(f'batch {batch_id} did not record the resolution of packet {packet_sha256[:12]}; '
                                   're-resolve it with context.py --role ... --batch --clip')
    return rows[0]


def packet_resolution(root: Path, batch_id: str, packet_sha256: str) -> dict:
    """{'clipId','role','resolvedElapsed','nowElapsed'} for a recorded packet, or a refusal (read only)."""
    wanted = _sha256(packet_sha256, 'a resolved packet')
    now, events = _read(root, batch_id)
    first = _resolution(events, batch_id, wanted)
    return {'clipId': first['clipId'], 'role': first['role'], 'resolvedElapsed': float(first['elapsed']),
            'nowElapsed': now}


def _submission_problem(record: dict, events: list[dict], review: SubmittedReview, now: float) -> str | None:
    """Why the stated submission cannot be recorded, or None."""
    packet, elapsed = review.packet, review.elapsed
    resolved = _resolution(events, packet.batch, packet.sha256)
    if (resolved['clipId'], resolved['role']) != (packet.clip, packet.role):
        return f'batch {packet.batch} recorded packet {packet.sha256[:12]} for another clip or role'
    if not float(resolved['elapsed']) <= elapsed <= now:
        return (f'the stated submission time {elapsed} s is not between the packet resolution '
                f'({resolved["elapsed"]} s) and the batch clock now ({now} s)')
    rows = record['clips'][packet.clip]['approvals']
    if rows and rows[-1]['elapsed'] > elapsed:
        return (f'the approved title or script of clip {packet.clip} changed at {round(rows[-1]["elapsed"], 3)} s, '
                f'after this review was checked at {elapsed} s; re-resolve the role packet and review again')
    return None


def _submitted(events: list[dict], record_sha256: str) -> list[dict]:
    """Every review-submitted event naming one record."""
    return [row for row in events if row.get('event') == REVIEW_EVENT and row.get('recordSha256') == record_sha256]


def _replayed(events: list[dict], event: dict) -> bool:
    """True for an identical replay of a recorded submission; a record recorded with other facts is refused."""
    earlier = _submitted(events, event['recordSha256'])
    if earlier and earlier != [event]:
        raise BudgetAuthorityError(f'record {event["recordSha256"][:12]} was already recorded with other facts')
    return bool(earlier)


def record_review_submitted(root: Path, review: SubmittedReview) -> dict:
    """Append one review-submitted event for a critic's record on an active or draining batch; returns the event."""
    packet = review.packet
    if packet.role not in CRITICS or type(review.elapsed) not in (int, float) or not math.isfinite(review.elapsed):
        raise BudgetAuthorityError('a review submission names a critic role and a finite batch-clock time')
    event = {'event': REVIEW_EVENT, 'clipId': packet.clip, 'role': packet.role,
             'recordSha256': _sha256(review.record_sha256, 'a submitted record'), 'elapsed': float(review.elapsed)}
    _sha256(packet.sha256, 'a resolved packet')
    with locked_batch(root, packet.batch) as session:
        record = _open_record(session, packet, ('active', 'draining'))
        events = _trail(session, packet.batch)
        if _replayed(events, event):
            return event
        problem = _submission_problem(record, events, review, round(advance_clock(record), 3))
        if problem:
            raise BudgetAuthorityError(f'Review submission not recorded: {problem}')
        return _append(session, event)


def review_submission(root: Path, batch_id: str, record_sha256: str) -> dict:
    """{'clipId','role','recordSha256','elapsed'} recorded for one record (any batch status, read only), or a refusal."""
    wanted = _sha256(record_sha256, 'a submitted record')
    rows = _submitted(_read(root, batch_id)[1], wanted)
    if len(rows) != 1:
        raise BudgetAuthorityError(f'batch {batch_id} did not record the submission of record {wanted[:12]}; a record '
                                   'is admitted only as the typed submission published it (submit it again)')
    return {'clipId': rows[0]['clipId'], 'role': rows[0]['role'], 'recordSha256': wanted,
            'elapsed': float(rows[0]['elapsed'])}
