"""Bounded normal-coordinator service demand, separate from inspection permission.

One cell measures the complete named entrypoint, including its transitive reads.
Counts are conservative entrypoint ceilings, not invented counts of SHA calls.
External inspections and replay/recovery calls are additional demand; they do not
invalidate media and are not silently included in the normal invocation slice.
"""
from __future__ import annotations

from native_work_service_pins import fields, identity, require

VERSION = 'long-review-service-reads-v1'
SITES = {
    'package-create': ('build-and-seal', 'native_segments.review_package.ensure_package:new'),
    'ready-discovery': ('cold-proof-read', 'production.section_chunk_presentation.package_ready_scopes:retained'),
    'ready-materialize': ('cold-proof-read', 'production.sections.materialize_section_reviews'),
    'review-progress': ('cold-proof-read', 'production.section_chunk_progress.record_progress'),
    'review-complete': ('cold-proof-read', 'production.callbacks.complete:chunk'),
    'assembly': ('cold-proof-read', 'native_segments.reviews.assembly_snapshot'),
    'publication': ('cold-proof-read', 'production.section_publication.publish_delivery'),
    'family-outcome': ('cold-proof-read', 'native_budget_family_outcome.apply_family_outcome'),
}
EXTRA_SITES = ('external-inspection', 'callback-replay', 'recovery', 'retry')


def call_row(site: str, scope: dict, calls: int) -> dict:
    """Bind a measured unit to one exact scope and a whole-entrypoint read plan."""
    unit, entrypoint = SITES[site]
    return {'key': identity([site, scope['id']]), 'site': site, 'scopeId': scope['id'],
            'unit': unit, 'calls': calls, 'entrypoint': entrypoint,
            'proofPlanVersion': f'{VERSION}:{site}'}


def normal_read_plan(scopes: list[dict], assignments: list[dict], windows: int) -> dict:
    """Bound the initial private sections plus one full integration, with no retry.

    Each section may publish once before dispatch and after every local window.
    Full integration is conservatively allowed every full-grid completion too.
    A scope belongs to at most its private invocation and the integrated one.
    Whole-task/whole-program sites are charged per participating scope; their
    calibration cell must cover the entire entrypoint, so this can overcharge.
    """
    rows = []
    for scope in scopes:
        local = next((row for row in assignments if scope['sectionIds'] == [row['sectionId']]), None)
        local_windows = local['windows'] if local else 0
        passes = windows + 1 + (local_windows + 1 if local else 0)
        counts = {'package-create': 1, 'ready-discovery': passes, 'ready-materialize': passes,
                  'review-progress': int(local is not None), 'review-complete': 1,
                  'assembly': 2, 'publication': 1, 'family-outcome': 2 * (1 + int(local is not None))}
        rows.extend(call_row(site, scope, calls) for site, calls in counts.items())
    body = {'version': VERSION, 'basis': 'normal-private-sections-and-full-integration',
            'calls': rows, 'additionalDemand': list(EXTRA_SITES)}
    return {**body, 'identity': identity(body)}


def remaining_selection(evidence: dict, calls: dict | None = None) -> dict:
    """Validate an explicit authority-supplied selection; never discover mutable completion.

    Every frozen entry is required, including explicit zeroes. This is a shape
    checker, not authority to mark work complete. The later family transaction
    must validate the caller's remaining counters against its recorded outcomes.
    """
    plan = evidence['readPlan']
    require(plan['identity'] == identity({key: value for key, value in plan.items() if key != 'identity'}),
            'service read plan changed')
    expected = {row['key']: row['calls'] for row in plan['calls']}
    selected = expected if calls is None else calls
    require(type(selected) is dict and set(selected) == set(expected), 'remaining service sites are incomplete')
    require(all(type(value) is int and 0 <= value <= expected[key] for key, value in selected.items()),
            'remaining service calls exceed their frozen normal slice')
    return {'readPlanIdentity': plan['identity'], 'calls': dict(selected), 'additionalDemand': [], 'actual': {}, 'actualReads': {}}


def selected_calls(evidence: dict, remaining: dict) -> list[dict]:
    """Refuse omitted or invented sites and preserve explicit uncovered extra demand."""
    fields(remaining, 'readPlanIdentity calls additionalDemand actual actualReads')
    checked = remaining_selection(evidence, remaining['calls'])
    require(checked['readPlanIdentity'] == remaining['readPlanIdentity'], 'remaining service plan differs')
    extra = remaining['additionalDemand']
    require(type(extra) is list and len(extra) <= len(EXTRA_SITES)
            and all(type(row) is str and row in EXTRA_SITES for row in extra) and len(set(extra)) == len(extra),
            'invalid additional service demand')
    actual = remaining['actual']
    scopes = {row['id'] for row in evidence['scopes']}
    require(type(actual) is dict and set(actual) <= scopes, 'actual service scopes differ')
    reads = remaining['actualReads']
    read_keys = {row['key'] for row in evidence['readPlan']['calls'] if row['unit'] == 'cold-proof-read'}
    require(type(reads) is dict and set(reads) <= read_keys, 'actual service read units differ')
    for row in [*actual.values(), *reads.values()]:
        fields(row, 'status reasons facts mediaValidated')
        require(row['status'] in ('miss', 'eligible') and type(row['mediaValidated']) is bool
                and type(row['reasons']) is list and len(row['reasons']) <= 64
                and all(type(reason) is str and 0 < len(reason) <= 256 for reason in row['reasons']),
                'invalid operational service observation')
        from native_work_service_schema import validate_dimensions
        validate_dimensions(row['facts'])
        require(row['status'] != 'eligible' or (row['mediaValidated'] and not row['reasons']),
                'eligible observation lacks cold validation')
    return [{**row, 'calls': remaining['calls'][row['key']]} for row in evidence['readPlan']['calls']
            if remaining['calls'][row['key']]]
