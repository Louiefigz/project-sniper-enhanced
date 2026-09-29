"""Partition Long service demand without changing grants, media validity or capacity.

Only cold_family_state may supply completion facts at a production hook. This
arithmetic layer is not authority to settle work. Existing conservative member
pricing is retained exactly when a measured slice is unknown or ineligible.
"""
from __future__ import annotations

from studio.native_segments.review_service_estimate import estimate_service
from studio.native_segments.review_service_plan import remaining_selection
from studio.native_budget_forecast import route_seconds


def local_section(scope: dict) -> str | None:
    """A global join belongs only to the integrated invocation."""
    return scope['sectionIds'][0] if len(scope['sectionIds']) == 1 else None


def window_count(evidence: dict, section_id: str | None) -> int:
    """Count exact encoder intervals once, despite overlapping chunk/join scopes."""
    if section_id is None:
        return evidence['windows']
    return len({tuple(bounds) for scope in evidence['scopes'] if local_section(scope) == section_id
                for bounds in scope['windowRanges']})


def future_passes(evidence: dict, state: dict, section_id: str | None) -> int:
    """Keep one conservative discovery pass plus each still-unsealed normal completion."""
    member = state['members'].get(section_id)
    if state['complete'] or (member and member['terminal']):
        return 0
    facts = member['facts'] if member else None
    return 1 + (facts['pendingWindows'] if facts is not None else window_count(evidence, section_id))


def pending_owner(state: dict, section_id: str | None) -> str | None:
    """Full integration owns required local work after that private invocation has settled."""
    member = state['members'].get(section_id)
    return None if member and member['terminal'] else section_id


def call_count(evidence: dict, state: dict, call: dict, member_id: str | None) -> int:
    """Assign all final all-scope reads to integration, preserving local early work."""
    scope = next(row for row in evidence['scopes'] if row['id'] == call['scopeId'])
    section, site = local_section(scope), call['site']
    local = member_id is not None and section == member_id
    if member_id is not None and not local:
        return 0
    done = state['complete']
    if site in ('ready-discovery', 'ready-materialize'):
        return future_passes(evidence, state, member_id)
    if site == 'package-create':
        owner = member_id == pending_owner(state, section)
        return int(owner and not done and scope['id'] not in state['packages'] | state['carry'])
    if site == 'review-progress':
        owner = section is not None and member_id == pending_owner(state, section)
        return int(owner and not done and scope['id'] not in state['progress'] | state['carry'])
    if site == 'review-complete':
        return int(member_id is None and not done and not set(scope['sectionIds']) <= state['completedSections'])
    if site == 'family-outcome':
        member = state['members'].get(member_id)
        return 0 if done or (member and member['terminal']) else 2
    return call['calls'] if member_id is None and not done else 0


def selected_remaining(evidence: dict, state: dict, member_id: str | None = '*') -> dict:
    """Derive bounded counts from cold state, never from calibration success or caller counters."""
    members = [None, *sorted({local_section(row) for row in evidence['scopes'] if local_section(row) is not None})]
    selected = members if member_id == '*' else [member_id]
    calls = {call['key']: sum(call_count(evidence, state, call, member) for member in selected)
             for call in evidence['readPlan']['calls']}
    remaining = remaining_selection(evidence, calls)
    remaining.update(additionalDemand=list(state['additionalDemand']),
                     actual=dict(state['actual']), actualReads=dict(state['actualReads']))
    return remaining


def conservative_seconds(evidence: dict, member_id: str | None, state: dict) -> float:
    """Preserve baseline member pricing and add newly required transferred local work."""
    scopes = [row for row in evidence['scopes'] if member_id == '*'
              or (member_id is None and len(row['sectionIds']) > 1) or row['sectionIds'] == [member_id]]
    if member_id is None:
        scopes.extend(row for row in evidence['scopes'] if local_section(row) is not None
                      and pending_owner(state, local_section(row)) is None
                      and row['id'] not in state['packages'] | state['carry'])
    return sum(route_seconds(evidence['fallbackRates'], 'final', row['seconds']) for row in scopes)


def family_service(evidence: dict, catalog: object, state: dict, member_id: str | None = '*') -> dict:
    """Price a normal slice; unknown actual traversal cannot inherit a prospective faster rate."""
    remaining = selected_remaining(evidence, state, member_id)
    if state['hasMedia'] and not remaining['actualReads'] and any(remaining['calls'].values()):
        result = {'status': 'fallback', 'reason': 'actual transitive proof-read inventory is unobserved'}
    else:
        result = estimate_service(evidence, catalog, remaining)
    if result['status'] == 'fallback':
        result = {**result, 'seconds': conservative_seconds(evidence, member_id, state), 'selected': []}
    return {**result, 'remaining': remaining, 'operationalOnly': True}
