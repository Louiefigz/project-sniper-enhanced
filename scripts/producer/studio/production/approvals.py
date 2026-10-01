"""Approved titles and scripts: added-clip binding, typed operator changes, and the single reader.

The approval bound at start (or when a clip is added) and every later operator change form one
chain per clip: each row names its predecessor's identity (``previous``, checked on every
read), each change writes an ``approval-changed`` event naming the old and new identities and the
operator's reason (kept in the new row too), the
authorization identity is written in ``batch-started`` and an added clip's first approval in
``clip-added`` (or, for an own-clock or derived output, ``output-authorized``). ``read_approval`` cross-checks the chain against the event trail and refuses a
mismatch as corrupt authority. An event the record never took (its writer was killed between the
append and the record replacement) counts as uncommitted, like one followed by ``commit-failed``,
so a retried change or add heals (``committed_changes``). The hashes are unkeyed: they detect an
inconsistent edit, not a forger who rewrites the record, its chain and its trail together; for the
same reason dropping the latest approval from the record looks exactly like a killed change.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from headless.durable_files import DurableFileError, read_private_file
from studio.native_budget_binding import advance_clock
from studio.native_budget_policy import Approval, admit_new_clip, change_approval, clip_record
from studio.native_budget_registry import owner_binding
from studio.native_budget_selection import CANONICAL_FORM
from studio.native_budget_store import (
    EVENTS, MAX_EVENT_BYTES, BatchSession, BudgetAuthorityError, TrailFull, archived_directory, batch_directory,
    locked_batch,
)
from studio.production.claims import Outcome
from studio.production.dependencies import refresh
from studio.production.duplication_check import ADDING_EVENTS, pending_decisions, pending_report, recorded_checks
from studio.production.host_contract import clip_text, encoded_length
from studio.production.outputs import OutputAuthorization, authorize_output, same_job
from studio.production.session import transact
from studio.production.tasks import TaskRefused

REASON_BYTES = 512
ADDED_REASON = 'approved title and script bound when the clip was added; its own clock starts here'


@dataclass(frozen=True)
class AddedClip:
    """A clip added after start: why, and its approved title and script (bound as it is added)."""

    reason: str
    approval: Approval


def add_clip(root: Path, batch_id: str, clip_id: str, added: AddedClip) -> dict:
    """Add a Short with its approved title and script bound; its own 40 counted minutes start now (C8).

    The clip is authorized as its own output (``outputs.authorize_output``): the forecast admits or refuses it by
    name at any minute, the same job is refused by name, and an identical retry is a replay that commits nothing.
    The answer's ``duplicationCheck`` is always the recorded one (``recorded_duplication``, X144).
    """
    def operation(record: dict, elapsed: float) -> Outcome:
        """Authorize the clip on its own clock and bind its approval in one commit."""
        refusal = _add_refusal(record, clip_id, added, elapsed)
        if refusal:
            raise TaskRefused(refusal)
        request = OutputAuthorization(clip_id, 'short', clip_text(added.reason), added.approval.recorded_by,
                                      approval=added.approval)
        result = authorize_output(record, request, elapsed)
        row = record['clips'][clip_id]['approvals'][0]
        if result['replayed']:                          # nothing is written; the recorded check is read back below
            return Outcome(False, {}, {**result, 'approval': row})
        row['reason'] = ADDED_REASON
        event = {'event': 'clip-added', 'clipId': clip_id, 'reason': clip_text(added.reason),
                 'approval': row['identity'], 'authorizedElapsed': result['output']['authorizedElapsed'],
                 'duplicationCheck': result.pop('duplicationCheck')}
        return Outcome(True, event, {**result, 'approval': row})
    done = transact(root, batch_id, operation)
    return {**done, **recorded_duplication(root, batch_id, clip_id)}


def _add_refusal(record: dict, clip_id: str, added: AddedClip, elapsed: float) -> str | None:
    """A new clip id passes ``admit_new_clip`` (an existing one is ``authorize_output``'s replay or conflict), and
    the addition records its reason."""
    decision = admit_new_clip(record, clip_id, elapsed) if clip_id not in record['clips'] else None
    if decision is not None and not decision.allowed:
        return decision.reason
    if type(added.reason) is not str or not added.reason.strip():
        return 'Adding a clip records its reason'
    return None


def recorded_duplication(root: Path, batch_id: str, clip_id: str) -> dict:
    """After an add or authorization (a replay too): the clip's recorded check, and the owed decision lines written.

    ``duplicationCheck`` is the value on the clip's committed adding event (absent when that event has none).
    Every decision line the trail owes (``pending_decisions``) is appended once (``append_decisions``), so a line
    missed by a crash or a refused append is written by the next add, replay or status. ``pendingDecisions`` is
    every line still owed afterwards, as ``status`` shows it (``append_pending_decisions``, X167).
    """
    with locked_batch(root, batch_id) as session:
        record = session.read()
        events = committed_trail(session, batch_id)
        checks = recorded_checks(events)
        written = append_pending_decisions(session, record, events, advance_clock(record))
    return {**({'duplicationCheck': checks[clip_id]} if clip_id in checks else {}), **written}


def append_decisions(session: BatchSession, lines: list[dict]) -> dict:
    """Append decision lines under the caller's lock; a refused line never undoes the committed add (X144).

    Returns ``decisions`` (the lines written now) and ``refusals``: each refused line's ``decisionId`` and the
    trail's refusal text (for example once it reached its reserve); a later add, replay or status retries them.
    """
    written, refusals = [], {}
    for line in lines:
        try:
            session.event(line)
            written.append(line)
        except TrailFull as error:   # only the trail's own refusal; unwritable authority still fails closed
            refusals[line['decisionId']] = str(error)
    return {'decisions': written, 'refusals': refusals}


def append_pending_decisions(session: BatchSession, record: dict, events: list | tuple, elapsed: float) -> dict:
    """Write the decision lines the locked trail read ``events`` shows are owed; a closed batch takes none.

    Returns ``decisions`` (the lines written now) and ``pendingDecisions``: every line still owed afterwards in
    ``status``'s shape (``pending_report``: ``decisionId`` and ``outputId``), plus ``refusal`` where this call's own
    append was refused (X167). ``recorded_duplication`` and ``status`` (``native_budget_status.status_observation``)
    call it.
    """
    owed = pending_decisions(record, events, elapsed) if record['status'] != 'closed' else []
    appended = append_decisions(session, owed)
    report = pending_report(record, [*events, *appended['decisions']], appended['refusals'])
    return {'decisions': appended['decisions'], 'pendingDecisions': report}


def change_reason(reason: object) -> str:
    """The operator's reason for a change, one bounded text (never cut)."""
    if type(reason) is not str or not reason.strip():
        raise ValueError("A change to approved content records the operator's reason")
    if encoded_length(reason.strip()) > REASON_BYTES:
        raise ValueError(f'The reason for a change is at most {REASON_BYTES} encoded bytes; shorten it')
    return reason.strip()


@dataclass(frozen=True)
class ApprovalChange:
    """One operator-approved content revision and its recorded reason."""

    approval: Approval
    reason: str


def record_script_change(root: Path, batch_id: str, clip_id: str, change: ApprovalChange) -> dict:
    """Record the operator's typed title/script change with its reason; never resets or extends the clock or
    refunds anything. The reason is stored in the new approval row and its ``approval-changed`` event.

    """
    reason = change_reason(change.reason)
    approval = change.approval

    def operation(record: dict, elapsed: float) -> Outcome:
        """Append the changed approval and report what changed."""
        result = change_approval(record, clip_id, approval, elapsed)   # never into another clip's job (X217 m4)
        refusal = result.get('refusal') or same_job(record, clip_id, {'approvals': [result['row']]})
        if refusal:
            raise TaskRefused(refusal)
        result['row']['reason'] = reason
        refresh(record, elapsed)                         # work built on the old approval stops satisfying
        event = {'event': 'approval-changed', 'clipId': clip_id, 'changed': result['changed'],
                 'material': result['material'], 'fromIdentity': result['from'], 'toIdentity': result['to'],
                 'recordedBy': result['row']['recordedBy'], 'reason': reason}
        return Outcome(True, event, {'clipId': clip_id, 'approval': result['row'], 'changed': result['changed'],
                                     'material': result['material'], 'reason': reason})
    return transact(root, batch_id, operation)


def committed_trail(session: BatchSession, batch_id: str) -> list[dict]:
    """The committed events of the locked batch's trail (``trail_events``)."""
    try:
        raw = read_private_file(session.dir_fd, EVENTS, 2 * MAX_EVENT_BYTES)
    except (OSError, DurableFileError) as error:
        raise BudgetAuthorityError(f'Budget event trail for {batch_id} is unreadable: {error}') from error
    return trail_events(raw)


def committed_events(session: BatchSession, batch_id: str, name: str) -> list[dict]:
    """The committed ``name`` events of the locked batch's trail. Only the lines that mention ``name`` are decoded (an
    event and its own ``commit-failed`` both do, and are adjacent), so the rest of the trail, however long or padded,
    is never parsed: a settling command that reads its own earlier lines works at a full trail (X217 m2b)."""
    return [row for row in committed_rows(session.lines_naming(name)) if row.get('event') == name]


def trail_events(raw: bytes) -> list[dict]:
    """The trail's committed events: an event followed by its own ``commit-failed`` never happened."""
    return committed_rows(json.loads(line) if line.strip() else None for line in raw.splitlines())


def committed_rows(rows: Iterable[object]) -> list[dict]:
    """``trail_events`` over lines already parsed (anything but a dict is skipped), for a reader that parses once."""
    events: list[dict] = []
    for row in rows:
        if type(row) is not dict:
            continue
        if row.get('event') == 'commit-failed' and events and events[-1].get('event') == row.get('failedEvent'):
            events.pop()
            continue
        events.append(row)
    return events


def committed_changes(changes: list[tuple], current: str) -> list[tuple] | None:
    """The approval changes the record took, or None when the trail contradicts itself.

    A process killed after appending its event but before replacing the record leaves an
    event the record never took: the next change of that clip then starts from the same
    identity again (a committed change is always followed from its target), and a trailing
    one names a target the record does not end on. Such events count as uncommitted, like
    one followed by ``commit-failed``; any other disagreement is a real mismatch.
    """
    kept = []
    for index, (source, target) in enumerate(changes):
        following = changes[index + 1][0] if index + 1 < len(changes) else current
        if following not in (source, target):
            return None
        if following == target:
            kept.append((source, target))
    return kept


def chain_problem(record: dict, clip_id: str, events: list[dict]) -> str | None:
    """Why the clip's approval chain disagrees with the trail, or None."""
    clip, rows = record['clips'][clip_id], record['clips'][clip_id]['approvals']
    if not rows:
        return None
    ours = [(index, row) for index, row in enumerate(events) if row.get('clipId') == clip_id]
    changes = [(row.get('fromIdentity'), row.get('toIdentity')) for _, row in ours
               if row.get('event') == 'approval-changed']
    if committed_changes(changes, rows[-1]['identity']) != [(before['identity'], after['identity'])
                                                          for before, after in zip(rows, rows[1:])]:
        return 'its approval-changed events do not match the approval chain'
    if clip['addedAfterStart']:
        return _added_problem(ours, rows[0]['identity'])
    named = [row.get('authorization') for row in events if row.get('event') == 'batch-started']
    identity = record['production']['authorization']['identity']
    return None if named == [identity] else 'its batch-started event does not name the authorization identity'


def _added_problem(ours: list[tuple], first: str) -> str | None:
    """An added clip: its last adding event (earlier ones were killed before their record) names the first
    approval, and no change of the clip precedes it. ``clip-added`` adds a Short on its own clock (C8);
    ``output-authorized`` authorizes an own-clock or derived output (unit D1), with the same
    ``clipId`` and ``approval`` fields."""
    added = [(index, row) for index, row in ours if row.get('event') in ADDING_EVENTS]
    if not added or added[-1][1].get('approval') != first:
        return 'its clip-added or output-authorized event does not name its first approval'
    if any(row.get('event') == 'approval-changed' and index < added[-1][0] for index, row in ours):
        return 'an approval change of the clip precedes the event that added it'
    return None


def read_approval(root: Path, batch_id: str, clip_id: str) -> dict:
    """The authority's approved title and script for one clip (live or archived batch): the single source.

    ``current`` is the latest approval (the one bound at start unless the operator changed it);
    ``history`` keeps every recorded approval. Compare with ``native_budget_selection.compare_approval``.
    """
    directory = batch_directory(root, batch_id)
    directory = directory if directory.is_dir() else archived_directory(root, batch_id)
    with locked_batch(root, batch_id, directory=directory) as session:
        record = session.read()
        events = committed_trail(session, batch_id)
    approvals = clip_record(record, clip_id)['approvals']
    problem = chain_problem(record, clip_id, events)
    if problem:
        raise BudgetAuthorityError(f'Approvals of clip {clip_id} in batch {batch_id} are corrupt authority: {problem}')
    return {'batchId': batch_id, 'clipId': clip_id, 'status': record['status'],
            'current': approvals[-1] if approvals else None, 'history': approvals, 'canonicalForm': CANONICAL_FORM}


def approval_for_project(root: Path, project: Path) -> dict | None:
    """``read_approval`` for the clip that owns this exact project folder, or None when none does."""
    binding = owner_binding(root, project)
    return read_approval(root, binding['batchId'], binding['clipId']) if binding else None
