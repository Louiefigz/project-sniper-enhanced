"""Content-bound static section inputs across private immutable project snapshots.

The contract proves equality of the supported static dependency subset. It is
not renderer qualification, editorial review, source-policy admission or an
excuse to omit original StageEvidence. Callers retain all of those boundaries.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_region_contract import RULE, read_region_map
from studio.native_segments.dependency import NOT_RENDERED, inventory
from studio.native_segments.long_plan import identity
from studio.native_stage_evidence import require


def covered(rows: list[dict], bounds: list[int]) -> list[dict]:
    """Require complete selected coverage; sections cannot borrow unknown empty timeline intervals."""
    require(type(bounds) is list and len(bounds) == 2 and all(type(value) is int for value in bounds)
            and 0 <= bounds[0] < bounds[1], 'invalid scoped section range')
    selected = [row for row in rows if row['startFrame'] < bounds[1] and row['endFrame'] > bounds[0]]
    cursor = bounds[0]
    for row in selected:
        require(row['startFrame'] <= cursor, 'scoped section has an undeclared timeline gap')
        cursor = max(cursor, row['endFrame'])
    require(cursor >= bounds[1], 'scoped section does not have complete mounted coverage')
    return selected


def scoped_plan_inputs(plan: dict, frame_range: list[int]) -> dict:
    """Retain frozen planning authority and the exact execution decisions owned by this range.

    The public source/prebuild reader separately validates each application's
    allocation and executable bindings. This projection cannot grant admission.
    Unfinished siblings may lack application rows, but no frozen scene ownership,
    allocation binding, source choice, canvas or selected decision is omitted.
    """
    application = plan.get('visualPlanApplication')
    if application is None:
        return plan
    require(type(application) is dict and set(application) ==
            {'schemaVersion', 'route', 'visualPlanSha256', 'decisions'}
            and type(application['decisions']) is list,
            'unsupported visual application in section dependency closure')
    start, end = frame_range
    selected = []
    for decision in application['decisions']:
        left, right = decision.get('startFrame'), decision.get('endFrameExclusive')
        require(type(left) is int and type(right) is int and 0 <= left < right,
                'invalid visual execution interval in section dependency closure')
        if right <= start or left >= end:
            continue
        require(start <= left < right <= end, 'visual execution crosses section dependency boundary')
        selected.append(decision)
    return {**plan, 'visualPlanApplication': {**application, 'decisions': selected}}


def section_input_closure(project: Path, frame_range: list[int]) -> dict:
    """Hash exact selected composition bytes and the complete supported shared source closure."""
    from studio.native_region_runtime import implementation_pins
    plan = bound_json(project / 'LONG-PROJECT.json')
    rows = read_region_map(project, plan['canvas'])
    require(all(row['isolation']['status'] == 'scoped' and row['isolation']['rule'] == RULE for row in rows),
            'section locality requires the bounded static isolation contract for every mounted composition')
    selected = covered(rows, frame_range)
    files = inventory(project)
    local = {row['file']: files[row['file']] for row in selected}
    region_files = {row['file'] for row in rows}
    shared = {name: sha for name, sha in files.items() if name not in region_files and name not in NOT_RENDERED}
    shared['LONG-PROJECT.json'] = identity(scoped_plan_inputs(plan, frame_range))
    if 'LONG-CHUNKS.json' in shared:
        from studio.native_long_chunks import scoped_chunk_inputs
        shared['LONG-CHUNKS.json'] = identity(scoped_chunk_inputs(project, frame_range))
    if 'VISUAL-SOURCES.json' in shared:
        from studio.native_review_regions import source_decisions
        shared['VISUAL-SOURCES.json'] = identity(source_decisions(bound_json(project / 'VISUAL-SOURCES.json')))
    context = [{key: row[key] for key in ('id', 'file', 'startFrame', 'endFrame', 'isolation')} for row in rows]
    shared_identity = identity({'rule': RULE, 'canvas': plan['canvas'], 'shared': shared, 'regions': context})
    return {'schemaVersion': 1, 'rule': RULE, 'frameRange': frame_range, 'canvas': plan['canvas'],
            'sharedIdentity': shared_identity, 'sectionIdentity': identity({'shared': shared_identity,
                'range': frame_range, 'files': local}), 'files': local, 'sharedFiles': shared,
            'regionFiles': sorted(region_files), 'requiredImplementationPins': implementation_pins(project),
            'runtimeQualification': 'not-established'}
