"""A Short's counted time stops at its first delivery, and its visible hand-off is timed (M-054, C12; P1 Step B11).

``queue_clock.status`` reads ``frozen_times`` for a v2 clock: ``countedProductionSeconds`` is the time at the first
delivery, from the credit ``record_delivery`` froze for it (``deliveryCredits``; 0 when absent, conservative);
``countedToHandoffSeconds`` runs until the visible hand-off, and after it nothing grows. ``commands.cmd_handoff``
calls ``record_handoff`` inside its lock at the command's batch-clock ``elapsed`` (B11; the confirmation's own
``visibleHandoffAt`` stays its own field, X191): the row holds the counted and total time, the delivery deadline with
the credit the Short holds then (E-CLOCK-6) and whether the hand-off met it, since minute 40 is the visible hand-off,
not the export. A v1 clock and a Long keep their rules (E-LS-1). Split from ``queue_clock`` to keep it within its
line budget.
"""
from __future__ import annotations

from studio.production.queue_clock import excluded, writable


def frozen_times(clip: dict, authorized: float, running: tuple[float, float]) -> dict:
    """A v2 Short's times: counted time stops at its first delivery, and the time to hand-off and the total at the
    visible hand-off (``record_handoff``). Before each, the running (total, counted) value."""
    clock, first = clip['capacityClock'], (clip.get('deliveries') or [None])[0]
    delivered = None if first is None else (
        max(0.0, first['elapsed'] - authorized),
        max(0.0, first['elapsed'] - authorized - clock['deliveryCredits'].get(first['attemptId'], 0.0)))
    handoff = clock['handoff']
    return {'totalElapsedSeconds': handoff['totalSeconds'] if handoff else running[0],
            'countedProductionSeconds': delivered[1] if delivered else running[1],
            'totalAtDeliverySeconds': delivered[0] if delivered else None,
            'countedAtDeliverySeconds': delivered[1] if delivered else None,
            'countedToHandoffSeconds': handoff['countedSeconds'] if handoff else running[1],
            'totalAtHandoffSeconds': handoff['totalSeconds'] if handoff else None,
            'handoffOnTime': handoff['onTime'] if handoff else None}


def record_handoff(record: dict, clip: dict, elapsed: float) -> dict | None:
    """Record a v2 Short's visible hand-off on its clock: its counted and total time, its delivery deadline with the
    credit it holds now, and whether the hand-off met it.

    Returns the row, or None for a clip without a writable clock (a v1 Short or a Long: its rules are unchanged).
    """
    if not writable(clip):
        return None
    from studio.production.formats import clip_deadlines
    authorized = clip.get('output', {}).get('authorizedElapsed', 0.0)
    deadline = clip_deadlines(record, clip)['deliverySeconds']
    row = {'elapsed': elapsed, 'countedSeconds': max(0.0, elapsed - authorized - excluded(clip)),
           'totalSeconds': max(0.0, elapsed - authorized), 'deadlineElapsed': deadline, 'onTime': elapsed <= deadline}
    clip['capacityClock']['handoff'] = row
    return dict(row)
