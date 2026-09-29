"""Cold geometry and dependency evidence for authored Long chunk transition decisions.

Exact file and timeline bindings establish currentness, not artistic continuity.
The existing independent prebuild review and later encoded checks own judgments.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_region_contract import read_region_map
from studio.native_segments.dependency import NOT_RENDERED, inventory
from studio.native_segments.long_chunks import assignment_chunk_map, derive_long_chunks
from studio.native_segments.long_plan import MAX_WINDOW_FRAMES, identity, initial_long_plan
from studio.native_stage_evidence import require

CONTRACT = 'LONG-CHUNKS.json'


def chunk_geometry(project: Path, context: dict) -> dict:
    """Recompute the fixed section/chunk/window geometry from original Long inputs."""
    plan = bound_json(project / 'LONG-PROJECT.json')
    canvas = plan['canvas']
    edges = sorted({*range(0, canvas['totalFrames'], MAX_WINDOW_FRAMES),
                    *[row['frameRange'][1] for row in context['assignments']]})
    revision = initial_long_plan(canvas, identity(canvas), edges)
    candidate = derive_long_chunks(project, context['assignments'], revision)
    return {'canvas': canvas, 'encoderBoundaries': candidate['encoderBoundaries'],
            'maps': [assignment_chunk_map(candidate, row['sectionId']) for row in context['assignments']],
            'dependencyInputs': inventory(project), 'timelinePlan': plan,
            'regions': read_region_map(project, canvas)}


def boundary_neighbors(geometry: dict, frame: int) -> list[dict]:
    """Return the two chunks owning the adjacent half-open output intervals."""
    chunks = [chunk for row in geometry['maps'] for chunk in row['chunks']]
    left = [row for row in chunks if row['frameRange'][1] == frame]
    right = [row for row in chunks if row['frameRange'][0] == frame]
    require(len(left) == len(right) == 1, 'transition must name one actual adjacent chunk boundary')
    return [left[0], right[0]]


def boundary_frames(geometry: dict) -> list[int]:
    """Every chunk edge except the program end needs one authored transition decision."""
    return [chunk['frameRange'][1] for row in geometry['maps'] for chunk in row['chunks']][:-1]


def transition_timeline(project: Path, geometry: dict, span: list[int]) -> dict:
    """Bind exact scenes and generated motion that intersect a declared transition span."""
    start, end = span
    plan = geometry['timelinePlan']
    scenes = [row for row in plan['scenes'] if row['startFrame'] < end and row['endFrame'] > start]
    motions = [motion for row in geometry['maps'] for motion in row['boundaryEvidence']['motionSpans']
               if motion['frameRange'][0] < end and motion['frameRange'][1] > start]
    return {'scenes': scenes, 'motionSpans': list({identity(row): row for row in motions}.values()),
            'clock': geometry['canvas'], 'seekPolicy': 'absolute-program-frame'}


def _plan_projection(plan: dict, span: list[int]) -> dict:
    """Keep shared authority and complete intersecting execution rows, excluding unrelated scenes."""
    start, end = span
    value = {**plan, 'scenes': [row for row in plan['scenes']
                               if row['startFrame'] < end and row['endFrame'] > start]}
    application = plan.get('visualPlanApplication')
    if application is not None:
        value['visualPlanApplication'] = {**application, 'decisions': [row for row in application['decisions']
            if row['startFrame'] < end and row['endFrameExclusive'] > start]}
    return value


def transition_dependencies(project: Path, geometry: dict, span: list[int]) -> dict:
    """Bind shared inputs and both sides' actual composition bytes without a self-hash cycle."""
    rows = geometry['regions']
    regions = {row['file'] for row in rows}
    selected = {row['file'] for row in rows if row['startFrame'] < span[1] and row['endFrame'] > span[0]}
    files = {name: sha for name, sha in geometry['dependencyInputs'].items()
             if name not in NOT_RENDERED and name != CONTRACT and (name not in regions or name in selected)}
    files['LONG-PROJECT.json'] = identity(_plan_projection(geometry['timelinePlan'], span))
    if 'VISUAL-SOURCES.json' in files:
        from studio.native_review_regions import source_decisions
        files['VISUAL-SOURCES.json'] = identity(source_decisions(bound_json(project / 'VISUAL-SOURCES.json')))
    return files


def transition_evidence(project: Path, geometry: dict, span: list[int]) -> dict:
    """Expose exact evidence for an authored decision; no purpose or verdict is generated."""
    return {'timeline': transition_timeline(project, geometry, span),
            'dependencies': transition_dependencies(project, geometry, span)}
