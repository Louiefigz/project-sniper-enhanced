"""Prospective operational rate envelopes; existing family fallback remains unwired.

Conditions are supplied by the later owner's validated runtime/filesystem
admission. Missing conditions never borrow them from a calibration record.
No future picture digest, byte size, cache hit or media approval is invented.
"""
from __future__ import annotations

import copy
from fractions import Fraction
from pathlib import Path

from native_work_service_pins import identity, require
from native_work_service_schema import validate_contract
from studio.native_segments.review_service_estimate import freeze_envelopes
from studio.native_segments.review_service_plan import VERSION, normal_read_plan


def planned_inventory(project: Path, context: dict) -> tuple[dict, list[dict], list[dict]] | None:
    """Reuse cold authored chunk admission and the actual encoder/scope geometry readers."""
    from studio.native_long_chunks import chunk_admission, read_chunk_contract
    from studio.native_segments.long_plan import initial_long_plan
    from studio.native_segments.review_scopes import declared_scopes, phase_for
    contract = read_chunk_contract(project)
    if contract is None:
        return None
    require(contract['context'] == context, 'service assignment authority changed')
    geometry = contract['geometry']
    canvas = geometry['canvas']
    revision = initial_long_plan(canvas, identity(canvas), geometry['encoderBoundaries'])
    request = {'sectionProduction': context, 'sectionChunks': chunk_admission(contract), 'revision': revision}
    rate = Fraction(canvas['frameRate'])
    scopes = [{**row, 'phase': phase_for(row['id']), 'frames': row['frameRange'][1] - row['frameRange'][0],
               'windowRanges': [[window['startFrame'], window['endFrame']] for window in row['windows']],
               'windows': len(row['windows']),
               'seconds': float((row['frameRange'][1] - row['frameRange'][0]) / rate)}
              for row in declared_scopes(request)]
    return canvas, scopes, revision['renderWindows']


def known_inputs(project: Path) -> dict:
    """Stat actual admitted project inventory; do not call an allocation estimate a byte ceiling."""
    from studio.native_preflight_inputs import inventory
    files, _directories = inventory(project)
    sizes = [{'path': str(file), 'bytes': file.stat().st_size} for file in files]
    return {'bytes': sum(row['bytes'] for row in sizes), 'files': len(sizes), 'inventory': sizes,
            'basis': 'current-project-only; future owner/runtime/media inputs remain eligibility-limited'}


def planned_service(project: Path, context: dict, catalog: object, conditions: dict | None = None) -> dict | None:
    """Freeze actual scope geometry and only exercised prospective eligibility limits.

    The optional conditions must come from current admitted tools/encoder/audio
    and destination filesystem. They are never inferred from a matching rate.
    Without them this helper records geometry but selects no faster rate.
    """
    from studio.production.formats import LONG_POLICY
    inventory = planned_inventory(project, context)
    if inventory is None:
        return None
    canvas, scopes, windows = inventory
    if conditions is not None:
        validate_contract(conditions)
        require(conditions['canvas'] == {key: canvas[key] for key in ('width', 'height', 'frameRate')}
                and conditions['proofPlanVersion'] == VERSION, 'service conditions differ from current geometry')
    assignments = [{**row, 'windows': sum(row['frameRange'][0] <= window['startFrame']
                    and window['endFrame'] <= row['frameRange'][1] for window in windows)}
                   for row in context['assignments']]
    body = {'schemaVersion': 1, 'kind': 'native-long-review-service-envelope', 'canvas': canvas,
            'scopes': scopes, 'windows': len(windows), 'knownInputs': known_inputs(project),
            'conditions': copy.deepcopy(conditions), 'readPlan': normal_read_plan(scopes, assignments, len(windows)),
            'fallbackRates': copy.deepcopy(LONG_POLICY['rates'])}
    body['envelopes'] = freeze_envelopes(body, catalog)
    return {**body, 'identity': identity(body)}
