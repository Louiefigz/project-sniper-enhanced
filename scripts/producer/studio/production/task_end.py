"""One end rule for production tasks: what an end proves about the slot and about tool cleanup (G9).

Every end of a task goes through ``end_proof``. It returns two separate results. ``slot_released``
says whether the logical AI slot is released. ``tool_cleanup`` is ``proved`` only when the task's own
handle host was observed to end a turn's tools for this cause (``handle_cleans_up``); it never
decides the slot. An outcome label (completed or failed) never changes either result: the cause
and the handle decide. A slot that is not released stays held with ``unresolved`` set, and a note
says why; a released director assignment carries a note too. The rule (MASTER-PLAN M-041 over P1
Step A1, with X79/X88):

| Task | Cause | Slot released when |
|---|---|---|
| not AI (media, check) | any but ``closure`` | always; acknowledged media reaches this rule only through its watchdog |
| AI, director, not revoked | ``closure``, ``host-ended``, ``interrupt`` | always: its batch assignment ends (X29) |
| AI, no handle | ``unlaunched`` | always: ``end_cause`` gives it only with a recorded launch-tool error |
| AI, no handle | any other | never: no execution is bound to the claim |
| AI, process handle | ``observed`` | always: reconcile saw the exact identity gone with an empty process group (G9 b) |
| AI, process handle | ``host-ended``, ``interrupt`` | never at report time: reconcile frees it later |
| AI, host handle | any | never: no end event on ``HOST_END_EVIDENCE`` identifies the execution (empty until M-102) |
| AI, any other handle type | any | never (fails closed; no such handle is valid before M-088) |
| AI, revoked director | ``closure`` | never: a director lost by takeover is an execution (X25) |

A director's ``observed`` end, and every end of a revoked director, follow the handle rows, as
reconcile does (X88 m5). ``closure`` is valid for a director only. Charges are never refunded:
``settle_end`` writes only ``endConfirmed`` and ``unresolved``.
"""
from __future__ import annotations

from dataclasses import dataclass

from studio.production.host_contract import clip_text, encoded_length
from studio.production.task_schema import LIVE, finish, handle_cleans_up, is_ai

CAUSES = ('host-ended', 'interrupt', 'observed', 'unlaunched', 'closure')
REPORTS = ('completed', 'failed', 'interrupted')
TOOL_CLEANUP = ('proved', 'unproven')
# Reconcile's evidence states; reconcile imports them from here, so the vocabulary has one owner.
ALIVE, TERMINATED, LOST = 'alive', 'terminated', 'lost'
# The host capability flag that proves tool cleanup for each cause; other causes prove none.
CLEANUP_FLAGS = {'host-ended': 'interruptCleansUp', 'interrupt': 'interruptCleansUp', 'observed': 'endCleansUp'}
ASSIGNMENT_ENDS = ('closure', 'host-ended', 'interrupt')
# The claim states a launch-tool error can end (claims._release's set); an abandoned claim's holder was
# observed gone, so no one can attest that nothing launched (X79, X88).
UNLAUNCHED = ('claimed', 'cancel-requested', 'superseded')
# Data catalog (G9 (a)): per host, the end events M-080a proved. Empty until M-102 fills it from
# PROBE.json (X30, X55, X58); nothing reads it before then, so no host end releases a slot.
HOST_END_EVIDENCE: dict = {}
NO_EXECUTION = 'no execution is bound to this claim, so its termination cannot be confirmed; the slot stays held'
PROCESS_RUNNING = ('the process reported its end while it still runs; reconcile frees the slot once its exact '
                   'identity is gone and its process group is empty')
ASSIGNMENT_ENDED = ("the director's batch assignment ended (its own recorded end or the batch's closure); that does "
                    'not show its host execution ended (X29)')


@dataclass(frozen=True)
class EndProof:
    """What one end proves: the slot result, the tool-cleanup result, and a note for every held slot."""

    cause: str
    slot_released: bool
    tool_cleanup: str
    note: str | None = None

    def event_fields(self) -> dict:
        """The keys every end event records (G9: ``toolCleanup`` is ``unproven`` unless proved)."""
        return {'endCause': self.cause, 'slotReleased': self.slot_released, 'toolCleanup': self.tool_cleanup}


def require_launch_error(value: object) -> str:
    """The launch tool's failure, verbatim: a non-empty string of at most 512 encoded bytes."""
    if type(value) is not str or not value.strip() or encoded_length(value) > 512:
        raise ValueError("A launch error is the launch tool's own failure text, verbatim, 1-512 bytes")
    return value


def end_cause(task: dict, report: str, launch_error: str | None = None) -> str:
    """The cause of a reported end.

    A launch error wins over a cancellation request: a request says nothing about whether anything
    launched (X88). The text is declared by the caller, not authenticated (G8): the code requires a
    recorded verbatim failure, not proof that the launch tool produced it.

    Args:
        task: The task row (reads ``state``, ``handle`` and ``cancelRequested``).
        report: ``completed``, ``failed`` or ``interrupted``.
        launch_error: The launch tool's failure, verbatim, when the launch call itself failed.

    Returns:
        ``unlaunched`` for a failed, unacknowledged claim in ``UNLAUNCHED`` with a launch error;
        otherwise ``interrupt`` for ``interrupted`` or a cancellation request, else ``host-ended``.

    Raises:
        ValueError: An unknown report; a launch error that is malformed, comes with another report,
            or belongs to an acknowledged task or to one not in ``UNLAUNCHED`` (``abandoned``, say).
    """
    if report not in REPORTS:
        raise ValueError('An end report is completed, failed or interrupted')
    if launch_error is not None:
        require_launch_error(launch_error)
        if report != 'failed' or task['handle'] is not None or task['state'] not in UNLAUNCHED:
            raise ValueError(f'A launch error belongs to a failed claim that no execution acknowledged and that is '
                             f'{", ".join(UNLAUNCHED)}; this task is {task["state"]}')
        return 'unlaunched'
    return 'interrupt' if report == 'interrupted' or task['cancelRequested'] else 'host-ended'


def _cause_problem(task: dict, cause: str) -> str | None:
    """Why this cause cannot end this task, or None."""
    if cause not in CAUSES:
        return f'An end cause is one of {", ".join(CAUSES)}'
    if cause == 'closure' and task['kind'] != 'director':
        return "Only a director's batch assignment ends by closure"
    if cause == 'unlaunched' and task['handle'] is not None:
        return 'An unlaunched end belongs to a claim that no execution acknowledged'
    return None


def _execution_row(handle: dict | None, cause: str) -> tuple[bool, str | None]:
    """Whether this cause is termination evidence for the execution behind ``handle``, and why not."""
    if cause == 'closure':
        return False, ('closure ends only a batch assignment; a director revoked by takeover is an execution whose '
                       'slot stays held until termination evidence')
    if handle is None:
        return (True, None) if cause == 'unlaunched' else (False, NO_EXECUTION)
    if handle['type'] == 'process':
        return (True, None) if cause == 'observed' else (False, PROCESS_RUNNING)
    if handle['type'] == 'host':
        return False, (f'host {handle["host"]} ended this turn, but no end event on the host end-evidence list '
                       '(HOST_END_EVIDENCE) identifies this execution; the slot stays held until termination evidence')
    return False, f'no termination evidence rule exists for a {handle["type"]} handle yet; the slot stays held'


def end_proof(task: dict, cause: str) -> EndProof:
    """The one rule: the slot and tool-cleanup results of ending ``task`` for ``cause`` (pure).

    Args:
        task: The task row (reads ``kind``, ``handle`` and ``revoked``).
        cause: One of ``CAUSES``.

    Returns:
        The proof; ``note`` explains every held slot, and a released director assignment.

    Raises:
        ValueError: An unknown cause, ``closure`` for a task that is not a director, or ``unlaunched``
            for a task an execution acknowledged.
    """
    if problem := _cause_problem(task, cause):
        raise ValueError(problem)
    flag = CLEANUP_FLAGS.get(cause)
    cleanup = 'proved' if flag is not None and handle_cleans_up(task['handle'], flag) else 'unproven'
    if not is_ai(task):
        return EndProof(cause, True, cleanup)
    if task['kind'] == 'director' and not task['revoked'] and cause in ASSIGNMENT_ENDS:
        return EndProof(cause, True, cleanup, ASSIGNMENT_ENDED)
    released, note = _execution_row(task['handle'], cause)
    return EndProof(cause, released, cleanup, note)


def settle_end(task: dict, cause: str) -> EndProof:
    """Record the end: ``endConfirmed``, and ``unresolved`` unless the slot is released. Charges stay."""
    proof = end_proof(task, cause)
    task.update(endConfirmed=True, unresolved=not proof.slot_released)
    return proof


def settles_only(task: dict, may_report: bool) -> bool:
    """Whether a completion reported now is recorded only as history, never published.

    ``may_report`` is ``callbacks._may_report(task)``, passed in so this module never imports callbacks.
    """
    if task['state'] in ('superseded', 'abandoned') and (may_report or bool(task['receipts'])):
        return True
    return task['cancelRequested'] and task['state'] in ('cancel-requested', 'cancelled')


def observed_state(handle: dict, status: str | None) -> str | None:
    """Reconcile's view of an observed state: a terminal state counts only when the ``observed`` row proves it.

    Process handles are returned unchanged (their ``TERMINATED`` already needs the exact identity gone and
    an empty process group). Any other handle seen terminal is ``LOST`` unless its end is evidence.
    """
    if handle['type'] == 'process' or status != TERMINATED:
        return status
    released, _ = _execution_row(handle, 'observed')
    return TERMINATED if released else LOST


def late_cancel(task: dict, late: tuple[list[dict], str, str], elapsed: float) -> EndProof:
    """Cancellation wins over a later reported end: the result is kept as history, never published.

    Args:
        task: A task whose cancellation was requested.
        late: (receipts, reported outcome, cause). The cause is ``interrupt``, or ``unlaunched`` when
            ``end_cause`` accepted the launch tool's error (no execution started; the slot is released).
        elapsed: The batch's elapsed seconds.

    Returns:
        The proof; the caller builds the event. A live task ends ``cancelled``; an ended one (abandoned,
        say) keeps its state and gains the text in its reason.

    Raises:
        ValueError: The task's cancellation was not requested, or the cause is neither of the two.
    """
    receipts, outcome, cause = late
    if not task['cancelRequested'] or cause not in ('interrupt', 'unlaunched'):
        raise ValueError('Only a task whose cancellation was requested ends as a late cancellation (interrupt or '
                         'unlaunched)')
    if receipts:
        task['receipts'] = receipts
    proof = settle_end(task, cause)
    text = (f'cancellation was requested; the launch call then failed ({outcome}); nothing ran'
            if cause == 'unlaunched' else f'cancellation was requested; the execution then reported {outcome}; its '
            'result is history and never published')
    if task['state'] in LIVE:
        finish(task, 'cancelled', elapsed, text)
    else:
        task['reason'] = clip_text(f'{task["reason"] or task["state"]}; {text}')
    return proof
