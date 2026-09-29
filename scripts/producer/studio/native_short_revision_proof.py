"""Conservative frame intervals for Short picture repair across verified project revisions.

Only composition bodies with cold-checked isolation can be local. Source clocks,
canvas, shared HTML, assets, runtime or unproved composition changes invalidate
all picture frames. This proof never treats a review-window schedule as a render
invalidation map: repair spans cover the complete changed composition mount.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json, digest
from studio.native_clip_lineage import lineage_projects
from studio.native_review_regions import implementation_digest
from studio.native_runtime import digest as file_digest
from studio.native_short_regions import plan_projection, region_map, shared_inputs
from studio.native_stage_evidence import require

POLICY = 'scoped-short-picture-v1'
MODE = 'cached-native-batches'


def picture_subject(request: dict) -> dict:
    """Separate actual picture dependencies from audio finishing and revision paths."""
    project = Path(request['project'])
    plan = bound_json(project / 'SHORT-PROJECT.json')
    rows = region_map(project, plan['canvas'])
    shared = shared_inputs(project, plan, rows)
    projection = plan_projection(plan, {row['file'] for row in rows})
    projection.pop('audioFinishing', None)
    shared['SHORT-PROJECT.json'] = digest(projection)
    shared['implementation'] = implementation_digest(request)
    shared['runtime'] = {key: request.get(key) for key in
                         ('runtime', 'tools', 'captureMode', 'sourceCacheMode')}
    return {'sharedHash': digest(shared), 'rows': rows, 'canvas': plan['canvas'],
            'files': {row['file']: file_digest(project / row['file']) for row in rows}}


def merged_ranges(ranges: list[list[int]]) -> list[list[int]]:
    """Merge overlapping and adjacent dirty intervals, preserving exact half-open frames."""
    result = []
    for start, end in sorted(ranges):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def complement(ranges: list[list[int]], total: int) -> list[list[int]]:
    """The full unchanged complement, with neither holes nor overlapping ownership."""
    result, cursor = [], 0
    for start, end in ranges:
        if cursor < start:
            result.append([cursor, start])
        cursor = end
    if cursor < total:
        result.append([cursor, total])
    return result


def revision_intervals(current: dict, previous: dict) -> tuple[dict | None, str]:
    """Return exact local repair intervals, or the reason complete picture work is necessary."""
    if current.get('captureMode') != MODE or previous.get('captureMode') != MODE:
        return None, 'The selected picture route has no reusable retained frame inventory'
    require(previous['project'] in lineage_projects(Path(current['project'])),
            'Picture repair donor is not this clip or its verified ancestor')
    old_map = Path(previous['project']) / 'REVIEW-REGIONS.json'
    if old_map.is_file() and any(row.get('isolation', {}).get('rule') == 'hyperframes-0.8.31-scoped-composition-v1'
                                for row in bound_json(old_map).get('units', [])):
        return None, 'Historical composition isolation predates the current safe locality proof'
    before, after = picture_subject(previous), picture_subject(current)
    if before['sharedHash'] != after['sharedHash'] or before['rows'] != after['rows']:
        return None, 'Shared picture inputs, composition scope or timeline changed'
    dirty = []
    for row in after['rows']:
        if before['files'][row['file']] == after['files'][row['file']]:
            continue
        require(row['isolation']['status'] == 'scoped', 'Unproved composition locality cannot authorize frame reuse')
        dirty.append([row['startFrame'], row['endFrame']])
    total = after['canvas']['totalFrames']
    require(type(total) is int and 0 < total <= 10800, 'Picture repair frame count exceeds Short bounds')
    dirty = merged_ranges(dirty)
    unchanged = complement(dirty, total)
    if not unchanged:
        return None, 'Every output frame depends on the changed compositions'
    return {'sharedHash': after['sharedHash'], 'dirtyRanges': dirty, 'unchangedRanges': unchanged,
            'totalFrames': total, 'frameRate': after['canvas']['frameRate']}, 'Scoped picture reuse is proved'
