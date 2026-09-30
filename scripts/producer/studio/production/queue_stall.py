"""The named ``capacity-stalled`` state of a Short's v2 clock (P1 Step B7, C2, as X19 and G1 correct it; M-050).

A verified capacity wait keeps earning credit for as long as it stays verified: time passing never stops it (X19).
When the live occupants behind a Short's verified waits have not changed for ``stall_seconds()`` (the longest
admissible render plus cleanup, derived from policy), the Short is named ``capacity-stalled``: a holder has held
the capacity longer than any legitimate render, so it is past its grant or not progressing. Status names the
holders and points to their watchdog, which stops a stuck render and releases its resources only on verified
cleanup, else quarantines them (G9). The state clears by itself when the occupants change or the verified wait
ends, a watchdog's settlement of the waiting owner included; a handed-off Short is not stalled (X184 m2). The
operator's one decision is ``cancel`` (``capacity-stall --clip ID --decision cancel --reason TEXT``): it freezes the
Short's work and closes it out for good. While a Short is stalled and not cancelled, the batch cannot close
(``close_refusal``), so a stalled Short never loses its authorization to a closing batch.

The stall's ``occupants`` are the sorted union of every verified waiting row's occupants, cut at
``MAX_STALL_OCCUPANTS`` with ``truncated`` true (X95, X98); the fingerprint hashes the full union, so a changed
set is still seen. A truncated stall is never credited (``suppressed``): its interval counts on the clock (fail
closed); nor is a cancelled Short, truncated or not (X184 m3). ``occupants`` and ``truncated`` are cleared
together on resume (X102). v1 clocks never stall.
"""
from __future__ import annotations

import functools
import hashlib
import json
from dataclasses import dataclass

from studio.production.host_contract import clip_text
from studio.production.queue_clock_schema import MAX_STALL_OCCUPANTS, POLICY

STALLED, CANCELLED = 'capacity-stalled', 'cancelled'
DECISIONS = ('cancel',)


@functools.lru_cache(maxsize=1)
def stall_seconds() -> float:
    """The policy-derived bound: the longest admissible render (a Short's delivery window or a 900 s Long's
    final forecast, whichever is longer) plus the cleanup reserve. It moves with the policy, never by hand."""
    from studio.native_budget_schema import DEADLINES
    from studio.production.formats import LONG_POLICY, long_demand
    longest = long_demand(LONG_POLICY['maxOutputSeconds'])['finalSeconds']
    return max(DEADLINES['deliverySeconds'], longest) + DEADLINES['cleanupReserveSeconds']


def _union(clock: dict) -> list[str]:
    """The sorted union of the occupants of every verified waiting row of the clip."""
    from studio.production.queue_clock import verified_wait
    return sorted({name for row in clock['workers'].values() if row['state'] == 'waiting' and verified_wait(row)
                   for name in row['occupants']})


def _fingerprint(names: list[str]) -> str | None:
    """sha256 of the full sorted union; None while no verified wait remains."""
    return hashlib.sha256(json.dumps(names).encode()).hexdigest() if names else None


def track(clock: dict, elapsed: float) -> str | None:
    """Update the occupancy window and the stall after an observation of a v2 clock; 'stalled', 'cleared' or None.

    A changed occupant set (or the end of every verified wait) starts a new window and clears a stall. An
    unchanged set held for ``stall_seconds()`` names the Short ``capacity-stalled``. A cancelled stall never
    changes again, and a v1 clock is never tracked.
    """
    stall = clock.get('stall')
    if clock.get('policy') != POLICY or stall['state'] == CANCELLED:
        return None
    names = _union(clock)
    fingerprint, occupancy = _fingerprint(names), clock['occupancy']
    if fingerprint != occupancy['fingerprint']:
        clock['occupancy'] = {'fingerprint': fingerprint, 'sinceElapsed': elapsed}
        if stall['state'] == STALLED:
            stall.update(state=None, sinceElapsed=None, occupants=[], truncated=False)
            return 'cleared'
        return None
    if fingerprint is None or stall['state'] is not None or elapsed - occupancy['sinceElapsed'] < stall_seconds():
        return None
    stall.update(state=STALLED, sinceElapsed=elapsed, occupants=names[:MAX_STALL_OCCUPANTS],
                 truncated=len(names) > MAX_STALL_OCCUPANTS)
    return 'stalled'


def suppressed(clock: dict) -> bool:
    """No credit while a stall's occupant list is cut (X98 M1, fail closed), nor ever after the operator's cancel,
    truncated or not (X184 m3): the Short was given up. The interval stays counted."""
    stall = clock.get('stall') or {}
    return stall.get('state') == CANCELLED or (stall.get('state') == STALLED and stall.get('truncated') is True)


def state(clip: dict) -> str | None:
    """The stall state of a v2 Short (None, ``capacity-stalled`` or ``cancelled``); None for any other clip."""
    clock = clip.get('capacityClock') or {}
    return clock['stall']['state'] if clock.get('policy') == POLICY else None


def closed_out(clip: dict) -> bool:
    """A Short whose stalled capacity wait the operator cancelled: closed for new work, never open again."""
    return state(clip) == CANCELLED


def stalled(clip: dict) -> bool:
    """A v2 Short named ``capacity-stalled``, not cancelled and not handed off (then nothing is left to protect,
    X184 m2)."""
    return state(clip) == STALLED and clip['state'] != 'handed-off'


def shown_state(clip: dict) -> str | None:
    """The state status reports: a handed-off Short's leftover ``capacity-stalled`` row is not a stall, as close and
    the actions already treat it (X190 s1)."""
    named = state(clip)
    return None if named == STALLED and not stalled(clip) else named


def cancelled_refusal(record: dict, clip: dict) -> str:
    """``phase_refusal``'s text for a Short the operator cancelled, naming it (X184 n1). The Short is the record's
    own clip, or failing that the equal one, so a copied clip is named too (X190 n3)."""
    names = [clip_id for clip_id, row in record['clips'].items() if row is clip] \
        or [clip_id for clip_id, row in record['clips'].items() if row == clip]
    return (f"Short {', '.join(names)}'s stalled capacity wait was cancelled by the operator; no new work is "
            'admitted for it')


def close_refusal(record: dict, elapsed: float) -> str | None:
    """A batch cannot close while a Short is capacity-stalled without a recorded cancel (X19, G1)."""
    from studio.production.queue_clock import status
    for clip_id, clip in record['clips'].items():
        if stalled(clip):
            counted = status(clip, elapsed)['countedProductionSeconds']
            return (f'Short {clip_id} is capacity-stalled with {counted:.0f}s counted and its authorization intact: '
                    f'the operator\'s cancel closes around it (capacity-stall --clip {clip_id} --decision cancel '
                    '--reason …); otherwise keep the batch open until its waits end (a dead owner\'s once '
                    'recovered or settled)')
    return None


def action(clip_id: str, clip: dict) -> str | None:
    """The first next action of a stalled Short: its holders, their watchdog, and the operator's one decision."""
    if not stalled(clip):
        return None
    stall = clip['capacityClock']['stall']
    holders = ', '.join(stall['occupants']) + (' …' if stall['truncated'] else '')
    return (f'Capacity stalled since {stall["sinceElapsed"]:.0f}s behind {holders}: a holder past its grant or not '
            'progressing is stopped by its watchdog (verified cleanup frees its slot, otherwise it is quarantined; '
            f'recover with native_work_recovery.py <nonce>). To give this Short up: native_batch.py capacity-stall '
            f'--clip {clip_id} --decision cancel --reason …; otherwise it resumes when capacity frees')


@dataclass(frozen=True)
class StallDecision:
    """The operator's decision on a stalled Short: ``cancel`` and the reason recorded with it."""

    kind: str
    reason: str


def decide(record: dict, clip_id: str, decision: StallDecision, elapsed: float) -> object:
    """Record the operator's cancel of a stalled Short: freeze its work and close it out (an ``Outcome``)."""
    from studio.production.claims import Outcome
    from studio.production.lifecycle import freeze
    from studio.production.tasks import TaskRefused
    if decision.kind not in DECISIONS or type(decision.reason) is not str or not decision.reason.strip():
        raise ValueError('A capacity-stall decision is cancel, with the operator\'s reason')
    clip = record['clips'].get(clip_id)
    if clip is None or not stalled(clip):
        raise TaskRefused(f'Short {clip_id} is not capacity-stalled')
    reason = clip_text(decision.reason)
    frozen = freeze(record, clip_id, f'operator cancelled a stalled capacity wait: {reason}', elapsed)
    stall = clip['capacityClock']['stall']
    stall.update(state=CANCELLED, decisions=[{'kind': decision.kind, 'reason': reason, 'elapsed': elapsed}])
    return Outcome(True, {'event': 'capacity-stall-decided', 'clipId': clip_id, 'kind': decision.kind,
                          'reason': reason, 'state': CANCELLED, 'frozen': frozen},
                   {'clipId': clip_id, 'state': CANCELLED, 'frozen': frozen})
