"""The enrolled director's own declaration of whether it is working on each Short (P1 Step B2, M-045; C4).

An enrolled director that says nothing counts as working (``directorWorking`` is True on every new v2 clock), so
its Shorts earn no render-queue credit while it holds its slot: undeclared director work and subagents that are
not claimed tasks are uncertain state, and uncertain state counts (G1). The director declares ``idle`` for Shorts
it only coordinates, and ``working`` before it authors or reviews itself, or launches a subagent that is not a
claimed task.

A declaration is the director's own claim, never an observation: the event says ``declared: True``, and nothing
here checks what the director actually does (G8). ``queue_clock.productive`` reads the flag on v2 clocks only.
The ``--all`` form covers every Short on a v2 clock that is not handed off; a named Short without a v2 clock, or
one already handed off, is refused by name.
"""
from __future__ import annotations

from dataclasses import dataclass

from studio.production.claims import ClaimRef, Outcome, check_claim
from studio.production.queue_clock import writable
from studio.production.task_schema import holds_slot
from studio.production.tasks import TaskRefused, task_of


@dataclass(frozen=True)
class DirectorActivity:
    """The Shorts one declaration covers (``None``: every open Short on a v2 clock) and whether the director works."""

    clips: tuple[str, ...] | None
    working: bool


def _clips(record: dict, activity: DirectorActivity) -> tuple[str, ...]:
    """The Shorts the declaration covers; a named Short must be open and on a v2 clock."""
    if activity.clips is None:
        return tuple(clip_id for clip_id, clip in record['clips'].items()
                     if writable(clip) and clip['state'] != 'handed-off')
    for clip_id in activity.clips:
        clip = record['clips'].get(clip_id, {})
        if not writable(clip):
            raise TaskRefused(f'Clip {clip_id} has no v2 Short capacity clock; director activity applies only to '
                              'Shorts on this policy')
        if clip['state'] == 'handed-off':
            raise TaskRefused(f'Clip {clip_id} was handed off')
    return tuple(activity.clips)


def declare(record: dict, ref: ClaimRef, activity: DirectorActivity, elapsed: float) -> Outcome:
    """Record the enrolled director's declared activity for the Shorts it names.

    The transaction has already checkpointed every clock to ``elapsed``, so time before the declaration is
    accounted under the previous state.

    Args:
        record: The batch record, read under its lock.
        ref: The director's own fenced claim.
        activity: The Shorts and the declared state.
        elapsed: The batch clock (the event records it through the transaction).

    Returns:
        The outcome; a declaration that changes no Short commits nothing.

    Raises:
        StaleClaim: The claim is not the director's current one.
        TaskRefused: The caller is not the enrolled director, or a named Short has no v2 clock or was handed off.
    """
    task = task_of(record, ref.task_id)
    check_claim(task, ref)
    if task['kind'] != 'director' or task['revoked'] or not holds_slot(task):
        raise TaskRefused('Only the enrolled director declares its own activity')
    clips = _clips(record, activity)
    changed = [clip_id for clip_id in clips
               if record['clips'][clip_id]['capacityClock']['directorWorking'] != activity.working]
    for clip_id in changed:
        record['clips'][clip_id]['capacityClock']['directorWorking'] = activity.working
    event = {'event': 'director-activity', 'clips': sorted(clips), 'changed': sorted(changed),
             'working': activity.working, 'declaredBy': ref.task_id, 'declared': True}
    return Outcome(bool(changed), event, {'clips': list(clips), 'changed': sorted(changed),
                                          'working': activity.working, 'declared': True})
