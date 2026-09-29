"""Frozen Long review-package membership, derived from admitted chunk geometry.

These are derived playback packages, never additional picture generations or
final AAC candidates. Each scope belongs to the original final launch family.
"""
from __future__ import annotations

import re

from studio.native_segments.long_plan import identity
from studio.native_stage_evidence import require


def phase_for(scope_id: str) -> str:
    """Name one bounded package member without permitting caller-selected paths."""
    return 'review-package-' + identity(scope_id)[:24]


def package_phase(phase: str) -> bool:
    """Recognize only canonical immutable review-package names."""
    return re.fullmatch(r'review-package-[0-9a-f]{24}', phase) is not None


def package_scopes(request: dict) -> list[dict]:
    """Derive all chunk and seam scopes from the cold admitted Long contract."""
    from studio.native_long_chunks import require_chunk_request
    require(request.get('adapter') == 'native-long' and request.get('sectionChunks'),
            'review packages require admitted Long chunks')
    require_chunk_request(request)
    return declared_scopes(request)


def declared_scopes(request: dict) -> list[dict]:
    """Project already cold-validated authored geometry for admission forecasts or worker scope reads."""
    from studio.production.section_chunk_plan import scope_inventory
    from studio.production.section_review_inputs import section_windows
    context = request['sectionProduction']
    selected = request.get('sectionScope', {}).get('sectionId')
    scopes = []
    for row in context['assignments']:
        if selected is not None and selected != row['sectionId']:
            continue
        mapping = next(item['map'] for item in request['sectionChunks']['assignments']
                       if item['sectionId'] == row['sectionId'])
        scopes.extend({**scope, 'sectionIds': [row['sectionId']]} for scope in
                      scope_inventory(mapping, section_windows(request, row)))
    scopes = [expanded_scope(request, scope) for scope in scopes]
    if selected is None:
        scopes.extend(global_scopes(request))
    require(len(scopes) <= 1535 and len({phase_for(row['id']) for row in scopes}) == len(scopes),
            'review package scope inventory exceeds its bound or has duplicate identities')
    return scopes


def global_scopes(request: dict) -> list[dict]:
    """Only full integration may package the actual encoded creative-section seams."""
    from studio.production.section_chunk_plan import window_identity
    rows = request['sectionProduction']['assignments']
    result = []
    for left, right in zip(rows, rows[1:]):
        windows = edge_windows(request, left['frameRange'][1])
        result.append({'id': f"encoded-join:{left['sectionId']}:{right['sectionId']}",
                       'kind': 'global-neighboring-edge',
                       'sectionIds': [left['sectionId'], right['sectionId']],
                       'frameRange': [windows[0]['startFrame'], windows[-1]['endFrame']],
                       'windows': [window_identity(window) for window in windows]})
    return result


def edge_windows(request: dict, edge: int) -> list[dict]:
    """Cover the complete authored transition and surrounding complete window context."""
    transitions = [transition for row in request['sectionChunks']['assignments']
                   for transition in row['transitions'] if transition['frame'] == edge]
    require(bool(transitions) and all(row == transitions[0] for row in transitions),
            'review edge lacks one current authored transition contract')
    start, end = transitions[0]['frameRange']
    windows = request['revision']['renderWindows']
    selected = [index for index, row in enumerate(windows)
                if row['startFrame'] < end and row['endFrame'] > start]
    require(bool(selected), 'transition has no admitted technical windows')
    chunks = [chunk for row in request['sectionChunks']['assignments'] for chunk in row['map']['chunks']]
    left = next(row for row in chunks if row['frameRange'][1] == edge)
    right = next(row for row in chunks if row['frameRange'][0] == edge)
    candidates = windows[max(0, selected[0] - 1):min(len(windows), selected[-1] + 2)]
    return [row for row in candidates if left['frameRange'][0] <= row['startFrame']
            and row['endFrame'] <= right['frameRange'][1]]


def expanded_scope(request: dict, scope: dict) -> dict:
    """Expand an internal edge without changing the chunk's review identity."""
    if scope['kind'] != 'neighboring-edge':
        return scope
    from studio.production.section_chunk_plan import window_identity
    edge = scope['windows'][0]['endFrame']
    windows = edge_windows(request, edge)
    owned = request.get('sectionScope', {}).get('frameRange')
    require(owned is None or (owned[0] <= windows[0]['startFrame'] and windows[-1]['endFrame'] <= owned[1]),
            'transition review context exceeds this immutable authored snapshot')
    return {**scope, 'frameRange': [windows[0]['startFrame'], windows[-1]['endFrame']],
            'windows': [window_identity(row) for row in windows]}


def request_scope(request: dict, scope_id: str) -> dict:
    """Reject invented scope identifiers and ranges before any package media work."""
    matches = [row for row in package_scopes(request) if row['id'] == scope_id]
    require(len(matches) == 1, 'review package is outside the admitted scope inventory')
    return matches[0]


def phase_scope(request: dict, phase: str) -> dict:
    """Resolve the phase against frozen membership, never parsing arbitrary frame arguments."""
    require(package_phase(phase), 'invalid review package phase')
    matches = [row for row in package_scopes(request) if phase_for(row['id']) == phase]
    require(len(matches) == 1, 'review package phase is outside the admitted scope inventory')
    return matches[0]


def owner_phase(phase: str) -> str | None:
    """Identify the same family member across distinct invocation tokens."""
    match = re.fullmatch(r'family-[0-9a-f]{32}-(review-package-[0-9a-f]{24})', phase)
    return match[1] if match else phase if package_phase(phase) else None
