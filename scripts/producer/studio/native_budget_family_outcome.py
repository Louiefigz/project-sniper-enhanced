"""Bounded family child settlement and exactly one complete-program delivery debit."""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_budget_family_state import family_of, invocation_of, require
from studio.native_budget_launch import failure_signature, find_attempt, record_outcome
from studio.native_budget_policy import clip_record, phase_refusal
from studio.native_runtime import digest
from studio.native_segments.long_plan import identity
from studio.production.settlement import launch_outcome

PREVIEW = 'native-motion-previews-complete'
SCOPED = 'native-long-section-sealed-awaiting-integration'
CHECKED = 'native-long-checked-for-review'
PENDING = 'section-review-pending'
AWAITING = 'native-long-rendered-awaiting-qc'


def apply_family_outcome(record: dict, request: dict, result: dict, elapsed: float) -> dict | None:
    """Settle under the caller's held batch lock; exact recorded callbacks are harmless replays."""
    binding = request['productionBudget']
    clip, family, row = bound_invocation(record, request)
    outcome = launch_outcome(result, (PREVIEW, SCOPED, CHECKED, AWAITING))
    status = PENDING if outcome.get('failureCategory') == PENDING else outcome['status']
    fingerprint = result_identity(outcome, status)
    if row['status'] in ('succeeded', 'failed'):
        require(row['resultIdentity'] == fingerprint, 'Family invocation already settled with a different outcome')
        return None
    require(row['status'] in ('running', 'abandoned'), 'Family invocation cannot settle')
    if status in (PREVIEW, SCOPED, CHECKED, AWAITING, PENDING):
        require_success_authority(record, request, (family, row, status), elapsed)
    success = validate_outcome(request, result, (family, row, status, record))
    complete = family_completion(record, binding, (family, row, status)) if success else False
    if success:
        from studio.native_budget_binding import advance_clock
        elapsed = max(elapsed, advance_clock(record))
        require_live_grant(record, binding, elapsed)
    row.update(status='succeeded' if success else 'failed', completedElapsed=elapsed,
               resultStatus=status, resultIdentity=fingerprint, failure=None)
    if not success:
        row['failure'] = {'category': outcome.get('failureCategory') or 'renderer-failure',
            'phase': outcome.get('failedPhase'), 'errorType': outcome.get('errorType'),
            'signature': failure_signature(outcome.get('errorType'), outcome.get('error'))}
    complete_family(record, binding, (family, outcome, complete), elapsed)
    return {'event': 'launch-completed', 'kind': 'section-family-invocation', 'clipId': binding['clipId'],
            'attemptId': family['id'], 'invocationId': row['id'], 'status': row['status'],
            'resultStatus': row['resultStatus'], 'elapsed': elapsed}


def bound_invocation(record: dict, request: dict) -> tuple[dict, dict, dict]:
    """Validate reserved path ownership and immutable request bytes, including preparation failures."""
    binding = request['productionBudget']
    require(record['batchId'] == binding['batchId'] and binding['attemptId'] == binding['familyId'],
            'Family outcome belongs to another authority')
    clip = clip_record(record, binding['clipId'])
    family = family_of(clip, binding['familyId'])
    attempt = find_attempt(record, binding['clipId'], family['id'])
    require(binding['route'] == attempt['route'], 'Family outcome route differs from its reserved attempt')
    row = invocation_of(family, binding['familyInvocation'])
    require((request.get('project', binding.get('familyProject')), request.get('output', binding.get('familyOutput')))
            == (row['project'], row['output']), 'Family outcome project/output differs')
    file = Path(row['output']) / 'export-request.json'
    if file.exists():
        require(bound_json(file) == request, 'Family outcome request differs from immutable publication')
        sha = digest(file)
        require(row['requestSha256'] in (None, sha), 'Family outcome request digest changed')
        row['requestSha256'] = sha
    else:
        require(row['requestSha256'] is None, 'Family outcome lost its published request')
    return clip, family, row


def require_success_authority(record: dict, request: dict, state: tuple, elapsed: float) -> None:
    """Only current authors, exact frozen request and live original authority can publish a successful child."""
    from studio.native_budget_family_state import verify_family_request
    from studio.production.section_plan import require_context, revalidate_context
    from studio.production.section_scope import selected_assignments
    from studio.production.sections import early_result, integrated_author
    family, row, status = state
    binding = request['productionBudget']
    require_live_grant(record, binding, elapsed)
    context = revalidate_context(request)
    require_context(record, context)
    phase = 'preview' if binding['route'] == 'preview' else 'capture'
    verify_family_request(record, request, phase)
    for assignment in selected_assignments(request, context):
        integrated_author(request, assignment, record)
        if binding['route'] == 'final':
            early_result(request, assignment, record)
    if status == CHECKED:
        from studio.native_segments.reviews import assembly_snapshot
        saved = bound_json(Path(request['output']) / 'revision-picture.json')['sectionSnapshot']
        require(assembly_snapshot(request, record) == saved, 'Family final current assembly proof changed')


def require_live_grant(record: dict, binding: dict, elapsed: float) -> None:
    """Recheck the unchanged authority's absolute deadline after potentially expensive proof hashes."""
    from studio.production.formats import clip_deadlines
    clip = clip_record(record, binding['clipId'])
    attempt = find_attempt(record, binding['clipId'], binding['familyId'])
    end = min(attempt['admittedElapsed'] + attempt['grantedSeconds'],
              clip_deadlines(record, clip)['deliverySeconds'] - clip_deadlines(record, clip)['handoffReserveSeconds'])
    refusal = phase_refusal(record, clip, elapsed)
    require(refusal is None and elapsed < end and attempt['status'] == 'running',
            refusal or 'Family original grant ended; successful outcome is fenced')


def result_identity(outcome: dict, status: str) -> str:
    """Stable exact outcome identity excludes elapsed timings but includes delivery and bounded failure."""
    return identity({'status': status, 'delivery': outcome.get('delivery'),
                     'failureCategory': outcome.get('failureCategory'), 'failedPhase': outcome.get('failedPhase'),
                     'errorType': outcome.get('errorType'),
                     'signature': failure_signature(outcome.get('errorType'), outcome.get('error'))})


def validate_outcome(request: dict, result: dict, state: tuple) -> bool:
    """Successful children must possess their actual saved evidence; pending review grants no new picture."""
    family, row, status, record = state
    route = request['productionBudget']['route']
    if status not in (PREVIEW, SCOPED, CHECKED, AWAITING, PENDING):
        return False
    require(row['requestSha256'] is not None, 'Successful family invocation has no immutable request')
    if status == PREVIEW:
        require(route == 'preview', 'Final family cannot claim preview completion')
        from studio.native_motion_previews import current_motion_previews
        current_motion_previews(request)
        from studio.native_preview_history import prior_preview
        prior_preview(Path(request['output']) / 'motion-previews.json', request['project'])
        return True
    require(route == 'final', 'Preview family cannot claim final section or delivery completion')
    require((row['sectionId'] is not None) == (status == SCOPED), 'Family result has the wrong section scope')
    if status == CHECKED:
        receipt = bound_json(Path(request['output']) / 'delivery.json')
        require(all(receipt.get(key) == result.get(key) for key in ('status', 'output', 'sha256')),
                'Family checked result differs from immutable delivery')
        require_complete_children(family, request, record)
        from studio.native_budget_family_delivery import require_checked_media
        require_checked_media(request, result)
    else:
        require_saved_sections(request, row['sectionId'])
    return True


def require_saved_sections(request: dict, section_id: str | None) -> None:
    """A pending review or saved section status cannot conceal missing or changed owner evidence."""
    from studio.native_segments.owners import current_window
    from studio.production.section_review_inputs import section_windows
    rows = request['sectionProduction']['assignments']
    selected = [row for row in rows if section_id is None or row['sectionId'] == section_id]
    require(bool(selected), 'Family result has no assigned saved section')
    for row in selected:
        for window in section_windows(request, row):
            current_window(request, f"segment-picture-{window['index']}")


def require_complete_children(family: dict, request: dict, record: dict) -> None:
    """Every fixed logical assignment must have one successful media invocation before delivery."""
    complete = {row['sectionId'] for row in family['invocations'] if row['status'] == 'succeeded'}
    from studio.native_budget_family_repair import retained_current_sections
    complete |= retained_current_sections(record, request)
    require({row['sectionId'] for row in family['assignments']} <= complete, 'Family still has incomplete sections')


def family_completion(record: dict, binding: dict, state: tuple) -> bool:
    """Read every completion dependency before the final absolute-clock check and state mutation."""
    family, row, status = state
    if status == CHECKED:
        return True  # Current child/media/repair proofs were already read by validate_outcome.
    if status != PREVIEW:
        return False
    finished = {item['sectionId'] for item in family['invocations'] if item['status'] == 'succeeded'}
    finished.add(row['sectionId'])
    expected = {item['sectionId'] for item in family['previewInventory']}
    from studio.production.section_plan import read_plan
    from studio.native_budget_family_repair import repair_state
    context = read_plan(Path(family['plan']['path']))
    repair = repair_state(record, {'context': context, 'project': binding['familyProject']}, lock_history=False)
    finished |= repair['retained'] if repair else set()
    return binding['route'] == 'preview' and expected <= finished


def complete_family(record: dict, binding: dict, state: tuple, elapsed: float) -> None:
    """Commit only pure in-memory changes after all proof IO and the final grant check."""
    family, outcome, complete = state
    if not complete:
        return
    clip = clip_record(record, binding['clipId'])
    require(not any(row['attemptId'] == family['id'] and row['kind'] == 'final' for row in clip['deliveries']),
            'Family already has its checked final delivery')
    attempt = find_attempt(record, binding['clipId'], family['id'])
    require(attempt['status'] == 'running', 'Family launch was already settled')
    record_outcome(record, binding, outcome, elapsed)
    family['state'] = 'complete'
