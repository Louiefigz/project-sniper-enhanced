"""Independent per-output milestones: preparation, encoding, visible MP4, matching Studio, approval, cleanup, SLA.

Each milestone has its own source and none implies another (plan §5 "Scheduling and deadlines"):
- ``draftRenderReadyAt`` / ``finalRenderReadyAt``: admission of the earliest draft (or final,
  promotion, verify or resume) launch that succeeded or is still running (``provisional``). A launch
  is admitted when its candidate is frozen; a failed launch establishes nothing.
- ``encodedAt``: the earliest delivery the exporter recorded (a complete MP4 and its receipts).
- ``visibleHandoffAt``: the batch-clock time of the ``clip-handed-off`` event that recorded a
  visible-handoff confirmation (``native_budget_handoffs``). A hand-off file named with ``--handoff``
  is ``confirmed-not-on-batch-clock``: real, but never meets the SLA. An encoded MP4 or a
  server-side ``views-ready`` record never sets it.
- ``editoriallyApprovedAt``: the batch time of check-final's current editorial final
  (``editorialApproval``; ``native_budget_review_timing``): a ``review-submitted`` trail event when
  one exists, else the submission's declared batch-clock ``submittedElapsed``, with the trail's
  ``packet-resolved`` second as its lower bound. It is ``current`` only for the clip's latest
  delivery under its current approval, else ``historical`` (and sets no timestamp). A closed
  batch's approval is ``not-verifiable-after-close``: check-final re-derives approved content only
  from the current active or draining batch.
- cleanup: the output's live or unresolved tasks and running launches. Delivery never waits for
  cleanup, and cancellation requested is not cancellation complete.
- SLA: met only by a visible hand-off by the delivery deadline (minute 40). The ``slaMiss``
  beside these is a v2 Short's recorded hand-off after minute 40 (M-054); without a recorded
  hand-off it is no MP4 encoded by minute 40, which is necessary, not sufficient (X218 F-m3).
Times are batch elapsed seconds; null means not established.
"""
from __future__ import annotations

from studio.production.task_schema import LIVE, TERMINAL, is_ai
from studio.production.tasks import tasks_of

RENDER_ROUTES = {'draft': ('draft',), 'final': ('final', 'promote', 'verify', 'resume')}
LIVE_ATTEMPT = ('running', 'succeeded')
VISIBLE_BASIS = ('a visible hand-off of a complete MP4 (draft or final) recorded on the batch clock by the '
                 'delivery deadline')


def render_ready(clip: dict, routes: tuple[str, ...]) -> dict:
    """The earliest admitted launch of these routes that succeeded or still runs."""
    rows = [row for row in clip['attempts'] if row['route'] in routes]
    good = sorted((row for row in rows if row['status'] in LIVE_ATTEMPT), key=lambda row: row['admittedElapsed'])
    failed = sum(row['status'] not in LIVE_ATTEMPT for row in rows)
    if not good:
        return {'at': None, 'failedLaunches': failed}
    return {'at': good[0]['admittedElapsed'], 'attemptId': good[0]['id'], 'route': good[0]['route'],
            'provisional': good[0]['status'] == 'running', 'failedLaunches': failed}


def _mine(rows: list[dict], clip_id: str) -> list[dict]:
    """The accepted verdicts about this output."""
    return [row for row in rows if row['accepted'] and row['delivery']['clipId'] == clip_id]


def _earliest(rows: list[dict], kind: str, source: str) -> dict | None:
    """The accepted verdict of this kind and source recorded first (by batch time, else in order)."""
    rows = [row for row in rows if row['kind'] == kind and row['source'] == source]
    return min(rows, key=lambda row: row['at'] if row['at'] is not None else 0.0) if rows else None


def _authorized_at(clip: dict) -> float | None:
    """When the output's approved content was handed over: its first approval, or batch start for a declared clip."""
    if clip['approvals']:
        return clip['approvals'][0]['elapsed']
    return None if clip['addedAfterStart'] else 0.0


def _first_dispatch(record: dict, clip_id: str) -> float | None:
    """The earliest AI dispatch for the output: an admitted dispatch or a current AI task claim."""
    times = [row['elapsed'] for row in record['clips'][clip_id]['dispatches']]
    times += [task['claim']['claimedElapsed'] for task in tasks_of(record).values()
              if task['clipId'] == clip_id and is_ai(task) and task['claim']]
    return min(times, default=None)


def preparation(deadlines: dict, renders: dict, elapsed: float) -> dict:
    """Render-ready (draft or final) by the output's own preparation deadline, late, missed or still pending."""
    target = deadlines['preparationSeconds']
    ready = min((row['at'] for row in renders.values() if row['at'] is not None), default=None)
    if ready is not None:
        status = 'met' if ready <= target else 'late'
    else:
        status = 'missed' if elapsed >= target else 'pending'
    return {'status': status, 'readyAt': ready, 'targetElapsed': target, 'draft': renders['draft'],
            'final': renders['final']}


def encoding(clip: dict) -> dict:
    """The output's complete MP4 deliveries (media receipts)."""
    rows = clip['deliveries']
    kinds = {kind: min((row['elapsed'] for row in rows if row['kind'] == kind), default=None)
             for kind in ('draft', 'final')}
    return {'status': 'encoded' if rows else 'not-encoded', 'at': min((row['elapsed'] for row in rows), default=None),
            'draftAt': kinds['draft'], 'finalAt': kinds['final'], 'latest': rows[-1] if rows else None}


def visible_mp4(handoffs: list[dict], encoded: dict) -> dict:
    """Visible on the batch clock only from a recorded hand-off; a hand-off file alone is off the clock."""
    recorded, named = _earliest(handoffs, 'visible-handoff', 'authority trail'), \
        _earliest(handoffs, 'visible-handoff', 'hand-off file')
    if recorded is not None:
        return {'status': 'visible', 'at': recorded['at'], 'clock': recorded['clock'], 'wall': recorded['wall'],
                'evidence': recorded['file'], 'confirmation': recorded['confirmation'],
                'delivery': recorded['delivery'],
                'approvedContent': recorded['content']}
    if named is not None:
        return {'status': 'confirmed-not-on-batch-clock', 'at': None, 'wall': named['wall'], 'evidence': named['file'],
                'delivery': named['delivery'], 'approvedContent': named['content'],
                'reason': 'a hand-off file is not on the batch clock and never meets the SLA; record the hand-off '
                          'with native_batch.py handoff'}
    reason = ('an encoded MP4 (a media receipt) is not a visible hand-off; a verified hand-off confirmation '
              'is required') if encoded['status'] == 'encoded' else 'no complete MP4 has been encoded'
    return {'status': 'not-established', 'at': None, 'reason': reason}


def matching_studio(handoffs: list[dict]) -> dict:
    """The matching editable Studio view: attested by a confirmation, or server-verified only."""
    confirmed = [row for row in handoffs if row['kind'] == 'visible-handoff']
    row = next(iter(confirmed or handoffs), None)
    if row is None:
        return {'status': 'not-established', 'reason': 'no hand-off record verified a matching Studio view'}
    return {'status': 'attested' if confirmed else 'server-verified', 'establishedBy': row['at'], 'clock': row['clock'],
            'wall': row['wall'], 'record': row['record'], 'evidence': row['file']}


def editorial_approval(reviews: list[dict], encoded: dict, closed: bool) -> dict:
    """check-final's editorial final: current only for the latest delivery under the current approval.

    Its batch time is the review's timing (declared at submission unless the trail recorded it);
    its wall stamps are display only; none of it is human approval.
    """
    current = [row for row in reviews if row['standing'] == 'current']
    historical = [row for row in reviews if row['standing'] == 'historical']
    if current:
        row = current[0]
        return {'status': 'approved', 'standing': 'current', 'at': row['timing']['approvedAt'],
                'timing': row['timing'], 'wall': row['wall'], 'humanApproved': False,
                'independence': row['independence'], 'evidence': row['file'], 'delivery': row['delivery'],
                'approvedContent': row['approvedContent'], 'historical': [item['file'] for item in historical]}
    if closed:
        return {'status': 'not-verifiable-after-close', 'at': None, 'humanApproved': False,
                'reason': 'the batch is closed: check-final re-derives approved content only from the current '
                          'active or draining batch, so no editorial final can be verified now'}
    reason = 'no final MP4 has been encoded (a review draft is never an editorial final)' \
        if encoded['finalAt'] is None \
        else 'no check-final result approves the latest delivery under the current approval'
    return {'status': 'historical-only' if historical else 'not-established', 'at': None, 'humanApproved': False,
            'reason': reason,
            'historical': [{'evidence': item['file'], 'delivery': item['delivery'],
                            'approvedContent': item['approvedContent']} for item in historical]}


def cleanup(record: dict, clip_id: str) -> dict:
    """The output's work still holding a slot, and its running launches."""
    tasks = [task for task in tasks_of(record).values() if task['clipId'] == clip_id]
    live = [task for task in tasks if task['state'] in LIVE]
    unresolved = [task for task in tasks if task['state'] in TERMINAL and task['unresolved']]   # G9: any ended task
    running = [row for row in record['clips'][clip_id]['attempts'] if row['status'] == 'running']
    return {'status': 'pending' if live or unresolved or running else 'settled',
            'liveTasks': [{'taskId': task['id'], 'kind': task['kind'], 'state': task['state']} for task in live],
            'unresolvedTasks': [{'taskId': task['id'], 'state': task['state']} for task in unresolved],
            'runningLaunches': [{'attemptId': row['id'], 'route': row['route']} for row in running],
            'note': 'cancellation requested is not cancellation complete; delivery never waits for cleanup'}


def sla(deadlines: dict, visible: dict, encoded_at: float | None, elapsed: float) -> dict:
    """Met only by a recorded visible hand-off by the output's counted delivery deadline; else a miss after it."""
    deadline, visible_at = deadlines['deliverySeconds'], visible['at']
    if visible_at is not None:
        status = 'met' if visible_at <= deadline else 'missed'
    else:
        status = 'missed' if elapsed >= deadline else 'pending'
    note = {'offClock': visible['reason']} if visible['status'] == 'confirmed-not-on-batch-clock' else {}
    return {'status': status, 'miss': status == 'missed', 'deadlineElapsed': deadline, 'basis': VISIBLE_BASIS,
            'visibleAt': visible_at, 'encodedByDeadline': None if encoded_at is None and elapsed < deadline
            else encoded_at is not None and encoded_at <= deadline, **note}


def milestones(record: dict, clip_id: str, elapsed: float, verdicts: dict) -> dict:
    """Every milestone of one output, each from its own evidence; timestamps are batch-clock times only."""
    from studio.production.formats import clip_deadlines
    clip = record['clips'][clip_id]
    deadlines = clip_deadlines(record, clip)  # P0 Step 4.3: this output's counted deadlines
    renders = {kind: render_ready(clip, routes) for kind, routes in RENDER_ROUTES.items()}
    encoded = encoding(clip)
    handoffs = _mine(verdicts['handoffs'], clip_id)
    visible = visible_mp4(handoffs, encoded)
    approval = editorial_approval(_mine(verdicts['finalReviews'], clip_id), encoded, record['status'] == 'closed')
    stamps = {'authorizedAt': _authorized_at(clip), 'firstAiDispatchAt': _first_dispatch(record, clip_id),
              'draftRenderReadyAt': renders['draft']['at'], 'finalRenderReadyAt': renders['final']['at'],
              'encodedAt': encoded['at'], 'visibleHandoffAt': visible['at'], 'editoriallyApprovedAt': approval['at']}
    return {'timestamps': stamps, 'preparation': preparation(deadlines, renders, elapsed), 'encoding': encoded,
            'visibleMp4': visible, 'matchingStudio': matching_studio(handoffs), 'editorialApproval': approval,
            'cleanup': cleanup(record, clip_id), 'slaMiss': sla(deadlines, visible, encoded['at'], elapsed)}
