"""What one native pool request runs, described for qualification-profile matching.

Admission matches this description against the host's qualification profiles
(native_work_profiles.py). Every field is read from files the owner has already bound,
never inferred from content:
- format: the project's single native plan, as studio/native_export.export_adapter
  requires ('short' for SHORT-PROJECT.json, 'long' for LONG-PROJECT.json). A project
  with both is 'ambiguous' and a linked or non-file plan 'invalid-plan' (no profile covers
  either); one with neither (review bundles, recognition, capability inspections, web
  capture) is 'unbound' supporting work.
- stage: the owner label its NativeRun receipt is named after (<label>.render.json);
  preview sections drop their index, as studio/native_preview_sections.section_phase
  names them.
- durationSeconds / pixels: the plan canvas. Shorts are 1080x1920 by contract
  (studio/native_short_worker.py); Long canvases declare width and height.
- cache: always 'unobserved'. Admission cannot see whether the owner's sources are
  already in the shared source store, so profiles must have exercised cold caches.
- engine: the content identity native_batch freezes (studio/native_budget_engine.py),
  computed only when a profile needs it (hashing the engine takes about 0.2-0.4 s).
"""
from __future__ import annotations

import os
from fractions import Fraction
from pathlib import Path

from cut_preview_io import bound_json

SHORT_CANVAS = (1080, 1920)
PLANS = (('SHORT-PROJECT.json', 'short'), ('LONG-PROJECT.json', 'long'))
SECTION_STAGES = ('preview-picture', 'preview-package', 'segment-picture')
RECEIPT_SUFFIX = '.render.json'
PLAN_LIMIT = 32 * 1024 * 1024
UNOBSERVED = 'unobserved'


def stage_label(label: str) -> str:
    """Normalize an owner label; 'preview-picture-3' becomes 'preview-picture'."""
    base, marker, retry = label.rpartition('-retry-')
    if marker and retry.isdigit():
        label = base
    stem, _, index = label.rpartition('-')
    return stem if stem in SECTION_STAGES and index.isdigit() else label


def stage_of(receipt: str | None) -> str | None:
    """The normalized owner label of a NativeRun receipt path, else None."""
    if not receipt or not receipt.endswith(RECEIPT_SUFFIX):
        return None
    return stage_label(Path(receipt).name[:-len(RECEIPT_SUFFIX)])


def plan_format(project: Path) -> str:
    """'short', 'long', 'unbound' (no plan) or, matching no profile, 'ambiguous'/'invalid-plan'."""
    present = [(project / name, kind) for name, kind in PLANS if os.path.lexists(project / name)]
    if len(present) > 1:
        return 'ambiguous'
    if not present:
        return 'unbound'
    path, kind = present[0]
    return kind if path.is_file() and not path.is_symlink() else 'invalid-plan'


def _canvas_bounds(canvas: object, kind: str) -> tuple[float | None, int | None]:
    """Output seconds and picture pixels from a plan canvas; None for any unreadable field."""
    if not isinstance(canvas, dict):
        return None, None
    frames, rate = canvas.get('totalFrames'), canvas.get('frameRate')
    try:
        seconds = float(frames / Fraction(rate)) if type(frames) is int and frames > 0 else None
    except (TypeError, ValueError, ZeroDivisionError):
        seconds = None
    width, height = SHORT_CANVAS if kind == 'short' else (canvas.get('width'), canvas.get('height'))
    pixels = width * height if type(width) is int and type(height) is int and width > 0 and height > 0 else None
    return seconds, pixels


def plan_bounds(project: Path) -> tuple[str, float | None, int | None]:
    """Format, output seconds and pixels of a project's single native plan."""
    kind = plan_format(project)
    if kind not in ('short', 'long'):
        return kind, None, None
    name = next(name for name, value in PLANS if value == kind)
    try:
        canvas = bound_json(project / name, maximum=PLAN_LIMIT).get('canvas')
    except (OSError, ValueError, RuntimeError):
        return kind, None, None
    return (kind, *_canvas_bounds(canvas, kind))


def describe(project: str, receipt: str | None, lane: str) -> dict:
    """The workload record admission matches; engine is filled in only when needed."""
    kind, seconds, pixels = plan_bounds(Path(project))
    return {'format': kind, 'stage': stage_of(receipt), 'class': lane, 'durationSeconds': seconds,
            'pixels': pixels, 'cache': UNOBSERVED, 'engine': None}


def unrecorded(lane: object) -> dict:
    """A queued or running request whose code recorded no workload (older checkouts)."""
    return {'format': 'unrecorded', 'stage': None, 'class': lane, 'durationSeconds': None,
            'pixels': None, 'cache': UNOBSERVED, 'engine': None}


def engine_record() -> dict:
    """{'identity', 'files'} of this checkout's engine, exactly as native_batch freezes it."""
    from studio.native_budget_engine import engine_identity
    from studio.native_runtime import REPO
    value = engine_identity(REPO)
    return {'identity': value['identity'], 'files': value['files']}


def current_engine() -> str:
    """The engine identity admission compares with a profile's frozen engine."""
    return engine_record()['identity']


def forecast_workload(engine: str | None, output_seconds: float | None, fmt: str = 'short') -> dict:
    """Describe known forecast facts; a Long has no project-bound stage or geometry here."""
    if fmt not in ('short', 'long'):
        raise ValueError('Forecast format must be short or long')
    return {'format': fmt, 'stage': 'pipeline' if fmt == 'short' else None, 'class': 'heavy',
            'durationSeconds': output_seconds, 'pixels': SHORT_CANVAS[0] * SHORT_CANVAS[1] if fmt == 'short' else None,
            'cache': UNOBSERVED, 'engine': engine}
