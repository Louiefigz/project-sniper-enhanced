"""Review-only Long continuation of completed sections, under the original authority."""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json

from studio.native_budget_binding import advance_clock
from studio.native_budget_clock import BudgetExhausted
from studio.native_budget_launch import charge_admitted_nested, find_attempt
from studio.native_budget_policy import clip_record, phase_refusal
from studio.native_budget_registry import BudgetRefused, owner_binding, project_identity
from studio.native_budget_sections import inherited_allocation
from studio.native_budget_store import locked_batch
from studio.native_export_history import attempt_reservation, require_current_section_attempt
from studio.native_segments.owners import current_window, revision_windows
from studio.production.outputs import long_launch_binding
from studio.production.host_contract import clip_text
from studio.production.settlement import RESULT_TEXT_BYTES, launch_outcome


def reserve_section_review(prior: dict, project: Path, output: Path) -> dict:
    """Reserve no new render; every required original window must still be sealed and current."""
    prior_delivery = Path(prior['output']) / 'delivery.json'
    if prior_delivery.exists() and bound_json(prior_delivery).get('status') == 'native-long-checked-for-review':
        raise BudgetRefused('Original continuation already published checked delivery; reconcile authority before retry')
    binding = prior.get('productionBudget')
    if not binding or prior.get('revision', {}).get('mode') != 'initial-long':
        raise BudgetRefused('Review continuation requires a budgeted section export')
    if prior['project'] != str(project) or not revision_windows(prior):
        raise BudgetRefused('Review continuation cannot change the Long project or its section plan')
    with attempt_reservation(prior):
        require_current_section_attempt(prior)
        for window in revision_windows(prior):
            current_window(prior, f"segment-picture-{window['index']}")
    root = Path(binding['authority'])
    found = owner_binding(root, project)
    if not found or (found['batchId'], found['clipId']) != (binding['batchId'], binding['clipId']):
        raise BudgetRefused('Review continuation lost its original production authority')
    long_output = long_launch_binding(root, found, project_identity(project))
    return _reserve_review(root, {**binding, 'attemptId': binding.get('continuationOf') or binding['attemptId']},
                           (prior, output), long_output)


def _reserve_review(root: Path, binding: dict, paths: tuple, long_output: dict) -> dict:
    """Keep the original deadline and spent launch counters while recording the new review attempt."""
    prior, output = paths
    with locked_batch(root, binding['batchId']) as session:
        record = session.read()
        elapsed = advance_clock(record)
        attempt = find_attempt(record, binding['clipId'], binding['attemptId'])
        try:
            grant = review_grant(record, binding, elapsed)
        except (BudgetRefused, BudgetExhausted) as error:
            session.commit(record, {'event': 'section-review-refused', 'elapsed': elapsed, 'reason': str(error)})
            raise
        session.commit(record, {'event': 'section-review-continuation', 'elapsed': elapsed,
                                'attemptId': attempt['id'], 'priorOutput': prior['output'], 'output': str(output)})
    return {**binding, 'attemptId': None, 'continuationOf': attempt['id'], 'route': 'resume',
            'allocation': grant, 'longOutput': long_output, 'sealedSectionPlan': prior['revision']['identity'],
            'continuationOutput': str(output)}


def review_grant(record: dict, binding: dict, elapsed: float) -> dict:
    """A terminal original attempt permits only its remaining original allowance."""
    grant = inherited_allocation(record, binding, elapsed)
    clip = clip_record(record, binding['clipId'])
    refuse_delivered(clip, binding['attemptId'])
    refusal = phase_refusal(record, clip, elapsed)
    attempt = find_attempt(record, binding['clipId'], binding['attemptId'])
    if refusal or attempt['status'] == 'running':
        raise BudgetRefused(refusal or 'Original export has not settled; wait before review continuation')
    return grant


def require_review_only(request: dict, phases: list[str]) -> None:
    """Refuse fallback rendering if any saved section proof vanished or was incompatible."""
    binding = request.get('productionBudget') or {}
    if binding.get('continuationOf') and (phases or request['revision']['identity'] != binding['sealedSectionPlan']):
        raise BudgetRefused('Review-only continuation cannot launch missing or changed section media')


def record_review_outcome(request: dict, result: dict) -> None:
    """Record the continuation without rewriting the original failure or refunding its debit."""
    binding = request['productionBudget']
    with locked_batch(Path(binding['authority']), binding['batchId']) as session:
        record = session.read()
        elapsed = advance_clock(record)
        event = apply_review_outcome(record, request, result, elapsed)
        if event is not None:
            session.commit(record, event)


def apply_review_outcome(record: dict, request: dict, result: dict, elapsed: float) -> dict | None:
    """Apply one outcome in the caller's held authority lock; exact already-committed replay is harmless.

    The outcome line is a settling line, bounded for the trail's reserve (X217 M1): the result status, as text, is
    cut to ``RESULT_TEXT_BYTES`` as launch outcomes are, and the output path is on the continuation's own
    ``section-review-continuation`` line, not repeated here.
    """
    binding = request['productionBudget']
    if record['batchId'] != binding['batchId']:
        raise BudgetRefused('Review outcome received another production authority')
    clip = clip_record(record, binding['clipId'])
    find_attempt(record, binding['clipId'], binding['continuationOf'])
    if result['status'] == 'native-long-checked-for-review' and not append_delivery(clip, binding, result, elapsed):
        return None
    return {'event': 'launch-completed', 'kind': 'section-review-continuation',
            'attemptId': binding['continuationOf'], 'status': clip_text(str(result['status']), RESULT_TEXT_BYTES),
            'elapsed': elapsed}


def append_delivery(clip: dict, binding: dict, result: dict, elapsed: float) -> bool:
    """One checked delivery per original attempt; only its exact committed receipt can be replayed."""
    delivery = launch_outcome(result, ())['delivery']
    row = {**delivery, 'attemptId': binding['continuationOf'], 'elapsed': elapsed}
    comparable = {key: value for key, value in row.items() if key != 'elapsed'}
    if any({key: value for key, value in item.items() if key != 'elapsed'} == comparable for item in clip['deliveries']):
        return False
    refuse_delivered(clip, binding['continuationOf'])
    if any(item['output'] == row['output'] for item in clip['deliveries']):
        raise BudgetRefused('Review continuation output belongs to another recorded delivery')
    clip['deliveries'].append(row)
    return True


def charge_review_audio(request: dict, kind: str, audio_key: str | None) -> None:
    """Charge fresh AAC against the settled original attempt without granting any picture work."""
    binding = request['productionBudget']
    if kind != 'aacCandidate' or request['output'] != binding['continuationOutput']:
        raise BudgetRefused('Review continuation permits only bound final audio candidates')
    require_review_only(request, [])
    original = {**binding, 'attemptId': binding['continuationOf']}
    with locked_batch(Path(binding['authority']), binding['batchId']) as session:
        record = session.read()
        elapsed = advance_clock(record)
        try:
            admit_review_audio(record, original, (request, audio_key), elapsed)
        except (BudgetRefused, BudgetExhausted) as error:
            session.commit(record, {'event': 'review-aac-refused', 'elapsed': elapsed, 'reason': str(error)})
            raise
        session.commit(record, {'event': 'nested-charged', 'kind': kind, 'elapsed': elapsed,
                                'attemptId': binding['continuationOf'], 'output': request['output']})


def admit_review_audio(record: dict, binding: dict, inputs: tuple, elapsed: float) -> None:
    """Check the original clock and project before sharing the ordinary AAC debit primitive."""
    request, audio_key = inputs
    review_grant(record, binding, elapsed)
    attempt = find_attempt(record, binding['clipId'], binding['attemptId'])
    if attempt['project'] != request['project']:
        raise BudgetRefused('Review audio must remain in its originally reserved project')
    decision = charge_admitted_nested(record, binding, 'aacCandidate', audio_key)
    if not decision.allowed:
        raise BudgetRefused(decision.reason)


def refuse_delivered(clip: dict, attempt_id: str) -> None:
    """A checked original attempt has one final delivery, even across different continuation paths."""
    if any(row['kind'] == 'final' and row['attemptId'] == attempt_id for row in clip['deliveries']):
        raise BudgetRefused('Original section attempt already has a checked delivery; no free final replay')
