"""Cold remaining-work facts from existing family, window and reviewer authority.

Call inside the existing batch transaction. No counter, claim, seal or clock is
changed. These facts only reduce normal forecast demand; they grant no launch.
"""
from __future__ import annotations

from pathlib import Path

from native_work_service_pins import identity, require


def registered_request(family: dict, invocation: dict) -> dict | None:
    """Read only an already owner-bound immutable invocation, never guessed output files."""
    sha = invocation['requestSha256']
    if sha is None:
        return None
    from studio.native_segments.compatibility import _parent
    request = _parent(Path(invocation['output']), sha)
    binding = request['productionBudget']
    require(request['project'] == invocation['project'] and request['output'] == invocation['output']
            and binding['familyId'] == family['id'] and binding['familyInvocation'] == invocation['id']
            and request['sectionProduction']['plan'] == family['plan'], 'service invocation authority differs')
    scope = request.get('sectionScope')
    require((identity(scope) if scope is not None else None) == invocation['scopeSha256']
            and (scope or {}).get('sectionId') == invocation['sectionId'], 'service invocation scope differs')
    return request


def current_reviewers(record: dict, request: dict, row: dict) -> list[dict]:
    """Select the exact current author generation, excluding obsolete or unclaimed tasks."""
    from studio.production.section_results import SCOPE
    values = []
    for task in record['production']['tasks'].values():
        binding = task.get('sectionBinding') or {}
        same = binding.get('role') == 'encoded-review' and binding.get('chunkPlan') \
            and binding.get('authorTaskId') == row['authorTaskId'] \
            and all(binding.get(key) == row['authorBinding'][key] for key in SCOPE)
        if same and task['state'] in ('running', 'completed') and not task.get('revoked'):
            require(task['id'] == row['encodedTaskId'] + '-' + identity(binding)[:12],
                    'service reviewer identity differs')
            values.append(task)
    require(len(values) <= 1, 'service reviewer generation is ambiguous')
    return values


def review_facts(record: dict, request: dict, row: dict) -> tuple[set, set, bool]:
    """Read actual recorded progress and independently retained judgments without new callbacks."""
    from studio.production.section_chunk_reuse import retained_chunk_scopes
    from studio.production.section_chunk_results import read_progress
    from studio.production.section_chunk_recovery import compare_current_scopes
    from studio.production.section_results import author_for, current, read_completed_result, task_of
    from studio.production.dependencies import stale_inputs
    carries = {proof['scopeId'] for proof in retained_chunk_scopes(record, request, row)}
    progress, complete = set(), False
    for task in current_reviewers(record, request, row):
        from studio.production.section_chunk_plan import read_chunk_plan
        plan, original = read_chunk_plan(task['sectionBinding'])
        if original.get('sectionScope') != request.get('sectionScope'):
            checked, done = integrated_review(record, request, row, task)
            progress.update(checked)
            complete = complete or done
            continue
        task_of(record, task['id'])
        current(task, ('running', 'completed'))
        require(stale_inputs(record).get(task['id']) is None, 'service reviewer dependency changed')
        author_for(record, task)
        values = [read_progress(task, pin) for pin in task.get('sectionProgress', {}).values()]
        compare_current_scopes(request, task, values)
        progress.update(value['scopeId'] for value in values)
        if task['state'] == 'completed':
            read_completed_result(record, task['id'], task['sectionBinding'])
            complete = True
    return progress, carries, complete


def integrated_review(record: dict, request: dict, row: dict, task: dict) -> tuple[set, bool]:
    """Use the existing full integration compatibility reader for a scoped completed reviewer."""
    from studio.production.section_review_reuse import retained_review
    from studio.production.section_chunk_plan import read_chunk_plan
    if task['state'] != 'completed' or retained_review(request, row, (record, 'encoded-review')) is None:
        return set(), False
    plan, _original = read_chunk_plan(task['sectionBinding'])
    return {scope['id'] for scope in plan['scopes']}, True


def package_ready(request: dict, scope: dict, sealed: set) -> bool:
    """Absent media stays pending; present corrupt package proof still raises normally."""
    from studio.native_segments.review_package import retained_package
    if not all(row['index'] in sealed for row in scope['windows']):
        return False
    return retained_package(request, scope['id']) is not None


def request_facts(record: dict, request: dict, evidence: dict) -> dict:
    """Cold-check current windows, packages and live carry before reducing demand."""
    from studio.production.section_plan import require_context, revalidate_context
    from studio.production.section_scope import selected_assignments
    from studio.production.section_chunk_reuse import window_ready
    from studio.native_long_scope import selected_windows
    from studio.native_segments.review_scopes import package_scopes
    context = revalidate_context(request)
    require_context(record, context)
    windows = selected_windows(request)
    sealed = {row['index'] for row in windows if window_ready(request, row['index'])}
    scopes = package_scopes(request)
    assignments = selected_assignments(request, context)
    expected = {row['id']: row for row in evidence['scopes']}
    packages, progress, carry, completed = set(), set(), set(), set()
    for row in assignments:
        checked, retained, done = review_facts(record, request, row)
        progress.update(checked)
        carry.update(retained)
        if done:
            completed.add(row['sectionId'])
    for scope in scopes:
        require(scope['id'] in expected and all(scope[key] == expected[scope['id']][key]
                for key in ('frameRange', 'sectionIds', 'kind')), 'service scope geometry changed')
        if scope['id'] not in carry and package_ready(request, scope, sealed):
            packages.add(scope['id'])
    return {'pendingWindows': len(windows) - len(sealed), 'packages': packages,
            'progress': progress, 'carry': carry, 'completedSections': completed,
            'hasMedia': bool(sealed), 'coveredScopes': {scope['id'] for scope in scopes},
            'coveredSections': {row['sectionId'] for row in assignments}}


def replace_covered_facts(reductions: dict, facts: dict) -> None:
    """Replace older reductions even when the current request explicitly finds none.

    A private request covers only its own scopes. A later full integration covers
    every scope, so a package valid only for an old master cannot suppress work.
    These sets are local forecast state, never persisted completion authority.
    """
    for key in ('packages', 'progress', 'carry', 'completedSections'):
        coverage = facts['coveredSections'] if key == 'completedSections' else facts['coveredScopes']
        require(facts[key] <= coverage, 'service completion exceeds current request coverage')
        reductions[key].difference_update(coverage)
        reductions[key].update(facts[key])


def unbound_coverage(evidence: dict, section_id: str | None) -> dict:
    """Clear possible superseded work without reading an unpublished request or media.

    A new invocation has not proved compatibility yet. Only its frozen scope
    inventory is known; no old completion may reduce work within that coverage.
    """
    scopes = [row for row in evidence['scopes']
              if section_id is None or row['sectionIds'] == [section_id]]
    require(bool(scopes), 'unbound service invocation has no frozen scope')
    return {**{key: set() for key in ('packages', 'progress', 'carry', 'completedSections')},
            'coveredScopes': {row['id'] for row in scopes},
            'coveredSections': {item for row in scopes for item in row['sectionIds']}}


def necessary_invocations(invocations: list[dict], evidence: dict) -> set[int]:
    """Prune wholly superseded proof roots using frozen coverage before any file IO.

    A partly covered full request still supplies global or sibling facts and is
    read normally, including every required donor and reviewer dependency.
    Unbound later invocations shadow old facts without borrowing their proofs.
    """
    selected, scopes, sections = set(), set(), set()
    for index in reversed(range(len(invocations))):
        coverage = unbound_coverage(evidence, invocations[index]['sectionId'])
        if coverage['coveredScopes'] - scopes or coverage['coveredSections'] - sections:
            selected.add(index)
        scopes.update(coverage['coveredScopes'])
        sections.update(coverage['coveredSections'])
    return selected


def cold_family_state(record: dict, family: dict, evidence: dict) -> dict:
    """Observe the frozen family without a parallel mutable service-accounting ledger."""
    registered = [(clip, item) for clip in record['clips'].values()
                  for item in clip.get('sectionFamilies', []) if item['id'] == family['id']]
    require(len(registered) == 1 and registered[0][1] == family, 'service family is not registered')
    attempt = next(row for row in registered[0][0]['attempts'] if row['id'] == family['id'])
    require(attempt['route'] == 'final', 'preview outcomes cannot reduce final service demand')
    require(evidence['identity'] == identity({key: value for key, value in evidence.items() if key != 'identity'}),
            'service envelope changed')
    members = {}
    reductions = {key: set() for key in ('packages', 'progress', 'carry', 'completedSections')}
    extra, has_media = set(), False
    selected = necessary_invocations(family['invocations'], evidence)
    for index, invocation in enumerate(family['invocations']):
        key = invocation['sectionId']
        if key in members:
            extra.add('recovery')
        if invocation['status'] in ('failed', 'abandoned'):
            extra.add('retry')
        request = registered_request(family, invocation) if index in selected else None
        facts = request_facts(record, request, evidence) if request is not None else None
        members[key] = {'terminal': invocation['status'] == 'succeeded', 'facts': facts}
        if index in selected:
            replace_covered_facts(reductions, facts if facts is not None else unbound_coverage(evidence, key))
        if facts is not None:
            has_media = has_media or facts['hasMedia']
    return {'members': members, **reductions, 'additionalDemand': sorted(extra), 'hasMedia': has_media,
            'actual': {}, 'actualReads': {}, 'complete': family['state'] == 'complete'}
