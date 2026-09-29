"""Bound a changed logical family to its original immutable saved-section authority.

Unchanged assignments are never copied into new successful invocation rows. Every
read derives retained scope from the frozen parent plan and reopens the registered
full parent request, its actual section seals and current isolated dependency
closure. A repair keeps the earliest original grant end and all spent counters.
"""
from __future__ import annotations

from pathlib import Path
from contextlib import nullcontext

from cut_preview_io import bound_json
from studio.native_budget_family_state import require
from studio.native_budget_launch import find_attempt, record_outcome
from studio.native_budget_policy import clip_record
from studio.native_export_history import attempt_reservation, require_current_section_attempt
from studio.native_segments.compatibility import _parent, section_snapshot_compatibility
from studio.native_segments.dependency import inventory
from studio.production.section_plan import read_plan
from studio.production.section_results import read_completed_result
from studio.production.settlement import launch_outcome


def repair_state(record: dict, settings: dict, lock_history: bool = True) -> dict | None:
    """Resolve parent under batch authority; final publication already holds its current history lock."""
    context = settings['context']
    if not context.get('parentPlan'):
        return None
    parent_context = read_plan(Path(context['parentPlan']['path']))
    require(parent_context['plan'] == context['parentPlan'], 'Repair parent plan pin changed')
    clip = clip_record(record, context['clipId'])
    attempts = {row['id']: row for row in clip['attempts']}
    parents = [row for row in clip.get('sectionFamilies', []) if row['plan'] == context['parentPlan']]
    candidates = [row for row in parents if attempts[row['id']]['route'] == 'final']
    require(len(candidates) == 1, 'Repair requires one original counted final family')
    family = candidates[0]
    require(family['sharedPlan'] == context['sharedPlan'], 'Repair changed the shared creative plan')
    require(not any(row['status'] == 'running' for item in parents for row in item['invocations']),
            'Repair cannot supersede a live family invocation')
    full = [row for row in family['invocations'] if row['sectionId'] is None and row['status'] == 'succeeded']
    require(bool(full), 'Repair requires a saved full parent integration')
    row = full[-1]
    require(row['requestSha256'] is not None, 'Repair parent integration was not published')
    original = _parent(Path(row['output']), row['requestSha256'])
    require(original['sectionProduction'] == parent_context and not original.get('sectionScope'),
            'Repair source differs from the original complete assignment plan')
    binding = original.get('productionBudget', {})
    require(binding.get('familyId') == family['id'] and binding.get('familyInvocation') == row['id'],
            'Repair parent request belongs to another invocation')
    history = attempt_reservation(original) if lock_history else nullcontext()
    with history:
        require_current_section_attempt(original)
        retained = retained_assignments(record, settings, original)
    attempt = attempts[family['id']]
    return {'family': family, 'attempt': attempt, 'original': original, 'retained': retained,
            'parents': parents, 'grantEnd': min(attempts[row['id']]['admittedElapsed'] +
                attempts[row['id']]['grantedSeconds'] for row in parents)}


def retained_assignments(record: dict, settings: dict, original: dict) -> set[str]:
    """Prove unchanged authors and actual saved media against the new fully pinned project snapshot."""
    from studio.native_segments.owners import current_window
    from studio.production.section_review_inputs import section_windows
    context = settings['context']
    previous = {row['sectionId']: row for row in original['sectionProduction']['assignments']}
    require(set(previous) == {row['sectionId'] for row in context['assignments']}, 'Repair changed logical sections')
    current = current_snapshot(original, Path(settings['project']))
    retained = set()
    for row in context['assignments']:
        prior = previous[row['sectionId']]
        require(row['frameRange'] == prior['frameRange'], 'Repair changed logical frame ownership')
        if row['authorBinding'] != prior['authorBinding']:
            continue
        read_completed_result(record, row['authorTaskId'], row['authorBinding'])
        section_snapshot_compatibility(original, current, row['frameRange'])
        for window in section_windows(original, prior):
            current_window(original, f"segment-picture-{window['index']}")
        retained.add(row['sectionId'])
    require(0 < len(retained) < len(previous), 'Repair family needs both changed and provably retained assignments')
    return retained


def current_snapshot(original: dict, project: Path) -> dict:
    """Use real current bytes with original verified tools; this is compatibility, not project admission."""
    old = Path(original['project'])
    pins = {name: sha for name, sha in original['pins'].items() if not Path(name).is_relative_to(old)}
    pins.update({str(project / name): sha for name, sha in inventory(project).items()})
    return {**original, 'project': str(project), 'pins': pins}


def fence_parent(record: dict, settings: dict, elapsed: float) -> None:
    """Close an idle superseded logical attempt, retaining all prior immutable charges and outcomes."""
    repair = settings.get('repair')
    if repair is None:
        return
    require(elapsed < repair['grantEnd'], 'Original family grant ended before repair')
    for family in repair['parents']:
        attempt = find_attempt(record, settings['context']['clipId'], family['id'])
        if attempt['status'] != 'running':
            continue
        binding = {'clipId': settings['context']['clipId'], 'attemptId': family['id']}
        outcome = launch_outcome({'status': 'failed', 'failureCategory': 'section-plan-repaired',
            'errorType': 'SectionFamilySuperseded', 'error': 'Changed section plan superseded idle original family'}, ())
        record_outcome(record, binding, outcome, elapsed)
        family['state'] = 'failed'


def clamp_grant(record: dict, settings: dict, family: dict, elapsed: float) -> None:
    """The counted repair attempt consumes only the original family's remaining absolute grant."""
    repair = settings.get('repair')
    if repair is None:
        return
    attempt = find_attempt(record, settings['context']['clipId'], family['id'])
    require(elapsed < repair['grantEnd'], 'Original family grant ended before repair')
    attempt['grantedSeconds'] = min(attempt['grantedSeconds'], repair['grantEnd'] - attempt['admittedElapsed'])


def retained_current_sections(record: dict, request: dict) -> set[str]:
    """At completion, require current restored media as well as its exact original scope compatibility."""
    from studio.native_segments.compatibility import validate_repair
    from studio.production.section_review_reuse import media_signature
    from studio.production.section_media import window_observations
    from studio.production.section_review_inputs import section_windows, window_media
    context = request['sectionProduction']
    if not context.get('parentPlan'):
        return set()
    settings = {'context': context, 'project': request['project']}
    repair = repair_state(record, settings, lock_history=False)
    original = validate_repair(request)
    require(original == repair['original'], 'Repair current request differs from its counted original authority')
    for row in context['assignments']:
        if row['sectionId'] not in repair['retained']:
            continue
        prior = next(item for item in original['sectionProduction']['assignments'] if item['sectionId'] == row['sectionId'])
        before = [item for window in section_windows(original, prior)
                  for item in window_observations(original, window_media(original, window))]
        after = [item for window in section_windows(request, row)
                 for item in window_observations(request, window_media(request, window))]
        require(media_signature(before) == media_signature(after), 'Retained family picture or PCM changed')
    return repair['retained']
