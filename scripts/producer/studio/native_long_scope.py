"""Explicit admission of one immutable authored snapshot without whole-program approval.

The selected assignment and bounded static source closure identify the work. All
actual snapshot bytes remain pinned. Final integration must obtain its separate
full-project review; this receipt cannot authorize assembly or delivery.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_runtime import digest
from studio.native_segments.long_plan import identity
from studio.native_segments.section_closure import section_input_closure
from studio.native_stage_evidence import require, verify_pins
from studio.production.section_plan import read_plan

SCOPE_KEYS = {'schemaVersion', 'sectionId', 'generation', 'inputIdentity', 'frameRange',
              'sharedPlan', 'snapshotProject', 'snapshotPinsHash'}


def scope_for_project(project: Path, plan_file: Path, section_id: str) -> dict:
    """Freeze one declared author and all actual snapshot policy/source inputs before review."""
    context = read_plan(plan_file)
    selected = [row for row in context['assignments'] if row['sectionId'] == section_id]
    require(len(selected) == 1, 'section scope requires one declared logical assignment')
    row = selected[0]
    section_input_closure(project, row['frameRange'])
    scope = {'schemaVersion': 1, **{key: row[key] for key in
             ('sectionId', 'generation', 'inputIdentity', 'frameRange')},
             'sharedPlan': context['sharedPlan'], 'snapshotProject': str(project)}
    from studio.native_long_prebuild import prebuild_snapshot
    snapshot = prebuild_snapshot(project, scope)
    scope['snapshotPinsHash'] = identity(snapshot['pins'])
    return scope


def scope_for_args(args: object, project: Path) -> dict | None:
    """Use an explicit frozen assignment or retain the original immutable resume scope."""
    section_id = getattr(args, 'section_id', None)
    plan = getattr(args, 'section_plan', None)
    if section_id:
        require(plan is not None, '--section-id requires its frozen --section-plan')
        return scope_for_project(project, plan.resolve(strict=True), section_id)
    parent = getattr(args, 'resume_from', None)
    if parent:
        original = bound_json(parent.resolve(strict=True) / 'export-request.json')
        scope = original.get('sectionScope')
        if scope:
            require(scope['snapshotProject'] == str(project), 'scoped resume requires its original immutable snapshot')
            return scope
    return None


def require_scope_request(request: dict, phase: str | None = None) -> None:
    """Cold-check scoped currentness and forbid a worker from crossing into another range or final work."""
    scope = request.get('sectionScope')
    if scope is None:
        return
    require(type(scope) is dict and set(scope) == SCOPE_KEYS and scope['schemaVersion'] == 1,
            'invalid immutable section scope')
    context = request.get('sectionProduction')
    require(context is not None, 'scoped rendering requires registered production assignments')
    expected = scope_for_project(Path(request['project']), Path(context['plan']['path']), scope['sectionId'])
    require(scope == expected, 'scoped snapshot or assignment changed after admission')
    verify_pins(request['pins'])
    require(request.get('prebuildReview', {}).get('scope') == 'native-long-section-snapshot',
            'section snapshot requires its distinct recorded prebuild admission')
    if phase is None:
        return
    require(phase not in {'picture', 'render', 'verify'}, 'scoped snapshot cannot assemble or deliver a full Long')
    if phase.startswith('segment-picture-'):
        index = int(phase.split('-')[2])
        require(any(row['index'] == index for row in selected_windows(request)),
                'section owner cannot render outside its admitted logical range')


def selected_windows(request: dict) -> list[dict]:
    """Select complete technical windows without changing their absolute indices or identities."""
    windows = request['revision']['renderWindows']
    scope = request.get('sectionScope')
    if scope is None:
        return windows
    start, end = scope['frameRange']
    selected = [row for row in windows if row['startFrame'] < end and row['endFrame'] > start]
    require(selected and selected[0]['startFrame'] == start and selected[-1]['endFrame'] == end,
            'logical section must contain complete technical windows')
    return selected


def request_preview_windows(request: dict, packet: dict, previous: dict | None = None) -> list[dict]:
    """Read only frozen join windows for a family integration; ordinary schedules stay unchanged."""
    from studio.native_review_regions import preview_windows
    declared = request.get('sectionPreviewWindows')
    if declared is None:
        windows = preview_windows(packet, previous)
        if request.get('adapter') == 'native-long' and request.get('sectionScope') and request.get('sectionProduction'):
            from studio.native_segments.review_forecast import preview_ranges
            return preview_ranges(Path(request['project']), request['sectionProduction'],
                                  request['sectionScope']['sectionId'], windows)
        return windows
    require(not request.get('sectionScope') and request.get('productionBudget', {}).get('familyId')
            and request.get('sectionProduction'), 'join-only previews require the original full integration family')
    from studio.native_long_contract import family_preview_inventory
    rows = family_preview_inventory(Path(request['project']), request['sectionProduction'])
    expected = next((row['windows'] for row in rows if row['sectionId'] is None), [])
    require(declared == expected, 'integrated preview differs from the frozen complete join schedule')
    return [{'startFrame': start, 'endFrame': end} for start, end in declared]


def bind_family_preview_windows(request: dict, budget: dict | None, plan_file: Path | None) -> None:
    """Bind full integration join membership before preview donor discovery or request publication."""
    if not budget or not budget.get('familyId') or request.get('sectionScope'):
        return
    context = request.get('sectionProduction') or read_plan(plan_file.resolve(strict=True))
    from studio.native_long_contract import family_preview_inventory
    rows = family_preview_inventory(Path(request['project']), context)
    request['sectionPreviewWindows'] = next((row['windows'] for row in rows if row['sectionId'] is None), [])
