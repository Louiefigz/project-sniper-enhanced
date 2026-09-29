"""Narrow provenance for replacing an already-authored logical section through repairCycle.

Ordinary authors still consume the existing author cap. A section repair must
replace a completed registered section author, advance that same logical scope
once, retain its immutable shared plan, and keep its original input references.
"""
from __future__ import annotations

from studio.production.section_results import read_completed_result, require, validate_binding


def apply_parent(row: dict, parent: dict | None) -> dict:
    """Reuse exactly unchanged author assignments or advance one explicitly named prior owner."""
    if parent is None:
        require(row.get('priorAuthorTaskId') is None, 'section repair needs a parent plan')
        return row
    require(row.get('priorAuthorTaskId') == parent['authorTaskId'], 'section assignment must name its exact prior author')
    require(row['sectionId'] == parent['sectionId'] and row['frameRange'] == parent['frameRange']
            and row['projectFiles'] == parent['projectFiles'], 'section repair changed logical ownership')
    if row['inputIdentity'] == parent['inputIdentity'] and row['generation'] == parent['generation']:
        return dict(parent)
    require(row['generation'] == parent['generation'] + 1, 'section repair must advance its author generation once')
    return {**row, 'authorKind': 'repairCycle', 'replacesAuthor': parent['authorTaskId']}


def binding_kind(binding: dict, kind: str, clip_id: str | None) -> bool:
    """Close allowed task kinds without granting repair provenance by kind alone."""
    expected = ('author', 'repairCycle') if binding['role'] == 'author' else ('review',)
    return kind in expected and clip_id is not None


def replacement_problem(row: dict, tasks: dict) -> str | None:
    """Check persisted repair lineage even after the prior task was correctly superseded."""
    if row.get('sectionBinding') is None or row['kind'] != 'repairCycle':
        return None
    target = tasks.get(row['replaces'])
    if target is None or target.get('sectionBinding') is None or target['kind'] not in ('author', 'repairCycle'):
        return 'section repair has no registered authored predecessor'
    current, previous = row['sectionBinding'], target['sectionBinding']
    scope = ('sectionId', 'sharedPlanSha256', 'frameRange', 'outputRoot')
    if current['role'] != previous['role'] or current['role'] != 'author' or row['clipId'] != target['clipId'] \
            or any(current[key] != previous[key] for key in scope) \
            or current['generation'] != previous['generation'] + 1:
        return 'section repair differs from its exact predecessor scope or next generation'
    if not all(pin in current['inputs'] for pin in previous['inputs']):
        return 'section repair did not retain its predecessor input provenance'
    if target.get('endConfirmed') is not True or len(target.get('receipts', [])) != 1:
        return 'section repair predecessor never completed its owned author output'
    return None


def validate_section_spec(record: dict, spec: object) -> None:
    """Validate section kind and a live completed predecessor before enqueue supersedes it."""
    binding = spec.section_binding
    validate_binding(binding)
    require(binding_kind(binding, spec.kind, spec.clip_id), 'section task kind or output scope differs')
    if spec.kind != 'repairCycle':
        return
    row = {'kind': spec.kind, 'clipId': spec.clip_id, 'replaces': spec.replaces, 'sectionBinding': binding}
    problem = replacement_problem(row, record['production']['tasks'])
    require(problem is None, problem or 'invalid section replacement')
    prior = record['production']['tasks'][spec.replaces]
    read_completed_result(record, prior['id'], prior['sectionBinding'])


def allows_kind_replacement(record: dict, spec: object) -> bool:
    """Permit only the validated section author-to-repairCycle transition across task kinds."""
    if spec.section_binding is None or spec.kind != 'repairCycle':
        return False
    validate_section_spec(record, spec)
    return True
