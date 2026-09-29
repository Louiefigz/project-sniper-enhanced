"""Restrict assigned work to an explicitly admitted immutable section snapshot.

Scoped prebuild owns snapshot admission. This adapter only matches that admitted
scope to its frozen logical assignment; it never grants full-project admission.
"""
from __future__ import annotations

from studio.production.section_results import require


def validate_scope(scope: dict) -> None:
    """Close the assignment projection; prebuild separately verifies its snapshot digest."""
    from studio.production.section_results import SHA256, matches
    fields = {'schemaVersion', 'sectionId', 'generation', 'inputIdentity', 'frameRange',
              'sharedPlan', 'snapshotProject', 'snapshotPinsHash'}
    require(type(scope) is dict and set(scope) == fields and type(scope['schemaVersion']) is int
            and scope['schemaVersion'] == 1 and matches(scope['snapshotPinsHash'], SHA256),
            'invalid scoped section admission')


def selected_assignments(request: dict, context: dict) -> list[dict]:
    """Select exactly the admitted logical author, or all authors for full integration."""
    scope = request.get('sectionScope')
    if scope is None:
        return context['assignments']
    validate_scope(scope)
    rows = [row for row in context['assignments'] if row['sectionId'] == scope.get('sectionId')]
    require(len(rows) == 1, 'scoped section has no frozen assignment')
    row = rows[0]
    require(all(scope.get(key) == row[key] for key in ('generation', 'inputIdentity', 'frameRange')),
            'scoped section differs from frozen assignment')
    require(scope.get('sharedPlan') == context['sharedPlan'] and scope.get('snapshotProject') == request['project'],
            'scoped section changed shared plan or immutable snapshot')
    return rows


def require_full_scope(request: dict) -> None:
    """A private admitted section is never a complete-project assembly authority."""
    require(request.get('sectionScope') is None, 'scoped section cannot assemble or publish a full Long')


def join_pairs(context: dict, row: dict) -> list[tuple[dict, dict]]:
    """Assign both three-section joins to the middle reviewer, or to the repaired neighbor."""
    rows = context['assignments']
    changed_ids = repaired_sections(context)
    pairs = []
    for left, right in zip(rows, rows[1:]):
        changed = [item for item in (left, right) if item['sectionId'] in changed_ids]
        owner = changed[0] if changed else rows[len(rows) // 2]
        if owner['sectionId'] == row['sectionId']:
            pairs.append((left, right))
    return pairs


def repaired_sections(context: dict) -> set[str]:
    """Distinguish this generation's repair from a retained author's older repairCycle kind."""
    pin = context.get('parentPlan')
    if pin is None:
        return set()
    from pathlib import Path
    from studio.production.section_plan import read_plan
    from studio.production.section_results import rehash
    rehash(pin)
    previous = {row['sectionId']: row['authorTaskId'] for row in read_plan(Path(pin['path']))['assignments']}
    return {row['sectionId'] for row in context['assignments'] if previous[row['sectionId']] != row['authorTaskId']}
