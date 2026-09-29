"""Atomic logical-family reservation; duplicate children share no fresh counters or clocks."""
from __future__ import annotations

import uuid
from fractions import Fraction
from pathlib import Path

from cut_preview_io import bound_json
from studio.native_budget_binding import _launch_decision
from studio.native_budget_family_schema import ASSIGNMENT_KEYS, MAX_FAMILIES, MAX_INVOCATIONS
from studio.native_budget_family_state import reconcile_family, require
from studio.native_budget_launch import LaunchRequest, TRANSIENT, find_attempt, own_identity
from studio.native_budget_policy import charge, clip_record, phase_refusal
from studio.native_budget_sections import inherited_allocation
from studio.native_segments.long_plan import identity
from studio.production.formats import clip_limits
from studio.production.outputs import binding_refusal
from studio.production.section_plan import require_context


def reserve_invocation(record: dict, settings: dict, elapsed: float) -> dict:
    """Apply one fully validated reservation in the caller's existing locked transaction."""
    context, options = settings['context'], settings['options']
    require_context(record, context)
    clip = clip_record(record, context['clipId'])
    require(record['engine'] is not None and record['engine']['identity'] == settings['engine']['identity'],
            'Section family requires this batch frozen engine')
    refusal = phase_refusal(record, clip, elapsed) or binding_refusal(record, context['clipId'], settings['projectIdentity'])
    require(refusal is None, refusal or 'Family authority refused work')
    rows = clip.setdefault('sectionFamilies', [])
    require(record['schemaVersion'] >= 7, 'Section families require current schema authority')
    from studio.native_budget_family_repair import fence_parent, clamp_grant
    family = select_family(clip, settings)
    from studio.native_segments.review_forecast import require_owner_room
    require_owner_room(clip, settings)
    if family is not None:
        reconcile_family(record, clip, family, (elapsed, settings['launchFacts'].processes))
    validate_invocation(clip, family, settings)
    if family is None:
        fence_parent(record, settings, elapsed)
        family = create_family(record, settings, elapsed)
        clamp_grant(record, settings, family, elapsed)
        rows.append(family)
    attempt = find_attempt(record, context['clipId'], family['id'])
    binding = {'schemaVersion': 1, 'authority': context['authority'], 'batchId': context['batchId'],
               'clipId': context['clipId'], 'attemptId': family['id'], 'route': settings['route']}
    grant = inherited_allocation(record, binding, elapsed)
    require(attempt['status'] == 'running', 'Family original launch has already ended')
    invocation = new_invocation(settings, elapsed)
    debit_retry(clip, family, options['sectionId'])
    family['invocations'].append(invocation)
    if options['sectionId'] is None:
        family['state'] = 'finalizing'
    return {**binding, 'allocation': grant, 'longOutput': settings['longOutput'],
            'familyId': family['id'], 'familyInvocation': invocation['id'],
            'familyProject': settings['project'], 'familyOutput': settings['output']}


def select_family(clip: dict, settings: dict) -> dict | None:
    """One immutable plan and route owns one counted logical family."""
    attempts = {row['id']: row for row in clip['attempts']}
    families = clip.get('sectionFamilies', [])
    rows = [row for row in families if row['plan'] == settings['context']['plan']
            and attempts[row['id']]['route'] == settings['route']]
    require(len(rows) <= 1, 'Ambiguous family authority')
    if not rows:
        require(len(families) < MAX_FAMILIES, 'Section family history is full')
        return None
    family = rows[0]
    expected = [{key: row[key] for key in ASSIGNMENT_KEYS} for row in settings['context']['assignments']]
    require(family['sharedPlan'] == settings['context']['sharedPlan'] and family['assignments'] == expected
            and family['previewInventory'] == settings['previewInventory'], 'Family inventory changed')
    return family


def create_family(record: dict, settings: dict, elapsed: float) -> dict:
    """Call the ordinary counted launch admission exactly once for the entire frozen family."""
    context = settings['context']
    facts = settings['launchFacts']
    decision = _launch_decision(record, facts.launch, (settings['engine'], elapsed, facts))
    require(decision.allowed, decision.reason)
    return {'id': decision.detail['attempt']['id'], 'plan': context['plan'], 'sharedPlan': context['sharedPlan'],
            'assignments': [{key: row[key] for key in ASSIGNMENT_KEYS} for row in context['assignments']],
            'previewInventory': settings['previewInventory'], 'state': 'awaiting-sections', 'invocations': [],
            **({'reviewService': settings['reviewService']} if settings.get('reviewService') else {})}


def launch_request(record: dict, settings: dict) -> LaunchRequest:
    """Resolve the exact candidate and preview duration while evidence reads are still allowed."""
    context = settings['context']
    return LaunchRequest(context['clipId'], settings['route'], identity({'plan': context['plan'],
        'sharedPlan': context['sharedPlan'], 'route': settings['route'], 'engine': settings['engine']['identity']}),
        (settings['project'], settings['output']), settings['longOutput']['outputSeconds'], preview_seconds(settings),
        family_members=len(settings['previewInventory']) if settings['route'] == 'preview' else len(context['assignments']) + 1,
        following_members=len(context['assignments']) + 1, service_seconds=service_seconds(record, settings))


def service_seconds(record: dict, settings: dict) -> float:
    """A frozen prospective selection or exact existing conservative package allowance."""
    if settings.get('reviewServiceSeconds') is not None:
        return settings['reviewServiceSeconds']
    from studio.native_segments.review_forecast import package_seconds
    from studio.production.formats import clip_rates
    context = settings['context']
    return package_seconds(settings.get('reviewWork'), clip_rates(record, record['clips'][context['clipId']]), '*')


def preview_seconds(settings: dict) -> float | None:
    """Forecast every separately rendered frozen preview window, including repeated join coverage."""
    if settings['route'] != 'preview':
        return None
    plan = bound_json(Path(settings['project']) / 'LONG-PROJECT.json')
    frames = sum(end - start for row in settings['previewInventory'] for start, end in row['windows'])
    from studio.native_short_dialogue import clock
    return float(Fraction(frames) / clock(plan['canvas']).fps.fraction)


def validate_invocation(clip: dict, family: dict | None, settings: dict) -> None:
    """No duplicate child, changed inventory, overlapping finalizer or uncharged deterministic retry."""
    section = settings['options']['sectionId']
    retained = (settings.get('repair') or {}).get('retained', set())
    require(section not in retained, 'Unchanged repair sections must reuse their saved original media')
    require(not any(invocation['output'] == settings['output'] for item in clip.get('sectionFamilies', [])
                    for invocation in item['invocations']), 'Family output path was already reserved')
    if family is None:
        require(section is not None, 'A family starts with an assigned section, not final integration')
        return
    require(family['state'] in ('awaiting-sections', 'finalizing'), 'Family is complete or failed')
    rows = family['invocations']
    require(len(rows) < MAX_INVOCATIONS, 'Family invocation history is full')
    active = [row for row in rows if row['status'] == 'running']
    require(not any(row['sectionId'] in (section, None) for row in active)
            and not (section is None and active), 'Family invocation overlaps an active owner')
    previous = [row for row in rows if row['sectionId'] == section]
    if section is None:
        require_integrated(family, settings, previous)
    elif previous:
        require(previous[-1]['status'] in ('failed', 'abandoned')
                and (previous[-1]['failure'] or {}).get('category') in TRANSIENT,
                'Section already succeeded or failed deterministically; no duplicate invocation')
        require(previous[-1]['planSha256'] == settings['longOutput']['planSha256']
                and previous[-1]['scopeSha256'] == identity(settings['options']['snapshotScope']),
                'Transient family retry changed its immutable section inputs')
        require(clip['counters']['transientRetry'] < clip_limits({}, clip)['transientRetry'],
                'The Long already used its transient-failure retry')


def require_integrated(family: dict, settings: dict, previous: list[dict]) -> None:
    """Full-program invocations only join completed children; pending review can continue without pictures."""
    completed = {row['sectionId'] for row in family['invocations'] if row['status'] == 'succeeded'}
    completed |= (settings.get('repair') or {}).get('retained', set())
    require({row['sectionId'] for row in family['assignments']} <= completed,
            'Final integration waits for every required section child')
    if settings['route'] == 'preview':
        require(any(row['sectionId'] is None for row in family['previewInventory']), 'No join preview was declared')
    if previous:
        prior = previous[-1]
        require(settings['route'] == 'final' and prior['resultStatus'] in
                ('native-long-rendered-awaiting-qc', 'section-review-pending'), 'Final family invocation already settled')
        require(settings['options'].get('parentAttempt') == prior['output'], 'Review continuation must name its prior invocation')
        require(settings['project'] == prior['project'], 'Review continuation changed its project')
        require(settings.get('validatedReviewParent') == prior['id'], 'Review continuation proof was not prepared')


def validate_review_parent(settings: dict, prior: dict, family_id: str) -> None:
    """A no-picture continuation must preserve its registered current original request."""
    from studio.native_export_history import attempt_reservation, known_attempts, require_current_section_attempt
    file = Path(prior['output']) / 'export-request.json'
    require(prior['requestSha256'] is not None, 'Review continuation parent was never published')
    request = bound_json(file, prior['requestSha256'])
    binding = request.get('productionBudget', {})
    require(request['project'] == settings['project'] and request['output'] == prior['output']
            and binding.get('familyId') == family_id and binding.get('familyInvocation') == prior['id'],
            'Review continuation parent family differs')
    with attempt_reservation(request):
        require(file.parent in known_attempts(request), 'Review continuation parent is not registered')
        require_current_section_attempt(request)


def debit_retry(clip: dict, family: dict, section: str | None) -> None:
    """One shared existing transient debit, only after every other child-admission check passed."""
    if section is not None and any(row['sectionId'] == section for row in family['invocations']):
        charge(clip, 'transientRetry')


def new_invocation(settings: dict, elapsed: float) -> dict:
    """Record actual supervisor identity and exact reserved project/scope before any child work."""
    scope = settings['options']['snapshotScope']
    return {'id': uuid.uuid4().hex, 'sectionId': settings['options']['sectionId'], 'project': settings['project'],
            'output': settings['output'], 'planSha256': settings['longOutput']['planSha256'],
            'scopeSha256': identity(scope) if scope is not None else None, 'requestSha256': None,
            'supervisor': settings['launchFacts'].supervisor, 'status': 'running', 'admittedElapsed': elapsed,
            'completedElapsed': None, 'resultStatus': None, 'resultIdentity': None, 'failure': None}
