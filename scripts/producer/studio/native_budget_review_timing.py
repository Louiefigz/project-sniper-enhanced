"""When an editorial final was approved, on the batch clock: seam (e) with unit I-B123.

A schema-2 FINAL-REVIEW submission of a batch-bound final-critic packet carries
``timing {basis: 'batch-authority', batchId, clipId, resolvedElapsed, submittedElapsed}``: the
batch-clock second at which the authority recorded the packet's resolution (the trail's
``packet-resolved`` event, ``studio.production.packets``) and the batch clock the submission read
when it was written. check-final has already re-checked that timing against the authority; this
reads it from the same bytes check-final accepted (``recordSha256`` equal to the bytes read here)
and cross-checks it against the trail this status observed:

- ``basis`` is ``batch-authority``, ``batchId`` is this batch and ``clipId`` the delivery's clip;
- the first ``packet-resolved`` event for ``submission.rolePacket.sha256`` names role
  ``final-critic`` and this clip, and its ``elapsed`` equals ``resolvedElapsed``.

``editoriallyApprovedAt`` is then ``submittedElapsed``, labelled as declared at submission (the
submission's own reading of the batch clock, not a trail event), with ``resolvedElapsed`` as its
trail-backed lower bound. A ``review-submitted`` trail event for the exact record bytes
(``recordSha256``, ``elapsed``; clip checked when named) is preferred when present: it is recorded
by the authority. No unit writes that event yet; it is read if present and never required.
A submission that reads a batch clock later than this observation is flagged, not refused (it
was checked by check-final against a later clock).
"""
from __future__ import annotations

import math

from studio.native_budget_evidence import mapping, require

PACKET_EVENT, SUBMITTED_EVENT, FINAL_ROLE = 'packet-resolved', 'review-submitted', 'final-critic'
DECLARED = 'declared at submission (submission.timing.submittedElapsed on the batch clock)'
RECORDED = 'recorded by the authority (review-submitted trail event)'
LOWER_BOUND = 'trail-backed lower bound: the packet-resolved event of the reviewed packet'


def _seconds(value: object) -> bool:
    """A finite, non-negative batch-clock second."""
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def submission_timing(record: dict, value: dict, clip_id: str) -> dict:
    """The submission's batch-clock timing, bound to this batch and this delivery's clip."""
    submission = mapping(value.get('submission'))
    timing = mapping(submission.get('timing'))
    require(timing.get('basis') == 'batch-authority',
            f'the review is not timed on the batch clock (submission.timing.basis {timing.get("basis")!r})')
    require(timing.get('batchId') == record['batchId'],
            f'the review is timed on batch {timing.get("batchId")!r}, not {record["batchId"]}')
    require(timing.get('clipId') == clip_id, f'the review is timed for clip {timing.get("clipId")!r}, not {clip_id}')
    resolved, submitted = timing.get('resolvedElapsed'), timing.get('submittedElapsed')
    require(_seconds(resolved) and _seconds(submitted) and resolved <= submitted,
            'submission.timing is not batch-clock seconds with the submission after the resolution')
    return {'resolvedElapsed': resolved, 'submittedElapsed': submitted,
            'packetSha256': mapping(submission.get('rolePacket')).get('sha256')}


def _resolution(events: tuple[dict, ...], timing: dict, clip_id: str) -> None:
    """The trail's first packet-resolved event for the reviewed packet agrees with the submission's timing."""
    first = next((row for row in events if row.get('event') == PACKET_EVENT
                  and row.get('packetSha256') == timing['packetSha256']), None)
    require(first is not None, 'the observed trail holds no packet-resolved event for the review\'s role packet')
    require((first.get('role'), first.get('clipId')) == (FINAL_ROLE, clip_id),
            f'the trail resolved the review\'s packet for {first.get("role")!r} on clip {first.get("clipId")!r}, '
            f'not {FINAL_ROLE} on {clip_id}')
    require(first.get('elapsed') == timing['resolvedElapsed'],
            'submission.timing.resolvedElapsed disagrees with the recorded packet-resolved event')


def _recorded(events: tuple[dict, ...], digest: str, clip_id: str, timing: dict) -> float | None:
    """The batch time of a review-submitted event for exactly these record bytes, when one was recorded."""
    first = next((row for row in events if row.get('event') == SUBMITTED_EVENT
                  and row.get('recordSha256') == digest), None)
    if first is None:
        return None
    require(first.get('clipId') in (None, clip_id), f'the review-submitted event names clip {first.get("clipId")!r}')
    require(_seconds(first.get('elapsed')) and first['elapsed'] >= timing['resolvedElapsed'],
            'the review-submitted event is not a batch time after the packet\'s resolution')
    return first['elapsed']


def approval_time(record: dict, value: dict, digest: str, trail: tuple[str, tuple[dict, ...]]) -> dict:
    """When this editorial final was approved on the batch clock. trail = (the delivery's clip, observed events)."""
    clip_id, events = trail
    timing = submission_timing(record, value, clip_id)
    _resolution(events, timing, clip_id)
    recorded = _recorded(events, digest, clip_id, timing)
    at = recorded if recorded is not None else timing['submittedElapsed']
    return {'approvedAt': at, 'basis': RECORDED if recorded is not None else DECLARED,
            'declaredSubmittedElapsed': timing['submittedElapsed'], 'resolvedElapsed': timing['resolvedElapsed'],
            'lowerBound': LOWER_BOUND, 'aheadOfObservation': at > record['clock']['elapsed']}
