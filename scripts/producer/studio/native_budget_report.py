"""Batch status: remaining time, per-output counters, forecasts and required actions.

The coordinator reads this instead of reconstructing state from history. It
states SLA misses plainly: an output without a delivery made by its own deadline
(a Short's minute 40, a Long's 180 minutes) is a miss, never a success because
work stopped on time or finished late. Each output is reported under its own
format policy; a run holding a Long also reports the mixed forecast. That
``slaMiss`` is necessary, not sufficient: the SLA is a visible hand-off, which
``native_budget_status.production_status`` (``native_batch.py status``) reports per
output beside it. ``wait`` and ``close`` keep this authority-only ``batch_status``.
"""
from __future__ import annotations

from studio.native_budget_forecast import launch_fits
from studio.production.formats import (
    LONG_POLICY, clip_deadlines, clip_limits, clip_rates, is_mixed, long_demand, long_latest_starts, output_format,
)

ROUTES = ('preview', 'final', 'draft', 'promote')
LONG_ROUTES = ('preview', 'final')
HANDOFF = ('open the delivered MP4 and its Studio project, then record the visible hand-off with native_batch.py '
           'handoff --confirmation <its visible-handoff confirmation record>')


def batch_status(record: dict, elapsed: float, audit: dict | None = None) -> dict:
    """Summarize the authoritative record at one observed elapsed time (``audit``: ``queue_audit.capacity_audit``)."""
    deadlines = clip_deadlines(record, None)  # a Shorts-only run: exactly its batch deadlines
    authorization = record['production']['authorization']
    clips = {clip_id: clip_status(record, clip_id, elapsed, audit) for clip_id in record['clips']}
    status = {'batchId': record['batchId'], 'status': record['status'],
              'elapsedSeconds': round(elapsed, 1), 'phase': phase(record, elapsed),
              'preparationRemainingSeconds': round(deadlines['preparationSeconds'] - elapsed, 1),
              'deliveryRemainingSeconds': round(deadlines['deliverySeconds'] - elapsed, 1),
              'poolSlots': record['poolSlots'], 'engineIdentity': (record['engine'] or {}).get('identity'),
              'holds': record['holds'], 'forecastRates': record['rates']['source'],
              'clips': clips, 'slaMisses': [clip_id for clip_id, row in clips.items() if row['slaMiss']],
              'actions': [f'{clip_id}: {action}' for clip_id, row in clips.items() for action in row['actions']]}
    status.update(priorAuthorizations=authorization['prior'],
                  priorAuthorizationsOmitted=authorization['priorOmitted'])
    status['actions'] += prior_actions(authorization)
    if is_mixed(record):
        from studio.production.mixed_forecast import mixed_status
        status.update(mixed=mixed_status(record, elapsed), longForecastRates=LONG_POLICY['rates']['source'])
    return status


def phase(record: dict, elapsed: float, clip: dict | None = None) -> str:
    """Name the schedule phase the batch (or one output, on its own clock) is in."""
    deadlines = clip_deadlines(record, clip)
    if record['status'] in ('closed', 'draining'):
        return record['status']
    if elapsed >= deadlines['deliverySeconds']:
        return 'past-delivery-deadline'
    if elapsed >= deadlines['preparationSeconds']:
        return 'export-and-handoff'
    if elapsed >= deadlines['draftDecisionSeconds']:
        return 'draft-decision'
    return 'preparation'


def on_time(record: dict, clip: dict) -> list[dict]:
    """Deliveries made by the output's own delivery deadline."""
    from studio.production.queue_clock import delivery_deadline
    return [row for row in clip['deliveries'] if row['elapsed'] <= delivery_deadline(record, clip, row)]


def forecasts(record: dict, clip_id: str, elapsed: float) -> dict | None:
    """Queue-aware route forecasts, or None while the output's duration is unknown."""
    clip = record['clips'][clip_id]
    long = output_format(clip) == 'long'
    seconds = clip['output']['outputSeconds'] if long and clip['outputSeconds'] is None else clip['outputSeconds']
    if seconds is None and not long:
        from studio.native_budget_policy import approved_seconds
        seconds = approved_seconds(record, clip_id)
    if seconds is None:
        return None
    return {route: launch_fits(record, (clip_id, route, seconds), elapsed) for route in (LONG_ROUTES if long else ROUTES)}


def _format_status(record: dict, clip: dict) -> dict:
    """The output's format, own clock and deadlines, and (a Long) its forecast demand and evidence."""
    row, deadlines = clip.get('output'), clip_deadlines(record, clip)
    status = {'format': output_format(clip), 'clock': 'own' if row else 'batch',
              'authorizedElapsed': row['authorizedElapsed'] if row else None,
              'preparationElapsed': deadlines['preparationSeconds'], 'deadlineElapsed': deadlines['deliverySeconds'],
              'derivedFrom': row['derivedFrom'] if row else None, 'forecastRates': clip_rates(record, clip)['source']}
    if row and row['format'] == 'long':
        status.update(lineage=row['lineage'], demand=long_demand(row['outputSeconds']))
    return status


def clip_status(record: dict, clip_id: str, elapsed: float, audit: dict | None = None) -> dict:
    """One output's counters, current launch, deliveries and next actions.

    ``creditVerified`` says whether ``audit`` (``queue_audit.capacity_audit``, passed in: this never reads the
    trail) found the Short's settled credit consistent with its trail; None when the clip was not audited.
    """
    clip = record['clips'][clip_id]
    limits = clip_limits(record, clip)
    running = [row for row in clip['attempts'] if row['status'] == 'running']
    failures = [row for row in clip['attempts'] if row['status'] in ('failed', 'abandoned')]
    fits = forecasts(record, clip_id, elapsed)
    miss = elapsed >= clip_deadlines(record, clip)['deliverySeconds'] and not on_time(record, clip) \
        or long_final_missed(record, clip_id, elapsed)
    from studio.production.queue_clock import status as clock_status
    return {**clock_status(clip, elapsed), 'state': clip['state'], 'addedAfterStart': clip['addedAfterStart'],
            'outputSeconds': clip['outputSeconds'], **_format_status(record, clip), 'phase': phase(record, elapsed, clip),
            'counters': {key: f'{value}/{limits[key]}' if key in limits else value
                         for key, value in clip['counters'].items()},
            'projects': [row['path'] for row in clip['projects']],
            'runningAttempt': running[-1] if running else None, 'runningRoutes': [row['route'] for row in running],
            'lastFailure': failures[-1] if failures else None, 'deliveries': clip['deliveries'],
            'forecast': fits, 'slaMiss': miss, 'creditVerified': _credit_verified(audit, clip_id),
            'actions': actions(record, clip_id, fits, (elapsed, running))}


def _credit_verified(audit: dict | None, clip_id: str) -> bool | None:
    """True or False for an audited clip (only ``consistent`` is verified); None when it was not audited."""
    row = (audit or {}).get(clip_id)
    return None if row is None else row['status'] == 'consistent'


def actions(record: dict, clip_id: str, fits: dict | None, context: tuple) -> list[str]:
    """Plain next steps derived from deadlines, forecasts and delivery state.

    A running full-program launch is the clip's MP4 in flight, so it silences advice; a running
    moving preview does not, since a review draft may run beside it.
    """
    elapsed, running = context
    clip = record['clips'][clip_id]
    deadlines, long = clip_deadlines(record, clip), output_format(clip) == 'long'
    if clip['state'] == 'handed-off' or any(row['route'] != 'preview' for row in running):
        return []
    if on_time(record, clip):
        return [HANDOFF] if long else _delivered_advice(record, clip, fits)
    if long_final_missed(record, clip_id, elapsed):
        return ['SLA MISS: no final of this Long can still end before its hand-off reserve (a Long has no draft '
                'route); report the miss now, do not render late']
    if elapsed >= deadlines['deliverySeconds']:
        limit = 'its 180 minutes' if long else 'minute 40'
        return [f'SLA MISS: no complete MP4 by {limit}; report the cause, do not continue autonomously']
    if fits is None:
        return (['bind a built project so forecasts can be computed']
                if elapsed >= deadlines['draftDecisionSeconds'] else [])
    return long_actions(record, clip_id, elapsed) if long else _timed_actions(deadlines, fits, elapsed)


def _projects(attempts: list[dict], route: str, status: str) -> set[str]:
    """Projects with an attempt of this route in this state."""
    return {row['project'] for row in attempts if row['route'] == route and row['status'] == status}


def _delivered_advice(record: dict, clip: dict, fits: dict | None) -> list[str]:
    """An on-time clip: promote its delivered draft, wait for a running same-project preview, or hand off."""
    attempts = clip['attempts']
    drafts = _projects(attempts, 'draft', 'succeeded')
    if any(row['route'] == 'promote' for row in attempts) or not drafts:
        return [HANDOFF]
    if drafts & _projects(attempts, 'preview', 'running'):
        return ['a moving preview of the delivered draft\'s project is running: wait for its motion review, '
                'then promote the draft or hand it off']
    if not drafts & _projects(attempts, 'preview', 'succeeded'):
        return [HANDOFF]
    if clip['counters']['exportAttempt'] >= record['limits']['exportAttempt']:
        return ['no full-program launch is left to promote the delivered draft; ' + HANDOFF]
    if not (fits and fits['promote']['fits']):
        return ['a promotion of the delivered draft no longer fits; ' + HANDOFF]
    return ['when the moving preview\'s motion review passes, promote the draft (--promote-draft); otherwise '
            + HANDOFF]


def _long_state(record: dict, clip_id: str) -> tuple[dict, float, bool]:
    """(clip, the seconds its forecasts use, whether a preview of it ran or runs)."""
    clip = record['clips'][clip_id]
    seconds = clip['outputSeconds'] or clip['output']['outputSeconds']
    previewed = any(row['route'] == 'preview' and row['status'] in ('running', 'succeeded') for row in clip['attempts'])
    return clip, seconds, previewed


def long_final_missed(record: dict, clip_id: str, elapsed: float) -> bool:
    """A Long whose final (its minimal deliverable) can no longer end before its hand-off reserve: a miss now.

    Without a preview yet, even one with no windows (early gates only) plus the final must fit; with one, the
    final must (queue and own forecast). Decided by the forecast, never by the preparation deadline alone.
    """
    clip = record['clips'][clip_id]
    if output_format(clip) != 'long' or clip['state'] == 'handed-off' or clip['deliveries'] \
            or any(row['route'] != 'preview' and row['status'] in ('running', 'succeeded') for row in clip['attempts']):
        return False
    clip, seconds, previewed = _long_state(record, clip_id)
    route, windows = ('final', None) if previewed else ('preview', 0.0)
    return not launch_fits(record, (clip_id, route, seconds, None, windows), elapsed)['fits']


def _clock_minute(clip: dict, elapsed: float) -> str:
    """A run-elapsed moment as a minute of the output's own clock."""
    return f'minute {(elapsed - clip["output"]["authorizedElapsed"]) / 60:.0f}'


def long_actions(record: dict, clip_id: str, elapsed: float) -> list[str]:
    """The Long's named next action while it can still be corrected: when its preview and final must launch.

    Latest starts exclude queueing (a busy pool makes them earlier). Once the whole-program-bound preview no
    longer fits, only a preview with fewer window seconds can still precede a final that fits.
    """
    clip, seconds, previewed = _long_state(record, clip_id)
    deadlines = clip_deadlines(record, clip)
    bound, fewest = long_latest_starts(deadlines, seconds), long_latest_starts(deadlines, seconds, 0.0)
    final = f'the final by {_clock_minute(clip, bound["latestFinalStart"])} of its clock'
    if previewed:
        return [f'long-final-at-risk: launch {final}; after that no MP4 can reach its hand-off by minute 180']
    if launch_fits(record, (clip_id, 'preview', seconds), elapsed)['fits']:
        return [f'long-final-deadline: the preview must launch by {_clock_minute(clip, bound["latestPreviewStart"])} '
                f'({bound["previewBasis"]}; with no windows at all, {_clock_minute(clip, fewest["latestPreviewStart"])}) '
                f'and {final}; after that no MP4 can reach its hand-off by minute 180']
    return [f'long-final-at-risk: a whole-program-bound preview no longer fits; the preview must launch with its '
            f'packet windows well before {_clock_minute(clip, fewest["latestPreviewStart"])} and {final}, or report '
            'the risk now']


def _timed_actions(deadlines: dict, fits: dict, elapsed: float) -> list[str]:
    """Draft/final advice once the clip's duration is known."""
    if not fits['final']['fits'] and not fits['draft']['fits']:
        return ['SLA RISK: no complete MP4 is forecast before the handoff reserve; launch the review '
                'draft immediately if any capacity exists and report the risk']
    if elapsed >= deadlines['draftDecisionSeconds'] and not fits['final']['fits']:
        return ['select the full-program review draft now (--review-draft); a final no longer fits']
    if elapsed >= deadlines['draftDecisionSeconds']:
        return ['launch the final export now or select the review draft; minute 20 has passed']
    return []


def prior_actions(authorization: dict) -> list[str]:
    """Earlier authorizations of this batch id that never became it: each is a miss of its own go time."""
    omitted = authorization['priorOmitted']
    return [f'PRIOR AUTHORIZATION MISSED: {row["name"]} was handed over at epoch {row["authorizedAtEpoch"]} and ended '
            f'{row["cause"]}; report it as a miss, this batch\'s clock does not replace it'
            for row in authorization['prior']] + ([f'{omitted} more prior authorizations were missed'] if omitted else [])
