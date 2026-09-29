"""Public Long section geometry and registered task-option binding."""
from __future__ import annotations

import argparse
from pathlib import Path
from cut_preview_io import bound_json


def section_options(args: argparse.Namespace) -> bool:
    """Continue an explicit section resume through its own route without requiring a repeated flag."""
    if any(getattr(args, key, None) for key in ('sections', 'chunks', 'section_plan', 'section_reviews', 'repair_from')):
        return True
    if not args.resume_from:
        return False
    original = bound_json(args.resume_from.resolve(strict=True) / 'export-request.json')
    return original.get('adapter') == 'native-long' and original.get('revision', {}).get('mode') == 'initial-long'


def section_boundaries(args: argparse.Namespace, canvas: dict) -> list[int] | None:
    """Split technical owners at logical assignment edges, retaining exact resume geometry."""
    from studio.native_segments.long_plan import MAX_WINDOW_FRAMES, _validate_previous
    from studio.native_stage_evidence import require
    planfile, logical = getattr(args, 'section_plan', None), []
    if planfile:
        from studio.production.section_plan import read_plan
        plan = read_plan(planfile)
        logical = [row['frameRange'][1] for row in plan['assignments']]
        require(logical[-1] == canvas['totalFrames'], 'section assignments must cover the current canvas')
    parent = getattr(args, 'resume_from', None) or getattr(args, 'repair_from', None)
    from studio.native_long_chunks import read_chunk_contract
    contract = read_chunk_contract(args.project.resolve(strict=True))
    expected = contract['geometry']['encoderBoundaries'] if contract else None
    if parent:
        original = bound_json(parent.resolve(strict=True) / 'export-request.json')
        previous = original.get('revision')
        if previous and previous.get('mode') == 'initial-long' and previous['canvas'] == canvas:
            _validate_previous(previous)
            boundaries = [row['startFrame'] for row in previous['renderWindows']] + [canvas['totalFrames']]
            require(set(logical) <= set(boundaries),
                    'repair or resume cannot move logical boundaries across saved technical windows')
            require(expected is None or expected == boundaries, 'chunk repair cannot change saved encoder geometry')
            return boundaries
    if expected is not None:
        return expected
    return sorted({0, *range(0, canvas['totalFrames'], MAX_WINDOW_FRAMES), *logical}) if logical else None


def bind_task_options(args: argparse.Namespace, request: dict) -> dict:
    """Bind assignments before registration and admit reviewed preview-to-final continuation."""
    plan = getattr(args, 'section_plan', None)
    if plan:
        from studio.production.sections import bind_section_tasks
        request = bind_section_tasks(request, plan.resolve(strict=True))
    if request.get('sectionProduction') and getattr(args, 'resume_from', None) \
            and not getattr(args, 'preview_only', False):
        from studio.production.sections import require_all_early_reviews
        require_all_early_reviews(request)
        request['previewOnly'] = False
    return request

