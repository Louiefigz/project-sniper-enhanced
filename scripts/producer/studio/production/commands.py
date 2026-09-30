"""The batch commands of ``native_batch.py``: start, bind, admit, status, wait, hold, hand-off, close, archive.

Moved out of the entry script unchanged in behaviour except these points: ``start`` requires the
operator's approved titles and scripts (``inputs.load_approvals``) and binds them at the
authorization instant (without them it is refused, exit 3, before anything is written) and
declares the run's AI slots and reservations within the policy maximum
(``native_budget_schema.AI_POLICY``); ``handoff`` requires a visible hand-off confirmation that
unit B3's verifier accepts (``handoff``); ``status`` reports each output's state and milestones and the
run's tasks, usage and dispatcher (``native_budget_status``).
add-clip, change-approval and the staged-start commands are in ``handover_commands``. Every
handler reads the authority root from ``native_budget_store.default_root`` at call time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from studio import native_budget_engine as engine
from studio import native_budget_forecast as forecast
from studio import native_budget_status as status
from studio import native_budget_store as store
from studio.native_budget_batches import archive_batch
from studio.native_budget_binding import BudgetRefused, advance_clock, bind_project
from studio.native_budget_launch import reconcile_running
from studio.native_budget_policy import BatchSpec, admit_dispatch, charge, clip_record
from studio.native_budget_report import batch_status
from studio.native_budget_schema import AI_POLICY, BOUNDS, DEADLINES, LIMITS
from studio.native_budget_store import BudgetAuthorityError, locked_batch, read_batch, require_clip_id
from studio.production import api, dispatch, handoff, inputs
from studio.production.authorization import Setup, authorize, complete_setup
from studio.production.handover_commands import NO_APPROVALS
from studio.production.lifecycle import freeze
from studio.production.tasks import TaskConflict

REPO = Path(__file__).resolve().parents[4]
AI_SOURCE = 'native_budget_schema.AI_POLICY (the engine\'s policy ceiling; no host record qualifies AI concurrency)'


def source_digests(sources: list[Path]) -> list[str]:
    """Hash every named source; this runs after authorization, inside the batch clock."""
    digests = []
    for source in sources:
        with source.resolve(strict=True).open('rb') as handle:
            digests.append(hashlib.file_digest(handle, 'sha256').hexdigest())
    return sorted(set(digests))


def ai_spec(args: argparse.Namespace) -> tuple[int, int | None]:
    """The run's declared AI slots (director included) and reservations; above the policy maximum is refused."""
    slots = AI_POLICY['defaultSlots'] if args.ai_slots is None else args.ai_slots
    if not 1 <= slots <= AI_POLICY['slotsCeiling']:
        raise BudgetRefused(f'--ai-slots {slots} is refused: the maximum is {AI_POLICY["slotsCeiling"]} concurrent AI '
                            f'slots, director included ({AI_SOURCE})')
    reservations = args.ai_reservations
    if reservations is not None and not 1 <= reservations <= AI_POLICY['reservationsCeiling']:
        raise BudgetRefused(f'--ai-reservations {reservations} is refused: the maximum is '
                            f'{AI_POLICY["reservationsCeiling"]} AI tasks per run ({AI_SOURCE})')
    return slots, reservations


def _recorded_ai(batch_id: str, requested: tuple[int, int | None]) -> dict:
    """The run's recorded AI allowance; a resumed authorization recorded with other values is refused."""
    ai = read_batch(store.default_root(), batch_id)['production']['ai']
    if ai['slots'] != requested[0] or requested[1] not in (None, ai['reservations']):
        raise TaskConflict(f'Batch {batch_id} was authorized with {ai["slots"]} AI slots and {ai["reservations"]} '
                           'reservations; start it again as recorded')
    return {'slots': ai['slots'], 'reservations': ai['reservations'], 'slotsMaximum': AI_POLICY['slotsCeiling'],
            'reservationsMaximum': AI_POLICY['reservationsCeiling'], 'maximumSource': AI_SOURCE,
            'hostQualified': False}


def cmd_start(args: argparse.Namespace) -> dict:
    """Authorize first (the clock starts, durable, with the approvals bound), then capacity, hashing, engine.

    Approvals and the AI declaration are checked before authorization (a refusal writes nothing). A
    failed setup keeps the authorization and its clock; running the same start again resumes it.
    """
    clips = tuple(require_clip_id(item) for item in args.clips.split(',') if item)
    approvals = inputs.load_approvals(args.approval or [], args.approvals, clips)
    if approvals is None:
        raise BudgetRefused(NO_APPROVALS.format(what='starting a batch without them',
                                                how='give --approval CLIP=FILE per clip or --approvals FILE'))
    ai = ai_spec(args)
    authorized = authorize(store.default_root(), BatchSpec(args.batch, clips, (), 1, ai[0], ai[1], approvals))
    ai_allowance = _recorded_ai(args.batch, ai)
    capacity = forecast.heavy_lane_capacity()
    slots = capacity if args.pool_slots is None else args.pool_slots
    if slots > capacity:
        raise BudgetRefused(f'--pool-slots {slots} is refused: this host\'s pool qualification record admits '
                            f'{capacity} heavy job(s) at a time (native_work_qualification via '
                            'native_budget_forecast.heavy_lane_capacity); more would make every forecast optimistic')
    claims = source_digests(args.source or [])
    identity = engine.engine_identity(REPO)
    setup = complete_setup(store.default_root(), args.batch, Setup(tuple(claims), slots, identity))
    return {'status': 'batch-started', 'batchId': args.batch, 'clips': list(clips), 'claimedSources': claims,
            'engine': identity, 'deadlines': dict(DEADLINES), 'limits': dict(LIMITS), 'ai': ai_allowance,
            'poolSlots': slots, 'authorizedAtEpoch': authorized['authorizedAtEpoch'], 'resumed': authorized['resumed'],
            'setupElapsed': setup['setupElapsed'], 'approvalsBound': True}


def cmd_admit(args: argparse.Namespace) -> dict:
    """Admit and charge one agent dispatch, or refuse with the reason."""
    with locked_batch(store.default_root(), args.batch) as session:
        record = session.read()
        elapsed = advance_clock(record)
        decision = admit_dispatch(record, args.clip, args.kind, elapsed)
        if decision.allowed:
            clip = record['clips'][args.clip]
            charge(clip, args.kind)
            clip['dispatches'].append({'kind': args.kind, 'label': args.label, 'elapsed': elapsed})
        session.commit(record, {'event': 'dispatch-admitted' if decision.allowed else 'dispatch-refused',
                                'clipId': args.clip, 'kind': args.kind, 'label': args.label,
                                'elapsed': elapsed, 'reason': decision.reason})
    if not decision.allowed:
        raise BudgetRefused(decision.reason)
    return {'status': 'admitted', 'clipId': args.clip, 'kind': args.kind, 'elapsed': round(elapsed, 1),
            **decision.detail}


def observed_record(batch_id: str) -> tuple[dict, float]:
    """Lock, advance the clock, mark provably dead launches abandoned, persist."""
    with locked_batch(store.default_root(), batch_id) as session:
        record = session.read()
        elapsed = advance_clock(record)
        abandoned = reconcile_running(record, elapsed)
        session.commit(record, {'event': 'observed', 'elapsed': elapsed, 'abandoned': abandoned})
    return record, elapsed


def cmd_status(args: argparse.Namespace) -> dict:
    """Counters, forecasts and actions, each output's state and milestones, and the run's tasks, usage and
    dispatcher (``native_budget_status``; the record and its trail are read under one batch lock)."""
    record, elapsed, events = status.status_observation(store.default_root(), args.batch)
    dispatcher = dispatch.status(store.default_root(), args.batch)
    return status.production_status(record, elapsed, status.status_inputs(args, events, dispatcher))


def progress_key(record: dict, clip: str | None, until: str) -> str:
    """Attempt outcomes (any terminal state wakes) and deliveries for the wait condition."""
    clips = {key: value for key, value in record['clips'].items() if not clip or key == clip}
    if until == 'delivery':
        return json.dumps({key: (len(value['deliveries']),
                                 [row['status'] for row in value['attempts'] if row['status'] != 'running'])
                           for key, value in clips.items()})
    return json.dumps({key: ([(row['id'], row['status']) for row in value['attempts']], len(value['deliveries']))
                       for key, value in clips.items()})


def cmd_wait(args: argparse.Namespace) -> dict:
    """Block (no model calls) until the condition changes or the bounded timeout expires."""
    until = time.monotonic() + min(args.timeout, 1800)
    baseline = progress_key(observed_record(args.batch)[0], args.clip, args.until)
    while time.monotonic() < until:
        time.sleep(2)
        record, elapsed = observed_record(args.batch)
        if progress_key(record, args.clip, args.until) != baseline:
            return {'waitResult': 'changed', 'batch': batch_status(record, elapsed)}
    record, elapsed = observed_record(args.batch)
    return {'waitResult': 'timeout', 'batch': batch_status(record, elapsed)}


def cmd_hold(args: argparse.Namespace) -> dict:
    """Operator-requested holds are shown separately and never subtract elapsed time."""
    with locked_batch(store.default_root(), args.batch) as session:
        record = session.read()
        elapsed = advance_clock(record)
        refusal = _hold_refusal(record['holds'], args.action)
        if refusal:
            raise BudgetRefused(refusal)
        if args.action == 'start':
            record['holds'].append({'startElapsed': elapsed, 'endElapsed': None, 'reason': args.reason})
        else:
            record['holds'][-1]['endElapsed'] = elapsed
        session.commit(record, {'event': f'hold-{args.action}', 'elapsed': elapsed, 'reason': args.reason})
    return {'status': f'hold-{args.action}', 'elapsed': round(elapsed, 1), 'holds': record['holds']}


def _hold_refusal(holds: list[dict], action: str) -> str | None:
    """Holds alternate start/end and are bounded."""
    open_hold = bool(holds) and holds[-1]['endElapsed'] is None
    if action == 'start' and open_hold:
        return 'A hold is already open'
    if action == 'start' and len(holds) >= BOUNDS['holds']:
        return 'The batch already has the maximum number of holds'
    if action == 'end' and not open_hold:
        return 'No open hold to end'
    return None


def cmd_handoff(args: argparse.Namespace) -> dict:
    """End autonomous work on a clip once its delivered MP4 and matching Studio view were visibly handed off.

    Requires the ``native_handoff.py confirm`` record (``visible-handoff``) that B3's verifier accepts,
    bound to the views-ready record of one of this clip's deliveries whose MP4 still re-hashes, with
    ``visibleHandoffAt`` between that delivery's completion on the batch clock and now. A clip is
    handed off once.
    """
    try:
        evidence = handoff.handoff_evidence(args.confirmation)
        if evidence['level'] != handoff.VISIBLE:
            raise handoff.HandoffEvidenceError(
                'a views-ready record is matching Studio, server-verified, not a visible hand-off: open the pages '
                'for the operator, run native_handoff.py confirm and pass its confirmation record')
    except handoff.HandoffEvidenceError as error:
        raise BudgetRefused(f'Handoff needs a visible hand-off confirmation: {error}') from error
    with locked_batch(store.default_root(), args.batch) as session:
        record = session.read()
        elapsed = advance_clock(record)
        clip = clip_record(record, require_clip_id(args.clip))
        delivery = _handoff_delivery(record, clip, evidence)
        clip['state'] = 'handed-off'
        frozen = freeze(record, args.clip, 'clip handed off', elapsed)
        summary = {key: evidence[key] for key in ('record', 'confirmation', 'mp4', 'viewsVerifiedAt',
                                                  'visibleHandoffAt')}
        session.commit(record, {'event': 'clip-handed-off', 'clipId': args.clip, 'elapsed': elapsed,
                                'delivery': delivery, 'frozenTasks': frozen, 'handoff': summary})
    return {'status': 'handed-off', 'clipId': args.clip, 'elapsed': round(elapsed, 1), 'delivery': delivery,
            'frozenTasks': frozen, 'handoff': summary}


def _handoff_delivery(record: dict, clip: dict, evidence: dict) -> dict:
    """The clip's delivery the confirmation hands off, checked against the batch clock; refusals raise."""
    if clip['state'] == 'handed-off':
        raise BudgetRefused('This clip is already handed off; a clip is handed off once')
    try:
        delivery = handoff.matching_delivery(evidence, clip['deliveries'])
    except handoff.HandoffEvidenceError as error:
        raise BudgetRefused(f'Handoff needs a delivered complete MP4 of this clip: {error}') from error
    problem = handoff.visible_time_problem(evidence, delivery, (record['startEpoch'], time.time()))
    if problem:
        raise BudgetRefused(f'Handoff refused: {problem} (on this batch\'s clock)')
    return delivery


def cmd_close(args: argparse.Namespace) -> dict:
    """Close when every clip is handed off or the deadline passed, listing unresolved work in the closure; while
    media work is live or a media launch runs, drain instead and run close again once it ends.

    Nothing is released: the closure and the host record keep the unresolved work's reservations (X25, X37).
    """
    result = api.close(store.default_root(), args.batch)
    record = read_batch(store.default_root(), args.batch)
    return {**batch_status(record, advance_clock(record)), 'unsettledTasks': result['unsettled'],
            'runningAttempts': result['runningAttempts']}


def cmd_bind(args: argparse.Namespace) -> dict:
    """Bind a native project folder to its logical clip."""
    project = args.project.resolve(strict=True)
    bind_project(store.default_root(), args.batch, require_clip_id(args.clip), project)
    return {'status': 'bound', 'batchId': args.batch, 'clipId': args.clip, 'project': str(project)}


def cmd_archive(args: argparse.Namespace) -> dict:
    """Move a closed batch out of resolution (explicit release); its record and trail are kept."""
    try:
        observed_record(args.batch)  # mark provably dead launches abandoned first (this engine's records)
    except BudgetAuthorityError:
        pass  # another engine version's record: archive_batch decides from its own status
    record = archive_batch(store.default_root(), args.batch, args.reason)
    return {'status': 'archived', 'batchId': args.batch, 'reason': args.reason,
            'closedAtElapsed': record.get('closedAtElapsed')}
