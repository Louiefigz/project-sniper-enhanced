"""Pure rate-cell selection over explicit geometry, eligibility and remaining work.

No capacity, grant, task or media validity is changed here. Prospective bytes
are limits copied from exercised cells, never predictions of future CRF output.
"""
from __future__ import annotations

import copy

from native_work_service_pins import identity, require
from native_work_service_schema import BOUND_DIMENSIONS, validate_cell, validate_contract, within_bounds
from studio.native_budget_forecast import route_seconds
from studio.native_segments.review_service_plan import selected_calls


def demand(evidence: dict, call: dict) -> dict:
    """Use full-program dimensions for transitive coordinator/read entrypoints."""
    scope = next(row for row in evidence['scopes'] if row['id'] == call['scopeId'])
    whole = call['site'] != 'package-create'
    return {'frames': evidence['canvas']['totalFrames'] if whole else scope['frames'],
            'windows': evidence['windows'] if whole else scope['windows'],
            **{key: None for key in BOUND_DIMENSIONS.values() if key not in ('frames', 'windows')},
            'pinnedInputBytes': evidence['knownInputs']['bytes'],
            'proofFiles': evidence['knownInputs']['files']}


def candidate(cell: dict, conditions: dict, work: dict) -> bool:
    """All known lower bounds must fit one joint exercised cell; unknown future bytes are capped."""
    validate_cell(cell)
    return cell['contract'] == conditions and work['frames'] >= cell['bounds']['minFrames'] \
        and all(work[key] is None or work[key] <= cell['bounds'][name]
                for name, key in BOUND_DIMENSIONS.items())


def select_cell(evidence: dict, catalog: object, call: dict) -> dict | None:
    """Select only currently validated evidence covering this exact transitive entrypoint."""
    conditions = evidence['conditions']
    if conditions is None or catalog.source is None or catalog.rejected:
        return None
    contract = {**conditions, 'proofPlanVersion': call['proofPlanVersion']}
    validate_contract(contract)
    work, candidates = demand(evidence, call), []
    cells = [(row['id'], cell) for row in catalog.rows for cell in row['cells']]
    for row_id, cell in cells:
        if cell['unit'] == call['unit'] and candidate(cell, contract, work):
            candidates.append({'rowId': row_id, 'cellId': cell['id'], 'cellSha256': identity(cell),
                'catalog': catalog.source, 'contract': cell['contract'], 'bounds': cell['bounds'],
                'secondsPerCall': cell['ceilingSeconds']})
    return copy.deepcopy(min(candidates, key=lambda row: (row['secondsPerCall'], row['rowId'], row['cellId']))) \
        if candidates else None


def freeze_envelopes(evidence: dict, catalog: object) -> list[dict]:
    """Freeze operational eligibility separately from source and picture identities."""
    return [{'key': call['key'], 'scopeId': call['scopeId'], 'site': call['site'],
             'selection': select_cell(evidence, catalog, call)} for call in evidence['readPlan']['calls']]


def same_selection(frozen: dict, current: dict | None) -> bool:
    """A changed/disappeared cell requires fallback; a newly faster cell is not auto-adopted."""
    return current is not None and frozen == current


def fallback(evidence: dict, calls: list[dict], reason: str) -> dict:
    """Retain the existing per-scope final-rate allowance, without claiming measured read coverage."""
    scopes = {call['scopeId'] for call in calls}
    seconds = sum(route_seconds(evidence['fallbackRates'], 'final', row['seconds'])
                  for row in evidence['scopes'] if row['id'] in scopes)
    return {'status': 'fallback', 'seconds': seconds, 'reason': reason, 'selected': [],
            'readPlanIdentity': evidence['readPlan']['identity'], 'remainingCoverage': 'conservative-existing-rate'}


def actual_miss(evidence: dict, remaining: dict, calls: list[dict]) -> bool:
    """Actual local packages cannot stand in for whole-entrypoint proof-read units.

    Before any actual observations, selection remains prospective and every
    frozen byte envelope is a future operational condition. Once observations
    arrive, each remaining reader needs its own validated full-program facts.
    Unobserved required readers fall back; overlapping package sizes are never
    summed to fabricate the transitive read inventory.
    """
    actual, reads = remaining['actual'], remaining['actualReads']
    if not actual and not reads:
        return False
    envelopes = {row['key']: row['selection'] for row in evidence['envelopes']}
    package_limits = {row['scopeId']: row['selection'] for row in evidence['envelopes']
                      if row['site'] == 'package-create'}
    if any(observed_miss(row, package_limits[scope_id]) for scope_id, row in actual.items()):
        return True
    for call in calls:
        if call['unit'] != 'cold-proof-read':
            continue
        observed = reads.get(call['key'])
        if observed is None or observed_miss(observed, envelopes[call['key']]):
            return True
        expected = demand(evidence, call)
        if any(observed['facts'][key] != expected[key] for key in ('frames', 'windows')):
            return True
    return False


def observed_miss(observed: dict, selection: dict | None) -> bool:
    """Compare an actual descriptor with its exact frozen unit, never a neighboring envelope."""
    return observed['status'] == 'miss' or selection is None \
        or not within_bounds(observed['facts'], selection['bounds'])


def estimate_service(evidence: dict, catalog: object, remaining: dict) -> dict:
    """Price only explicit remaining calls; no file scan can silently declare work completed."""
    require(evidence['identity'] == identity({key: value for key, value in evidence.items() if key != 'identity'}),
            'frozen service evidence changed')
    calls = selected_calls(evidence, remaining)
    if remaining['additionalDemand']:
        return fallback(evidence, evidence['readPlan']['calls'],
                        'additional read/retry demand requires a new remaining-work forecast')
    if actual_miss(evidence, remaining, calls):
        return fallback(evidence, calls, 'sealed media falls outside the frozen operational rate envelope')
    frozen = {row['key']: row['selection'] for row in evidence['envelopes']}
    selected = []
    for call in calls:
        row = select_cell(evidence, catalog, call)
        if frozen.get(call['key']) is None or not same_selection(frozen[call['key']], row):
            return fallback(evidence, calls, f"uncovered or changed service cell: {call['site']}")
        selected.append({'key': call['key'], 'calls': call['calls'], **row})
    return {'status': 'measured', 'seconds': sum(row['calls'] * row['secondsPerCall'] for row in selected),
            'reason': None, 'selected': selected, 'readPlanIdentity': evidence['readPlan']['identity'],
            'remainingCoverage': 'explicit-normal-coordinator-slice'}
