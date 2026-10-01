"""The worst case of every settling class past the trail's stop (X217 M1), for ``test_trail_reserve_budget``.

``CLASSES`` maps every member of ``native_budget_trail.TERMINAL_EVENTS``, and the abandoning ``observed`` line
(``native_budget_trail.terminal``), to a function returning that class's worst case in bytes: how many lines the
batch can still owe past the 15 MiB stop, times its widest line as ``canonical()`` encodes it (with the ``elapsed``
that ``session.transact`` adds). Each docstring states its counting basis.

The basis is the trail module's: past the stop no claim, launch, owner row, task or clip can begin, so each line
settles something that existed at the stop, a bounded number of times. Where several classes can carry the same
transition (a reconcile change, a task's end), it is counted in each class that names it: the sum over-counts. Texts
use their writers' bounds (``clip_text``'s 512 encoded bytes, ``RESULT_TEXT_BYTES``, ``DELIVERY_PATH_BYTES``),
integers ``MAX_COUNT`` and floats the longest spelling. Pure arithmetic on constants; nothing is written.
"""
from __future__ import annotations

import sys

from studio.native_budget_family_schema import MAX_FAMILIES, MAX_INVOCATIONS
from studio.native_budget_schema_data import BOUNDS
from studio.native_budget_section_schema import MAX_SECTION_OWNERS
from studio.native_budget_store import MAX_RECORD_BYTES, canonical
from studio.native_budget_trail import ERROR_TEXT_CHARS, TERMINAL_EVENTS
from studio.production.handoff import TIME_CHARS
from studio.production.host_contract import HOSTS, MAX_COUNT, MAX_PID, MAX_RECEIPTS
from studio.production.queue_authority import CHECKPOINT_EVENT_BYTES
from studio.production.queue_clock import SETTLED
from studio.production.queue_clock_schema import MAX_CHECKPOINTS, MAX_WORKERS
from studio.production.settlement import DELIVERY_PATH_BYTES, RESULT_TEXT_BYTES, _section_owner_room, encoded
from studio.production.task_end import CAUSES, TOOL_CLEANUP
from studio.production.task_schema import MAX_TASK_OWNERS

BIG = sys.float_info.max                  # the longest float spelling
TEXT = 'x' * 512                          # clip_text and the validators bound a text at 512 encoded bytes
TASK, CLIP, ATTEMPT = 'T' * 64, 'C' * 64, 'a' * 32
DIGEST = 'f' * 16                         # queue_audit.owner_digest
PATH = 'p' * DELIVERY_PATH_BYTES          # a delivered or hand-off evidence path, at its encoded bound
CLIPS, TASKS, ATTEMPTS = BOUNDS['clips'], BOUNDS['tasks'], BOUNDS['clips'] * BOUNDS['attempts']
OWNER_ROWS = MAX_WORKERS * CLIPS          # owner rows the clocks can hold at the stop
PROCESS = {'type': 'process', 'pid': MAX_PID, 'pgid': MAX_PID, 'started': 's' * 64}
HOST = {'type': 'host', 'host': max(HOSTS, key=len), 'thread': 'x' * 128, 'turn': 'y' * 128}
END = {'endCause': max(CAUSES, key=len), 'slotReleased': False, 'toolCleanup': max(TOOL_CLEANUP, key=len)}
FAILURE = {'category': 'c' * 64, 'detail': TEXT}
SETTLEMENT = {SETTLED: {CLIP: {'elapsed': BIG, 'excludedSeconds': BIG, 'removedWorkers': [DIGEST] * MAX_WORKERS}}}
CHANGE = {'taskId': TASK, 'from': 'cancel-requested', 'to': 'superseded', 'unresolved': True, 'reason': TEXT}
RECEIPT = {'path': 'p' * 1024, 'sha256': 'e' * 64, 'bytes': MAX_COUNT}   # host_contract.valid_receipt


def line(**fields: object) -> int:
    """Bytes of one trail line with these fields and the transaction's ``elapsed``."""
    return len(canonical({**fields, 'elapsed': BIG}))


def ids(count: int, value: str) -> int:
    """Bytes ``count`` more entries of ``value`` add to a list."""
    return count * (encoded(value) + 1)


def checkpoint() -> int:
    """<= MAX_CHECKPOINTS per Short (its record's count; X190 n6 never repeats a written one), each written only
    within CHECKPOINT_EVENT_BYTES (``queue_authority._checkpoint_due``)."""
    return MAX_CHECKPOINTS * CLIPS * CHECKPOINT_EVENT_BYTES


def stall_decided() -> int:
    """One per Short (``queue_stall.decide`` refuses a second); a task is frozen once, on whichever line freezes it."""
    return CLIPS * line(event='capacity-stall-decided', clipId=CLIP, kind='cancel', reason=TEXT, state='cancelled',
                        frozen=[]) + ids(TASKS, TASK)


def settled_widest() -> int:
    """The widest ``capacity-settled`` line naming no recovered or orphaned owner (``queue_authority._settled_line``)."""
    return len(canonical({'event': 'capacity-settled', 'clipId': CLIP, 'workerDigest': DIGEST, 'state': 'finished',
                          'elapsed': BIG, 'excludedSeconds': BIG, 'recoveredDigests': [], 'orphanedDigests': [],
                          'capacityState': 'capacity-stalled'}))


def capacity_settled() -> int:
    """An owner's end is a line only when it removes an owner row, and a row begins with a ``capacity-observed``
    line, so <= OWNER_ROWS lines; every owner is named by its digest, each removed row at most once more in a
    recovered or orphaned list (``queue_authority._settled_line``)."""
    return OWNER_ROWS * settled_widest() + ids(OWNER_ROWS, DIGEST)


def observed() -> int:
    """An abandoning observation names each attempt once (its record marks it; X217 m3 writes a failed one once)."""
    return ATTEMPTS * line(event='observed', abandoned=[ATTEMPT])


def task_completed() -> int:
    """Per task, one end carrying receipts (``task-completed``, a late ``task-cancelled`` or ``task-failed``: one
    per claim, a claim cannot begin past the stop) and the export watchdog's one settling line (``task-*`` with its
    ``capacitySettled``, or ``tasks-reconciled`` with its owners: ``run-media`` takes only a claimed, unacknowledged
    task, and its settlement ends that state)."""
    end = line(event='task-cancelled', taskId=TASK, epoch=MAX_COUNT, receipts=[RECEIPT] * MAX_RECEIPTS,
               lateOutcome='c' * 64, publishable=False, approvalStale=False, unresolved=True, launchError=TEXT, **END)
    watchdog = max(line(event='task-completed', epoch=MAX_COUNT, taskId=TASK, state='superseded', failure=FAILURE,
                        owners=[], **SETTLEMENT),
                   line(event='tasks-reconciled', epoch=MAX_COUNT, taskId=TASK, state='abandoned', failure=FAILURE,
                        owners=[PROCESS] * MAX_TASK_OWNERS))
    return TASKS * (end + watchdog)


def task_failed() -> int:
    """A claim refused at its deadline fails the task once (``claims.expired_claim``); callback ends are counted in
    ``task_completed``."""
    return TASKS * line(event='task-failed', taskId=TASK, category='deadline-expired', checkedElapsed=BIG)


def task_cancelled() -> int:
    """A confirmed termination, once per claim (then the task is cancelled or replayed)."""
    return TASKS * line(event='task-cancelled', taskId=TASK, epoch=MAX_COUNT, state='cancel-requested',
                        unresolved=True, **END)


def task_cancel_requested() -> int:
    """A request commits only when it changes the task (``callbacks._mark_cancel``); counted twice per task."""
    return 2 * TASKS * line(event='task-cancel-requested', taskId=TASK, state='cancel-requested', reason=TEXT)


def task_abandoned() -> int:
    """A host's ``lost`` event abandons live work once per claim."""
    return TASKS * line(event='task-abandoned', taskId=TASK, epoch=MAX_COUNT)


def task_superseded() -> int:
    """A task is revoked once and its chunk carry withdrawn once; a line names at least one of them."""
    return 2 * TASKS * line(event='task-superseded', taskIds=[TASK], reason=TEXT)


def task_resource_settled() -> int:
    """One statement per task and phase, its revocation and its unresolved resource (X217 m2b)."""
    return 2 * TASKS * line(event='task-resource-settled', taskId=TASK, basis='operator-statement', statement=TEXT,
                            phase='unresolved resource')


def task_attached() -> int:
    """An execution attaches once per claim (a host event or the callback, whichever binds the handle)."""
    return TASKS * line(event='task-attached', taskId=TASK, epoch=MAX_COUNT, handle=HOST)


def task_released() -> int:
    """An unacknowledged claim is released once; claiming again is not a settling line."""
    return TASKS * line(event='task-released', taskId=TASK, epoch=MAX_COUNT, launchError=TEXT, **END)


def tasks_reconciled() -> int:
    """A reconcile change is written once, on a ``tasks-reconciled`` line or among a close's or drain's
    ``reconciled`` entries, and a task changes at most twice (its end, then its resolution), its owners settling once;
    each abandoned launch and each expired freeze is named once. A line names at least one of them."""
    empty = {'changes': [], 'abandonedLaunches': [], 'expiredFrozen': []}
    return TASKS * line(event='tasks-reconciled', **{**empty, 'changes': [{**CHANGE, **SETTLEMENT}]}) \
        + TASKS * line(event='tasks-reconciled', **{**empty, 'changes': [CHANGE]}) \
        + ATTEMPTS * line(event='tasks-reconciled', **{**empty, 'abandonedLaunches': [ATTEMPT]}) \
        + TASKS * line(event='tasks-reconciled', **{**empty, 'expiredFrozen': [TASK]})


def batch_closed() -> int:
    """Once: closed is final. It closes only with no launch running; its reconciled entries are counted in
    ``tasks_reconciled``."""
    return line(event='batch-closed', unsettled=[TASK] * TASKS, runningAttempts=[], revoked=[TASK] * TASKS,
                directorEnd={'taskId': TASK, **END})


def batch_draining() -> int:
    """Once: ``drain`` and a close of an active batch both need it active; a close that leaves a draining batch
    draining records nothing (X217 m2a). Its reconciled entries are counted in ``tasks_reconciled``."""
    return max(line(event='batch-draining', frozen=[TASK] * TASKS, reason=TEXT),
               line(event='batch-draining', unsettled=[TASK] * TASKS, runningAttempts=[ATTEMPT] * ATTEMPTS,
                    directorEnd=None, revoked=[]))


def clip_handed_off() -> int:
    """Once per clip (a clip is handed off once); its delivery path and evidence paths are bounded at
    DELIVERY_PATH_BYTES and its times at ``handoff.TIME_CHARS``; a task is frozen once on whichever line."""
    binding = {'path': PATH, 'sha256': 'e' * 64}
    summary = {'record': binding, 'confirmation': binding, 'mp4': binding, 'viewsVerifiedAt': 't' * TIME_CHARS,
               'visibleHandoffAt': 't' * TIME_CHARS}
    delivery = {'kind': 'final', 'output': PATH, 'sha256': 'e' * 64, 'attemptId': ATTEMPT, 'elapsed': BIG,
                'late': True}
    clock = {'elapsed': BIG, 'deadlineElapsed': BIG, 'countedSeconds': BIG, 'totalSeconds': BIG, 'onTime': False}
    return CLIPS * line(event='clip-handed-off', clipId=CLIP, delivery=delivery, frozenTasks=[], handoff=summary,
                        clock=clock) + ids(TASKS, TASK)


def batch_archived() -> int:
    """Once: an archived batch leaves the live root. Its reason is cut to 512 characters, each at most 12 bytes."""
    return len(canonical({'event': 'batch-archived', 'batchId': 'b' * 64, 'reason': '\U0001F600' * 512}))


def section_owners() -> int:
    """Running section owners at the stop: each reserved its widest outcome in the record (``settlement``), so at
    most MAX_RECORD_BYTES over the smallest running row and its room, and never more than the clips' rows."""
    row = {'id': 'a' * 32, 'phase': 'p', 'inputIdentity': 'f' * 64, 'planIdentity': 'f' * 64, 'attemptId': 'a' * 32,
           'output': 'o', 'supervisor': {'pid': 0, 'pgid': 0, 'started': ''}, 'admittedElapsed': 0,
           'completedElapsed': None, 'status': 'running', 'failure': None, 'picture': False, 'retryOf': None}
    return min(CLIPS * MAX_SECTION_OWNERS, MAX_RECORD_BYTES // (encoded(row) + _section_owner_room(row)))


def launch_completed() -> int:
    """An export's outcome once per attempt; a family invocation's once per invocation row; a running section
    owner's once; a review continuation's once per original Long attempt (one live continuation per attempt, each
    begun with a ``section-review-continuation`` line before the stop)."""
    result = 'r' * RESULT_TEXT_BYTES
    return ATTEMPTS * line(event='launch-completed', clipId=CLIP, attemptId=ATTEMPT, status='succeeded',
                           resultStatus=result) \
        + CLIPS * MAX_FAMILIES * MAX_INVOCATIONS * line(event='launch-completed', kind='section-family-invocation',
                                                         clipId=CLIP, attemptId=ATTEMPT, invocationId=ATTEMPT,
                                                         status='succeeded', resultStatus=result) \
        + section_owners() * line(event='launch-completed', sectionOwner='f' * 32, status='succeeded') \
        + ATTEMPTS * line(event='launch-completed', kind='section-review-continuation', attemptId=ATTEMPT,
                          status=result)


def failed_widest() -> int:
    """The widest ``commit-failed`` line: its error is ``error_text``, at most ERROR_TEXT_CHARS printable ASCII
    characters, each at most 2 bytes encoded."""
    return len(canonical({'event': 'commit-failed', 'failedEvent': max(TERMINAL_EVENTS, key=len),
                          'error': '"' * ERROR_TEXT_CHARS}))


def commit_failed() -> int:
    """One failed attempt of each automatic writer that never repeats a written line: a checkpoint (X190 n6) and an
    abandoned launch (X217 m3)."""
    return (MAX_CHECKPOINTS * CLIPS + ATTEMPTS) * failed_widest()


CLASSES = {
    'capacity-checkpoint': checkpoint, 'capacity-stall-decided': stall_decided, 'capacity-settled': capacity_settled,
    'observed': observed, 'task-completed': task_completed, 'task-failed': task_failed,
    'task-cancelled': task_cancelled, 'task-cancel-requested': task_cancel_requested,
    'task-abandoned': task_abandoned, 'task-superseded': task_superseded,
    'task-resource-settled': task_resource_settled, 'task-attached': task_attached,
    'task-released': task_released, 'tasks-reconciled': tasks_reconciled, 'batch-closed': batch_closed,
    'batch-draining': batch_draining, 'clip-handed-off': clip_handed_off, 'batch-archived': batch_archived,
    'launch-completed': launch_completed, 'commit-failed': commit_failed,
}
